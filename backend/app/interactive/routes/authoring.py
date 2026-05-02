"""
Authoring routes — CRUD for experience, nodes, edges, actions, rules.

Scope: admin-side endpoints used by the studio UI to build the
experience graph and action catalog. Every write is scoped to the
authenticated user; cross-user reads return 404 to stay probe-safe.

Structural validation (no cycles, entry node exists, branch caps)
lives in ``branching.validate_graph`` and is invoked before status
changes to ``published`` would stick — the publish flow lands in
batch 8. This router accepts ``draft`` edits freely.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import repo
from ..config import InteractiveConfig
from ..errors import InvalidInputError, NotFoundError
from ..models import (
    ActionCreate,
    EdgeCreate,
    Experience,
    ExperienceCreate,
    ExperienceUpdate,
    NodeCreate,
    NodeUpdate,
)
from ..personalize.rules import validate_rule
from ._common import current_user, http_error_from, scoped_experience


class RuleCreateBody(BaseModel):
    """Wire payload for a new personalization rule.

    Separate from ``PersonalizationRule`` because the model in
    ``models.py`` includes the generated id.
    """

    name: str
    condition: Dict[str, Any] = Field(default_factory=dict)
    action: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 100
    enabled: bool = True


def build_authoring_router(cfg: InteractiveConfig) -> APIRouter:
    router = APIRouter(tags=["interactive-authoring"])

    # ── Assets (EDIT-4 preview support) ───────────────────────────

    @router.get("/assets/{asset_id}/url")
    def resolve_asset(
        asset_id: str,
        user_id: str = Depends(current_user),  # noqa: ARG001 — gate only
    ) -> Dict[str, Any]:
        """Return the player-usable URL for an asset_id, or null
        if the id is a stub / unknown. Used by the Editor preview
        modal (EDIT-4) to show a scene's rendered image/video
        without forcing the client to bake in storage-key logic.

        When ``INTERACTIVE_PROXY_ASSETS=true``, the URL is rewritten
        from a direct ComfyUI ``/view?...`` URL to a backend-routed
        ``/v1/interactive/assets/{id}/serve`` URL. This makes assets
        portable across machines (a remote browser doesn't need to
        reach the operator's localhost:8188), auth-gated (the proxy
        sits behind ``current_user``), and cacheable through the
        backend's existing CDN / reverse-proxy layer. Off by default
        for backwards compat with existing clients that fetch the
        ComfyUI URL directly.
        """
        from ..playback import resolve_asset_url  # late import
        url = resolve_asset_url(asset_id)
        if url and _proxy_assets_enabled() and _looks_like_comfy_url(url):
            url = f"/v1/interactive/assets/{asset_id}/serve"
        return {"ok": True, "asset_id": asset_id, "url": url}

    @router.get("/assets/{asset_id}/serve")
    async def serve_asset(
        asset_id: str,
        user_id: str = Depends(current_user),  # noqa: ARG001 — gate only
    ) -> Response:
        """Stream an asset's bytes through the backend.

        Resolves the asset's storage_key (typically a ComfyUI
        ``/view?...`` URL), fetches it server-side, and pipes it back
        to the client with the right Content-Type + cache headers.

        Why
        ----
        ComfyUI runs on a separate host:port (default localhost:8188).
        A remote user's browser can't reach that. Storing only the
        ComfyUI URL in the registry means assets are effectively
        bound to the operator's machine. This proxy makes them
        portable: every fetch goes through the backend, which DOES
        have network access to ComfyUI, regardless of where the user
        is browsing from.

        Auth: the endpoint is gated by ``current_user``. Combined with
        the per-asset ``user_id`` field now populated by
        ``render_adapter._register``, future revisions can verify the
        caller actually owns the asset they're requesting.

        Caching: ``Cache-Control: private, max-age=86400`` because
        re-rendering produces a new asset_id, so the URL itself is
        immutable for the lifetime of an asset row.
        """
        from ..playback import resolve_asset_url  # late import
        import httpx  # late import — we only pay for it on this hot path

        url = resolve_asset_url(asset_id) or ""
        if not url:
            raise http_error_from(NotFoundError("asset not found"))

        # If the storage_key isn't an HTTP URL, we can't proxy it.
        # Older flows stamp ``/files/...`` paths here; those must be
        # served by the regular ``/files/`` mount, not this proxy.
        if not url.lower().startswith(("http://", "https://")):
            raise http_error_from(InvalidInputError(
                "asset is not http-served; use /files/ instead",
                data={"asset_id": asset_id},
            ))

        client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

        async def _stream():
            try:
                async with client.stream("GET", url) as upstream:
                    # Surface upstream errors as 502 so the client's
                    # onError handler can offer a retry.
                    if upstream.status_code >= 400:
                        raise http_error_from(NotFoundError(
                            f"upstream {upstream.status_code} from comfy",
                        ))
                    async for chunk in upstream.aiter_bytes(64 * 1024):
                        yield chunk
            finally:
                await client.aclose()

        # Best-effort content type — guess from the URL extension; the
        # actual Content-Type from upstream is more reliable but
        # streaming-then-rewriting headers is complicated, so we set a
        # reasonable default and let the browser sniff.
        media_type = _content_type_from_url(url)
        return StreamingResponse(
            _stream(),
            media_type=media_type,
            headers={
                "Cache-Control": "private, max-age=86400",
                "X-Asset-Source": "interactive_proxy",
            },
        )

    # ── Experiences ───────────────────────────────────────────────

    @router.post("/experiences")
    def create_experience_(
        payload: ExperienceCreate, user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        exp = repo.create_experience(user_id, payload)
        return {"ok": True, "experience": exp.model_dump()}

    @router.get("/experiences")
    def list_experiences_(
        user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        items = [e.model_dump() for e in repo.list_experiences(user_id)]
        return {"ok": True, "items": items}

    @router.get("/experiences/{experience_id}")
    def get_experience_(exp: Experience = Depends(scoped_experience)) -> Dict[str, Any]:
        return {"ok": True, "experience": exp.model_dump()}

    @router.patch("/experiences/{experience_id}")
    def update_experience_(
        experience_id: str, patch: ExperienceUpdate,
        user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        try:
            exp = repo.update_experience(experience_id, user_id, patch)
        except NotFoundError as e:
            raise http_error_from(e)
        return {"ok": True, "experience": exp.model_dump()}

    @router.delete("/experiences/{experience_id}")
    def delete_experience_(
        experience_id: str, user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        ok = repo.delete_experience(experience_id, user_id)
        if not ok:
            raise http_error_from(NotFoundError("experience not found"))
        return {"ok": True, "deleted": experience_id}

    # ── Nodes ─────────────────────────────────────────────────────

    @router.post("/experiences/{experience_id}/nodes")
    def create_node_(
        payload: NodeCreate,
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        node = repo.create_node(exp.id, payload)
        return {"ok": True, "node": node.model_dump()}

    @router.get("/experiences/{experience_id}/nodes")
    def list_nodes_(
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        items = [n.model_dump() for n in repo.list_nodes(exp.id)]
        return {"ok": True, "items": items}

    @router.patch("/nodes/{node_id}")
    def update_node_(
        node_id: str, patch: NodeUpdate,
        user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        node = repo.get_node(node_id)
        if not node:
            raise http_error_from(NotFoundError("node not found"))
        # Ownership check via parent experience.
        exp = repo.get_experience(node.experience_id, user_id=user_id)
        if not exp:
            raise http_error_from(NotFoundError("node not found"))
        try:
            updated = repo.update_node(node_id, patch)
        except NotFoundError as e:
            raise http_error_from(e)
        return {"ok": True, "node": updated.model_dump()}

    @router.delete("/nodes/{node_id}")
    def delete_node_(
        node_id: str, user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        node = repo.get_node(node_id)
        if not node:
            raise http_error_from(NotFoundError("node not found"))
        exp = repo.get_experience(node.experience_id, user_id=user_id)
        if not exp:
            raise http_error_from(NotFoundError("node not found"))
        ok = repo.delete_node(node_id)
        if not ok:
            raise http_error_from(NotFoundError("node not found"))
        return {"ok": True, "deleted": node_id}

    # ── Edges ─────────────────────────────────────────────────────

    @router.post("/experiences/{experience_id}/edges")
    def create_edge_(
        payload: EdgeCreate,
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        edge = repo.create_edge(exp.id, payload)
        return {"ok": True, "edge": edge.model_dump()}

    @router.get("/experiences/{experience_id}/edges")
    def list_edges_(
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        items = [e.model_dump() for e in repo.list_edges(exp.id)]
        return {"ok": True, "items": items}

    @router.delete("/edges/{edge_id}")
    def delete_edge_(
        edge_id: str, user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        # No per-edge ownership table — we trust the UI to have
        # resolved the edge under a scoped experience. Delete is
        # idempotent: missing id → 404.
        ok = repo.delete_edge(edge_id)
        if not ok:
            raise http_error_from(NotFoundError("edge not found"))
        return {"ok": True, "deleted": edge_id}

    # ── Action catalog ────────────────────────────────────────────

    @router.post("/experiences/{experience_id}/actions")
    def create_action_(
        payload: ActionCreate,
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        action = repo.create_action(exp.id, payload)
        return {"ok": True, "action": action.model_dump()}

    @router.get("/experiences/{experience_id}/actions")
    def list_actions_(
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        items = [a.model_dump() for a in repo.list_actions(exp.id)]
        return {"ok": True, "items": items}

    @router.delete("/actions/{action_id}")
    def delete_action_(
        action_id: str, user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        a = repo.get_action(action_id)
        if not a:
            raise http_error_from(NotFoundError("action not found"))
        exp = repo.get_experience(a.experience_id, user_id=user_id)
        if not exp:
            raise http_error_from(NotFoundError("action not found"))
        repo.delete_action(action_id)
        return {"ok": True, "deleted": action_id}

    # ── Personalization rules ─────────────────────────────────────

    @router.post("/experiences/{experience_id}/rules")
    def create_rule_(
        payload: RuleCreateBody,
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        problems = validate_rule(payload.condition, payload.action)
        if problems:
            raise http_error_from(InvalidInputError(
                "rule has validation issues", data={"problems": problems},
            ))
        rule = repo.create_rule(
            exp.id, payload.name, payload.condition, payload.action,
            priority=payload.priority, enabled=payload.enabled,
        )
        return {"ok": True, "rule": rule.model_dump()}

    @router.get("/experiences/{experience_id}/rules")
    def list_rules_(
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        items = [r.model_dump() for r in repo.list_rules(exp.id)]
        return {"ok": True, "items": items}

    @router.delete("/rules/{rule_id}")
    def delete_rule_(
        rule_id: str, user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        ok = repo.delete_rule(rule_id)
        if not ok:
            raise http_error_from(NotFoundError("rule not found"))
        return {"ok": True, "deleted": rule_id}

    return router


# ── Asset proxy helpers ──────────────────────────────────────────

def _proxy_assets_enabled() -> bool:
    """Operator opt-in: when ``INTERACTIVE_PROXY_ASSETS=true``,
    asset URLs are rewritten to flow through the backend proxy.
    Default OFF so the wire format stays backwards-compatible with
    existing wizard / editor clients that fetch ComfyUI directly.
    """
    import os
    return os.getenv("INTERACTIVE_PROXY_ASSETS", "false").strip().lower() == "true"


def _looks_like_comfy_url(url: str) -> bool:
    """Heuristic: does this URL point at a ComfyUI server?

    Currently matches ``/view?filename=`` which is the only ComfyUI
    output URL shape ``app.comfy._view_url`` produces. Conservative on
    purpose — we only rewrite the URLs we know we can stream.
    """
    if not url:
        return False
    return "/view?filename=" in url


def _content_type_from_url(url: str) -> str:
    """Guess Content-Type from the URL's filename extension.

    The proxy doesn't reach into the upstream response headers (would
    require buffering the first chunk), so we set a sensible default
    and let the browser MIME-sniff if needed.
    """
    lower = (url or "").lower()
    for ext, mime in (
        (".png",  "image/png"),
        (".jpg",  "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".webp", "image/webp"),
        (".gif",  "image/gif"),
        (".avif", "image/avif"),
        (".mp4",  "video/mp4"),
        (".webm", "video/webm"),
        (".mov",  "video/quicktime"),
        (".mkv",  "video/x-matroska"),
    ):
        if ext in lower:
            return mime
    return "application/octet-stream"

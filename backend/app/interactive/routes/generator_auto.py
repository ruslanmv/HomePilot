"""
Stage-2 auto-generator HTTP surface.

POST /v1/interactive/experiences/{id}/auto-generate
  body   {}        (may be extended with overrides later)
  200    {
    "ok": true,
    "source": "llm" | "heuristic",
    "already_generated": false,
    "node_count": 9,
    "edge_count": 11,
    "action_count": 4
  }

GET /v1/interactive/experiences/{id}/auto-generate/stream (PIPE-2)
  200    text/event-stream.
         Emits one SSE frame per generation phase (generating_graph,
         persisting_nodes, persisting_edges, persisting_actions,
         seeding_rule, running_qa) then a final ``result`` frame
         with the same payload as POST /auto-generate, then
         ``done``. Lets the wizard spinner show real progress
         instead of a timer-driven animation.

Idempotent: if the experience already has any nodes, both routes
return ``already_generated: true`` without mutating anything.
Owners can re-run generation by clearing the graph via the
authoring API first.

Non-destructive: the existing ``/seed-graph`` authoring route is
unchanged — it's the deterministic path the 5-step wizard uses.
``/auto-generate`` is the one-shot Stage-2 path the new one-box
wizard uses after Stage-1's ``/plan-auto`` populated the project.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from .. import repo
from ..config import InteractiveConfig
from ..errors import CapacityError, NotFoundError
from ..models import ActionCreate, EdgeCreate, Experience, NodeCreate, NodeUpdate
from ..planner.autogen_llm import (
    ActionSpec, EdgeSpec, GraphPlan, NodeSpec, generate_graph,
)
# Import the render_adapter MODULE (not the function) so tests
# can patch ``render_adapter.render_scene_async`` on the source
# module and have the patch visible to us without depending on a
# stable top-level import binding that may drift across module
# purge/reimport cycles.
from ..playback import persona_asset_library as _persona_asset_library
from ..playback import render_adapter as _render_adapter
# Additive: Persona-Live-aware render-set selector. Scopes the eager
# pre-render pass so persona_live_play skips the wasted scene-graph
# pass and Standard projects only render reachable depth. Falls back
# to the original target list when the selector has no signal.
from ..playback.render_set import filter_targets_for_play
from ..qa import run_qa
from ._common import http_error_from, scoped_experience


log = logging.getLogger(__name__)


# Event callback used by the shared auto-generate body. Accepts
# the event kind (plain string) + a small JSON-able payload dict.
EventHook = Callable[[str, Dict[str, Any]], None]


def build_generator_auto_router(cfg: InteractiveConfig) -> APIRouter:
    router = APIRouter(tags=["interactive-planner"])

    @router.post("/experiences/{experience_id}/auto-generate")
    async def auto_generate(
        experience_id: str,  # noqa: ARG001 — scoped_experience consumes it
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        """Generate + persist a full scene graph from the experience
        brief. Idempotent on repeat calls while the graph exists.
        """
        return await _run_auto_generate(exp, cfg, on_event=_noop_hook)

    @router.get("/experiences/{experience_id}/auto-generate/stream")
    async def auto_generate_stream(
        experience_id: str,  # noqa: ARG001 — scoped_experience consumes it
        exp: Experience = Depends(scoped_experience),
    ) -> StreamingResponse:
        """SSE stream mirroring the non-streaming route's result
        shape. Emits one frame per generation phase so the wizard
        spinner can surface real progress to the author.
        """
        return StreamingResponse(
            _auto_generate_event_stream(exp, cfg),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @router.get("/experiences/{experience_id}/generate-all/stream")
    async def generate_all_stream(
        experience_id: str,  # noqa: ARG001 — scoped_experience consumes it
        exp: Experience = Depends(scoped_experience),
    ) -> StreamingResponse:
        """Full-project generation stream.

        Chains Stage-2 graph generation (``/auto-generate``) +
        eager per-scene asset rendering behind a single SSE feed,
        so the wizard modal can stay up through the entire
        plan → graph → render → ready lifecycle.

        Events emitted (in order):
          started / generating_graph / graph_generated /
          persisting_nodes / persisting_edges / persisting_actions
          / seeding_rule / running_qa / qa_done
          rendering_started { total } / rendering_scene {index,
            total, scene_id, title} / scene_rendered | scene_skipped
            | scene_render_failed (per scene)
          rendering_done / result / done

        Scene rendering respects ``audience_profile.render_media_type``
        (image vs video) and is idempotent: a second call on an
        already-rendered experience short-circuits to ``result``
        without re-running the render loop (the render flag being
        off also skips rendering cleanly).
        """
        return StreamingResponse(
            _generate_all_event_stream(exp, cfg),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @router.post("/experiences/{experience_id}/nodes/{node_id}/render")
    async def render_single_node(
        experience_id: str,  # noqa: ARG001 — scoped_experience consumes it
        node_id: str,
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        """Re-render one scene node (EDIT-3).

        Author-facing recovery + polish path: the Editor's
        "Regenerate scene" button calls this after the user
        tweaks a scene's narration or notices a bad asset.
        Bypasses the idempotent ``asset_ids`` skip that the bulk
        stream applies so a second call on a rendered node still
        produces a fresh asset.

        Response shape mirrors the per-scene events the bulk
        stream emits, so the same UI code can display both paths:
            { ok, scene_id, title, status, asset_id?, reason? }
        """
        node = repo.get_node(node_id)
        if not node or node.experience_id != exp.id:
            raise http_error_from(NotFoundError("node not found"))

        media_type = _media_type_from_audience(exp)
        persona_ctx = _persona_render_context(exp)
        pseudo_session = f"ixs_eager_{exp.id}"
        status = "rendered"
        asset_id: Optional[str] = None
        reason: Optional[str] = None

        try:
            asset_id = await _render_adapter.render_scene_async(
                scene_prompt=(node.narration or node.title or "Scene").strip(),
                duration_sec=int(node.duration_sec or 5),
                session_id=pseudo_session,
                persona_hint=persona_ctx["hint"] or (exp.description or "").strip(),
                media_type=media_type,
                edit_recipe=persona_ctx["edit_recipe"],
                persona_project_id=persona_ctx["persona_project_id"],
                user_id=str(getattr(exp, "user_id", "") or ""),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "single_scene_render_failed exp=%s scene=%s: %s",
                exp.id, node_id, str(exc)[:200],
            )
            return {
                "ok": False,
                "scene_id": node_id,
                "title": node.title,
                "status": "failed",
                "reason": f"{exc.__class__.__name__}: {str(exc)[:180]}",
            }

        if not asset_id:
            return {
                "ok": True,
                "scene_id": node_id,
                "title": node.title,
                "status": "skipped",
                "reason": "render_disabled_or_empty",
            }

        # Replace (not append) — this endpoint is the explicit
        # "re-render this scene" intent; keeping stale ids from a
        # prior run would confuse the player's latest-asset logic.
        try:
            repo.update_node(node_id, NodeUpdate(asset_ids=[asset_id]))
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "single_scene_node_patch_failed exp=%s scene=%s: %s",
                exp.id, node_id, str(exc)[:200],
            )
            # Asset is still registered; just report the patch miss.
            status = "rendered_but_not_attached"

        return {
            "ok": True,
            "scene_id": node_id,
            "title": node.title,
            "status": status,
            "asset_id": asset_id,
            "media_type": media_type,
        }

    return router


def _noop_hook(_kind: str, _payload: Dict[str, Any]) -> None:
    """Default event hook for the non-streaming path — the HTTP
    response already carries the final result, so the hook has
    nothing to do."""
    return None


# ── Shared body ────────────────────────────────────────────────

async def _run_auto_generate(
    exp: Experience, cfg: InteractiveConfig,
    *, on_event: EventHook,
) -> Dict[str, Any]:
    """End-to-end stage-2 generation body shared by both the POST
    and streaming routes. Emits phase events through ``on_event``
    so the SSE handler can forward them to the client.

    Raises the same typed HTTPException the POST route raised
    before — the streaming path converts that to an ``error``
    frame on its side.
    """
    on_event("started", {"experience_id": exp.id})

    existing = repo.list_nodes(exp.id)
    if existing:
        existing_edges = repo.list_edges(exp.id)
        existing_actions = repo.list_actions(exp.id)
        payload = {
            "ok": True,
            "source": "existing",
            "already_generated": True,
            "node_count": len(existing),
            "edge_count": len(existing_edges),
            "action_count": len(existing_actions),
        }
        on_event("already_generated", {
            "node_count": len(existing),
            "edge_count": len(existing_edges),
            "action_count": len(existing_actions),
        })
        return payload

    on_event("generating_graph", {})
    plan: GraphPlan = await generate_graph(exp, cfg=cfg)
    on_event("graph_generated", {
        "source": plan.source,
        "node_count": len(plan.nodes),
        "edge_count": len(plan.edges),
    })

    if len(plan.nodes) > cfg.max_nodes_per_experience:
        raise http_error_from(CapacityError(
            "generated graph exceeds node cap",
            data={"nodes": len(plan.nodes), "cap": cfg.max_nodes_per_experience},
        ))

    on_event("persisting_nodes", {"count": len(plan.nodes)})
    id_map = _persist_nodes(exp.id, plan.nodes)

    on_event("persisting_edges", {"count": len(plan.edges)})
    _persist_edges(exp.id, plan.edges, id_map)

    actions = list(plan.actions)
    if not actions:
        actions = list(_default_actions(exp))
    on_event("persisting_actions", {"count": len(actions)})
    _persist_actions(exp.id, actions)

    on_event("seeding_rule", {})
    rule_count = _persist_default_rule(exp.id)

    on_event("running_qa", {})
    qa_verdict = ""
    qa_issues: List[Dict[str, Any]] = []
    qa_counts: Dict[str, int] = {}
    try:
        summary = run_qa(exp)
        qa_verdict = summary.verdict
        qa_issues = list(summary.issues)
        qa_counts = dict(summary.counts)
    except Exception:  # noqa: BLE001 — QA is best-effort
        qa_verdict = "skipped"
    on_event("qa_done", {"verdict": qa_verdict, "counts": qa_counts})

    return {
        "ok": True,
        "source": plan.source,
        "already_generated": False,
        "node_count": len(plan.nodes),
        "edge_count": len(plan.edges),
        "action_count": len(actions),
        "rule_count": rule_count,
        "qa": {
            "verdict": qa_verdict,
            "counts": qa_counts,
            "issues": qa_issues,
        },
        "warnings": list(plan.warnings),
    }


# ── SSE plumbing ──────────────────────────────────────────────

async def _auto_generate_event_stream(
    exp: Experience, cfg: InteractiveConfig,
) -> AsyncGenerator[bytes, None]:
    """Run the shared body and yield SSE frames per phase event.

    Bridges the sync ``on_event`` callback to an asyncio queue so
    the generator can ``await`` and yield frames as phases tick.
    """
    queue: "asyncio.Queue[Optional[Dict[str, Any]]]" = asyncio.Queue()

    def _hook(kind: str, payload: Dict[str, Any]) -> None:
        try:
            queue.put_nowait({"type": kind, "payload": dict(payload or {})})
        except Exception:  # noqa: BLE001
            log.exception("auto-generate sse enqueue failed")

    async def _task() -> Optional[Dict[str, Any]]:
        try:
            return await _run_auto_generate(exp, cfg, on_event=_hook)
        finally:
            await queue.put(None)

    runner = asyncio.create_task(_task())

    # Drain phase events.
    while True:
        item = await queue.get()
        if item is None:
            break
        yield _sse_frame(item).encode("utf-8")

    # Resolve the result (or surface the error).
    try:
        final = await runner
    except Exception as exc:  # noqa: BLE001
        log.exception("auto-generate stream crashed")
        yield _sse_frame({
            "type": "error",
            "payload": {
                "reason": f"{exc.__class__.__name__}: {str(exc)[:200]}",
            },
        }).encode("utf-8")
        yield _sse_frame({"type": "done"}).encode("utf-8")
        return

    if final is not None:
        yield _sse_frame({"type": "result", "payload": final}).encode("utf-8")
    yield _sse_frame({"type": "done"}).encode("utf-8")


def _sse_frame(obj: Dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, separators=(',', ':'))}\n\n"


def _default_actions(experience: Optional[Experience] = None) -> List[ActionSpec]:
    """Minimal action set so every generated project can be played.

    Persona Live Play gets the intent-driven Level-1 catalog so a
    fall-through (e.g. plan.actions came back empty) doesn't saddle
    the panel with "Continue / Ask for a hint" — those actions don't
    have a reaction mapping in ``_INTENT_CATALOG`` and the Live Action
    panel would render them as dead buttons.
    """
    project_type = ""
    if experience is not None:
        project_type = str(getattr(experience, "project_type", "") or "").strip().lower()

    if project_type == "persona_live":
        return [
            ActionSpec(label="Say something playful",  intent_code="say_playful",   xp_award=5),
            ActionSpec(label="Compliment her",          intent_code="compliment",    xp_award=5),
            ActionSpec(label="Ask about her day",       intent_code="ask_about_her", xp_award=5),
            ActionSpec(label="Stay quiet and listen",   intent_code="stay_quiet",    xp_award=3),
        ]

    return [
        ActionSpec(label="Continue", intent_code="continue", xp_award=5),
        ActionSpec(label="Ask for a hint", intent_code="request_hint", xp_award=3),
    ]


def _persist_default_rule(experience_id: str) -> int:
    """Seed one personalization rule so the feature is visibly
    wired on first open. Warm-up rule: when affinity is low (a
    fresh viewer), prefer a warm tone so the first scene lands
    friendly. Returns the rule count actually created (always 1,
    but pattern-compatible with future multi-rule seeding).
    """
    try:
        repo.create_rule(
            experience_id,
            name="Warm up new viewers",
            condition={"max_affinity": 0.3},
            action={"prefer_tone": "warm", "bump_affinity": 0.01},
            priority=100,
            enabled=True,
        )
        return 1
    except Exception:  # noqa: BLE001 — rule seeding is best-effort
        return 0


# ── Persistence helpers ───────────────────────────────────────

def _persist_nodes(
    experience_id: str, nodes: List[NodeSpec],
) -> Dict[str, str]:
    id_map: Dict[str, str] = {}
    for n in nodes:
        created = repo.create_node(experience_id, NodeCreate(
            kind=n.kind, title=n.title, narration=n.narration,
        ))
        id_map[n.local_id] = created.id
    return id_map


def _persist_edges(
    experience_id: str, edges: List[EdgeSpec], id_map: Dict[str, str],
) -> None:
    for e in edges:
        src = id_map.get(e.from_local_id)
        dst = id_map.get(e.to_local_id)
        if not src or not dst:
            continue  # autogen already dedup'd, but be safe
        trigger_payload: Dict[str, Any] = {}
        if e.label:
            trigger_payload["label"] = e.label
        repo.create_edge(experience_id, EdgeCreate(
            from_node_id=src, to_node_id=dst,
            trigger_kind=e.trigger_kind,
            trigger_payload=trigger_payload,
            ordinal=int(e.ordinal or 0),
        ))


def _persist_actions(
    experience_id: str, actions: List[ActionSpec],
) -> None:
    for i, a in enumerate(actions):
        repo.create_action(experience_id, ActionCreate(
            label=a.label,
            intent_code=a.intent_code or "choice",
            required_level=1,
            required_scheme="xp_level",
            required_metric_key="level",
            xp_award=int(a.xp_award or 0),
            cooldown_sec=0,
            ordinal=i,
        ))


# ── Full-project generation: graph + per-scene asset rendering ─

async def _run_generate_all(
    exp: Experience, cfg: InteractiveConfig,
    *, on_event: EventHook,
) -> Dict[str, Any]:
    """Chain ``/auto-generate`` + eager per-scene asset rendering +
    (for persona_live) the persona asset-library pre-render pack.

    Keeps every step idempotent + restart-safe:
      * graph generation skips when nodes already exist.
      * per-scene render skips nodes that already carry an
        ``asset_ids`` entry (previous run resumed).
      * library build is idempotent — re-runs skip asset ids that
        already exist in persona_appearance.asset_library.
      * render failures are non-fatal — we emit ``scene_render_failed``
        and continue so the editor still opens with a usable graph.
    """
    # Phase 1 — plan + graph + baseline wiring.
    plan_result = await _run_auto_generate(exp, cfg, on_event=on_event)

    # Phase 2 — per-scene asset rendering.
    render_stats = await _render_all_scenes(exp, on_event=on_event)

    # Phase 3 — persona asset library pre-render pack. Only runs for
    # persona_live projects with a linked persona_project_id; for
    # everyone else this is a no-op. Makes the last wizard step
    # responsible for the whole pack so the player hits an instant
    # library on day one instead of waiting for a separate
    # library/build call to land.
    library_stats = await _build_persona_library(exp, on_event=on_event)

    # Phase 4 — attach library assets to the persona_live scene
    # graph so the editor preview ("Right? It's Complicated…")
    # actually shows an image per scene instead of the
    # "No asset rendered yet" placeholder. The library lives on the
    # persona project; the scene nodes live on the experience. This
    # phase bridges the two by mapping scene titles to library asset
    # ids — see ``_link_persona_library_assets``. No-op for non-
    # persona_live projects and no-op when the library build itself
    # was skipped or failed.
    link_stats = await _link_persona_library_assets(
        exp, library_stats, on_event=on_event,
    )

    return {
        **plan_result,
        "rendering": render_stats,
        "library": library_stats,
        "library_linking": link_stats,
    }


def _list_experience_nodes(experience_id: str) -> List[Any]:
    """Module-level seam wrapping ``repo.list_nodes`` so tests can
    patch this one function deterministically. Same rationale as
    ``_lookup_persona_project``: directly monkey-patching ``repo``
    sometimes loses to test-ordering when other tests have already
    bound ``repo`` into their own namespaces.
    """
    return list(repo.list_nodes(experience_id))


def _patch_node_assets(node_id: str, asset_ids: List[str]) -> None:
    """Module-level seam wrapping ``repo.update_node`` (same reasoning
    as ``_list_experience_nodes``)."""
    repo.update_node(node_id, NodeUpdate(asset_ids=asset_ids))


def _lookup_persona_project(persona_project_id: str) -> Dict[str, Any]:
    """Load a persona project record for the library build phase.

    Factored out so tests can patch this one function deterministically
    instead of juggling ``sys.modules["app.projects"]`` — that path is
    fragile when other tests have already imported the real module and
    cached references into namespaces we can't reach from a monkeypatch.
    """
    try:
        from ... import projects  # late import — heavy
    except Exception:  # noqa: BLE001
        return {}
    try:
        return projects.get_project_by_id(persona_project_id) or {}
    except Exception:  # noqa: BLE001
        return {}


async def _build_persona_library(
    exp: Experience, *, on_event: EventHook,
) -> Dict[str, Any]:
    """Phase-3 wizard pass — build the persona's pre-render pack.

    Runs only when:
      * ``project_type == "persona_live"`` (Standard Interactive has
        no persona anchor, so there's nothing to pre-render)
      * ``audience_profile.persona_project_id`` is set
      * the persona has a committed portrait (without it the edit
        recipes abort — see ``render_adapter.render_scene_async``)

    Any failure here is non-fatal: the wizard still reports success
    and the operator can re-run the pack later via the explicit
    ``/persona-live/{pid}/library/build`` endpoint. Emits
    ``library_*`` SSE events so the wizard modal can show a coverage
    bar as the pack fills in.
    """
    project_type = str(getattr(exp, "project_type", "") or "").strip().lower()
    if project_type != "persona_live":
        return {"skipped": True, "reason": "not_persona_live"}

    ap = getattr(exp, "audience_profile", None) or {}
    persona_project_id = ""
    if isinstance(ap, dict):
        persona_project_id = str(ap.get("persona_project_id") or "").strip()
    if not persona_project_id:
        return {"skipped": True, "reason": "no_persona_project_id"}

    # Bind the module-level import to the local name ``pal`` so tests
    # can swap the reference via
    # ``monkeypatch.setattr(generator_auto, "_persona_asset_library", stub)``
    # and this function consistently sees the stub without fighting
    # ``sys.modules`` or late-import caching.
    pal = _persona_asset_library
    from ..playback import resolve_asset_url
    from ..playback.render_adapter import render_scene_async

    # Resolve allow_explicit + persona identity from the project via
    # the module-level helper — tests patch _lookup_persona_project
    # directly to avoid fragile sys.modules monkeypatches.
    persona_data = _lookup_persona_project(persona_project_id) or {}
    persona_agent = persona_data.get("persona_agent") if isinstance(persona_data, dict) else {}
    safety = persona_agent.get("safety") if isinstance(persona_agent, dict) else {}
    allow_explicit = bool((safety or {}).get("allow_explicit", False))
    persona_hint = ", ".join([
        str((persona_data or {}).get("name") or "").strip(),
        str((persona_agent or {}).get("persona_class") or "").strip(),
    ]).strip(", ").strip()

    # Persist the wizard's adult_llm pick onto the persona project so
    # the Persona Live runtime (which only has persona_id, not the
    # experience id) can read it via _load_persona. Idempotent — only
    # fires when ``audience_profile.adult_llm`` is set on this
    # experience and the value isn't already on the persona. Skipped
    # silently when projects.update_project isn't reachable.
    ap_for_llm = getattr(exp, "audience_profile", None) or {}
    wizard_adult_llm = ""
    if isinstance(ap_for_llm, dict):
        wizard_adult_llm = str(ap_for_llm.get("adult_llm") or "").strip()
    if wizard_adult_llm:
        existing_llm = ""
        if isinstance(persona_agent, dict):
            existing_llm = str(persona_agent.get("llm_override") or "").strip()
        if existing_llm != wizard_adult_llm:
            try:
                from ... import projects as _projects_mod  # late import
                _projects_mod.update_project(persona_project_id, {
                    "persona_agent": {"llm_override": wizard_adult_llm},
                })
                on_event("persona_llm_persisted", {
                    "persona_project_id": persona_project_id,
                    "model": wizard_adult_llm,
                })
            except Exception as exc:  # noqa: BLE001 — non-fatal
                log.warning(
                    "persona_llm_persist_failed persona=%s: %s",
                    persona_project_id, str(exc)[:200],
                )

    # Confirm the persona has a portrait — render_scene_async bails
    # out when the edit recipe can't anchor, so check up front and
    # emit a clear reason if this is why we're skipping.
    appearance = persona_data.get("persona_appearance") if isinstance(persona_data, dict) else {}
    selected_filename = ""
    if isinstance(appearance, dict):
        selected_filename = str(appearance.get("selected_filename") or "").strip()
    if not selected_filename:
        on_event("library_skipped", {"reason": "no_persona_portrait"})
        return {"skipped": True, "reason": "no_persona_portrait"}

    # Tier 2 is the v1 spec's "should pre-generate" set — Tier 1 base
    # (idles + all expressions + default outfit + medium camera) PLUS
    # pose variations + close-up / wide camera + extra outfits. That
    # adds ~6 renders (~25-30s on a 4080) for the day-one variety the
    # spec calls out as "users feel the persona react instantly with
    # variety, not just five expressions in the same hoodie." Tier 3
    # (environments + formal outfit) stays opt-in via the explicit
    # ``/library/build`` endpoint to keep the wizard fast.
    target_tier = 2

    async def _render_one(spec: pal.AssetSpec) -> Optional["pal.RenderResult"]:
        # Edit-hint → workflow mapping. The four "img2img on the
        # persona portrait" hints (expression / pose / outfit /
        # composition) all route to avatar_expression_change because
        # the actual diffusion is identical — what changes is the
        # prompt fragment + denoise. The shipped edit_inpaint_cn
        # workflow needs a mask + ControlNet input we don't have at
        # library-build time, so reusing the plain img2img graph
        # there avoids a "Required input is missing: noise_mask"
        # failure for cam_medium / cam_close_up assets.
        workflow_map = {
            "expression":  "avatar_expression_change",
            "pose":        "avatar_body_pose",
            "outfit":      "avatar_inpaint_outfit",
            "bg":          "change_background",
            "composition": "avatar_expression_change",
        }
        edit_recipe = {
            "workflow_id": workflow_map.get(spec.edit_hint, "edit"),
            "category": spec.kind,
            "params": {"mode": "img2img", "steps": 28, "cfg": 5.0, "denoise": 0.45},
            "locks": ["face"] if spec.edit_hint == "expression" else [],
        }
        scene_prompt = (
            f"{spec.prompt_fragment}, identity locked, same subject, tasteful"
        )
        try:
            asset_id = await render_scene_async(
                scene_prompt=scene_prompt,
                duration_sec=5,
                session_id=f"wizard_lib_{persona_project_id}",
                persona_hint=persona_hint,
                media_type="image",
                edit_recipe=edit_recipe,
                persona_project_id=persona_project_id,
                user_id=str(getattr(exp, "user_id", "") or ""),
            )
        except Exception as exc:  # noqa: BLE001 — per-asset failures non-fatal
            log.warning(
                "wizard_library_asset_error persona=%s asset=%s: %s",
                persona_project_id, spec.asset_id, str(exc)[:200],
            )
            return None
        if not asset_id:
            return None
        url = str(resolve_asset_url(asset_id) or "")
        if not url:
            return None
        # Return BOTH ids — registry asset_id powers the editor preview
        # + Phase-4 scene-link path; the URL powers the runtime fast-
        # path lookup. See pal.RenderResult / AssetRecord docstrings.
        return pal.RenderResult(asset_id=asset_id, url=url)

    def _library_progress(kind: str, payload: Dict[str, Any]) -> None:
        on_event(f"library_{kind}", payload)

    try:
        stats = await pal.build_library(
            persona_project_id,
            render_fn=_render_one,
            max_tier=target_tier,
            allow_explicit=allow_explicit,
            on_progress=_library_progress,
        )
    except Exception as exc:  # noqa: BLE001 — whole-pass failure is non-fatal
        log.warning(
            "wizard_library_build_failed persona=%s: %s",
            persona_project_id, str(exc)[:200],
        )
        on_event("library_failed", {
            "persona_project_id": persona_project_id,
            "reason": f"{exc.__class__.__name__}: {str(exc)[:200]}",
        })
        return {"ok": False, "persona_project_id": persona_project_id}

    return {
        "ok": True,
        "persona_project_id": persona_project_id,
        "tier": target_tier,
        "allow_explicit": allow_explicit,
        "total": stats.total,
        "rendered": stats.rendered,
        "skipped": stats.skipped,
        "failed": stats.failed,
    }


# Substring → library asset_id mapping for the persona_live scene
# spine. Keys are the lowercase scene title fragments produced by
# ``_persona_live_graph`` in autogen_llm.py; matched in the order
# below (most specific first). Anything that doesn't match leaves
# the scene unlinked — safer than guessing a wrong asset.
_PERSONA_LIVE_TITLE_TO_ASSET: List[Tuple[str, str]] = [
    ("playful smirk",       "expr_smirk"),
    ("soft blush",          "expr_blush"),
    ("warm smile",          "expr_smile"),
    ("quiet anticipation",  "expr_neutral_attentive"),
    ("first moment",        "idle_neutral"),
    ("keep the moment",     "idle_soft_smile"),
    ("until next time",     "idle_soft_smile"),
]


async def _link_persona_library_assets(
    exp: Experience, library_stats: Dict[str, Any], *, on_event: EventHook,
) -> Dict[str, Any]:
    """Attach library asset URLs to persona_live scene nodes.

    The library build phase pre-renders the persona's reaction pack
    (idle / expressions / outfit / camera) and persists it onto the
    PERSONA project's ``persona_appearance.asset_library`` dict. The
    scene nodes live on the EXPERIENCE — separate row, no automatic
    join. Without this phase the editor's graph view shows
    "No asset rendered yet" on every scene even though the rendered
    images are sitting in the library waiting to be referenced.

    Strategy: walk the experience's scene nodes, match each title
    against ``_PERSONA_LIVE_TITLE_TO_ASSET``, look up the library
    URL, and patch ``asset_ids = [url]`` on the node. The play
    route's ``_resolve_scene_asset_url`` accepts ``/files/...`` and
    ``http(s)://`` URLs as direct refs, so no separate registry hop
    is needed.

    No-op when:
      * library_stats says the build was skipped or failed
      * the persona project has no library yet (operator hasn't run
        the build pass)
      * the scene title doesn't map to any library asset
      * the scene already has asset_ids (idempotent — re-runs leave
        existing scene assets alone)
    """
    if not isinstance(library_stats, dict) or not library_stats.get("ok"):
        return {"ok": False, "linked": 0, "reason": "library_not_built"}

    persona_project_id = str(library_stats.get("persona_project_id") or "").strip()
    if not persona_project_id:
        return {"ok": False, "linked": 0, "reason": "no_persona_project_id"}

    # Late import — pal is already top-level in this module via
    # _persona_asset_library; the local rebind keeps the lookup path
    # consistent with _build_persona_library.
    pal = _persona_asset_library

    library = pal.load_library(persona_project_id)
    if not library:
        return {"ok": False, "linked": 0, "reason": "library_empty"}

    linked = 0
    skipped_already_linked = 0
    skipped_no_match = 0
    for node in _list_experience_nodes(exp.id):
        if getattr(node, "kind", "") != "scene":
            continue
        if list(getattr(node, "asset_ids", []) or []):
            skipped_already_linked += 1
            continue
        title_lc = str(getattr(node, "title", "") or "").strip().lower()
        if not title_lc:
            skipped_no_match += 1
            continue

        asset_id_in_library: Optional[str] = None
        for needle, lib_id in _PERSONA_LIVE_TITLE_TO_ASSET:
            if needle in title_lc:
                asset_id_in_library = lib_id
                break

        if asset_id_in_library is None:
            skipped_no_match += 1
            continue

        row = library.get(asset_id_in_library) if isinstance(library, dict) else None
        if not isinstance(row, dict):
            continue
        # Prefer the registry asset_id (the ``a_xxx`` id from
        # asset_registry.register_asset). The editor preview hits
        # ``GET /v1/interactive/assets/{asset_id}/url`` which expects
        # a registry id, NOT the raw ComfyUI URL — we used to write
        # ``row["asset_url"]`` (the URL) here, which got URL-encoded
        # into the path and 404'd. Falls back to the URL only when the
        # registry id is missing (older library rows from before this
        # field existed) so the player still shows an image even if
        # the editor preview can't resolve it.
        registry_asset_id = str(row.get("registry_asset_id") or "").strip()
        url = str(row.get("asset_url") or "").strip()

        # Backfill: older library rows (rendered before
        # ``registry_asset_id`` existed) only carry ``asset_url``.
        # Reverse-look-up the registry by storage_key so we can write
        # the proper id to ``node.asset_ids`` instead of the raw URL.
        # Without this backfill, re-running the wizard against an
        # already-built library produced 404 storms in the editor
        # preview because Phase 4 fell back to the URL.
        if not registry_asset_id and url:
            try:
                from ...asset_registry import find_asset_id_by_storage_key
                found = find_asset_id_by_storage_key(url)
                if found:
                    registry_asset_id = found
                    # Patch the library row in place so subsequent
                    # link passes use the id directly without another
                    # registry hit.
                    row["registry_asset_id"] = found
                    pal.save_asset_record(persona_project_id, pal.AssetRecord(
                        asset_id=str(row.get("asset_id") or asset_id_in_library),
                        asset_url=url,
                        kind=str(row.get("kind") or "expression"),
                        tier=int(row.get("tier") or 1),
                        reaction_intent=str(row.get("reaction_intent") or ""),
                        registry_asset_id=found,
                        generated_at=float(row.get("generated_at") or 0.0),
                        source=str(row.get("source") or "library_build"),
                    ))
            except Exception as exc:  # noqa: BLE001 — backfill is best-effort
                log.warning(
                    "scene_link_backfill_failed exp=%s lib=%s: %s",
                    exp.id, asset_id_in_library, str(exc)[:200],
                )

        link_value = registry_asset_id or url
        if not link_value:
            continue

        try:
            _patch_node_assets(node.id, [link_value])
            linked += 1
            on_event("scene_linked", {
                "scene_id": node.id,
                "asset_id": asset_id_in_library,
                "registry_asset_id": registry_asset_id,
                "asset_url": url,
            })
        except Exception as exc:  # noqa: BLE001 — patching one node failing
            log.warning(
                "scene_link_failed exp=%s scene=%s lib=%s: %s",
                exp.id, node.id, asset_id_in_library, str(exc)[:200],
            )

    return {
        "ok": True,
        "persona_project_id": persona_project_id,
        "linked": linked,
        "skipped_already_linked": skipped_already_linked,
        "skipped_no_match": skipped_no_match,
    }


async def _render_all_scenes(
    exp: Experience, *, on_event: EventHook,
) -> Dict[str, Any]:
    """Iterate scenes + decision nodes; render each.

    Emits events per scene so the frontend modal can show a live
    'rendering 5 of 12' progress bar. Always resolves with a
    stats dict (total / rendered / skipped / failed) so the caller
    can summarise the run even when the render flag is off.
    """
    nodes = repo.list_nodes(exp.id)
    edges = repo.list_edges(exp.id)
    # Only scenes + decision beats need visual assets — endings
    # typically lean on the scene's trailing frame + a callout.
    targets = [
        n for n in nodes
        if n.kind in ("scene", "decision", "assessment", "remediation")
    ]
    # Additive scope filter: persona_live_play skips the whole pass
    # (own render pipeline); standard projects keep only reachable
    # nodes within the configured depth. Deferred nodes emit a
    # dedicated ``scene_deferred`` event so they don't collide with
    # the existing ``scene_skipped`` counter consumed by the UI and
    # by test_interactive_generate_all_stream.
    targets, _render_decisions = filter_targets_for_play(
        targets, experience=exp, edges=edges, nodes=nodes,
    )
    for _decision in _render_decisions:
        if not _decision.selected and _decision.reason != "already_rendered":
            on_event("scene_deferred", {
                "scene_id": _decision.node_id,
                "reason": _decision.reason,
            })
    total = len(targets)
    media_type = _media_type_from_audience(exp)
    persona_ctx = _persona_render_context(exp)
    on_event("rendering_started", {
        "total": total, "media_type": media_type,
    })

    rendered = 0
    skipped = 0
    failed = 0
    pseudo_session = f"ixs_eager_{exp.id}"

    for index, node in enumerate(targets, start=1):
        # Idempotency: a node that already carries an asset stays
        # as-is; rerunning generate-all shouldn't double-render.
        if node.asset_ids:
            skipped += 1
            on_event("scene_skipped", {
                "index": index, "total": total,
                "scene_id": node.id, "title": node.title,
                "reason": "already_rendered",
            })
            continue

        on_event("rendering_scene", {
            "index": index, "total": total,
            "scene_id": node.id, "title": node.title,
            "kind": node.kind,
        })

        try:
            asset_id = await _render_adapter.render_scene_async(
                scene_prompt=(node.narration or node.title or "Scene").strip(),
                duration_sec=int(node.duration_sec or 5),
                session_id=pseudo_session,
                persona_hint=persona_ctx["hint"] or (exp.description or "").strip(),
                media_type=media_type,
                edit_recipe=persona_ctx["edit_recipe"],
                persona_project_id=persona_ctx["persona_project_id"],
                user_id=str(getattr(exp, "user_id", "") or ""),
            )
        except Exception as exc:  # noqa: BLE001 — non-fatal per scene
            failed += 1
            log.warning(
                "generate_all_render_failed exp=%s scene=%s: %s",
                exp.id, node.id, str(exc)[:200],
            )
            on_event("scene_render_failed", {
                "index": index, "total": total,
                "scene_id": node.id, "title": node.title,
                "reason": f"{exc.__class__.__name__}: {str(exc)[:120]}",
            })
            continue

        if not asset_id:
            # Render flag off or adapter returned None cleanly.
            skipped += 1
            on_event("scene_skipped", {
                "index": index, "total": total,
                "scene_id": node.id, "title": node.title,
                "reason": "render_disabled_or_empty",
            })
            continue

        # Attach the asset id to the node so the player can load
        # the pre-rendered preview on open. Patch failures here
        # are swallowed — the asset still exists in the registry,
        # and the player has session-time render fallback anyway.
        try:
            repo.update_node(
                node.id, NodeUpdate(asset_ids=[asset_id]),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "generate_all_node_patch_failed exp=%s scene=%s: %s",
                exp.id, node.id, str(exc)[:200],
            )

        rendered += 1
        on_event("scene_rendered", {
            "index": index, "total": total,
            "scene_id": node.id, "title": node.title,
            "asset_id": asset_id,
        })

    stats = {
        "total": total,
        "rendered": rendered,
        "skipped": skipped,
        "failed": failed,
    }
    on_event("rendering_done", stats)
    return stats


def _media_type_from_audience(exp: Experience) -> str:
    """Read ``audience_profile.render_media_type`` off the
    experience. Mirrors the helper in routes/playback.py but stays
    local so this module has zero extra coupling."""
    ap = getattr(exp, "audience_profile", None) or {}
    if not isinstance(ap, dict):
        return "video"
    raw = str(ap.get("render_media_type") or "").strip().lower()
    return "image" if raw == "image" else "video"


def _persona_render_context(exp: Experience) -> Dict[str, Any]:
    """If this is a persona_live project with a linked persona id,
    force wizard-generated scenes through identity-preserving edit
    flow (img2img against the canonical portrait) instead of free
    txt2img.
    """
    ap = getattr(exp, "audience_profile", None) or {}
    if not isinstance(ap, dict):
        return {"persona_project_id": "", "hint": "", "edit_recipe": None}
    persona_project_id = str(ap.get("persona_project_id") or "").strip()
    if not persona_project_id:
        return {"persona_project_id": "", "hint": "", "edit_recipe": None}
    if str(getattr(exp, "project_type", "") or "").strip().lower() != "persona_live":
        return {"persona_project_id": "", "hint": "", "edit_recipe": None}

    hint = ""
    try:
        from ... import projects
        pdata = projects.get_project_by_id(persona_project_id) or {}
        if isinstance(pdata, dict):
            agent = pdata.get("persona_agent") if isinstance(pdata.get("persona_agent"), dict) else {}
            hint = ", ".join([
                str((pdata or {}).get("name") or "").strip(),
                str((agent or {}).get("persona_class") or "").strip(),
                str(((agent or {}).get("response_style") or {}).get("tone") if isinstance((agent or {}).get("response_style"), dict) else "").strip(),
            ]).strip(", ").strip()
    except Exception:
        hint = ""

    edit_recipe = {
        "workflow_id": "avatar_identity_reproject",
        "params": {"mode": "img2img", "steps": 28, "cfg": 5.2, "denoise": 0.42},
        "locks": ["face"],
    }
    return {
        "persona_project_id": persona_project_id,
        "hint": hint,
        "edit_recipe": edit_recipe,
    }


async def _generate_all_event_stream(
    exp: Experience, cfg: InteractiveConfig,
) -> AsyncGenerator[bytes, None]:
    """SSE plumbing for /generate-all/stream. Same asyncio.Queue
    bridge pattern as /auto-generate/stream — the sync on_event
    hook pushes events; the async generator yields them as SSE
    frames without blocking the orchestrator."""
    queue: "asyncio.Queue[Optional[Dict[str, Any]]]" = asyncio.Queue()

    def _hook(kind: str, payload: Dict[str, Any]) -> None:
        try:
            queue.put_nowait({"type": kind, "payload": dict(payload or {})})
        except Exception:  # noqa: BLE001
            log.exception("generate-all sse enqueue failed")

    async def _task() -> Optional[Dict[str, Any]]:
        try:
            return await _run_generate_all(exp, cfg, on_event=_hook)
        finally:
            await queue.put(None)

    runner = asyncio.create_task(_task())

    while True:
        item = await queue.get()
        if item is None:
            break
        yield _sse_frame(item).encode("utf-8")

    try:
        final = await runner
    except Exception as exc:  # noqa: BLE001
        log.exception("generate-all stream crashed")
        yield _sse_frame({
            "type": "error",
            "payload": {
                "reason": f"{exc.__class__.__name__}: {str(exc)[:200]}",
            },
        }).encode("utf-8")
        yield _sse_frame({"type": "done"}).encode("utf-8")
        return

    if final is not None:
        yield _sse_frame({"type": "result", "payload": final}).encode("utf-8")
    yield _sse_frame({"type": "done"}).encode("utf-8")

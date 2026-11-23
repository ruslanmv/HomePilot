"""
Provider factory (PR 2).

Turns a routing *target* string (see ``policies``) into a concrete
``ComputeProvider`` plus any per-call routing metadata. The existing PR 1
providers (``LocalComputeProvider``, ``OllaBridgeCloudComputeProvider``) live at
the package root and are re-exported here; new backends (OpenAI-compatible) live
in this subpackage.

``build_target`` returns ``None`` for a target that can't be built right now (a
missing/disabled source, an unconfigured cloud, a hop-limited gateway); the
router simply skips it and moves to the next candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..base import ComputeProvider
from ..local import LocalComputeProvider
from ..ollabridge_cloud import OllaBridgeCloudComputeProvider
from .hosted import HostedGatewayProvider
from .openai_compatible import OpenAICompatibleComputeProvider

__all__ = [
    "LocalComputeProvider",
    "OllaBridgeCloudComputeProvider",
    "OpenAICompatibleComputeProvider",
    "HostedGatewayProvider",
    "BuiltTarget",
    "build_target",
]


@dataclass
class BuiltTarget:
    target: str
    provider: ComputeProvider
    health_key: str
    remote: bool = False
    extra: dict[str, Any] = field(default_factory=dict)  # merged into call kwargs


def _cloud_token() -> str:
    """The bearer token for owner-scoped Cloud calls (devices, generation jobs).

    OllaBridge scopes devices to whoever the token belongs to, so the token
    decides *whose* machines a request can reach:

    * the signed-in user's own linked OllaBridge token, when they have one;
    * otherwise, on a single-user local install, the configured token (it is
      that user's own);
    * otherwise — the hosted, multi-user edition with no linked account —
      nothing. The operator's token is never used to reach devices on a
      user's behalf: it would address the operator's machines, not theirs.
    """
    from app.config import OLLABRIDGE_CLOUD_TOKEN
    from .. import routing
    try:
        from app.connectors.context import current_user_id
        user_id = current_user_id()
    except Exception:
        user_id = ""
    own = routing._user_cloud_token(user_id)
    if own:
        return own
    if routing.is_web():
        return ""
    return (OLLABRIDGE_CLOUD_TOKEN or "").strip()


def _build_cloud(settings) -> Optional[OllaBridgeCloudComputeProvider]:
    """Cloud relay provider from persisted settings + the caller's own token."""
    from app.config import OLLABRIDGE_CLOUD_TIMEOUT
    from .. import routing
    cloud_url = settings.cloud_url
    if not cloud_url:
        return None
    token = _cloud_token()
    if not token and routing.is_web():
        return None  # no linked account ⇒ no devices to reach (see _cloud_token)
    return OllaBridgeCloudComputeProvider(
        cloud_url,
        token,
        image_model=settings.cloud_image_model,
        video_model=settings.cloud_video_model,
        timeout=OLLABRIDGE_CLOUD_TIMEOUT,
    )


def _build_hosted(alias: str, settings) -> Optional[BuiltTarget]:
    """``provider:<alias>`` — chat through OllaBridge's provider selection."""
    from app.config import OLLABRIDGE_CLOUD_TIMEOUT
    from .. import routing
    from .hosted import HostedGatewayProvider
    if not settings.cloud_url or not alias:
        return None
    if not routing.gateway_allowed():
        # This request already came *from* the gateway (a persona it routed to
        # us). Sending it back could loop — answer with our own executor.
        return None
    try:
        from app.connectors.context import current_user_id
        user_id = current_user_id()
    except Exception:
        user_id = ""
    provider = HostedGatewayProvider(
        settings.cloud_url,
        alias,
        user_id=user_id,
        vision_alias=routing.hosted_alias("multimodal"),
        timeout=OLLABRIDGE_CLOUD_TIMEOUT,
    )
    return BuiltTarget(f"provider:{alias}", provider, f"provider:{alias}", remote=True)


def build_target(target: str, *, settings=None) -> Optional[BuiltTarget]:
    from .. import registry
    from .. import secrets

    settings = settings or registry.load_settings()

    if target == "local":
        return BuiltTarget("local", LocalComputeProvider(), "local", remote=False)

    if target in ("ollabridge_cloud", "ollabridge:any"):
        cloud = _build_cloud(settings)
        if cloud is None:
            return None
        return BuiltTarget(target, cloud, "ollabridge_cloud", remote=True)

    if target.startswith("device:"):
        device_id = target.split(":", 1)[1]
        cloud = _build_cloud(settings)
        if cloud is None:
            return None
        return BuiltTarget(
            target,
            cloud,
            f"device:{device_id}",
            remote=True,
            extra={"routing": {"device_id": device_id}},
        )

    if target.startswith("source:"):
        source_id = target.split(":", 1)[1]
        source = registry.get_source(source_id)
        if source is None or not source.enabled:
            return None
        key = f"source:{source_id}"
        if source.kind == "local":
            return BuiltTarget(target, LocalComputeProvider(), key, remote=False)
        if source.kind in ("openai_compatible", "vllm", "openai_api"):
            # SSRF defense-in-depth: never dial a blocked endpoint even if a bad
            # base_url slipped into the registry.
            from ..netguard import is_safe_outbound_url
            if not is_safe_outbound_url(source.base_url):
                return None
            api_key = secrets.get_secret(source.credential_ref)
            provider = OpenAICompatibleComputeProvider(
                source.base_url or "",
                api_key,
                default_model=(source.meta or {}).get("default_model"),
            )
            return BuiltTarget(target, provider, key, remote=True)
        if source.kind in ("ollabridge", "ollabridge_cloud"):
            cloud = _build_cloud(settings)
            if cloud is None:
                return None
            return BuiltTarget(target, cloud, key, remote=True)
        return None

    if target.startswith("provider:"):
        return _build_hosted(target.split(":", 1)[1], settings)

    return None

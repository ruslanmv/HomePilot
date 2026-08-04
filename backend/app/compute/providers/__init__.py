"""
Provider factory (PR 2).

Turns a routing *target* string (see ``policies``) into a concrete
``ComputeProvider`` plus any per-call routing metadata. The existing PR 1
providers (``LocalComputeProvider``, ``OllaBridgeCloudComputeProvider``) live at
the package root and are re-exported here; new backends (OpenAI-compatible) live
in this subpackage.

``build_target`` returns ``None`` for a target that can't be built right now (a
missing/disabled source, an unconfigured cloud, an unimplemented alias); the
router simply skips it and moves to the next candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..base import ComputeProvider
from ..local import LocalComputeProvider
from ..ollabridge_cloud import OllaBridgeCloudComputeProvider
from .openai_compatible import OpenAICompatibleComputeProvider

__all__ = [
    "LocalComputeProvider",
    "OllaBridgeCloudComputeProvider",
    "OpenAICompatibleComputeProvider",
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


def _build_cloud(settings) -> Optional[OllaBridgeCloudComputeProvider]:
    """Cloud relay provider from persisted settings + env token (PR 1 parity)."""
    from app.config import OLLABRIDGE_CLOUD_TIMEOUT, OLLABRIDGE_CLOUD_TOKEN
    cloud_url = settings.cloud_url
    if not cloud_url:
        return None
    return OllaBridgeCloudComputeProvider(
        cloud_url,
        OLLABRIDGE_CLOUD_TOKEN,
        image_model=settings.cloud_image_model,
        video_model=settings.cloud_video_model,
        timeout=OLLABRIDGE_CLOUD_TIMEOUT,
    )


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

    # "provider:<alias>" (hosted-provider aliases) not yet implemented here.
    return None

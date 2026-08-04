"""
Compute Sources & Routing — data model (PR 2).

Plain dataclasses (no pydantic dependency) for the entities the registry
persists and the router resolves against. Each has ``from_dict``/``to_dict`` so
they round-trip through SQLite JSON columns and the admin API.

Entities mirror the design doc:

* ``ComputeSource``  — a place work can run (local, an OllaBridge relay, an
  OpenAI-compatible endpoint, …).
* ``ComputeDevice``  — a concrete machine advertised by a source (a Colab T4, a
  home RTX 4090). Devices are reported by the source; the registry caches them.
* ``ModelManifest``  — what a model *is* on a device: runtime, capabilities,
  digest, VRAM need. Capabilities come from the manifest, not name-guessing.
* ``ModelRoute``     — a per-model (or per-modality-default) routing decision:
  where to run it, what to fall back to, and the policy that governs it.
* ``ComputeSettings``— global, persisted settings that used to be env-only
  flags (compute mode, burst gating, cloud defaults) plus per-modality defaults.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# ---- controlled vocabularies (kept as plain strings for forward-compat) -----

SourceKind = str      # local | ollabridge | openai_compatible | comfyui | ...
ExecutionType = str   # local | direct | relay
Runtime = str         # ollama | vllm | comfyui | openai_api
Capability = str      # chat | vision | image | video | edit | multimodal
Modality = str        # chat | multimodal | image | video | edit
Strategy = str        # pinned | prefer_local | prefer_remote | lowest_cost
Privacy = str         # local_only | private_nodes | hosted_allowed

VALID_STRATEGIES = ("pinned", "prefer_local", "prefer_remote", "lowest_cost")
VALID_PRIVACY = ("local_only", "private_nodes", "hosted_allowed")


def _now() -> float:
    return time.time()


@dataclass
class ComputeSource:
    id: str
    name: str
    kind: SourceKind = "local"
    base_url: Optional[str] = None
    credential_ref: Optional[str] = None  # key into the secrets store, never the secret
    enabled: bool = True
    execution_type: ExecutionType = "local"
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ComputeSource":
        return cls(
            id=d["id"],
            name=d.get("name") or d["id"],
            kind=d.get("kind", "local"),
            base_url=d.get("base_url"),
            credential_ref=d.get("credential_ref"),
            enabled=bool(d.get("enabled", True)),
            execution_type=d.get("execution_type", "local"),
            meta=dict(d.get("meta") or {}),
        )


@dataclass
class ComputeDevice:
    id: str
    source_id: str
    name: str = ""
    online: bool = False
    ephemeral: bool = False
    gpu_name: Optional[str] = None
    vram_mb: Optional[int] = None
    utilization: Optional[float] = None
    capacity: int = 1
    active_jobs: int = 0
    last_heartbeat: Optional[float] = None  # epoch seconds

    def heartbeat_age_s(self, now: Optional[float] = None) -> Optional[float]:
        if self.last_heartbeat is None:
            return None
        return (now or _now()) - self.last_heartbeat

    def is_online(self, ttl_s: float = 45.0, now: Optional[float] = None) -> bool:
        """Online if the flag is set *and* the heartbeat hasn't expired."""
        if not self.online:
            return False
        age = self.heartbeat_age_s(now)
        return age is None or age <= ttl_s

    def has_capacity(self) -> bool:
        return self.capacity <= 0 or self.active_jobs < self.capacity

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ComputeDevice":
        return cls(
            id=d["id"],
            source_id=d["source_id"],
            name=d.get("name", ""),
            online=bool(d.get("online", False)),
            ephemeral=bool(d.get("ephemeral", False)),
            gpu_name=d.get("gpu_name"),
            vram_mb=d.get("vram_mb"),
            utilization=d.get("utilization"),
            capacity=int(d.get("capacity", 1)),
            active_jobs=int(d.get("active_jobs", 0)),
            last_heartbeat=d.get("last_heartbeat"),
        )


@dataclass
class ModelManifest:
    id: str
    runtime: Runtime = "ollama"
    capabilities: list[Capability] = field(default_factory=list)
    device_ids: list[str] = field(default_factory=list)
    digest: Optional[str] = None
    minimum_vram_mb: Optional[int] = None
    workflow_version: Optional[str] = None

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ModelManifest":
        return cls(
            id=d["id"],
            runtime=d.get("runtime", "ollama"),
            capabilities=list(d.get("capabilities") or []),
            device_ids=list(d.get("device_ids") or []),
            digest=d.get("digest"),
            minimum_vram_mb=d.get("minimum_vram_mb"),
            workflow_version=d.get("workflow_version"),
        )


@dataclass
class ModelRoute:
    """A per-model routing decision. ``model_id`` is the key; ``modality`` scopes
    it (a name can differ across image/chat)."""
    modality: Modality
    model_id: str
    primary_target: str
    fallback_targets: list[str] = field(default_factory=list)
    strategy: Strategy = "pinned"
    max_queue_seconds: Optional[int] = None
    max_cost_usd: Optional[float] = None
    privacy: Privacy = "private_nodes"

    def normalized_strategy(self) -> Strategy:
        return self.strategy if self.strategy in VALID_STRATEGIES else "pinned"

    def normalized_privacy(self) -> Privacy:
        return self.privacy if self.privacy in VALID_PRIVACY else "private_nodes"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ModelRoute":
        return cls(
            modality=d["modality"],
            model_id=d["model_id"],
            primary_target=d["primary_target"],
            fallback_targets=list(d.get("fallback_targets") or []),
            strategy=d.get("strategy", "pinned"),
            max_queue_seconds=d.get("max_queue_seconds"),
            max_cost_usd=d.get("max_cost_usd"),
            privacy=d.get("privacy", "private_nodes"),
        )


@dataclass
class ModalityDefault:
    """Default routing for a whole modality when no per-model route matches."""
    modality: Modality
    strategy: Strategy = "prefer_local"
    target: Optional[str] = None
    fallback_targets: list[str] = field(default_factory=list)
    privacy: Privacy = "private_nodes"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ModalityDefault":
        return cls(
            modality=d["modality"],
            strategy=d.get("strategy", "prefer_local"),
            target=d.get("target"),
            fallback_targets=list(d.get("fallback_targets") or []),
            privacy=d.get("privacy", "private_nodes"),
        )


@dataclass
class ComputeSettings:
    """Persisted global settings — the successor to the env-only flags.

    ``from_env()`` seeds these from ``app.config`` so an unconfigured install
    behaves exactly as before; the registry persists overrides on top.
    """
    compute_mode: str = "local"                 # local | ollabridge_cloud | auto
    burst_requires_premium: bool = False
    premium_enabled: bool = False
    cloud_url: Optional[str] = None
    cloud_image_model: str = "flux-schnell"
    cloud_video_model: str = "ltx-video"
    device_heartbeat_ttl_s: float = 45.0
    modality_defaults: dict[str, ModalityDefault] = field(default_factory=dict)
    # PR 5 — cost-aware routing. Budget is a per-request USD cap (None = no cap).
    # The catalog is a timestamped, operator-supplied price map (never hardcoded);
    # it can be synced from OllaBridge's provider registry.
    max_cost_usd_per_request: Optional[float] = None
    cost_catalog: dict[str, Any] = field(default_factory=dict)

    def default_for(self, modality: Modality) -> Optional[ModalityDefault]:
        return self.modality_defaults.get(modality)

    def to_dict(self) -> dict[str, Any]:
        return {
            "compute_mode": self.compute_mode,
            "burst_requires_premium": self.burst_requires_premium,
            "premium_enabled": self.premium_enabled,
            "cloud_url": self.cloud_url,
            "cloud_image_model": self.cloud_image_model,
            "cloud_video_model": self.cloud_video_model,
            "device_heartbeat_ttl_s": self.device_heartbeat_ttl_s,
            "modality_defaults": {
                k: v.to_dict() for k, v in self.modality_defaults.items()
            },
            "max_cost_usd_per_request": self.max_cost_usd_per_request,
            "cost_catalog": self.cost_catalog,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ComputeSettings":
        defaults = {
            k: ModalityDefault.from_dict({**v, "modality": v.get("modality", k)})
            for k, v in (d.get("modality_defaults") or {}).items()
        }
        return cls(
            compute_mode=(d.get("compute_mode") or "local").strip().lower(),
            burst_requires_premium=bool(d.get("burst_requires_premium", False)),
            premium_enabled=bool(d.get("premium_enabled", False)),
            cloud_url=d.get("cloud_url"),
            cloud_image_model=d.get("cloud_image_model", "flux-schnell"),
            cloud_video_model=d.get("cloud_video_model", "ltx-video"),
            device_heartbeat_ttl_s=float(d.get("device_heartbeat_ttl_s", 45.0)),
            modality_defaults=defaults,
            max_cost_usd_per_request=d.get("max_cost_usd_per_request"),
            cost_catalog=dict(d.get("cost_catalog") or {}),
        )

    @classmethod
    def from_env(cls) -> "ComputeSettings":
        """Seed from ``app.config`` (deployment defaults)."""
        from app import config
        mode = (getattr(config, "HOMEPILOT_COMPUTE_MODE", "local") or "local").strip().lower()
        if mode not in ("local", "ollabridge_cloud", "auto"):
            mode = "local"
        return cls(
            compute_mode=mode,
            burst_requires_premium=bool(getattr(config, "COMPUTE_BURST_REQUIRES_PREMIUM", False)),
            premium_enabled=bool(getattr(config, "PREMIUM_COMPUTE_ENABLED", False)),
            cloud_url=getattr(config, "OLLABRIDGE_CLOUD_URL", None) or None,
            cloud_image_model=getattr(config, "OLLABRIDGE_CLOUD_IMAGE_MODEL", "flux-schnell"),
            cloud_video_model=getattr(config, "OLLABRIDGE_CLOUD_VIDEO_MODEL", "ltx-video"),
        )

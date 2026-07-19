"""
Studio Model Manager (essay-to-video pipeline, Batch 3).

Makes "download it from Civitai" an actual capability instead of the manual
wget + hand-edit process MODELS_README.md used to describe. Wraps the
official Civitai REST API (civitai.com - see sourcing rule 1) and Hugging
Face Hub file downloads, verifies hashes, resolves licenses against an
allowlist, and registers installs into a JSON registry that
providers.available_image_models()/available_video_models() already read -
no hand-edits, no code changes per model.

Three sourcing rules, from the design doc
(docs/design/essay-to-video/BATCH-3-model-manager.md):

1. civitai.com, never civitai.red. This pipeline is 100% SFW; the base URL
   is a constant, not a config knob.
2. Hugging Face first for base checkpoints, Civitai for style layers
   (LoRAs/finetunes). MODEL_SOURCE_PREFERENCE=huggingface_first records the
   policy; the two download paths exist either way.
3. The essay pipeline's picker never surfaces the mature-lane models
   (essay_pipeline_models() filters them; HomePilot's general pickers are
   untouched).

License rule: register() refuses any model without a resolved license row.
That's the guard against pulling something not cleared for a monetized
channel - a hard stop, not a warning.

ADDITIVE ONLY - reuses backend/app/civitai.py (CivitaiClient) and
backend/app/providers.py (models path + registry read); modifies neither.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

ModelType = Literal["image", "video", "lora"]


# ============================================================================
# License allowlist
# ============================================================================

class LicenseRow(BaseModel):
    """A resolved license decision for one model family."""
    key: str                     # substring matched against model/repo ids
    license: str
    commercial_ok: bool
    notes: str = ""


# Mid-2026 state, per the design doc's license table. Order matters: first
# substring match wins. A model that matches no row cannot be registered.
LICENSE_ALLOWLIST: List[LicenseRow] = [
    LicenseRow(key="flux.2-klein", license="Apache-2.0", commercial_ok=True,
               notes="Default image model for the essay pipeline."),
    LicenseRow(key="flux2-klein", license="Apache-2.0", commercial_ok=True),
    LicenseRow(key="flux.2-dev", license="BFL non-commercial", commercial_ok=False,
               notes="Paid license required for commercial use - manual hero shots only."),
    LicenseRow(key="flux2-dev", license="BFL non-commercial", commercial_ok=False),
    LicenseRow(key="stable-diffusion-3.5", license="Stability Community License",
               commercial_ok=True, notes="Free under $1M annual revenue."),
    LicenseRow(key="sd3.5", license="Stability Community License", commercial_ok=True),
    LicenseRow(key="wan2.2", license="Apache-2.0", commercial_ok=True),
    LicenseRow(key="wan-2.2", license="Apache-2.0", commercial_ok=True),
    LicenseRow(key="mochi", license="Apache-2.0", commercial_ok=True),
    LicenseRow(key="ltx-video", license="LTX community license", commercial_ok=True,
               notes="Verify current terms for monetized channels."),
    LicenseRow(key="hunyuanvideo", license="Tencent community license", commercial_ok=True,
               notes="Verify current terms for monetized channels."),
    LicenseRow(key="qwen-image", license="UNRESOLVED", commercial_ok=False,
               notes="Design doc: verify at integration time. Blocked until resolved."),
    # Rows below cover the essay-video bundle components (bundles.py)
    LicenseRow(key="sd_xl_base", license="CreativeML Open RAIL++-M", commercial_ok=True),
    LicenseRow(key="sdxl", license="CreativeML Open RAIL++-M", commercial_ok=True),
    LicenseRow(key="svd", license="Stability AI Community License", commercial_ok=True,
               notes="Free under $1M annual revenue."),
    LicenseRow(key="flux1-schnell", license="Apache-2.0", commercial_ok=True),
    LicenseRow(key="flux-schnell", license="Apache-2.0", commercial_ok=True),
    LicenseRow(key="hunyuan-video", license="Tencent community license", commercial_ok=True,
               notes="Verify current terms for monetized channels."),
    LicenseRow(key="ltx", license="LTX community license", commercial_ok=True,
               notes="Verify current terms for monetized channels."),
]

# Model IDs (and matching substrings) that belong to HomePilot's mature
# lane. The essay pipeline filters these out entirely - not just by default.
MATURE_LANE_PATTERNS = ("pony", "uncensored", "nsfw")


def resolve_license(model_id: str) -> Optional[LicenseRow]:
    """First allowlist row whose key appears in the model id (case-insensitive)."""
    needle = (model_id or "").lower()
    for row in LICENSE_ALLOWLIST:
        if row.key in needle:
            return row
    return None


# ============================================================================
# Data shapes
# ============================================================================

class CivitaiModelSummary(BaseModel):
    model_id: int
    version_id: Optional[int] = None
    name: str
    type: str = ""
    creator: str = ""
    download_count: int = 0
    allow_commercial_use: str = ""       # Civitai's own field, informative only
    nsfw: bool = False


class InstalledModel(BaseModel):
    id: str                              # picker id, e.g. "flux2-klein"
    model_type: ModelType
    filename: str
    path: str
    sha256: str = ""
    source: Literal["huggingface", "civitai"]
    source_ref: str = ""                 # repo_id or civitai version id
    license: str = ""
    commercial_ok: bool = False
    workflow: str = ""                   # ComfyUI workflow this maps to
    installed_at: float = Field(default_factory=time.time)


# ============================================================================
# Registry (read by providers.available_*_models(), written here)
# ============================================================================

def registry_path() -> Path:
    p = os.getenv("MODEL_REGISTRY_PATH", "").strip()
    if p:
        return Path(p)
    return Path(__file__).resolve().parents[2] / "data" / "installed_models.json"


def read_registry() -> List[Dict[str, Any]]:
    try:
        with open(registry_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_registry(entries: List[Dict[str, Any]]) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2)
    tmp.replace(path)


# ============================================================================
# The manager
# ============================================================================

class ModelManager:
    # Rule 1: the PG front door, hard-coded. Never civitai.red.
    CIVITAI_BASE = "https://civitai.com/api/v1"

    def __init__(self, api_key: Optional[str] = None, models_dir: Optional[Path] = None):
        self.api_key = (api_key or os.getenv("CIVITAI_API_KEY", "")).strip() or None
        if models_dir is None:
            from ..providers import get_comfy_models_path
            models_dir = get_comfy_models_path()
        self.models_dir = Path(models_dir)
        self.source_preference = os.getenv(
            "MODEL_SOURCE_PREFERENCE", "huggingface_first").strip()

    # ── Search ──────────────────────────────────────────────────────────────

    async def search_civitai(self, query: str, model_type: str = "image",
                             sfw_only: bool = True, limit: int = 20
                             ) -> List[CivitaiModelSummary]:
        """SFW-only search against civitai.com. sfw_only=False is accepted for
        signature compatibility but ignored - this pipeline never requests
        NSFW results (rule 1/3)."""
        from ..civitai import CivitaiClient, CivitaiSearchQuery

        client = CivitaiClient(api_key=self.api_key)
        raw = await client.search_models(CivitaiSearchQuery(
            query=query, model_type=model_type, limit=limit, nsfw=False))

        out: List[CivitaiModelSummary] = []
        for item in raw.get("items", []):
            if item.get("nsfw"):
                continue  # belt and braces on top of the SFW query
            versions = item.get("modelVersions") or []
            out.append(CivitaiModelSummary(
                model_id=item.get("id", 0),
                version_id=(versions[0].get("id") if versions else None),
                name=item.get("name", ""),
                type=item.get("type", ""),
                creator=(item.get("creator") or {}).get("username", ""),
                download_count=(item.get("stats") or {}).get("downloadCount", 0),
                allow_commercial_use=str(item.get("allowCommercialUse", "")),
                nsfw=bool(item.get("nsfw")),
            ))
        return out

    # ── Downloads ───────────────────────────────────────────────────────────

    def _download_stream(self, url: str, dest: Path,
                         headers: Optional[Dict[str, str]] = None) -> str:
        """Stream a file to dest, returning its sha256."""
        import httpx

        dest.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with httpx.stream("GET", url, headers=headers or {}, timeout=None,
                          follow_redirects=True) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=1 << 20):
                    fh.write(chunk)
                    digest.update(chunk)
        tmp.replace(dest)
        return digest.hexdigest()

    def download_from_huggingface(self, repo_id: str, filename: str,
                                  model_type: ModelType = "image",
                                  subdir: str = "checkpoints",
                                  revision: str = "main") -> InstalledModel:
        """Rule 2: base checkpoints come from official Hugging Face repos."""
        license_row = resolve_license(f"{repo_id}/{filename}")
        if license_row is None:
            raise PermissionError(
                f"No resolved license row for '{repo_id}/{filename}'. "
                "Add it to LICENSE_ALLOWLIST before installing (design §7.3).")

        url = f"https://huggingface.co/{repo_id}/resolve/{revision}/{filename}"
        headers = {}
        hf_token = os.getenv("HF_TOKEN", "").strip()
        if hf_token:
            headers["Authorization"] = f"Bearer {hf_token}"

        dest = self.models_dir / subdir / filename
        sha = self._download_stream(url, dest, headers)

        return InstalledModel(
            id=_picker_id(filename), model_type=model_type,
            filename=filename, path=str(dest), sha256=sha,
            source="huggingface", source_ref=repo_id,
            license=license_row.license, commercial_ok=license_row.commercial_ok,
        )

    async def download_by_version_id(self, version_id: int,
                                     model_type: ModelType = "lora",
                                     subdir: str = "loras") -> InstalledModel:
        """Rule 2: Civitai is the style-layer source (LoRAs/finetunes)."""
        import httpx

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{self.CIVITAI_BASE}/model-versions/{version_id}",
                                 headers=headers)
            r.raise_for_status()
            meta = r.json()

        model_meta = meta.get("model") or {}
        if model_meta.get("nsfw"):
            raise PermissionError("NSFW model refused: the essay pipeline is SFW-only.")

        name = f"{model_meta.get('name', 'model')} @ {meta.get('name', version_id)}"
        license_row = resolve_license(name) or self._license_from_civitai(model_meta)
        if license_row is None:
            raise PermissionError(
                f"No resolvable license for Civitai version {version_id} ('{name}'). "
                "Refusing to install (design §7.3).")

        files = meta.get("files") or []
        primary = next((f for f in files if f.get("primary")), files[0] if files else None)
        if not primary:
            raise ValueError(f"Civitai version {version_id} has no downloadable files")

        filename = primary.get("name") or f"civitai-{version_id}.safetensors"
        url = primary.get("downloadUrl") or f"{self.CIVITAI_BASE}/download/models/{version_id}"
        dest = self.models_dir / subdir / filename
        sha = self._download_stream(url, dest, headers)

        declared = ((primary.get("hashes") or {}).get("SHA256") or "").lower()
        if declared and declared != sha:
            dest.unlink(missing_ok=True)
            raise ValueError(f"SHA256 mismatch for {filename}: "
                             f"declared {declared[:12]}…, got {sha[:12]}…")

        return InstalledModel(
            id=_picker_id(filename), model_type=model_type,
            filename=filename, path=str(dest), sha256=sha,
            source="civitai", source_ref=str(version_id),
            license=license_row.license, commercial_ok=license_row.commercial_ok,
        )

    @staticmethod
    def _license_from_civitai(model_meta: Dict[str, Any]) -> Optional[LicenseRow]:
        """Derive a license row from Civitai's allowCommercialUse when the
        model isn't in the static allowlist. 'None'/missing -> unresolvable."""
        allow = model_meta.get("allowCommercialUse")
        values = {str(v).lower() for v in (allow if isinstance(allow, list) else [allow])}
        if values & {"image", "rentcivit", "rent", "sell"}:
            return LicenseRow(key="civitai-declared", license="Civitai: commercial use declared",
                              commercial_ok=True,
                              notes=f"allowCommercialUse={sorted(values)}")
        return None

    # ── Registration ────────────────────────────────────────────────────────

    def register(self, model: InstalledModel, workflow: str = "") -> None:
        """Make an installed model selectable. Refuses unlicensed models
        (defense in depth - the download paths already check)."""
        if not model.license or model.license == "UNRESOLVED":
            raise PermissionError(
                f"Refusing to register '{model.id}': no resolved license row.")
        if model.workflow == "" and workflow:
            model.workflow = workflow

        entries = read_registry()
        entries = [e for e in entries if e.get("id") != model.id]
        entries.append(json.loads(model.model_dump_json()))
        _write_registry(entries)

    def installed(self) -> List[InstalledModel]:
        return [InstalledModel(**e) for e in read_registry()]


def _picker_id(filename: str) -> str:
    """checkpoint filename -> stable picker id (lowercase, no extension)."""
    stem = Path(filename).stem.lower()
    return re.sub(r"[^a-z0-9.]+", "-", stem).strip("-")


# ============================================================================
# Essay-pipeline model filtering (rule 3)
# ============================================================================

def essay_pipeline_models(model_type: str = "image") -> List[str]:
    """The model list the essay pipeline's picker shows: the general list
    minus the mature lane, entirely - not just defaulted away."""
    from ..providers import available_image_models, available_video_models

    models = available_image_models() if model_type == "image" else available_video_models()
    return [m for m in models
            if not any(pat in m.lower() for pat in MATURE_LANE_PATTERNS)]


# ============================================================================
# Background install jobs (downloads are long; endpoints return 202 + poll)
# ============================================================================

_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def submit_install(kind: str, **kwargs: Any) -> Dict[str, Any]:
    """kind: 'huggingface' (repo_id, filename, model_type, subdir) or
    'civitai' (version_id, model_type, subdir). Returns the job descriptor."""
    job_id = str(uuid.uuid4())
    job = {"id": job_id, "kind": kind, "status": "running",
           "params": kwargs, "error": "", "model": None,
           "started_at": time.time()}
    with _JOBS_LOCK:
        _JOBS[job_id] = job

    def _run() -> None:
        try:
            mgr = ModelManager()
            if kind == "huggingface":
                model = mgr.download_from_huggingface(
                    repo_id=kwargs["repo_id"], filename=kwargs["filename"],
                    model_type=kwargs.get("model_type", "image"),
                    subdir=kwargs.get("subdir", "checkpoints"))
            elif kind == "civitai":
                import asyncio
                model = asyncio.run(mgr.download_by_version_id(
                    version_id=int(kwargs["version_id"]),
                    model_type=kwargs.get("model_type", "lora"),
                    subdir=kwargs.get("subdir", "loras")))
            else:
                raise ValueError(f"Unknown install kind: {kind}")
            mgr.register(model, workflow=kwargs.get("workflow", ""))
            with _JOBS_LOCK:
                job["status"] = "done"
                job["model"] = json.loads(model.model_dump_json())
        except Exception as e:
            with _JOBS_LOCK:
                job["status"] = "error"
                job["error"] = str(e)

    threading.Thread(target=_run, daemon=True).start()
    return {"id": job_id, "status": "running"}


def get_install_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None

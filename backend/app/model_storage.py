"""
Model storage locations — where ComfyUI models (image, video, edit, upscale…) live.

The built-in location is the existing ``models/comfy`` folder (``providers.get_comfy_models_path``)
and is never moved or changed. Extra locations — e.g. an external drive, ``E:\\homepilot-models``
— can be added, and one location is chosen as the target for new downloads. ComfyUI reads models
from all of them (``--extra-model-paths-config`` written here, one file per OS runtime), and
HomePilot's "is it installed" checks look in all of them.

Stored in ``<data dir>/model-storage.json``::

    {"locations": [{"path": "/mnt/e/homepilot-models", "label": "External E:"}],
     "download_target": "/mnt/e/homepilot-models"}        # or "builtin"

With no file, everything behaves exactly as before (one location, ``models/comfy``).

    GET /v1/models/storage   locations with free space, the download target
    PUT /v1/models/storage   {"locations": [{path, label?}], "download_target": "builtin" | path}
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/models/storage", tags=["models"])

MAX_LOCATIONS = 5
BUILTIN = "builtin"

# ComfyUI model folders created in (and mapped from) every extra location. The names are the
# same as under models/comfy, so a location is laid out exactly like the built-in one.
MODEL_FOLDERS = [
    "checkpoints", "diffusion_models", "unet", "clip", "text_encoders", "clip_vision", "vae",
    "loras", "controlnet", "upscale_models", "embeddings", "hypernetworks", "style_models",
    "photomaker", "instantid", "ipadapter", "insightface", "pulid", "gfpgan", "sams", "rembg",
    "facerestore_models", "vae_approx", "gligen",
]


# ── paths ──────────────────────────────────────────────────────────────────────

def _data_dir() -> Path:
    from .users import _get_db_path
    return Path(_get_db_path()).resolve().parent


def _config_file() -> Path:
    return _data_dir() / "model-storage.json"


def builtin_root() -> Path:
    from .providers import get_comfy_models_path
    return Path(get_comfy_models_path())


def is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


_WIN_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def to_local_path(raw: str) -> Path:
    """A path as this backend sees it. Under WSL a Windows path (E:\\x) becomes /mnt/e/x."""
    raw = (raw or "").strip().strip('"').strip("'")
    if not raw:
        raise ValueError("empty path")
    if _WIN_PATH.match(raw):
        if is_wsl():
            drive, rest = raw[0].lower(), raw[2:].replace("\\", "/").lstrip("/")
            return Path(f"/mnt/{drive}") / rest
        if os.name == "nt":
            return Path(raw)
        raise ValueError(f"{raw} is a Windows path, but this HomePilot runs on Linux")
    p = Path(os.path.expanduser(raw))
    if not p.is_absolute():
        raise ValueError(f"{raw} is not an absolute path")
    return p


def to_windows_path(p: Path) -> Optional[str]:
    """The Windows spelling of a WSL path (/mnt/e/x -> E:\\x), for the Windows ComfyUI."""
    s = str(p)
    m = re.match(r"^/mnt/([a-z])(/.*)?$", s)
    if m:
        return f"{m.group(1).upper()}:" + (m.group(2) or "/").replace("/", "\\")
    try:
        out = subprocess.run(["wslpath", "-w", s], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def display_path(p: Path) -> str:
    """What to show the user: the Windows form under WSL when it is a Windows drive."""
    if is_wsl():
        w = to_windows_path(p)
        if w and re.match(r"^[A-Z]:\\", w):
            return w
    return str(p)


# ── config ─────────────────────────────────────────────────────────────────────

def load_config() -> Dict[str, Any]:
    try:
        data = json.loads(_config_file().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {"locations": [l for l in data.get("locations", []) if isinstance(l, dict) and l.get("path")],
                    "download_target": data.get("download_target") or BUILTIN}
    except (OSError, ValueError):
        pass
    return {"locations": [], "download_target": BUILTIN}


def extra_roots() -> List[Path]:
    """Configured extra locations that exist right now (an unplugged drive is skipped)."""
    out: List[Path] = []
    for loc in load_config()["locations"]:
        p = Path(loc["path"])
        if p.is_dir() and p not in out:
            out.append(p)
    return out


def comfy_model_roots() -> List[Path]:
    """Every folder ComfyUI models may be in: the built-in one first, then the extra ones."""
    roots = [builtin_root()]
    for p in extra_roots():
        if p.resolve() != roots[0].resolve():
            roots.append(p)
    return roots


def download_root() -> Path:
    """Where new downloads go: the chosen location when it is present and writable,
    otherwise the built-in one (so a missing external drive never breaks installs)."""
    target = load_config()["download_target"]
    if target and target != BUILTIN:
        p = Path(target)
        if p.is_dir() and os.access(p, os.W_OK):
            return p
    return builtin_root()


def find_model_file(rel: str) -> Optional[Path]:
    """The first location that has ``rel`` (e.g. "rembg/u2net.onnx"), or None."""
    for root in comfy_model_roots():
        p = root / rel
        if p.exists():
            return p
    return None


def model_dirs(sub: str) -> List[Path]:
    """``<root>/<sub>`` for every location (existing or not)."""
    return [root / sub for root in comfy_model_roots()]


# ── files ComfyUI reads ────────────────────────────────────────────────────────

def comfy_paths_file(windows: bool) -> Path:
    return _data_dir() / ("comfy-extra-model-paths.windows.yaml" if windows else "comfy-extra-model-paths.yaml")


def _yaml_for(roots: List[str]) -> str:
    lines = ["# Written by HomePilot (app/model_storage.py) from Settings > Models > Model storage.",
             "# Extra ComfyUI model locations; models/comfy is still read as before."]
    for i, base in enumerate(roots):
        lines.append(f"homepilot_location_{i}:")
        lines.append(f"  base_path: {json.dumps(base)}")
        for key in MODEL_FOLDERS:
            lines.append(f"  {key}: {key}")
    return "\n".join(lines) + "\n"


def write_comfy_paths_files() -> None:
    """Write (or remove) the per-OS extra-model-paths files the ComfyUI launchers pass on."""
    roots = [p for p in extra_roots() if p.resolve() != builtin_root().resolve()]
    linux_file, win_file = comfy_paths_file(False), comfy_paths_file(True)
    if not roots:
        for f in (linux_file, win_file):
            try:
                f.unlink()
            except OSError:
                pass
        return
    linux_file.write_text(_yaml_for([str(p) for p in roots]), encoding="utf-8")
    win = [w for w in (to_windows_path(p) for p in roots) if w]
    if is_wsl() and win:
        win_file.write_text(_yaml_for(win), encoding="utf-8")
    else:
        try:
            win_file.unlink()
        except OSError:
            pass


# ── API ────────────────────────────────────────────────────────────────────────

def _describe(p: Path, *, builtin: bool, label: str, target: Path) -> Dict[str, Any]:
    exists = p.is_dir()
    info: Dict[str, Any] = {
        "path": str(p), "display_path": display_path(p), "label": label, "builtin": builtin,
        "exists": exists, "writable": exists and os.access(p, os.W_OK),
        "is_download_target": p.resolve() == target.resolve() if exists else False,
        "free_gb": None, "total_gb": None, "model_files": None,
    }
    if exists:
        try:
            usage = shutil.disk_usage(p)
            info["free_gb"] = round(usage.free / 2**30, 1)
            info["total_gb"] = round(usage.total / 2**30, 1)
        except OSError:
            pass
        n = 0
        for sub in ("checkpoints", "diffusion_models", "unet", "loras", "vae", "controlnet", "upscale_models"):
            d = p / sub
            if d.is_dir():
                try:
                    n += sum(1 for f in d.iterdir() if f.is_file() and not f.name.startswith("put_"))
                except OSError:
                    pass
        info["model_files"] = n
    return info


def storage_status() -> Dict[str, Any]:
    cfg = load_config()
    target = download_root()
    builtin = builtin_root()
    locations = [_describe(builtin, builtin=True, label="Built-in (current models)", target=target)]
    for loc in cfg["locations"]:
        p = Path(loc["path"])
        locations.append(_describe(p, builtin=False, label=loc.get("label") or display_path(p), target=target))
    return {
        "locations": locations,
        "download_target": display_path(target),
        "download_target_fallback": cfg["download_target"] != BUILTIN and target == builtin,
        "restart_note": "ComfyUI reads new locations when it starts: restart HomePilot (make start) after adding one.",
    }


class LocationIn(BaseModel):
    path: str = Field(..., min_length=1, max_length=500)
    label: str = Field("", max_length=80)


class StorageIn(BaseModel):
    locations: List[LocationIn] = Field(default_factory=list)
    download_target: str = Field(BUILTIN, max_length=500)


@router.get("")
def get_storage():
    return {"ok": True, **storage_status()}


@router.put("")
def put_storage(body: StorageIn):
    if len(body.locations) > MAX_LOCATIONS:
        raise HTTPException(400, f"At most {MAX_LOCATIONS} extra locations")
    builtin = builtin_root().resolve()
    seen: List[Path] = []
    stored: List[Dict[str, str]] = []
    for loc in body.locations:
        try:
            p = to_local_path(loc.path)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if p.resolve() == builtin or p in seen:
            continue
        try:
            p.mkdir(parents=True, exist_ok=True)
            for sub in MODEL_FOLDERS:
                (p / sub).mkdir(exist_ok=True)
        except OSError as e:
            raise HTTPException(400, f"Cannot use {loc.path}: {e.strerror or e}")
        if not os.access(p, os.W_OK):
            raise HTTPException(400, f"{loc.path} is not writable")
        seen.append(p)
        stored.append({"path": str(p), "label": loc.label.strip()})

    target = BUILTIN
    if body.download_target and body.download_target != BUILTIN:
        try:
            t = to_local_path(body.download_target)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if t.resolve() != builtin:
            if t not in seen:
                raise HTTPException(400, "The download location must be one of the listed locations")
            target = str(t)

    cfg = _config_file()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"locations": stored, "download_target": target}, indent=2), encoding="utf-8")
    write_comfy_paths_files()
    return {"ok": True, **storage_status()}

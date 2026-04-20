"""
Runtime config — small persistent shell-sourceable env file.

Some settings (ComfyUI VRAM mode, future launcher flags) must
survive across a backend + ComfyUI restart because their consumer
is a bash script started by ``make start``, not the Python
process. Shell scripts can't read the Python SettingsDraft, so we
write the subset they care about into ``$DATA_DIR/runtime.env``
which ``scripts/start-comfyui.sh`` sources before launch.

Format is deliberately plain ``KEY=value`` one-per-line so the
shell-script ``source`` builtin handles it without extra tooling.
We keep it minimal on purpose — anything Python-only should stay
in the main settings store.

Thread-safety is handled by writing atomically via tmp+rename.
"""
from __future__ import annotations

import os
import pathlib
import re
import tempfile
from typing import Dict


# Allowed keys. Unknown keys in incoming payloads are silently
# dropped so a future frontend doesn't accidentally leak arbitrary
# env into ComfyUI's process.
ALLOWED_KEYS = frozenset({
    "COMFY_VRAM_MODE",
    # Global media settings persisted from Settings UI so backend
    # startup paths (e.g. warmup) can resolve the same models the
    # user selected previously.
    "IMAGE_MODEL",
    "VIDEO_MODEL",
    "COMFY_BASE_URL",
})


def _runtime_env_path() -> pathlib.Path:
    # Late-binds to DATA_DIR at call time so tests that monkeypatch
    # the path don't have to reach into a frozen module constant.
    data_dir = (
        os.getenv("DATA_DIR", "").strip()
        or os.path.dirname(os.getenv("UPLOAD_DIR", "").strip() or "")
        or str(pathlib.Path(__file__).parent.parent / "data")
    )
    return pathlib.Path(data_dir) / "runtime.env"


def read_runtime_config() -> Dict[str, str]:
    """Return the current runtime.env as a dict. Missing file or
    malformed lines are tolerated — the caller gets an empty dict /
    the subset of parseable entries."""
    path = _runtime_env_path()
    if not path.exists():
        return {}
    out: Dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, _, val = stripped.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key in ALLOWED_KEYS:
                out[key] = val
    except OSError:
        return {}
    return out


_VALID_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


def write_runtime_config(values: Dict[str, str]) -> Dict[str, str]:
    """Persist a subset of ``ALLOWED_KEYS`` to the runtime.env file.

    Atomic: writes to a tmp sibling and ``os.replace`` onto the
    final path. Unknown / malformed keys are dropped. Returns the
    final written dict so the caller can echo it back.

    Values that shell scripts could interpret (backticks, ``$()``,
    etc.) are rejected — keep the file boring and safe to ``source``.
    """
    sanitised: Dict[str, str] = {}
    for raw_key, raw_val in (values or {}).items():
        key = str(raw_key or "").strip()
        if key not in ALLOWED_KEYS or not _VALID_KEY.match(key):
            continue
        val = str(raw_val or "").strip()
        # Reject anything that looks like shell meta-characters.
        # We only need alnum + a handful of punctuation for real
        # config values.
        if not re.match(r"^[A-Za-z0-9_./:\-+]*$", val):
            continue
        sanitised[key] = val

    path = _runtime_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Lightly-commented header so a sysadmin opening the file knows
    # what produced it.
    body_lines = [
        "# HomePilot runtime config — written by the backend on",
        "# POST /v1/system/runtime-config. sourced by",
        "# scripts/start-comfyui.sh at launch. Do not hand-edit",
        "# while the app is running.",
    ]
    for key in sorted(sanitised):
        body_lines.append(f"{key}={sanitised[key]}")
    body = "\n".join(body_lines) + "\n"

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8",
        dir=str(path.parent), prefix=".runtime-env-", delete=False,
    ) as tmp:
        tmp.write(body)
        tmp_path = pathlib.Path(tmp.name)
    os.replace(tmp_path, path)
    return sanitised


__all__ = ["read_runtime_config", "write_runtime_config", "ALLOWED_KEYS"]

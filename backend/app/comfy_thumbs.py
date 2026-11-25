"""
Thumbnails for images in ComfyUI's output folder.

Gallery grids ask for ``/comfy/view/<file>?thumb=<px>``; the backend serves a
small cached WEBP instead of the ~500 KB original. Sizes snap to THUMB_SIZES so
the cache stays small. Thumbnails live in ``<data dir>/cache/thumbs`` and are
keyed by path, modification time, file size and size, so an edited source gets
a fresh one.
"""
from __future__ import annotations

import atexit
import hashlib
import threading
from pathlib import Path, PurePath
from typing import Iterable, Optional

THUMB_SIZES = (128, 256, 384, 512)
_warm_lock = threading.Lock()
# Set when the process exits, so a warm-up thread stops before its next image
# instead of being inside the image library while Python shuts down.
_stopping = threading.Event()
atexit.register(_stopping.set)


def _output_dir() -> Optional[Path]:
    try:
        from .comfy import _get_comfyui_output_dir
        return _get_comfyui_output_dir()
    except Exception:
        return None


def local_comfy_output_file(filename: str, subfolder: str) -> Optional[Path]:
    """The file in ComfyUI's output folder on this computer, if it is there."""
    safe = PurePath(filename)
    if ".." in safe.parts or safe.is_absolute() or not safe.name:
        return None
    sub = PurePath(subfolder or "")
    if ".." in sub.parts or sub.is_absolute():
        return None
    root = _output_dir()
    if root is None:
        return None
    for candidate in (root / sub / safe, root / sub / safe.name):
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _cache_dir() -> Path:
    from . import config
    return Path(config.SQLITE_PATH).resolve().parent / "cache" / "thumbs"


def thumb_file(src: Path, size: int) -> Path:
    """A cached WEBP thumbnail of ``src`` (made on first request)."""
    from PIL import Image

    size = min(THUMB_SIZES, key=lambda s: abs(s - size))
    stat = src.stat()
    key = hashlib.sha1(f"{src}|{stat.st_mtime_ns}|{stat.st_size}|{size}".encode()).hexdigest()
    cache = _cache_dir()
    out = cache / f"{key}.webp"
    if not out.is_file():
        cache.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im.thumbnail((size, size))
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            tmp = out.with_name(f"{out.stem}.{threading.get_ident()}.tmp")
            im.save(tmp, "WEBP", quality=80, method=4)
            tmp.replace(out)
    return out


def warm_thumbnails(files: Iterable[tuple], size: int = 384) -> threading.Thread:
    """Make thumbnails for (filename, subfolder) pairs in a background thread,
    so a freshly restored gallery shows its pictures without waiting."""
    pairs = list(files)

    def run() -> None:
        with _warm_lock:  # one warm-up at a time
            for name, sub in pairs:
                if _stopping.is_set():
                    return
                src = local_comfy_output_file(name, sub)
                if src is None:
                    continue
                try:
                    thumb_file(src, size)
                except Exception:
                    continue

    t = threading.Thread(target=run, name="thumb-warm", daemon=True)
    t.start()
    return t

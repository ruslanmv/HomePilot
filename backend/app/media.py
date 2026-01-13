from __future__ import annotations

import requests

from .config import MEDIA_BASE_URL, TOOL_TIMEOUT_S

_session = requests.Session()


def upscale_video(input_path: str, output_path: str, width: int = 1920, height: int = 1080):
    url = f"{MEDIA_BASE_URL.rstrip('/')}/upscale"
    r = _session.post(
        url,
        json={
            "input_path": input_path,
            "output_path": output_path,
            "width": int(width),
            "height": int(height),
        },
        timeout=TOOL_TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()

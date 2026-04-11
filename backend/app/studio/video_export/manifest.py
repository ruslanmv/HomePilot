from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    payload = {
        **payload,
        "written_at": time.time(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

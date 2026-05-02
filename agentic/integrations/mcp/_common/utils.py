from __future__ import annotations

import hashlib
import time
import uuid


def now_ts() -> int:
    return int(time.time())


def short_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

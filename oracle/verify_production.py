#!/usr/bin/env python3
"""Wait until the public Oracle site reports the commit this deploy wrapped.

GET /version is the same check the Hugging Face workflow uses. A browser
navigation used to receive the SPA shell for that path; callers here ask for
JSON so nginx forwards the request to the API.

    PRODUCTION_URL=https://homepilot.ruslanmv.com EXPECTED_SHA=<commit> \
        python3 oracle/verify_production.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

TIMEOUT = int(os.environ.get("VERIFY_TIMEOUT", "720"))
INTERVAL = int(os.environ.get("VERIFY_INTERVAL", "15"))


def version_matches(body: dict, expected: str) -> bool:
    sha = str(body.get("sha") or "")
    if not sha or sha == "unknown" or not expected:
        return False
    return sha == expected or sha.startswith(expected) or expected.startswith(sha)


def fetch(url: str) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "homepilot-oracle-verify"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def main() -> None:
    base = os.environ.get("PRODUCTION_URL", "").strip().rstrip("/")
    expected = os.environ.get("EXPECTED_SHA", "").strip()
    if not base or not expected:
        raise SystemExit("PRODUCTION_URL and EXPECTED_SHA are required")
    deadline = time.time() + TIMEOUT
    last = ""
    while time.time() < deadline:
        status, text = fetch(f"{base}/version")
        try:
            body = json.loads(text)
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        running = str(body.get("sha") or "")
        note = f"HTTP {status} sha={running or text[:120].strip()!r}"
        if note != last:
            print(f"   … {note}", flush=True)
            last = note
        if status == 200 and version_matches(body, expected):
            edition = body.get("edition") or "?"
            print(f"   ✓ {base} is serving {running} (edition={edition})", flush=True)
            return
        time.sleep(INTERVAL)
    raise SystemExit(
        f"timed out after {TIMEOUT}s waiting for {base}/version to report {expected} (last: {last})"
    )


if __name__ == "__main__":
    main()

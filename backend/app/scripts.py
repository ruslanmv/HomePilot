from __future__ import annotations

import os
import subprocess
import sys


def dev() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = os.getenv("PORT", "8000")

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        host,
        "--port",
        str(port),
        "--reload",
    ]
    raise SystemExit(subprocess.call(cmd))


def test() -> None:
    cmd = [sys.executable, "-m", "pytest", "-q"]
    raise SystemExit(subprocess.call(cmd))

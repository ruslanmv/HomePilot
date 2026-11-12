#!/usr/bin/env python3
"""Back up or restore HomePilot's canonical data.

    python backend/scripts/homepilot_backup.py status
    python backend/scripts/homepilot_backup.py backup [--keep 7] [--no-media] [--dest DIR]
    python backend/scripts/homepilot_backup.py backup --if-older-than 24
    python backend/scripts/homepilot_backup.py list
    python backend/scripts/homepilot_backup.py restore ARCHIVE [--force]

Uses the same DATA_DIR / SQLITE_PATH / UPLOAD_DIR / OUTPUT_DIR settings as the
app. ``backup`` is safe while the app runs; run ``restore`` with it stopped.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from app.durable_storage import main as run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Inject HomePilot notice assets into a compiled frontend index."""

from __future__ import annotations

import sys
from pathlib import Path

CSS_TAG = '<link rel="stylesheet" href="/homepilot-content-notice.css">'
JS_TAG = '<script defer src="/homepilot-content-notice.js"></script>'


def inject(index_path: Path) -> None:
    if not index_path.is_file():
        raise SystemExit(f"Frontend index not found: {index_path}")

    content = index_path.read_text(encoding="utf-8")

    if CSS_TAG not in content:
        if "</head>" not in content:
            raise SystemExit("Cannot inject notice CSS: </head> is missing")
        content = content.replace("</head>", f"  {CSS_TAG}\n</head>", 1)

    if JS_TAG not in content:
        if "</body>" not in content:
            raise SystemExit("Cannot inject notice script: </body> is missing")
        content = content.replace("</body>", f"  {JS_TAG}\n</body>", 1)

    index_path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: inject-notifications.py /path/to/index.html")
    inject(Path(sys.argv[1]))

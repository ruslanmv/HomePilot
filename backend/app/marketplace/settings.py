"""Marketplace configuration from environment variables."""

from __future__ import annotations

import os

# Matrix Hub connection (optional — marketplace is disabled if not set)
MATRIXHUB_BASE_URL = os.getenv("MATRIXHUB_BASE_URL", "").strip().rstrip("/")

# Feature flag: marketplace is enabled only if MATRIXHUB_BASE_URL is provided
MARKETPLACE_ENABLED = bool(MATRIXHUB_BASE_URL)

# HTTP timeout for Matrix Hub requests (seconds)
MATRIXHUB_TIMEOUT = float(os.getenv("MATRIXHUB_TIMEOUT", "10.0"))

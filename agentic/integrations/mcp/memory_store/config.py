from __future__ import annotations

import os

LOG_LEVEL = os.getenv('MEMORY_STORE_LOG_LEVEL', 'INFO')
SERVICE_NAME = os.getenv('MEMORY_STORE_SERVICE_NAME', 'mcp-memory-store')

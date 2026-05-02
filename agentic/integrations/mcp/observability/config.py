from __future__ import annotations

import os

LOG_LEVEL = os.getenv('OBSERVABILITY_LOG_LEVEL', 'INFO')
SERVICE_NAME = os.getenv('OBSERVABILITY_SERVICE_NAME', 'mcp-observability')

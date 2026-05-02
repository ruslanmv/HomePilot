from __future__ import annotations

import os

LOG_LEVEL = os.getenv('CODE_SANDBOX_LOG_LEVEL', 'INFO')
SERVICE_NAME = os.getenv('CODE_SANDBOX_SERVICE_NAME', 'mcp-code-sandbox')

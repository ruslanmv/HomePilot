from __future__ import annotations

import os

LOG_LEVEL = os.getenv('SAFETY_POLICY_LOG_LEVEL', 'INFO')
SERVICE_NAME = os.getenv('SAFETY_POLICY_SERVICE_NAME', 'mcp-safety-policy')

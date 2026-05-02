from __future__ import annotations

import os

LOG_LEVEL = os.getenv('JOB_ORCHESTRATOR_LOG_LEVEL', 'INFO')
SERVICE_NAME = os.getenv('JOB_ORCHESTRATOR_SERVICE_NAME', 'mcp-job-orchestrator')

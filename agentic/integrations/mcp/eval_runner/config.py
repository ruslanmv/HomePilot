from __future__ import annotations

import os

LOG_LEVEL = os.getenv('EVAL_RUNNER_LOG_LEVEL', 'INFO')
SERVICE_NAME = os.getenv('EVAL_RUNNER_SERVICE_NAME', 'mcp-eval-runner')

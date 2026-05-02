from __future__ import annotations

import os

LOG_LEVEL = os.getenv('COST_ROUTER_LOG_LEVEL', 'INFO')
SERVICE_NAME = os.getenv('COST_ROUTER_SERVICE_NAME', 'mcp-cost-router')

from __future__ import annotations

import os

LOG_LEVEL = os.getenv('CITATION_PROVENANCE_LOG_LEVEL', 'INFO')
SERVICE_NAME = os.getenv('CITATION_PROVENANCE_SERVICE_NAME', 'mcp-citation-provenance')

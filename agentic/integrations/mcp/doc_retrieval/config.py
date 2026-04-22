from __future__ import annotations

import os

LOG_LEVEL = os.getenv('DOC_RETRIEVAL_LOG_LEVEL', 'INFO')
SERVICE_NAME = os.getenv('DOC_RETRIEVAL_SERVICE_NAME', 'mcp-doc-retrieval')

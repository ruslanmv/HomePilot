from __future__ import annotations

import uvicorn

from agentic.integrations.mcp.code_sandbox.app import app


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8100)

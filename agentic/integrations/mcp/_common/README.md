# MCP reference server (common)

Small shared helpers for the sample MCP servers in this repo.

These servers implement a **minimal MCP JSON-RPC surface** suitable for
Context Forge federation.

Endpoints:

* `POST /rpc` – JSON-RPC requests
* `GET /health` – simple health probe

Supported RPC methods:

* `initialize`
* `tools/list`
* `tools/call`

The result format follows the MCP conventions (returning `content` with
text parts).

# Community External MCP Servers

This directory stores external MCP servers that are auto-cloned from git
during persona import. Each subdirectory is a cloned MCP server repository.

## Structure

```
community/external/
├── registry.json           # Tracks all installed external servers
├── README.md               # This file
└── <server-name>/          # Cloned server repos (auto-managed)
    ├── app/
    ├── requirements.txt
    └── ...
```

## How It Works

1. When a shared persona (.hpersona) is imported that requires an external
   MCP server (e.g., `mcp-news`), the system checks `registry.json`.

2. If the server is not installed, the user is prompted to confirm installation.

3. On confirmation, the server is:
   - Cloned from its git URL into this directory
   - Python dependencies are installed
   - The server process is started on an allocated port
   - Tools are discovered and registered in Context Forge
   - A full sync updates virtual server associations

4. `registry.json` tracks all installed servers with their ports and status.

## Port Range

External servers use ports 8700-8999 (separate from core 9101-9120
and community bundles 9200-9999).

# External applications on the Cloud Mirror (`agentic.invoke`)

Status: implemented, **off by default**. Part of Phase 4 ("MCP") of the
[Cloud Mirror design](README.md).

An owner's own application — for example [SmartMirror](https://github.com/ruslanmv/SmartMirror)
on an Echo Show — can call one of the owner's MCP tools through the mirror job
plane, from anywhere, without opening a port:

```
App (server-side) ─► OllaBridge Cloud  POST /v1/mirror/nodes/{node}/jobs      owner-scoped
                 ─► OllaBridge Local   homepilot.mirror.job.create           HOMEPILOT_MIRROR_RELAY_ENABLED
                 ─► HomePilot          POST /v1/node/jobs  agentic.invoke    localhost-only
                 ─► Context Forge      the app's registered MCP gateway/tool
```

## 1. Register the application's MCP server

Register it once as a Context Forge gateway through HomePilot's existing,
additive endpoint:

```http
POST /v1/agentic/register/gateway
{ "name": "smartmirror", "url": "http://smartmirror-api:8100/rpc", "transport": "HTTP" }
```

Forge discovers its tools. HomePilot resolves the names an app asks for
(`hp.smartmirror.style_suggest`) to Forge's names (exact, original name, or a
gateway-prefixed slug such as `smartmirror-hp-smartmirror-style-suggest`).

## 2. Enable and allow-list

```env
HOMEPILOT_MIRROR_JOBS_ENABLED=true          # existing: node job plane
HOMEPILOT_MIRROR_MCP_ENABLED=true           # registers agentic.invoke
HOMEPILOT_MIRROR_ALLOWED_TOOLS=hp.smartmirror.*   # comma-separated fnmatch globs
```

- With `HOMEPILOT_MIRROR_MCP_ENABLED` off, `agentic.invoke` is **not registered**:
  the job whitelist, `/v1/node/jobs/operations` and the manifest are unchanged.
- An empty `HOMEPILOT_MIRROR_ALLOWED_TOOLS` **denies every tool**. Matching is
  case-sensitive.
- When on, the manifest capabilities include `agentic.invoke`.

## 3. Job contract

```jsonc
// create
{ "operation": "agentic.invoke",
  "params": { "tool": "hp.smartmirror.style_suggest",
              "arguments": { "prompt": "black mini skirt for dinner" },
              "timeout_s": 30 } }            // optional, clamped to 1..120

// completed
{ "status": "completed",
  "output": { "tool": "hp.smartmirror.style_suggest", "result": { "outfits": [ … ] } } }

// failed — the error starts with a stable code
{ "status": "failed", "error": "ToolNotAllowed: TOOL_NOT_ALLOWED: hp.homepilot.shell_exec" }
```

| Code | Meaning |
|---|---|
| `TOOL_NOT_ALLOWED` | name invalid or not in `HOMEPILOT_MIRROR_ALLOWED_TOOLS` |
| `CAPABILITY_UNAVAILABLE` | `HOMEPILOT_MIRROR_MCP_ENABLED` is off |
| `TOOL_FAILED` | Forge returned an error or no result; bad arguments |

`result` is the tool's own payload: MCP `structuredContent` when present,
otherwise a single JSON text block parsed, otherwise `{"text": …}`.

## 4. Guarantees

- Only allow-listed tools run; everything else fails honestly without calling Forge.
- Tool arguments and results are never logged — only tool name, duration and outcome.
- No new network surface: `/v1/node/jobs` stays localhost-only; the cloud path
  exists only when OllaBridge Cloud (`HOMEPILOT_MIRROR_ENABLED`) and OllaBridge
  Local (`HOMEPILOT_MIRROR_RELAY_ENABLED`) are also switched on.
- Rollback: set `HOMEPILOT_MIRROR_MCP_ENABLED=false`.

## 5. Personas that use the app's tools

A `.hpersona` package may declare the app's MCP server in
`dependencies/mcp_servers.json`; on import HomePilot pins the listed
`tools_provided`. Declare them only once the tools are reachable — pinned but
missing tools make persona chat fail.

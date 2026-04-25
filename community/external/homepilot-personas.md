# HomePilot Viral Persona Pack

The HomePilot Viral Persona Pack ships ten production-ready personas with
MCP servers, .hpersona v2 packages and gallery previews.

Upstream repository: https://github.com/HomePilotAI/personas

## Personas

| #  | Persona             | MCP server              | Port  |
|---:|---------------------|-------------------------|------:|
| 01 | Creator Muse        | mcp-creator-muse        | 9101  |
| 02 | Style Muse          | mcp-style-muse          | 9102  |
| 03 | Secretary Pro       | mcp-secretary-pro       | 9103  |
| 04 | Researcher          | mcp-researcher          | 9104  |
| 05 | Personal Trainer    | mcp-personal-trainer    | 9105  |
| 06 | Room Stylist        | mcp-room-stylist        | 9106  |
| 07 | Storyteller         | mcp-storyteller         | 9107  |
| 08 | Exam Coach          | mcp-exam-coach          | 9108  |
| 09 | Mindfulness Coach   | mcp-mindfulness-coach   | 9109  |
| 10 | General Doctor      | mcp-general-doctor      | 9110  |

## Quick start

```sh
git clone https://github.com/HomePilotAI/personas.git
cd personas
make install
make build
docker compose up   # starts all 10 servers on ports 9101-9110
```

## Importing into HomePilot

The servers in `community/external/registry.json` are picked up by the
HomePilot community gallery. Each persona is also published as a
`.hpersona` v2 package under `dist/packages/<id>/<version>/persona.hpersona`
in the upstream repo.

## MCP Context Forge

The same servers can be imported into MCP Context Forge via the bundle at
`https://github.com/ruslanmv/mcp-context-forge/tree/claude/upgrade-mcp-agent-system-dwrvU/homepilot-personas`.

# HomePilot Teams Relay

Lightweight WebSocket router that lets multiple HomePilot instances
share a meeting room in real time.

## Quick start

```bash
pip install -r requirements.txt
uvicorn services.teams-relay.app:app --host 0.0.0.0 --port 8765
```

## How it works

1. Each HomePilot backend connects via WebSocket to `/ws`.
2. Client sends `{"type": "join", "room_code": "MEET-XXXX"}`.
3. All subsequent messages are broadcast to every other client in the
   same room.
4. No LLM calls, no persistence — just routing.

## Health check

```
GET /health
```

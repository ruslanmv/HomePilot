# Turning the Avatar Director on

**HomePilot's `avatar.enabled` does not flip.** It ships off, it stays off, and this page is
how someone turns it on deliberately. That is a decision, not an omission — this is a
self-hosted server that already does a great deal, and adding a websocket, a vision endpoint
and an MCP tool server to every existing install because a client feature became ready would
be taking that choice away from the person running it.

The client's own `behaviorEngine.enabled` is a different question with a different answer;
see `3D-Avatar-Chatbot/docs/QA_CHECKLIST.md`.

## What is off right now

With `AVATAR_ENABLED` unset — which is every install that has not read this page:

- **No routes are mounted.** `register()` returns `False` before it imports anything.
- **Nothing is imported.** Not FastAPI's websocket machinery, not the vision module, not the
  tool bridge. `backend/tests/avatar/test_registration.py` asserts this against `sys.modules`
  rather than trusting it.
- **The import cost is one dataclass and a handful of `os.getenv` calls.**

That is the whole footprint of this feature on an install that does not want it.

## Turning it on

```bash
AVATAR_ENABLED=true
```

One variable, and it mounts two routes: the session socket at `/avatar/session` and the
control endpoint at `/avatar/control`. Nothing else changes; no existing route is modified,
no table is created, no default moves.

### The four gates beneath it

`avatar.enabled` is the kill switch, not a master switch. Four capabilities have their own,
and **none of them is implied by turning the director on**:

| Variable | Default | What it adds |
|---|---|---|
| `AVATAR_VOICE_ENABLED` | `false` | The voice uplink (B10). Without it, `voice_offer` is refused by name |
| `AVATAR_VISION_MODEL` | *(empty)* | The vision endpoint (B15). **No model named, no route mounted** — a route that answers every request "not configured" looks like a feature to anything probing the API |
| `AVATAR_ADULT_ENABLED` | `false` | The adult tier's server half (B28). Independent of everything above by design |
| `AVATAR_KB_MANIFEST` | *(empty)* | Path to the client's `kb/animations.manifest.jsonl`, for the MCP catalogue tools (B17). Without it they refuse by name rather than returning nothing |

`backend/tests/avatar/test_config_defaults.py` asserts each default and that
`AVATAR_ENABLED=true` turns none of the others on.

## What it does with data

The short version: **frames are never stored, and there is nowhere to store them.**

- `frames.retention` is `0` and a typo in the environment cannot widen it — a malformed
  value falls back to the safe default rather than being interpreted.
- `avatar_director/vision.py` contains no `open(`, no `Path(`, no `tempfile` and no
  `upload_path`. Retention is zero because there is no store, not because a policy says so.
- `backend/tests/avatar/test_vision_retention.py` proves it behaviourally: a real request
  runs against a stubbed model with `open`, `Path.write_bytes`, `Path.write_text` and
  `os.replace` patched **process-wide** and the root logger captured, and a recognisable
  needle baked into the frame reaches neither disk nor logs — including on the error path.
- The 768 px cap is re-checked server-side by reading the image header, never by decoding.
  Decoding a hostile 20000×20000 JPEG to discover it is too big *is* the attack.

**What is not claimed:** that a hosted model provider stores nothing. That is somebody else's
disk. It is why `AVATAR_VISION_MODEL` names a model rather than defaulting to a service, and
why the recommended configuration is a local one through HomePilot's own model runner.

Curiosity's interest records (B16) live in the persona memory that already exists, as a new
`interest` category — not a parallel store. Forgetting a persona through the existing path
forgets its interests with it, which is the property that made "inside the existing memory"
worth insisting on: a parallel store is a second place a user's data hides from the delete
button they already have.

## What it does with permission

Two rules, both enforced server-side and both tested as negative assertions:

1. **Anything touching capture or vision needs the *client's* live consent state**, not just
   an operator's approval. A server-side yes is not the same as the user having opted in on
   the device holding the camera; the MCP tools require both.
2. **Server-sent intents get no special powers.** They pass the same §6.2 whitelist and the
   same §6.5 ranker gates as a locally parsed tag, and they carry a `source` that is never
   `"user"` — so the rule that she never initiates anything explicit holds against the
   server exactly as it holds against a chat reply.

## Turning it off again

Unset `AVATAR_ENABLED` and restart. The routes are gone, nothing is imported, and the only
trace left is whatever curiosity wrote into the persona memory — which the existing
`forget_all` clears, like everything else that memory holds.

## Why there is no rollout plan here

There is nothing to roll out. The client flips its own default after three green audits
(`3D-Avatar-Chatbot/docs/QA_CHECKLIST.md`), and it works fully without a server: Tier 0 and
Tier 1 run on the device, and pulling the network mid-session leaves them running — which is
asserted in the client's own suite rather than hoped for.

So this server is an addition, not a dependency, and it stays one until somebody with an
install decides otherwise.

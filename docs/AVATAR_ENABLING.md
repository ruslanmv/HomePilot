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

### The tuning knobs

These change behaviour rather than switching a capability on, and every one has a default
that works. They are listed so an operator knows the surface is finite.

| Variable | Default | What it tunes |
|---|---|---|
| `AVATAR_VISION_MAX_IMAGE_PX` | `768` | Longest edge accepted by the vision endpoint. Read from the image *header*, never by decoding — decoding a hostile 20000×20000 JPEG in order to reject it is the attack |
| `AVATAR_FRAMES_RETENTION` | `0` | How many frames are kept. Zero, and there is nowhere in the code to put one |
| `AVATAR_CURIOSITY_SESSION_BUDGET` | `4` | How often she may raise something of her own, per session |
| `AVATAR_CURIOSITY_MIN_GAP_MS` | `90000` | And how far apart. A budget of four spent in two minutes is still four interruptions in two minutes |
| `AVATAR_CURIOSITY_MIN_SESSION_AGE_MS` | `120000` | How long a session runs before she may. Found by a twenty-minute replay, not by the spec: with only a budget and a gap she opened an evening fifteen seconds in with "Mum's scan results are due this week" |
| `AVATAR_VOICE_MODEL` | *(empty)* | What the uplink asks the chat endpoint for |
| `AVATAR_VOICE_MEDIA` | `transcript` | `transcript` (the client's recogniser, works today) or `webrtc` (needs a media terminus; without one the server refuses the offer by name rather than accepting one it cannot honour) |
| `AVATAR_PANEL_MAX_KB` | `64` | Panel size limit. An oversized payload is **rejected with its size named**, never trimmed — a truncated agenda is an agenda with the afternoon missing, drawn as confidently as a complete one |
| `AVATAR_ADULT_PROVIDER` | `owner-attest` | The verification plugin. See below |
| `AVATAR_REDACTION_ENABLED` | `true` | Memory redaction in the adult tier. On by default, unlike everything else here |

## The adult tier, specifically

`AVATAR_ADULT_ENABLED=true` is necessary and nowhere near sufficient.

**`owner-attest` refuses to load on a multi-user instance.** The self-host default is honest:
the person who owns the machine attests their own age about their own machine. That is only
honest while there is exactly one account — on an instance with several, the owner is
attesting for people they have never met, which is worse than no gate because it looks like
one. So the provider raises rather than degrading, and the server answers every verification
request "no".

A distribution build **must** configure a real provider via `AVATAR_ADULT_PROVIDER`. The
interface is one method, `verify(user) -> Attestation`, and it is where a deployment meets
its local obligations; compliance requirements vary by jurisdiction and this code does not
pretend to know them. An unknown provider name is **refused, never defaulted** — silently
falling back to owner-attest when somebody typos their real provider is how an instance ends
up with no gate and no warning.

An attestation is a fact about a *session*: it expires, it is re-asked on every reconnect, it
carries no identity, and it is written nowhere. Revoking is closing the tab.

With `AVATAR_ADULT_ENABLED` false the provider factory returns a refusing provider **without
consulting the configured one at all** — a test asserts the user count is never even read.
The tier is unactivatable, not merely unadvertised.

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

## Testing it

```bash
cd backend

# The whole avatar surface — 369 tests, no network, no sqlite, no model.
python3 -m pytest tests/avatar -q

# The invariants specifically. Written before the features they guard, and most
# of them would pass on an empty repository — which is the point.
python3 -m pytest tests/avatar/test_adult_gates.py -q     # verification + redaction
python3 -m pytest tests/avatar/test_vision_retention.py -q # nothing reaches disk or logs
python3 -m pytest tests/avatar/test_config_defaults.py -q  # every flag ships off
```

A live smoke test, once `AVATAR_ENABLED=true`:

```bash
# The socket is up and speaks §6.9.
websocat ws://localhost:8000/avatar/session   # then: {"v":1,"type":"hello","client":"x","auth":"t"}

# The control route is mounted (and refuses an unconfirmed confirm-level tool).
curl -s localhost:8000/avatar/control -H 'content-type: application/json' \
     -d '{"tool":"play_animation","args":{"name":"wave"}}'
```

The client half — flags, browser requirements, and a per-feature recipe — is in
[3D-Avatar-Chatbot `docs/ENABLING.md`](https://github.com/ruslanmv/3D-Avatar-Chatbot/blob/main/docs/ENABLING.md).

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

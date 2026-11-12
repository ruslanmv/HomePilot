# HomePilot One — architecture

One HomePilot, one interface, every AI resource the user has. HomePilot is the
brain and the source of truth; OllaBridge Cloud is the inference and
connectivity backbone; Hugging Face is the first hosted provider; other APIs
are fallback capacity; a paired PC adds private GPU compute.

Setup: [HOMEPILOT_ONE_SETUP.md](HOMEPILOT_ONE_SETUP.md) ·
Testing: [HOMEPILOT_ONE_TESTING.md](HOMEPILOT_ONE_TESTING.md) ·
Gateway side: `ollabridge-cloud/docs/HOMEPILOT_ONE_ROUTING.md`,
`ollabridge-cloud/docs/HOMEPILOT_ONE_INTEGRATION.md`.

## Who owns what

| HomePilot (canonical) | OllaBridge Cloud | HomePilot Local |
|---|---|---|
| users, sessions, workspaces | provider registration and keys | local model weights |
| conversations, personas, memories | model and capability catalog | Ollama / ComfyUI runtimes |
| projects, knowledge bases | provider health, quotas, selection | local-only content |
| generated media (durable copies) | device pairing, presence, relay | offline workflows |
| privacy and spending preferences | execution diagnostics | |
| the spending ledger and budgets | | |

Neither service keeps a copy of the other's database. They meet at versioned
HTTP contracts.

## Request lifecycle

```
Browser ──► HomePilot backend ──────────────► OllaBridge Cloud ──► provider / my PC
            1 authenticate the user           5 verify the policy
            2 load the user's strategy,       6 filter: privacy, capability,
              privacy and budgets               credentials, paid, cost
            3 work out required capability    7 order by tier, then try in order
            4 sign a per-request policy       8 report who answered (provenance)
            9 record provenance + cost  ◄────
           10 persist the message / asset in HomePilot storage
```

HomePilot decides **policy**. OllaBridge decides **execution**. There is one
provider list and one selection algorithm (in OllaBridge); HomePilot does not
re-rank providers.

## Routing strategies

Set per user in Settings → Compute → **My AI** (`PUT /v1/routing`).

| Strategy | Order |
|---|---|
| `hf_first` — default on the hosted web edition | Hugging Face → other free APIs → authorised paid APIs → my computers |
| `local_first` | my computers → the hosted tiers |
| `private_local` | my computers only; never a hosted provider; offline is an error |
| `lowest_cost`, `fastest`, `quality_first` | reorder what is permitted |
| `pinned` | the per-model routes in Settings → Compute → Routing |
| `legacy` — default on a local install | routing as it was before HomePilot One |

### Precedence

1. **Operator restrictions** — e.g. the paid kill switch
   (`HOMEPILOT_ALLOW_PAID_FALLBACK=false`) overrides any user preference.
2. **Privacy** — `private_local` removes every hosted target and the fallback
   tail before anything is ordered.
3. **Spending** — per-request ceiling, daily and monthly budgets.
4. **Per-model route** — an explicit route in Routing is the user's override.
5. **The user's strategy**.
6. **The edition default**.

A user can always make routing stricter than the operator allows, never
looser.

### What HomePilot sends for each strategy

| | Chat / vision targets | Generation targets |
|---|---|---|
| gateway strategies | `provider:homepilot-auto` (or `-vision`), then `local` | gateway job when `HOMEPILOT_MEDIA_VIA_GATEWAY=true`, else the direct connector |
| `private_local`, web | `provider:<alias>` only — the gateway is told to use only the user's devices | gateway job only |
| `private_local`, local install | `local`, and a hosted LLM provider is refused | `local` |
| `legacy` / `pinned` | unchanged | unchanged |

`local` is HomePilot's own executor: the direct Hugging Face connector, then
the local Ollama model. It is the **emergency path** for when OllaBridge
cannot be reached. It follows the same switches — operator inference, the
tracked Hugging Face allowance, private mode — but it is a fixed fallback, not
a second router.

## The policy contract

`backend/app/compute/routing.py` mints, per request and server-side:

```
X-HomePilot-Policy: <base64url(json)>.<hmac-sha256>     signed with HOMEPILOT_POLICY_SECRET
X-HomePilot-Provider-Credentials: <base64url(json)>      only this user's own linked key
X-OllaBridge-Origin: homepilot   X-OllaBridge-Hop: n   X-Request-Id: <id>
```

The browser never sees these headers and cannot forge them. Full field list
and trust rules: `ollabridge-cloud/docs/HOMEPILOT_ONE_ROUTING.md`.

`max_cost_usd` in the policy is the smallest of the user's per-request
ceiling, what is left of today's budget and what is left of this month's — so
budgets are enforced from HomePilot's own durable ledger.

## Tenant isolation

| Rule | Where |
|---|---|
| Routing preferences and the ledger are keyed by user id. | `user_routing_prefs`, `inference_usage` |
| The gateway is called with **the signed-in user's own** OllaBridge token when they linked one; only then may their devices be used. | `routing.build_gateway_call` |
| With no linked account, the hosted edition uses the operator's service token for hosted providers only, with `allow_relay: false`. The operator token is never used to reach devices. | `routing.build_gateway_call`, `providers._cloud_token` |
| `device:*` and `ollabridge_cloud` targets are not built at all for a hosted user without a linked account. | `providers._build_cloud` |
| Only the user's own linked Hugging Face token is forwarded, inside that request. | `routing._user_hf_token` |
| The Space's shared token is used for a visitor only when `HOMEPILOT_OPERATOR_INFERENCE` allows it. | `connectors/huggingface.shared_token` |
| A refusal for one user (budget, privacy, quota) does not open the circuit breaker for everyone. | `router._trips_breaker` |

Known limit: the per-model **route table** and compute **sources** in
Settings → Compute are still one shared registry per installation
(`/compute/readiness` reports `multi_tenant_registry: false`). On a multi-user
deployment treat them as operator configuration. Strategy, privacy, budgets,
credentials and device access — everything that decides whose resources a
request can touch — are per user.

## Provenance, cost and the ledger

Every gateway answer says who served it. HomePilot:

* attaches it to the reply as `answered_by` (the badge under a message:
  model · provider, and why when it was not the first choice);
* records it in `inference_usage` — provider, model, tier, billing, credential
  (caller or operator), cost, tokens, whether it fell back;
* stores it with a generated asset's message (`served_by`, `execution`,
  `generated_at`).

`GET /v1/routing` returns the month's usage per provider. A cost that is not
known is stored as unknown and counted in `unknown_cost_requests`; it is never
recorded as zero.

Hugging Face exposes no credit balance. If the operator sets
`HOMEPILOT_HF_INCLUDED_USD`, HomePilot tracks the estimated value used and,
once it is spent, Hugging Face needs the same paid authorisation as any paid
provider. Without it, exhaustion is detected when Hugging Face answers `402`
and the next tier is used.

## Streaming

`POST /v1/compute/chat/stream` relays tokens from the gateway. Fallback happens
only before the first token; a failure after output is surfaced as an error,
never restarted on another target.

## Loop guard

OllaBridge can route `persona:*` requests to HomePilot. Each service stamps
`X-OllaBridge-Hop`. HomePilot's persona API records the inbound hop; anything
it sends on carries hop + 1, and at the limit the gateway target is not built
at all — the request is answered by HomePilot's own executor. OllaBridge
refuses to forward a persona request that came from HomePilot.

## Durable storage

HomePilot's data root holds the SQLite database (users, conversations,
personas, memories, projects, routing preferences, the ledger, linked-account
tokens), uploads and generated outputs.

| Order | Root | |
|---|---|---|
| 1 | `DATA_DIR` | any mounted volume |
| 2 | `/data/homepilot` | a Hugging Face persistent-storage volume, when present |
| 3 | `/tmp/homepilot` | **ephemeral** — erased on restart; reported as a blocking readiness finding and shown in the UI |

* A one-time, non-destructive copy moves data from the old scratch location to
  a newly mounted durable root. Existing durable data is never overwritten.
* `python -m app.durable_storage backup|restore|list|status` — a consistent
  SQLite snapshot plus uploads and outputs in one archive under
  `<root>/backups`; the Space takes one daily and keeps seven.
* Generated media arriving from the gateway is copied into HomePilot storage;
  a conversation never references the gateway's temporary cache.

Long term: the archive layout (`db/`, `uploads/`, `outputs/`, `manifest.json`)
is the export format for moving to external PostgreSQL and object storage.
Media already has a pluggable backend (`app/media_storage`, local or S3). The
database access is still SQLite-specific; moving it is a separate project.

## New and changed modules

| Module | Role |
|---|---|
| `compute/routing.py` | per-user preferences, operator restrictions, budgets, ledger, policy signing, hop context |
| `compute/providers/hosted.py` | the `provider:<alias>` target (chat + streaming), structured `GatewayError` |
| `compute/media_gateway.py` | generation jobs through the gateway, durable persistence |
| `compute/one_routes.py` | `/v1/routing`, `/v1/ecosystem/status`, `/v1/ecosystem/catalog` |
| `compute/policies.py`, `router.py`, `local.py` | strategy plans, no local tail in private mode, provenance in the route report |
| `durable_storage.py` | storage status, backup, restore |
| `frontend/.../EcosystemPanel.tsx` | Settings → Compute → My AI |

# HomePilot One — testing

What is tested, how to run it, and — separately — what has been verified
against live services. A scenario covered only by scripted stand-ins is listed
as such; it is not claimed as live verification.

## Run the tests

HomePilot:

```bash
cd backend && python -m pytest -q tests/test_homepilot_one.py tests/test_durable_storage.py tests/test_compute_*.py tests/test_connectors_*.py
```

```bash
cd frontend && npx tsc -b && npx vitest run
```

OllaBridge Cloud:

```bash
python -m pytest -q tests/test_homepilot_one_policy.py tests/test_homepilot_one_media.py
```

The cross-repository contract test
(`test_the_signed_policy_is_accepted_by_the_gateways_own_parser`) runs when
`ollabridge_cloud` is importable and is skipped otherwise; a fixed signature
vector is asserted in HomePilot either way.

## Scenario coverage

HP = `HomePilot/backend/tests/test_homepilot_one.py`,
OB = `ollabridge-cloud/tests/test_homepilot_one_policy.py`,
OB-media = `…/test_homepilot_one_media.py`.

| | Scenario | Automated | Live |
|---|---|---|---|
| A | Hugging Face answers first | OB: HF tried first whatever the alias order or score; HP: chat served through the gateway with provenance | HF **attempted first** against the real router: yes. A **successful** HF completion: **no** — the test token lacks the Inference Providers permission (`403`) |
| B | HF unavailable → next permitted tier | OB: quota-exhausted HF falls to free; streaming fail-over before first token | yes — real `403` from HF, classified `auth_failed`, next tier answered |
| C | Paid protection | OB: no paid call with paid off; unsigned policy cannot authorise; unknown price not free | scripted only |
| D | Authorised paid fallback | OB: paid answers inside the ceiling, refused above it | scripted only — no paid key available |
| E | Vision | OB: image reaches only vision-verified models, payload intact; HP: image bytes forwarded, `require: vision` | the HF live catalogue lookup: yes; a vision completion: no (same token limit) |
| F | Image generation + persistence | OB-media: hosted tier, provenance; HP: artifact copied into HomePilot storage | scripted only |
| G | Local PC | OB: private/local-first run on the caller's device | simulated relay hub only — the account's PC was offline |
| H | Disconnected PC | OB: local-first falls back to cloud; HP: gateway unreachable → own executor | simulated |
| I | Private-local | OB + HP + OB-media: refuses, calls nothing hosted | yes, on a local gateway process: `503 device_offline`, "Nothing was sent to a hosted provider" |
| J | Tenant isolation | OB: other user's device never used, forwarded key per request, key needs a vouching policy, one user's failure does not degrade shared health; HP: per-user credentials, device targets not built from the operator token, per-user prefs | not applicable |
| K | Recursive routing | OB: persona from HomePilot not sent back, hop limit; HP: forwarded request not re-sent at the limit | not exercised live |
| L | Streaming | OB + HP: tokens relayed; a stream that dies after output is never replayed | yes — streamed through a local gateway process |
| M | Persistence | HP: preferences and ledger survive a process restart; backup → loss → restore; restore never silently overwrites | not exercised on a real Space volume |
| N | Backward compatibility | OB: requests without a policy take the legacy path; full existing suites | yes — HomePilot's router against production `app.ollabridge.com` got a real answer |

## Results (2026-11-12)

| Suite | Result |
|---|---|
| OllaBridge Cloud, full | 804 passed |
| HomePilot backend, full (excluding `tests/meetingsense`) | no new failures: the same 19 tests fail on the untouched source branch (S3 tests need `boto3`, two need internet, four need `langgraph`, one is order-dependent) |
| HomePilot frontend | `tsc -b` clean; compute component tests pass |

## Live checks performed

1. `https://app.ollabridge.com` — health `200`; login; `/v1/models`; a real
   `free-best` completion; the account's paired device listed (offline).
   `https://ruslanmv-ollabridge-cloud.hf.space` answered `404`;
   `ollabridge.cloud` was not reachable from the test environment.
2. HomePilot's router → production gateway → real model: "The capital of
   France is Paris." (`HOMEPILOT_HOSTED_ALIAS=free-best`).
3. HomePilot HTTP API (`/chat`) → a local build of the gateway → the real
   Hugging Face router. Hugging Face was called first and refused the token;
   the gateway reported `auth_failed`, skipped the remaining HF rungs, and the
   next free tier answered. HomePilot returned `answered_by` with the reason
   and recorded the request in the ledger. In this run the "next free tier"
   was a **stand-in** for the gateway's local Ollama, not a real model.
4. `/v1/ecosystem/status` and the My AI panel against that stack, at desktop
   and phone widths.

## To finish live verification

* A Hugging Face token with "Make calls to Inference Providers" → rerun A, E, F.
* The paired PC online → G and H end to end.
* One paid provider key and a small budget → D.
* A Space with persistent storage attached → M on the real volume.

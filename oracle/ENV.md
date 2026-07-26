# Oracle Web Deployment — Environment Variables

This is the setup trace for the hosted **web** edition on Oracle Cloud (Always
Free). It documents every environment variable the deploy touches, where you set
it, and why — so future fixes have a single source of truth.

Deploy workflow: [`.github/workflows/oracle.yml`](../.github/workflows/oracle.yml)
· Compose: [`oracle/docker-compose.yml`](./docker-compose.yml)
· Base image build: [`.github/workflows/container.yml`](../.github/workflows/container.yml)

## How config flows

There are two independent layers. Set each value in the place that matches its
layer or it will have no effect.

```
Backend runtime flags
  GitHub → Environment "oracle-production" (variable or secret)
    → oracle.yml writes them into /opt/homepilot/.env  (on every deploy)
      → docker-compose  env_file: .env
        → backend reads os.getenv(...) at runtime

Frontend build-time flags (VITE_*)
  GitHub → Repository variables
    → container.yml passes them as docker build-args
      → container/Dockerfile bakes them via `npm run build` into homepilot:latest
        → the Oracle image FROM homepilot:latest inherits the built frontend
```

Key consequence: **backend flags take effect on the next Oracle deploy; `VITE_*`
flags take effect only after `container.yml` rebuilds and republishes
`homepilot:latest`** (the Oracle image extends that base and does not rebuild the
frontend).

`.env` is rewritten from CI on **every** deploy, so CI/GitHub is the source of
truth — hand edits on the box are overwritten. Only variables listed in the
workflow's `envs:` allow-list reach the box.

---

## 1. Required deployment config (already set)

On the **`oracle-production` Environment**. Each is read as `vars.X || secrets.X`,
so a variable or a secret both work — except the two marked secret, which must be
secrets.

| Name | Kind | Purpose |
| --- | --- | --- |
| `ORACLE_HOST` | variable/secret | SSH host of the Oracle instance |
| `ORACLE_USER` | variable/secret | SSH user |
| `ORACLE_SSH_PRIVATE_KEY` | **secret** | SSH key for deploy |
| `ORACLE_SSH_PORT` | variable/secret | Optional, defaults to `22` |
| `HOMEPILOT_DOMAIN` | variable/secret | Public domain; also sets `PUBLIC_BASE_URL=https://<domain>` |
| `ACME_EMAIL` | variable/secret | Let's Encrypt / ACME contact email |
| `HOMEPILOT_API_KEY` (or `API_KEY`) | **secret** | Backend API key |
| `OPENAI_API_KEY` | secret | Optional; hosted web defaults `HOMEPILOT_LLM_BACKEND=openai` |
| `ANTHROPIC_API_KEY` | secret | Optional Claude key |

---

## 2. OllaBridge account features — Environment variables

On the **`oracle-production` Environment**, add as **variables** (not secret —
they are not sensitive). All three flags already **default to `true`** and the
URL defaults to the canonical host in `oracle.yml`, so the web edition comes up
correct even if you add nothing. Add them explicitly only to make them
visible/overridable — set a value to `false` to turn one off.

| Name | Value | Why |
| --- | --- | --- |
| `OLLABRIDGE_CLOUD_URL` | `https://app.ollabridge.com` | Canonical cloud host — backend cloud calls, device pairing, and `/v1/account/providers` |
| `HOMEPILOT_MIRROR_BFF_ENABLED` | `true` | Mounts the `/v1/account/mirror/*` BFF (same-origin proxy to the cloud mirror) |
| `HOMEPILOT_BFF_SESSION_ENABLED` | `true` | Server holds the cloud token — a linked user needs no browser token |
| `HOMEPILOT_ACCOUNT_PROVIDERS_ENABLED` | `true` | Mounts `GET /v1/account/providers` (the account-providers aggregate) |

## 3. OllaBridge account features — Environment secret (optional)

| Name | Value | Why |
| --- | --- | --- |
| `OLLABRIDGE_CLOUD_TOKEN` | operator cloud bearer token | **Optional** operator-wide fallback. Per-user linking stores each user's token server-side at sign-in, so this is only needed for an operator default. Written to `.env` **only when set**. |

## 4. Frontend flags — Repository variables (build-time)

On **Repository → Variables** (consumed by `container.yml` when it builds
`homepilot:latest`). Empty defaults preserve today's behavior, so these do
nothing until set, and only apply after the base image is rebuilt.

| Name | Value | Why |
| --- | --- | --- |
| `VITE_ACCOUNTS_UX` | `1` | Renders the OllaBridge account/computers UI under Settings → Providers |
| `VITE_BFF_SESSION` | `1` | Browser stops storing the cloud token (pairs with `HOMEPILOT_BFF_SESSION_ENABLED`) |
| `VITE_OLLABRIDGE_CLOUD_URL` | `https://app.ollabridge.com` | Optional — the code default is already this |

> Note: `VITE_ACCOUNTS_UX` currently surfaces the existing OllaBridge panel under
> Providers. Merging remote providers into the capability selectors is separate
> UI work not yet shipped, so treat this variable as optional until then.

---

## 5. Generated `.env` reference (written on the box)

For traceability, this is the full set of keys `oracle.yml` writes to
`/opt/homepilot/.env` on each deploy. Values in `${...}` come from GitHub;
literals are fixed by the workflow.

| Key | Source / default | Notes |
| --- | --- | --- |
| `HOMEPILOT_DOMAIN` | `${HOMEPILOT_DOMAIN}` | required |
| `ACME_EMAIL` | `${ACME_EMAIL}` | required |
| `HOMEPILOT_IMAGE` | `${IMAGE_REF}` | GHCR tag built this run |
| `HOMEPILOT_BIND_ADDRESS` | `127.0.0.1` | behind the reverse proxy |
| `API_KEY` | `${API_KEY}` | required |
| `HOMEPILOT_EDITION` | `web` | fixed |
| `PUBLIC_BASE_URL` | `https://${HOMEPILOT_DOMAIN}` | derived |
| `DATA_DIR` | `/home/user/app/data` | mounted writable volume |
| `OUTPUT_DIR` | `/home/user/app/data/outputs` | |
| `HOMEPILOT_LLM_BACKEND` | `openai` | fixed for hosted web |
| `OPENAI_API_KEY` | `${OPENAI_API_KEY:-}` | optional |
| `ANTHROPIC_API_KEY` | `${ANTHROPIC_API_KEY:-}` | optional |
| `INTERACTIVE_ENABLED` | `true` | |
| `INTERACTIVE_PLAYBACK_LLM` | `false` | |
| `INTERACTIVE_PLAYBACK_RENDER` | `false` | |
| `OLLABRIDGE_CLOUD_URL` | `${OLLABRIDGE_CLOUD_URL:-https://app.ollabridge.com}` | §2 |
| `OLLABRIDGE_CLOUD_TOKEN` | `${OLLABRIDGE_CLOUD_TOKEN}` | written only when set — §3 |
| `HOMEPILOT_MIRROR_BFF_ENABLED` | `${...:-true}` | §2 |
| `HOMEPILOT_BFF_SESSION_ENABLED` | `${...:-true}` | §2 |
| `HOMEPILOT_ACCOUNT_PROVIDERS_ENABLED` | `${...:-true}` | §2 |

---

## 6. Adding a new deployment variable (checklist)

When a future fix needs a new backend env var on the box, wire all three points
in `oracle.yml` or it will silently not reach the container:

1. Add it to the `env:` block of the **Bootstrap and deploy** step
   (`${{ vars.X || secrets.X }}` for config, `${{ secrets.X }}` for secrets).
2. Add its name to that step's `envs:` comma-separated allow-list.
3. Add an `echo "X=${X}"` line to the `.env` writer (use `${X:-default}` for a
   default, or the `[ -n "${X:-}" ] && echo ...` guard to write only when set).

For a new frontend `VITE_*` flag: add an `ARG`/`ENV` in `container/Dockerfile`
(before `npm run build`) and a `build-args:` line in `container.yml`.

## 7. Repository-secret vs Environment-secret

`oracle-production` **Environment** secrets/variables scope to this deployment
and are the right home for anything Oracle- or web-edition-specific. **Repository**
secrets (DockerHub, Cloudflare, R2, HF) are shared across all workflows. Put new
deploy config on the Environment unless it is genuinely shared.

# HomePilot One — setup and deployment

Architecture: [HOMEPILOT_ONE_ARCHITECTURE.md](HOMEPILOT_ONE_ARCHITECTURE.md).

## 1. Deploy in this order

1. **OllaBridge Cloud** — additive; existing clients are unaffected.
2. Set the shared secret on both services.
3. **HomePilot**.

Running HomePilot against a gateway that has not been upgraded yet works if
you set `HOMEPILOT_HOSTED_ALIAS=free-best`: chat goes through the gateway and
is answered, but the policy is ignored there (no tier order, no provenance).
Without that setting the new alias is unknown to the old gateway and
HomePilot answers with its own executor, as it does today.

## 2. Secrets and settings

Set these as Space secrets / environment variables. Never commit them.

### Both services

| Variable | Notes |
|---|---|
| `HOMEPILOT_POLICY_SECRET` | The same long random value on HomePilot and OllaBridge. Without it users' own Hugging Face tokens are not forwarded and paid fallback cannot be authorised. Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |

### HomePilot

| Variable | Default | Purpose |
|---|---|---|
| `HOMEPILOT_EDITION` | auto (`web` on a Space) | `web` or `local`. |
| `HOMEPILOT_ROUTING_STRATEGY` | `hf_first` on web, `legacy` on local | Default strategy for users who have not chosen. |
| `OLLABRIDGE_CLOUD_URL` | `https://app.ollabridge.com` | The gateway. One place; do not hardcode elsewhere. |
| `OLLABRIDGE_CLOUD_TOKEN` | — | Operator service token, used for hosted providers when a user has not linked their own OllaBridge account. Never used to reach devices. |
| `HOMEPILOT_HOSTED_ALIAS` / `HOMEPILOT_VISION_ALIAS` | `homepilot-auto` / `homepilot-vision` | Gateway aliases. |
| `HOMEPILOT_OPERATOR_INFERENCE` | `true` on web | May operator-held keys serve visitors who linked no account. `false` = each user pays with their own account or gets nothing hosted. |
| `HOMEPILOT_ALLOW_PAID_FALLBACK` | `false` | Paid kill switch. While false no user can enable paid providers. |
| `HOMEPILOT_MAX_REQUEST_COST_USD`, `HOMEPILOT_DAILY_BUDGET_USD`, `HOMEPILOT_MONTHLY_BUDGET_USD` | unset = no limit of that kind | Defaults; each user can set their own. |
| `HOMEPILOT_HF_INCLUDED_USD` | unset | The Hugging Face monthly allowance to track (e.g. `2.00` for PRO). Unset = not tracked; exhaustion is detected from Hugging Face's `402`. |
| `HOMEPILOT_MEDIA_VIA_GATEWAY` | `false` | Send image and text-to-video generation through gateway jobs. Needs `JOBS_ENABLED=true` on the gateway. |
| `HF_TOKEN` / `HOMEPILOT_HF_TOKEN` | — | The Space's own Hugging Face token (emergency direct path). |
| `DATA_DIR` | see below | Durable data root. |
| `HOMEPILOT_CLOUD_TOKEN_KEY`, `HOMEPILOT_COMPUTE_SECRET_KEY` | — | Fernet keys that encrypt stored tokens at rest. |
| `API_KEY` | — | Protects the OpenAI-compatible ingress. |

`GET /compute/readiness` lists what is still missing for production.

### OllaBridge Cloud

See `ollabridge-cloud/docs/HOMEPILOT_ONE_INTEGRATION.md`. In short:
`HOMEPILOT_POLICY_SECRET`, `HUGGINGFACE_API_KEY`, optional free and paid
provider keys, `JOBS_ENABLED=true` for hosted generation.

### The Hugging Face token must be able to run inference

Create a fine-grained token with **"Make calls to Inference Providers"**
(`inference.serverless.write`):
<https://huggingface.co/settings/tokens/new?ownUserPermissions=inference.serverless.write&tokenType=fineGrained>

A token with only repository permissions is accepted by `whoami` but every
inference call answers `403`. HomePilot and the gateway report that as
`auth_failed` and move to the next tier.

## 3. Durable storage (required for production)

HomePilot must not keep user data on the container's scratch disk.

* **Hugging Face Space:** attach persistent storage in the Space's Settings.
  It mounts at `/data` and HomePilot uses `/data/homepilot` automatically.
  This is a **paid Hugging Face add-on**; nothing in this repository
  provisions it. Until it is attached the Space runs on `/tmp/homepilot`,
  says so at boot, in `/compute/readiness` and in Settings → Compute → My AI.
* **Anywhere else:** mount a volume and set `DATA_DIR`.

First boot with a durable root copies any data found in `/tmp/homepilot` once;
it never overwrites what is already on the durable root.

### Backup and restore

```bash
python -m app.durable_storage status
```

```bash
python -m app.durable_storage backup --keep 7
```

```bash
python -m app.durable_storage list
```

```bash
python -m app.durable_storage restore /data/homepilot/backups/homepilot-backup-<stamp>.tar.gz --force
```

Run from the backend directory (`/app` in the Space image). `backup` is safe
while the app is running. Run `restore` with the app stopped; `--force` is
needed to replace an existing database, and the replaced file is kept beside
it as `homepilot.db.pre-restore`. The Space takes a backup at boot when the
latest is older than 24 hours. Backups live on the same volume: copy them off
the volume (`--dest`) for protection against losing the volume itself.

## 4. For users — no command line needed

* **Hugging Face:** Settings → Connectors → Continue with Hugging Face.
* **OllaBridge account:** Settings → OllaBridge Link.
* **My computer:** install HomePilot Local with OllaBridge on the PC and pair
  it from Settings → OllaBridge Link. The PC connects outbound; no router
  changes. It appears under My AI → My computers as online or offline.
* **How HomePilot chooses, and spending limits:** Settings → Compute → My AI.
  Private mode is "Private — my computers only".

HomePilot Web works without a linked PC. A linked PC that goes offline does
not affect cloud use, except in private mode, where requests then fail with an
explicit message instead of going to the cloud.

## 5. Rollback

| To undo | Do |
|---|---|
| The new routing, keeping the release | `HOMEPILOT_ROUTING_STRATEGY=legacy` (users who chose a strategy keep theirs; they can pick "This installation's provider") |
| Gateway generation jobs | `HOMEPILOT_MEDIA_VIA_GATEWAY=false` (the default) |
| The storage move | set `DATA_DIR` back; data on the durable root is untouched |
| Everything | redeploy the previous image. New tables (`user_routing_prefs`, `inference_usage`) are additive and ignored by the old code |

## 6. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Badge says a fallback answered: "did not accept the token" | The Hugging Face token lacks the Inference Providers permission. |
| "Hugging Face credits ran out" | Monthly allowance spent. Another free tier answers; or enable paid with a budget. |
| `device_offline` in private mode | No paired computer of yours is online. Start it, or change the routing mode. |
| `paid_not_authorized` / `budget_exceeded` | All free tiers failed and paid is off, or a limit was reached. |
| Model list not available in My AI | No usable gateway token, or the gateway predates `/v1/catalog`. |
| `invalid_policy` from the gateway | `HOMEPILOT_POLICY_SECRET` differs between the services, or clocks differ by more than two minutes. |
| Storage warning banner | Data is on `/tmp`. See section 3. |

# HomePilot on Oracle Cloud (Always Free)

This folder provides an additive deployment for an Oracle Cloud Infrastructure
(OCI) **Always Free** compute instance. It does not modify the existing
HomePilot frontend, backend, Docker Compose stack, or container image.

The wrapper image extends the published HomePilot image and injects the neutral
welcome notice plus the optional mature-mode consent dialog from
`notifications/`.

Everything here is designed to run at **$0** on Oracle's Always Free tier, using
an external LLM API instead of a local model.

## Always Free instance

Create an **Instance** (Compute → Instances → Create instance) with an Always
Free eligible shape:

| Shape | Arch | Free allowance | Notes |
|-------|------|----------------|-------|
| `VM.Standard.A1.Flex` | ARM (aarch64) | up to 4 OCPU / 24 GB RAM total | **Recommended** — plenty of headroom |
| `VM.Standard.E2.1.Micro` | x86_64 (AMD) | 1/8 OCPU / 1 GB RAM (up to 2) | Works but tight; add swap |

Other Always Free details:

- **Image:** **Oracle Linux 9** (default on the A1 shape, SSH user `opc`) or
  **Ubuntu** (SSH user `ubuntu`). `install.sh` detects the OS and configures
  Docker + the host firewall for either — no manual edits needed.
- **Boot/block storage:** stays within the 200 GB Always Free block volume total.
- **Public IP:** assign one (reserve it if you want it to survive instance
  recreation), and create a DNS **A record** pointing your domain at it.
- **SSH key:** add your public key during creation — this is the same key pair
  GitHub Actions will use to deploy.

Use external LLM APIs (OpenAI/Anthropic) rather than a local model on these
CPU-only shapes.

## 1. Open the network (OCI has two firewalls)

OCI blocks inbound traffic in **two** places — both must allow TCP 80 and 443:

1. **Security List / NSG (cloud firewall):** In the OCI console open
   Networking → Virtual Cloud Networks → your VCN → the instance's subnet →
   Security List, and add **Ingress** rules:
   - Source `0.0.0.0/0`, IP protocol TCP, destination port **80**
   - Source `0.0.0.0/0`, IP protocol TCP, destination port **443**
2. **Host firewall:** handled by `install.sh` below — `firewalld` on Oracle
   Linux, `iptables` on Ubuntu.

## 2. Bootstrap the instance

Clone the repository or copy this directory to the instance, then run:

```bash
sudo bash oracle/install.sh
sudo cp -R oracle /opt/homepilot
cd /opt/homepilot
cp .env.example .env
```

`install.sh` is OS-aware. It:

- installs Docker (dnf on Oracle Linux, apt on Ubuntu);
- opens ports 80/443 (firewalld on Oracle Linux, iptables on Ubuntu) and
  persists them across reboots;
- creates a **4 GB swap file** so pulls/spikes don't OOM-kill the app on the
  small shapes (override with `SWAP_SIZE=2G`, or `SWAP_SIZE=0` to skip);
- adds the deploy user (the account that ran `sudo`, e.g. `opc`) to the
  `docker` group and gives it `/opt/homepilot`, so no `chown`/`sudo` is needed.

> After `install.sh` adds you to the `docker` group, **open a new SSH session**
> before running `deploy.sh` so the group membership takes effect. (GitHub
> Actions reconnects on every run, so it is unaffected.)

Edit `.env`, set the domain and API credentials, and generate the application
API key:

```bash
openssl rand -hex 32
```

Do not expose HomePilot with an empty `API_KEY`.

## 3. Deploy

```bash
cd /opt/homepilot
bash deploy.sh
```

Caddy obtains and renews HTTPS certificates automatically. Ports 80 and 443
must be reachable (both firewalls above), and the domain must already resolve
to the instance.

## 4. GitHub Actions deployment

The workflow `.github/workflows/oracle.yml` builds the additive image
(multi-arch `linux/amd64,linux/arm64`, so it runs on either Always Free shape)
and publishes it as:

```text
ghcr.io/<repository-owner>/homepilot-oracle:<commit-sha>
```

Configure the `oracle-production` GitHub environment (Settings → Environments →
`oracle-production`). Non-sensitive values are **environment variables**;
credentials are **environment secrets**:

**Variables** (Environment variables):

- `ORACLE_HOST`: instance public IP or hostname (e.g. `193.122.156.100`)
- `ORACLE_USER`: SSH user with permission to run Docker + `sudo` — `opc` on
  Oracle Linux, `ubuntu` on Ubuntu
- `ORACLE_SSH_PORT`: optional; defaults to 22
- `HOMEPILOT_DOMAIN`: public hostname with a DNS A record → the instance IP
  (used to seed `.env` on first deploy)
- `ACME_EMAIL`: email for Let's Encrypt certificate registration

**Secrets** (Environment secrets):

- `ORACLE_SSH_PRIVATE_KEY`: private deployment key (full PEM, matching a public
  key in the instance's `~/.ssh/authorized_keys`)
- `HOMEPILOT_API_KEY`: application API key (`openssl rand -hex 32`)

> The workflow reads host/user/port/domain via `vars.*` and the key/API key via
> `secrets.*`. Putting `ORACLE_HOST`/`ORACLE_USER` under *Secrets* instead of
> *Variables* (or vice-versa for the key) leaves the value empty at deploy time
> and surfaces as `missing server host`.

### Zero-touch bootstrap

The `deploy` job is **self-bootstrapping** — it works against a bare instance,
so the manual steps in sections 2–3 above are optional. On each run it:

1. copies `oracle/` to the instance (staged in `$HOME`, then `sudo`-moved to
   `/opt/homepilot`);
2. runs `install.sh` on first deploy if Docker is absent (also creates swap and
   opens the host firewall);
3. creates `.env` from `.env.example` the first time, seeding it from
   `HOMEPILOT_DOMAIN` / `ACME_EMAIL` / `HOMEPILOT_API_KEY` — an existing `.env`
   is never overwritten, so operator edits survive;
4. points `HOMEPILOT_IMAGE` at the freshly built tag and runs `deploy.sh` via
   `sudo` (so it works before the new `docker` group membership takes effect).

You still must, once, in the OCI console: open **TCP 22, 80, 443** ingress on
the subnet Security List / NSG, and create a **DNS A record** for
`HOMEPILOT_DOMAIN` pointing at the instance IP — Caddy cannot obtain an HTTPS
certificate for an IP address, only for a real domain.

Make the GHCR package public, or authenticate Docker on the instance with a
read-only GitHub Packages token before deployment.

The workflow runs automatically after these deployment files are changed on
`master`, and it can also be started manually.

## Troubleshooting the build

### `docker.io/ruslanmv/homepilot:latest: not found`

The Oracle image is a thin wrapper that starts `FROM` the published HomePilot
image. If the build fails with:

```text
ERROR: failed to solve: ruslanmv/homepilot:latest:
failed to resolve source metadata for docker.io/ruslanmv/homepilot:latest: not found
```

the wrapper is trying to pull its base from **Docker Hub**, where a `:latest`
tag only exists after a GitHub *release* (`dockerhub.yml`). The base image is
published on every default-branch push to **GHCR** instead
(`ghcr.io/<owner>/homepilot:latest`, see `.github/workflows/container.yml`),
so the wrapper must build from GHCR:

- `oracle/Dockerfile` defaults to `ghcr.io/ruslanmv/homepilot:latest`.
- `.github/workflows/oracle.yml` passes
  `BASE_IMAGE=ghcr.io/${{ github.repository_owner }}/homepilot:latest` as a
  build arg, so forks build from their own GHCR image.

Before running the Oracle workflow, make sure the GHCR base image exists:
trigger **📦 Publish Container (GHCR)** (the `container.yml` workflow) once — via
a push that touches `container/`, `backend/`, or `frontend/`, a release, or a
manual **Run workflow** — and confirm `ghcr.io/<owner>/homepilot:latest` shows
up under the repository's *Packages*. The base image is already multi-arch
(`linux/amd64,linux/arm64`), so it builds on the ARM Ampere shape too.

### Warnings that are not the cause

The `Node 20 is being deprecated` notice and the `punycode module is
deprecated` `DeprecationWarning` come from the GitHub Actions runner and the
Docker action's Node runtime. They are informational only and do not fail the
build — the failure is always the missing base image above.

## Operations

View status and logs:

```bash
docker compose ps
docker compose logs -f homepilot
docker compose logs -f caddy
```

Back up persistent application data:

```bash
docker run --rm \
  -v oracle_homepilot-data:/data:ro \
  -v "$PWD":/backup \
  alpine tar czf "/backup/homepilot-data-$(date +%F).tar.gz" -C /data .
```

The exact Docker volume prefix depends on the Compose project directory. Confirm
it with `docker volume ls` before backing up.

### Resource limits

`docker-compose.yml` caps the app at **5 GB RAM** (`mem_limit`) with a 7 GB
RAM+swap ceiling (`memswap_limit`) and Caddy at **256 MB**, sized for the
1 OCPU / 6 GB `A1.Flex`. Container logs are rotated (3 × 10 MB) so they can't
fill the boot volume. On a larger shape, raise them in `.env` without editing
the compose file:

```bash
HOMEPILOT_MEM_LIMIT=20g
HOMEPILOT_MEMSWAP_LIMIT=24g
CADDY_MEM_LIMIT=512m
```

## Notice behavior

The welcome notice explains that HomePilot is a general-purpose AI platform. It
does not label the whole application as adult or pornographic.

Age confirmation appears only when the application dispatches:

```js
window.dispatchEvent(new CustomEvent("homepilot:mature-mode-requested"));
```

See `notifications/README.md` for the integration API. The browser notice does
not replace server-side moderation, account controls, or legally required
age-assurance measures.

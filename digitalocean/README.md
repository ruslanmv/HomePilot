# HomePilot on DigitalOcean

This folder provides an additive deployment for a DigitalOcean Ubuntu Droplet. It does not modify the existing HomePilot frontend, backend, Docker Compose stack, or container image.

The wrapper image extends the published HomePilot image and injects the neutral welcome notice plus the optional mature-mode consent dialog from `notifications/`.

## Recommended Droplet

- Ubuntu 24.04 LTS
- At least 4 GB RAM
- 50–80 GB storage
- A domain with an A record pointing to the Droplet
- External LLM APIs rather than a local model on a CPU-only Droplet

## 1. Bootstrap the server

Clone the repository or copy this directory to the Droplet, then run:

```bash
sudo bash digitalocean/install.sh
sudo cp -R digitalocean /opt/homepilot
sudo chown -R "$USER":"$USER" /opt/homepilot
cd /opt/homepilot
cp .env.example .env
```

Edit `.env`, set the domain and API credentials, and generate the application API key:

```bash
openssl rand -hex 32
```

Do not expose HomePilot with an empty `API_KEY`.

## 2. Deploy

```bash
cd /opt/homepilot
bash deploy.sh
```

Caddy obtains and renews HTTPS certificates automatically. Ports 80 and 443 must be reachable, and the domain must already resolve to the Droplet.

## 3. GitHub Actions deployment

The workflow `.github/workflows/digitalocean.yml` builds the additive image and publishes it as:

```text
ghcr.io/<repository-owner>/homepilot-digitalocean:<commit-sha>
```

Configure the `digitalocean-production` GitHub environment with:

- `DO_HOST`: Droplet IP or hostname
- `DO_USER`: SSH user with permission to run Docker
- `DO_SSH_PRIVATE_KEY`: private deployment key
- `DO_SSH_PORT`: optional; defaults to 22

The server must already contain `/opt/homepilot`, `docker-compose.yml`, `Caddyfile`, `deploy.sh`, and a completed `.env`.

Make the GHCR package public, or authenticate Docker on the Droplet with a read-only GitHub Packages token before deployment.

The workflow runs automatically after these deployment files are changed on `master`, and it can also be started manually.

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
  -v digitalocean_homepilot-data:/data:ro \
  -v "$PWD":/backup \
  alpine tar czf "/backup/homepilot-data-$(date +%F).tar.gz" -C /data .
```

The exact Docker volume prefix depends on the Compose project directory. Confirm it with `docker volume ls` before backing up.

## Notice behavior

The welcome notice explains that HomePilot is a general-purpose AI platform. It does not label the whole application as adult or pornographic.

Age confirmation appears only when the application dispatches:

```js
window.dispatchEvent(new CustomEvent("homepilot:mature-mode-requested"));
```

See `notifications/README.md` for the integration API. The browser notice does not replace server-side moderation, account controls, or legally required age-assurance measures.
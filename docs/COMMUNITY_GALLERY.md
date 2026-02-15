<p align="center">
  <img src="../assets/homepilot-logo.svg" alt="HomePilot" width="320" />
</p>

<p align="center">
  <b>COMMUNITY GALLERY</b><br>
  <em>Share personas with the world. Install with one click.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Status-Shipped-brightgreen?style=for-the-badge" alt="Shipped" />
  <img src="https://img.shields.io/badge/Cloud-Cloudflare_Worker+R2-orange?style=for-the-badge" alt="Cloudflare Worker + R2" />
  <img src="https://img.shields.io/badge/Pattern-MMORPG_Patcher-blue?style=for-the-badge" alt="MMORPG Patcher" />
  <img src="https://img.shields.io/badge/Tests-43_Passing-green?style=for-the-badge" alt="43 Tests" />
</p>

---

## The Problem

You spent an hour crafting the perfect persona — dialing in the personality, picking the right tools, generating the ideal avatar. It works beautifully on your machine. Now your friend in another country wants the same one.

What do you do? Copy-paste a JSON file? Write instructions? Upload screenshots?

This is not how sharing should work. A persona is a living identity — not a config dump.

---

## The Solution

The **Community Gallery** turns persona sharing into a one-click experience. You export a `.hpersona` file. It gets published to a cloud registry. Anyone running HomePilot can browse, search, preview, and install it — without leaving the app.

No accounts. No app stores. No walled gardens. Just a public registry and a file format that carries everything.

```
You create a persona in Tokyo.
Someone in Brazil opens their "Shared with me" tab.
They see your persona, click Install, and get the exact same identity.
Same personality. Same tools. Same look.
```

---

## How It Works

The architecture follows an **MMORPG patcher pattern** — the same technique used by game launchers to distribute and update assets at scale.

The production stack uses a **Cloudflare Worker** as the edge proxy in front of an R2 bucket. R2 direct access is kept as a fallback for development.

```
    ┌──────────────────────┐
    │   Cloudflare R2      │  <- immutable versioned packages (source of truth)
    │   (persona storage)  │
    └──────────┬───────────┘
               │
    ┌──────────┴───────────┐
    │   Cloudflare Worker  │  <- edge-cached, no rate limits, clean URLs
    │   (production proxy) │     https://homepilot-persona-gallery.cloud-data.workers.dev
    └──────────┬───────────┘
               │
    ┌──────────┴───────────┐
    │   HomePilot Backend  │  <- caching proxy, never exposes external URLs
    │   /community/*       │
    └──────────┬───────────┘
               │
    ┌──────────┴───────────┐
    │   HomePilot Frontend │  <- browse, search, one-click install
    │   "Shared with me"   │
    └──────────────────────┘
```

| | Production — Worker Proxy | Fallback — R2 Direct |
| :--- | :--- | :--- |
| **Env var** | `COMMUNITY_GALLERY_URL` | `R2_PUBLIC_URL` |
| **Status** | **Active default** | Development / backup |
| **Rate limits** | None (Workers free tier: 100k req/day) | Cloudflare-imposed on `r2.dev` |
| **Edge caching** | 60s registry, 1h assets, 24h packages | None |
| **URLs** | `/registry.json`, `/v/id/ver`, `/c/id/ver`, `/p/id/ver` | `/registry/registry.json`, `/previews/id/ver/preview.webp`, etc. |
| **Health check** | `GET /health` | N/A |

**Priority:** `COMMUNITY_GALLERY_URL` wins if both are set. To fall back to R2 direct, comment out `COMMUNITY_GALLERY_URL` in `.env`.

**Why a backend proxy?** The frontend never calls external URLs directly. This keeps CORS clean, keeps future auth/moderation server-side, caches the registry locally (2 minutes), and degrades gracefully when the gallery is offline.

---

## The Registry

Everything starts with `registry.json` — a single file that lists every published persona. Think of it as the patch manifest in a game launcher.

```json
{
  "schema_version": 1,
  "generated_at": "2026-02-15T12:00:00Z",
  "items": [
    {
      "id": "scarlett_exec_secretary",
      "name": "Scarlett",
      "short": "Executive secretary — professional, proactive",
      "tags": ["professional", "secretary"],
      "nsfw": false,
      "author": "HomePilot Community",
      "downloads": 1204,
      "latest": {
        "version": "1.0.0",
        "package_url": "/p/scarlett_exec_secretary/1.0.0",
        "preview_url": "/v/scarlett_exec_secretary/1.0.0",
        "card_url": "/c/scarlett_exec_secretary/1.0.0",
        "sha256": "",
        "size_bytes": 524288
      }
    }
  ]
}
```

URLs are **relative** — the backend proxy resolves them to absolute upstream URLs. This means the registry never hardcodes infrastructure details. Move to a different CDN tomorrow, and no client needs to update.

The registry may contain two URL formats depending on how it was populated:
- **Worker-relative:** `/p/id/ver`, `/v/id/ver`, `/c/id/ver` (from bootstrap)
- **R2-relative:** `packages/id/ver/persona.hpersona`, `previews/id/ver/preview.webp` (from GitHub Actions)

Both are resolved correctly by the backend regardless of which mode is active.

---

## The Install Flow

When a user clicks **Install** on a gallery card, three things happen automatically:

```
1. Download     -> fetch .hpersona from upstream (via backend proxy)
2. Preview      -> parse manifest, show persona card + dependency check
3. Install      -> create local persona project via POST /persona/import
```

The same import pipeline used for local `.hpersona` files is reused here — no new code paths, no new edge cases. If a package worked locally, it works from the gallery.

The dependency checker shows green/amber/red for each requirement (models, tools, MCP servers, A2A agents) so users know exactly what's ready before installing.

---

## Storage Layout

All assets live in a single R2 bucket, organized by persona and version:

```
registry/
  registry.json                     <- the catalog (short-cached, changes over time)

packages/<persona_id>/<version>/
  persona.hpersona                  <- downloadable package (immutable forever)

previews/<persona_id>/<version>/
  preview.webp                      <- card image (immutable)
  card.json                         <- pre-rendered metadata (immutable)
```

Versioned paths are **immutable** — once a version is uploaded, it never changes. This allows aggressive CDN caching (24h for packages), safe rollback, and clients that can pin exact versions.

---

## API Reference

### Cloudflare Worker (production)

Base URL: `https://homepilot-persona-gallery.cloud-data.workers.dev`

| Route | Description | Cache |
| :--- | :--- | :--- |
| `GET /registry.json` | Persona catalog | 60s client, 5min edge |
| `GET /v/<id>/<ver>` | Preview image (webp) | 1h, immutable |
| `GET /c/<id>/<ver>` | Card JSON | 1h, immutable |
| `GET /p/<id>/<ver>` | `.hpersona` package | 24h, immutable |
| `GET /health` | Health check | no-store |

### R2 Public Bucket (fallback)

Base URL: `https://pub-0274961e62694c09bdb4c8f2822ca3f1.r2.dev`

| Route | Description |
| :--- | :--- |
| `GET /registry/registry.json` | Persona catalog |
| `GET /previews/<id>/<ver>/preview.webp` | Preview image |
| `GET /previews/<id>/<ver>/card.json` | Card metadata |
| `GET /packages/<id>/<ver>/persona.hpersona` | `.hpersona` package |

### HomePilot Backend Proxy

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/community/status` | GET | Is the gallery configured and reachable? Returns `mode` (`worker` or `r2`). |
| `/community/registry` | GET | Cached registry with search, tag, NSFW filters |
| `/community/card/{id}/{ver}` | GET | Persona card metadata |
| `/community/preview/{id}/{ver}` | GET | Persona preview image |
| `/community/download/{id}/{ver}` | GET | Download `.hpersona` package |

**Registry query parameters:**

| Param | Type | Description |
| :--- | :--- | :--- |
| `search` | string | Filter by name, description, or tags |
| `tag` | string | Filter by exact tag match |
| `nsfw` | boolean | Show only SFW (`false`) or NSFW (`true`) personas |

---

## Getting Started

### Production Setup (Worker + R2)

The Worker is already deployed. For a fresh setup:

```bash
# 1. Bootstrap everything — creates R2 bucket, deploys Worker, uploads samples
make community-bootstrap

# 2. Your .env should have (already set by default in .env.example):
COMMUNITY_GALLERY_URL=https://homepilot-persona-gallery.cloud-data.workers.dev
R2_PUBLIC_URL=https://pub-0274961e62694c09bdb4c8f2822ca3f1.r2.dev

# 3. Restart HomePilot — the gallery appears in "Shared with me"
make run
```

#### Step-by-Step (if setting up from scratch)

1. **Deploy the Worker**

   ```bash
   cd community/worker
   npm install
   wrangler login       # first time only
   wrangler deploy
   ```

   Copy the Workers URL from the output.

2. **Create the R2 Bucket**

   ```bash
   wrangler r2 bucket create homepilot
   ```

3. **Upload Sample Data**

   ```bash
   cd community
   ./bootstrap.sh
   ```

4. **Configure HomePilot**

   ```bash
   # .env — Worker is primary, R2 is fallback
   COMMUNITY_GALLERY_URL=https://homepilot-persona-gallery.cloud-data.workers.dev
   R2_PUBLIC_URL=https://pub-0274961e62694c09bdb4c8f2822ca3f1.r2.dev
   ```

   Restart HomePilot. Open **Projects > Shared with me**. You should see the gallery.

5. **(Optional) Deploy the Public Gallery Page**

   ```bash
   make community-deploy-pages
   ```

### Fallback — R2 Direct (development only)

If you need to bypass the Worker temporarily (e.g., Worker is down, debugging):

1. Comment out `COMMUNITY_GALLERY_URL` in `.env`
2. Ensure `R2_PUBLIC_URL` is set
3. Restart HomePilot — the backend falls back to R2 direct mode automatically

> **Note:** The `r2.dev` URL is rate-limited by Cloudflare and not suitable for production traffic. Use it only for development or as a temporary fallback.

### GitHub Secrets for Automated Publishing

The persona-publish GitHub Actions pipeline needs these secrets (**Settings > Secrets and variables > Actions**):

| Secret | Required | Description |
| :--- | :--- | :--- |
| `R2_ACCESS_KEY_ID` | Yes | R2 API token Access Key ID |
| `R2_SECRET_ACCESS_KEY` | Yes | R2 API token Secret Access Key |
| `CLOUDFLARE_ACCOUNT_ID` | Yes | Cloudflare account ID |
| `R2_BUCKET_NAME` | Yes | R2 bucket name (e.g. `homepilot`) |
| `CLOUDFLARE_API_TOKEN` | Optional | API token with Cache Purge permission — purges Worker edge cache on publish for instant gallery updates. If not set, cache expires naturally (60s for registry). |

Create R2 API tokens at: **Cloudflare Dashboard > R2 > Overview > Manage R2 API Tokens** (not the User API Tokens page).

Create Cache Purge API token at: **Cloudflare Dashboard > My Profile > API Tokens > Create Token > Custom Token** with `Zone > Cache Purge > Purge` permission.

---

## Publishing Your Persona

### Automated (GitHub Issues)

The easiest way. Open a new issue using the **Persona Submission** template. Fill in the form, attach your `.hpersona` file, and a maintainer applies the `persona-approved` label. The pipeline handles everything:

1. Validates the package (ZIP, manifest, schema, size limit)
2. Extracts preview image and card metadata
3. Creates a GitHub Release with the `.hpersona` as a release asset
4. Uploads package, preview, and card to R2
5. Updates `registry.json` in R2
6. Purges the Worker edge cache (if `CLOUDFLARE_API_TOKEN` secret is set)
7. Comments with success details and closes the issue

### Manual (CLI)

#### 1. Export

In **My Projects**, find your persona card and click **Export**. You'll get a `.hpersona` file.

#### 2. Create a Preview Image

Generate or crop a 3:4 aspect ratio WebP image (600x800px recommended). This is the card thumbnail.

#### 3. Upload to R2

```bash
PERSONA_ID="my_persona"
VERSION="1.0.0"

wrangler r2 object put homepilot/packages/${PERSONA_ID}/${VERSION}/persona.hpersona \
  --file my_persona.hpersona --content-type "application/octet-stream"

wrangler r2 object put homepilot/previews/${PERSONA_ID}/${VERSION}/preview.webp \
  --file preview.webp --content-type "image/webp"

wrangler r2 object put homepilot/previews/${PERSONA_ID}/${VERSION}/card.json \
  --file card.json --content-type "application/json"
```

#### 4. Update the Registry

Add your persona entry to `registry.json` and re-upload:

```bash
wrangler r2 object put homepilot/registry/registry.json \
  --file registry.json --content-type "application/json"
```

Every HomePilot installation will see your persona within minutes (registry caches for 60 seconds at the edge, 2 minutes in the backend).

---

## File Structure

```text
community/
├── worker/                      # Cloudflare Worker (Option A)
│   ├── src/index.ts             # Registry + R2 proxy with caching
│   ├── wrangler.toml            # R2 bucket binding
│   └── package.json             # Dependencies
├── pages/                       # Static gallery website (Cloudflare Pages)
│   ├── index.html               # Browse personas in a browser
│   ├── app.js                   # Search + card rendering
│   └── styles.css               # Dark theme
├── scripts/
│   └── process_submission.py    # Validate, extract, build registry entries
├── sample/                      # Bootstrap sample data
│   ├── registry.json            # Example registry with 2 personas
│   └── card.json                # Example card metadata
└── bootstrap.sh                 # One-shot: bucket + upload + deploy
```

---

## Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `COMMUNITY_GALLERY_URL` | *(empty)* | **Production.** Worker URL (edge-cached, no rate limits). |
| `R2_PUBLIC_URL` | *(empty)* | **Fallback.** R2 public bucket URL (rate-limited, dev only). |

`COMMUNITY_GALLERY_URL` takes precedence when both are set. The `.env.example` ships with both set — Worker as primary, R2 as fallback.

When neither is set, the "Shared with me" tab shows a friendly setup prompt with a link to this doc. No errors, no broken UI — just a clear path to enable it.

The `/community/status` endpoint returns the active `mode` (`"worker"` or `"r2"`) and `reachable` status so the frontend can display which backend is serving the gallery.

---

## Test Coverage

The gallery ships with **43 tests** covering:

- Backend proxy endpoints (status, registry, card, preview, download)
- Registry caching and TTL behavior
- Server-side search/filter (name, tag, NSFW, combined)
- URL resolution (relative to absolute — both Worker and R2 formats)
- R2 direct mode (upstream URL construction, mode detection, priority)
- Graceful degradation (not configured, unreachable)
- Worker route regex patterns (including path traversal rejection)
- Registry schema validation
- R2 bucket key conventions
- End-to-end install flow (download -> preview -> import)
- Sample data integrity

```bash
# Run gallery tests only
python -m pytest backend/tests/test_community_gallery.py -v

# Run full suite
python -m pytest backend/tests/ -v
```

---

## Production Checklist

- [x] R2 bucket `homepilot` created
- [x] Cloudflare Worker deployed (`homepilot-persona-gallery`)
- [x] Worker URL: `https://homepilot-persona-gallery.cloud-data.workers.dev`
- [x] R2 public access enabled (fallback URL)
- [x] `.env` has `COMMUNITY_GALLERY_URL` set (Worker — primary)
- [x] `.env` has `R2_PUBLIC_URL` set (R2 direct — fallback)
- [x] `registry.json` uploaded to R2 (`registry/registry.json`)
- [ ] R2 API token created (for GitHub Actions uploads)
- [ ] GitHub Secrets configured (`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `R2_BUCKET_NAME`)
- [ ] (Optional) `CLOUDFLARE_API_TOKEN` secret for edge cache purge on publish
- [ ] Gallery visible in HomePilot **Shared with me** tab
- [ ] Static gallery page deployed (optional — `make community-deploy-pages`)

---

## What's Next

See [docs/TODO.md](./TODO.md) for the full roadmap. Key items:

- [ ] Custom domain for Worker (e.g. `gallery.yourdomain.com`)
- [ ] Auto-deploy Worker on push to `master` (GitHub Actions)
- [ ] Upload form — submit personas from the gallery page without CLI
- [ ] Moderation pipeline — approve/reject before listing
- [ ] `sha256` integrity verification on download
- [ ] Delta updates — download only what changed
- [ ] Featured personas and popularity sorting
- [ ] Rating system
- [ ] Update notifications for installed personas

---

<p align="center">
  <b>HomePilot Community Gallery</b>
  <br>
  <sub>Create once, share everywhere.</sub>
</p>

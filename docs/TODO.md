# HomePilot — Future Release TODO

> Tracking upcoming improvements, migrations, and production hardening tasks.

---

## COMPLETED: Community Gallery — Worker Proxy Migration

> **Completed February 2026** — Worker deployed and configured as the
> production primary. R2 direct kept as fallback.

- [x] Deploy Cloudflare Worker (`homepilot-persona-gallery`)
- [x] Worker URL: `https://homepilot-persona-gallery.cloud-data.workers.dev`
- [x] `.env.example` updated — `COMMUNITY_GALLERY_URL` is the active default
- [x] Backend (`config.py`, `community.py`) — Worker is primary, R2 is fallback
- [x] Gallery pages (`community/pages/index.html`, `docs/gallery.html`) — Worker mode
- [x] GitHub Actions `persona-publish.yml` — cache purge step added (step 11)

### Current architecture

```
Frontend ──> HomePilot Backend ──> Cloudflare Worker ──> R2 Bucket
                                  (edge-cached)         (source of truth)

GitHub Issue (persona-approved)
  └──> GitHub Actions persona-publish.yml
         ├── validate .hpersona
         ├── create GitHub Release
         ├── upload to R2
         ├── update registry.json in R2
         └── purge Worker edge cache (immediate visibility)
```

### Rollback to R2 direct

Comment out `COMMUNITY_GALLERY_URL` in `.env` and restart. `R2_PUBLIC_URL` takes over automatically.

---

## GitHub Actions — What It Should Do

The `persona-publish.yml` pipeline runs when `persona-approved` label is added to an issue:

### Current pipeline (12 steps)

| Step | Action | Status |
|------|--------|--------|
| 1 | Checkout repository | Done |
| 2 | Parse issue body (name, tags, version, URLs) | Done |
| 3 | Download `.hpersona` package | Done |
| 4 | Download preview image (if provided) | Done |
| 5 | Validate package (ZIP, manifest, schema, size) | Done |
| 6 | Extract metadata + preview assets | Done |
| 7 | Prepare R2 upload files | Done |
| 8 | Create GitHub Release with `.hpersona` asset | Done |
| 9 | Upload to Cloudflare R2 (package, preview, card) | Done |
| 10 | Update `registry.json` in R2 | Done |
| 11 | **Purge Worker edge cache** (new) | Done |
| 12 | Comment success + close issue | Done |

### Required GitHub Secrets

| Secret | Purpose |
|--------|---------|
| `R2_ACCESS_KEY_ID` | R2 API token Access Key ID |
| `R2_SECRET_ACCESS_KEY` | R2 API token Secret Access Key |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID |
| `R2_BUCKET_NAME` | R2 bucket name (e.g. `homepilot`) |
| `CLOUDFLARE_API_TOKEN` | **(new, optional)** API token with Cache Purge permission |

### Future GitHub Actions improvements

- [ ] Add a **scheduled workflow** to verify R2 registry integrity (weekly)
- [ ] Add a **persona removal workflow** — triggered by `persona-removed` label
- [ ] Add **size / download metrics** — update download counts in registry on release download events
- [ ] Add **Wrangler deploy step** — auto-redeploy Worker if `community/worker/` changes on push to `master`
- [ ] Add **Pages deploy step** — auto-redeploy gallery pages if `community/pages/` changes on push to `master`

---

## Community Gallery — Custom Domain (Optional)

Connect a custom domain to the Worker for cleaner URLs.

### Steps

1. **Cloudflare Dashboard** > Workers & Pages > `homepilot-persona-gallery` > Settings > Domains & Routes
2. Add domain (e.g. `gallery.yourdomain.com`) — must be on Cloudflare DNS
3. Update `.env`:
   ```bash
   COMMUNITY_GALLERY_URL=https://gallery.yourdomain.com
   ```
4. Update gallery pages JS config to match
5. Restart backend

### Alternative: Custom domain on R2 bucket (no Worker)

1. **Cloudflare Dashboard** > R2 > `homepilot` bucket > Settings > Custom Domains
2. Add domain (e.g. `r2.yourdomain.com`)
3. Update `.env`:
   ```bash
   R2_PUBLIC_URL=https://r2.yourdomain.com
   ```
4. Restart backend

---

## Other Future Items

### Community Gallery
- [ ] Upload form — submit personas from gallery page without CLI
- [ ] Moderation pipeline — approve/reject queue before listing
- [ ] `sha256` integrity verification on download
- [ ] Delta updates — download only what changed between versions
- [ ] Featured personas and popularity sorting
- [ ] Rating system (stars / thumbs)
- [ ] Update notifications for installed personas
- [ ] Persona collections / curated lists

### Infrastructure
- [x] ~~Cloudflare Worker proxy (remove `r2.dev` rate limit)~~ — **Done**
- [x] ~~CDN cache purge on registry update (via GitHub Actions)~~ — **Done**
- [ ] Custom domain for Worker or R2 bucket
- [ ] Monitoring / alerting for gallery uptime (`/health` endpoint ready)
- [ ] Automated backup of R2 registry data

### Platform
- [ ] Persona versioning — update installed personas from gallery
- [ ] Dependency auto-resolver — auto-install missing models/tools
- [ ] Gallery analytics — download counts, popular tags
- [ ] Multi-language persona support

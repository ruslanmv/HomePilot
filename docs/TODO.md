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

---

## COMPLETED: Multimodal Intelligence — Four Processing Topologies

> **Completed February 2026** — All 4 topologies implemented and tested.

- [x] T1: Basic Chat (direct LLM)
- [x] T2: Project-Scoped Knowledge (RAG with ChromaDB)
- [x] T3: Agent Tool Use (6-tool registry: vision, knowledge, memory recall/store, web search, image index)
- [x] T4: Knowledge Companion (agent + user profile + session context + persona memory)
- [x] Cross-topology Memory V2 ingestion
- [x] Frontend topology selector (direct / smart / agent / knowledge)
- [x] Image-as-text indexing pipeline (images → vision analysis → ChromaDB)
- [x] 800 backend tests passing, topology health tests for CI
- [x] Documentation: `docs/MULTIMODAL.md` + animated SVG diagrams in README

---

## Feature: Multi-User Accounts & Onboarding Wizard

> **Status**: In Progress
> **Priority**: High
> **Scope**: Allow multiple users on the same HomePilot instance, each with their own profile, personas, sessions, and memory. Minimalist onboarding (Claude-style, 3 steps max).

### Design

**Philosophy**: Open source, self-hosted — no phone verification, no plan selection, no external auth providers. Password is optional (for single-user local setups). Email is optional (for password recovery only).

### Onboarding Flow (3 steps)

```
Step 1: Create Account
  - Username (required)
  - Password (optional — skip for passwordless local use)
  - Email (optional — only for password recovery)

Step 2: About You
  - Display name / preferred name
  - What you'll use HomePilot for (multi-select):
    ○ Chat & conversation
    ○ Image generation & editing
    ○ Research & knowledge
    ○ Personal AI companion
    ○ Content creation
  - Preferred tone: Casual / Balanced / Professional

Step 3: Ready
  - Quick summary of your profile
  - "Start using HomePilot" button
  - Links to: Create your first persona, Explore the gallery
```

### Technical Plan

#### Backend
- [x] `users` SQLite table (id, username, password_hash, email, created_at, onboarding_complete)
- [x] `POST /v1/auth/register` — create account
- [x] `POST /v1/auth/login` — authenticate, return session token
- [x] `POST /v1/auth/logout` — invalidate session
- [ ] `POST /v1/auth/forgot-password` — send reset email (if email configured)
- [x] `PUT /v1/auth/onboarding` — save onboarding answers
- [x] Session tokens via bearer tokens (stored in `user_sessions` table, 30-day expiry)
- [ ] `user_id` foreign key added to: projects, conversations, profile, persona_sessions
- [x] Existing single-user data migrated to a default "admin" user on first boot

#### Frontend
- [x] Login/Register screen (shown when no active session)
- [x] 3-step onboarding wizard (shown after first registration)
- [ ] User switcher in sidebar (avatar + dropdown)
- [ ] All API calls include `Authorization: Bearer <token>` header
- [x] LocalStorage stores token per user

#### Migration Strategy (ADDITIVE)
- Existing data belongs to a default user (zero data loss)
- If only one user exists and no password is set, auto-login (backward compatible)
- Multi-user is opt-in: single-user setups work exactly as before

---

## Feature: Synthetic Avatar Generator (Optional Extra Package)

> **Status**: Planned
> **Priority**: Medium
> **Scope**: Add a dedicated avatar generation pipeline that can produce photorealistic synthetic face portraits — replicating the quality of services like *This Person Does Not Exist* (StyleGAN2) — as an optional, downloadable extra package within HomePilot.

### Background & Motivation

HomePilot currently generates persona avatars via **ComfyUI diffusion models** (SD1.5, SDXL, Flux) with text-to-image prompts. This works well for general imagery but has limitations for **face-specific** generation:

- Diffusion models can produce inconsistent facial features across batches
- No deterministic face identity control (seed-based reproducibility is approximate)
- Quality depends heavily on the prompt and model choice
- No face-identity-preserving regeneration (same person, different pose/outfit)

**Goal**: Provide an optional "Avatar Generator" workflow that uses **specialized face generation models** (GAN-based and identity-preserving diffusion adapters) to produce studio-quality synthetic portraits that rival services like *This Person Does Not Exist*, *Generated Photos*, and *Artbreeder*.

---

### How Existing Services Generate Faces

| Service | Underlying Model | Resolution | Self-Hostable? | License |
|---------|-----------------|------------|----------------|---------|
| **This Person Does Not Exist** | StyleGAN2 (NVIDIA, trained on FFHQ) | 1024x1024 | Yes (weights public) | Non-Commercial |
| **Generated Photos** | StyleGAN2 (custom private dataset) | 1024x1024 | No (proprietary fine-tune) | Proprietary |
| **Artbreeder** | BigGAN + StyleGAN + SDXL/Flux | 512-1024px | Partial (BigGAN Apache 2.0) | Mixed |
| **Fotor AI Face Generator** | Likely Stable Diffusion based | Unknown | No (proprietary) | Proprietary |
| **Adobe Firefly** | Proprietary diffusion transformer | Up to 4MP | No (fully proprietary) | Proprietary |

**Key insight**: The core technology behind "This Person Does Not Exist" is NVIDIA's **StyleGAN2** trained on the **FFHQ** (Flickr-Faces-HQ) dataset. The pre-trained weights are publicly available but under a **non-commercial** license. For commercial-safe alternatives, we target **Apache 2.0** licensed models.

---

### Proposed Architecture

```
HomePilot Frontend (PersonaWizard Step 3: Appearance)
    │
    ├── [Existing] Text-to-Image via ComfyUI (SD1.5/SDXL/Flux)
    │
    └── [NEW] Avatar Generator Mode (toggle in UI)
            │
            ├── Option A: StyleGAN2 Random Face
            │   └── Backend: FastAPI → StyleGAN2 inference → PNG
            │       (seed-based, instant, ~0.1s per face)
            │
            ├── Option B: Identity-Preserving Generation
            │   └── Backend: ComfyUI → InstantID / PhotoMaker V2 / PuLID
            │       (reference photo → consistent face in different styles)
            │
            └── Option C: Face Swap onto Diffusion Output
                └── Backend: ComfyUI → SD/SDXL generate body → InsightFace swap face
                    (best of both: creative poses + consistent face)
```

#### Data Flow (Option A — StyleGAN2 Random Face)

```
1. User clicks "Generate Avatar" with mode="stylegan"
2. Frontend POST /api/avatar/generate
   { mode: "stylegan", count: 4, truncation: 0.7, seed?: number }
3. Backend loads StyleGAN2 generator (cached in memory)
4. Generate N images from random/seeded latent vectors
5. Save to projects/{id}/persona/appearance/
6. Return URLs + seeds for reproducibility
7. User picks favorite → commit_persona_avatar() as usual
```

#### Data Flow (Option B — Identity-Preserving)

```
1. User uploads a reference face OR selects a StyleGAN2-generated face
2. Frontend POST /api/avatar/generate
   { mode: "instantid", reference_url: "...", prompt: "business attire, office" }
3. Backend routes to ComfyUI with InstantID/PhotoMaker workflow
4. ComfyUI generates identity-consistent images in requested style
5. Return URLs → user picks → commit
```

---

### Models to Include (Extra Package Downloads)

These models would be downloadable as optional extra packages via the existing
model management system, extending `edit_models.py` with a new `AVATAR_GENERATION`
category.

#### Tier 1 — Core Avatar Models (Recommended)

| Model | Type | License | VRAM | Size | HuggingFace / Download |
|-------|------|---------|------|------|----------------------|
| **StyleGAN2 FFHQ 1024x1024** | GAN (random faces) | Non-Commercial | 4-8 GB | ~370 MB | `NVlabs/stylegan2` via NGC |
| **StyleGAN2 FFHQ 256x256** | GAN (random faces, fast) | Non-Commercial | 2-3 GB | ~100 MB | `NVlabs/stylegan2` via NGC |
| **FLUX.1 [schnell]** | Diffusion (text-to-image) | Apache 2.0 | 8-16 GB | ~23 GB | `black-forest-labs/FLUX.1-schnell` |
| **InstantID** | Identity-preserving adapter | Apache 2.0 | 18 GB+ | ~1.7 GB | `InstantX/InstantID` |
| **PhotoMaker V2** | Identity-preserving adapter | Apache 2.0 | 11 GB+ | ~1.5 GB | `TencentARC/PhotoMaker-V2` |
| **InsightFace (antelopev2)** | Face detection + embeddings | MIT (code) | 2-4 GB | ~360 MB | `deepinsight/insightface` |

#### Tier 2 — Extended Models (Advanced Users)

| Model | Type | License | VRAM | Size | HuggingFace / Download |
|-------|------|---------|------|------|----------------------|
| **PuLID-FLUX** | Minimal-disruption face ID | Apache 2.0 | 16 GB | ~1.2 GB | `guozinan/PuLID` |
| **IP-Adapter-FaceID-PlusV2** | Face-conditioned generation | Non-Commercial | 8-18 GB | ~1.1 GB | `h94/IP-Adapter-FaceID` |
| **StyleGAN3 FFHQ 1024x1024** | Alias-free GAN | Non-Commercial | 8-12 GB | ~490 MB | `NVlabs/stylegan3` via NGC |
| **BigGAN-deep-512** | Class-conditional GAN | Apache 2.0 | 4-8 GB | ~340 MB | `huggingface/pytorch-pretrained-BigGAN` |
| **Qwen-Image** | Realistic human diffusion | Apache 2.0 | TBD | TBD | `Qwen/Qwen-Image` |

#### Tier 3 — Supporting / Post-Processing Models (Already Partially Present)

| Model | Purpose | License | Status in HomePilot |
|-------|---------|---------|-------------------|
| **GFPGANv1.4** | Face restoration / enhancement | Apache 2.0 | Already registered in `edit_models.py` |
| **CodeFormer** | Face restoration with fidelity | S-Lab License | Already registered in `edit_models.py` |
| **InsightFace inswapper_128** | Face swapping | MIT | New — for face swap workflows |

---

### Implementation Plan

#### Phase 1: Backend Model Registry Extension
- [ ] Add `ModelCategory.AVATAR_GENERATION` to `backend/app/edit_models.py`
- [ ] Register StyleGAN2 FFHQ weights (256, 1024) as downloadable models
- [ ] Register InsightFace antelopev2 as a dependency
- [ ] Register InstantID, PhotoMaker V2, PuLID as optional adapters
- [ ] Add download URLs and SHA256 checksums for each model
- [ ] Add `make download-avatar-models` target in Makefile

#### Phase 2: StyleGAN2 Inference Service
- [ ] Add `backend/app/avatar/stylegan_service.py`
  - Load StyleGAN2 generator from `.pkl` weights
  - Expose `generate(seeds, truncation_psi, count)` method
  - Support deterministic generation via seed
  - Cache generator in memory (lazy-load on first request)
  - CPU fallback if no GPU available (slower but functional)
- [ ] Add FastAPI endpoint `POST /api/avatar/generate`
  - Params: `mode`, `count`, `truncation`, `seed`, `resolution`
  - Returns: `{ urls: string[], seeds: number[] }`
- [ ] Wire into existing `commit_persona_avatar()` pipeline

#### Phase 3: ComfyUI Identity-Preserving Workflows
- [ ] Create ComfyUI workflow: `avatar_instantid.json`
  - Input: reference face image + text prompt
  - Pipeline: InsightFace embed → InstantID adapter → SDXL generate
  - Output: identity-consistent portrait
- [ ] Create ComfyUI workflow: `avatar_photomaker.json`
  - Input: 1-4 reference face images + text prompt
  - Pipeline: PhotoMaker V2 encoder → SDXL generate
- [ ] Create ComfyUI workflow: `avatar_faceswap.json`
  - Input: source face + target body prompt
  - Pipeline: SDXL generate body → InsightFace swap face → GFPGAN restore

#### Phase 4: Frontend UI Integration
- [ ] Add "Avatar Mode" toggle in PersonaWizard Step 3
  - Mode selector: "Creative" (existing) | "Portrait Studio" (new)
- [ ] Portrait Studio sub-options:
  - "Random Face" → StyleGAN2 batch of 4
  - "From Reference" → upload photo → InstantID/PhotoMaker
  - "Face + Style" → generate body, swap face
- [ ] Display seed alongside each generated face for reproducibility
- [ ] "Regenerate with same face" button (reuse seed, change outfit prompt)
- [ ] Store `avatar_generation_settings.mode = "stylegan" | "instantid" | "photomaker"`

#### Phase 5: Packaging & Distribution
- [ ] Create `make download-avatar-models-basic` (StyleGAN2 256px + InsightFace, ~460 MB)
- [ ] Create `make download-avatar-models-full` (all Tier 1 + Tier 2, ~28 GB)
- [ ] Add model availability checks in UI (gray out unavailable modes)
- [ ] Document GPU requirements per mode in Settings panel
- [ ] Export avatar generation mode in `.hpersona` package metadata

---

### Architecture Decision: Why StyleGAN2 + Identity Adapters

**StyleGAN2** was chosen as the primary GAN model because:
1. **Proven quality**: FID ~2.84 on FFHQ 1024x1024 — the gold standard for synthetic faces
2. **Speed**: ~0.1-0.3s per image (vs 3-10s for diffusion models)
3. **Deterministic**: Seed-based — same seed always produces the same face
4. **Lightweight**: Only 4-8 GB VRAM for inference (runs on consumer GPUs)
5. **Latent space control**: Can interpolate between faces, adjust attributes

**Identity-preserving adapters** (InstantID, PhotoMaker, PuLID) complement StyleGAN2:
1. **Consistency**: Generate the same person in different poses, outfits, settings
2. **Outfit system integration**: Perfect for HomePilot's existing wardrobe/outfit feature
3. **Reference-based**: Users can upload a photo or use a StyleGAN2 face as reference
4. **ComfyUI compatible**: Integrates with the existing generation pipeline

**Combined workflow** (face swap) provides the best of both worlds:
1. Use diffusion models for creative body/scene generation (existing strength)
2. Use InsightFace to swap in a consistent face identity
3. Use GFPGAN (already installed) to restore face quality after swap

### StyleGAN2 Generator Architecture (Reference)

```
Latent z (512-dim Gaussian)
    │
    ▼
Mapping Network (8-layer MLP)
    │
    ▼
Intermediate Latent w (512-dim, disentangled)
    │
    ▼
Synthesis Network:
    ├── Learned Constant (4x4x512)
    ├── Style Injection via Weight Modulation/Demodulation (replaces AdaIN)
    ├── Per-pixel Noise Injection (stochastic variation)
    ├── Progressive Upsampling: 4→8→16→32→64→128→256→512→1024
    └── Skip Connections (summing upsampled RGB at each resolution)
    │
    ▼
Output Image (1024x1024 RGB)
```

Key innovations over StyleGAN1:
- **Weight demodulation** eliminates droplet artifacts
- **No progressive growing** — fixed architecture with skip connections
- **Perceptual path length regularization** for smooth latent traversals
- **Lazy R1 regularization** every 16 minibatches

---

### Dependencies to Add to `pyproject.toml` (Optional Avatar Group)

```toml
[project.optional-dependencies]
avatar = [
    "torch>=2.0",
    "torchvision>=0.15",
    "numpy>=1.24",
    "Pillow>=10.0",
    "insightface>=0.7.3",
    "onnxruntime-gpu>=1.16",      # For InsightFace on GPU
    # "stylegan2-pytorch",         # Alternative: lucidrains pip package
]
```

---

### Configuration in `.env`

```bash
# Avatar Generator (Optional)
AVATAR_GENERATOR_ENABLED=false                       # Master toggle
AVATAR_STYLEGAN2_MODEL=stylegan2-ffhq-1024x1024.pkl # Default StyleGAN2 weights
AVATAR_STYLEGAN2_TRUNCATION=0.7                      # Default truncation psi
AVATAR_DEFAULT_MODE=stylegan                         # stylegan | instantid | photomaker
AVATAR_GPU_DEVICE=cuda:0                             # GPU device for StyleGAN2
```

---

### How to Implement (Step-by-Step Guide for Next Version)

#### Step 1: Download StyleGAN2 Weights

```bash
# Option A: From NVIDIA NGC (official)
wget https://api.ngc.nvidia.com/v2/models/nvidia/research/stylegan2/versions/1/files/stylegan2-ffhq-1024x1024.pkl \
  -O models/avatar/stylegan2-ffhq-1024x1024.pkl

# Option B: 256x256 (lighter, faster, good for avatars)
wget https://api.ngc.nvidia.com/v2/models/nvidia/research/stylegan2/versions/1/files/stylegan2-ffhq-256x256.pkl \
  -O models/avatar/stylegan2-ffhq-256x256.pkl
```

#### Step 2: Create the StyleGAN2 Service

```python
# backend/app/avatar/stylegan_service.py (pseudocode)
import torch
import pickle
from PIL import Image

class StyleGAN2Service:
    def __init__(self, model_path: str, device: str = "cuda"):
        with open(model_path, 'rb') as f:
            self.G = pickle.load(f)['G_ema'].to(device).eval()
        self.device = device

    def generate(self, seeds: list[int], truncation: float = 0.7) -> list[Image.Image]:
        images = []
        for seed in seeds:
            z = torch.randn(1, self.G.z_dim,
                          generator=torch.Generator(self.device).manual_seed(seed),
                          device=self.device)
            img = self.G(z, None, truncation_psi=truncation)
            img = (img.clamp(-1, 1) + 1) / 2 * 255
            img = img[0].permute(1, 2, 0).cpu().numpy().astype('uint8')
            images.append(Image.fromarray(img))
        return images
```

#### Step 3: Add the API Endpoint

```python
# In backend/app/main.py
@app.post("/api/avatar/generate")
async def generate_avatar(body: dict):
    mode = body.get("mode", "stylegan")
    count = min(body.get("count", 4), 8)
    truncation = body.get("truncation", 0.7)
    seeds = body.get("seeds") or [random.randint(0, 2**32) for _ in range(count)]

    if mode == "stylegan":
        service = get_stylegan_service()  # Lazy singleton
        images = service.generate(seeds, truncation)
        urls = save_temp_images(images)
        return {"urls": urls, "seeds": seeds, "mode": "stylegan"}
    elif mode == "instantid":
        # Route to ComfyUI InstantID workflow
        ...
```

#### Step 4: Frontend Toggle

Add a mode selector in `PersonaWizard.tsx` Step 3 that switches between
"Creative Mode" (existing ComfyUI text-to-image) and "Portrait Studio"
(StyleGAN2 / identity-preserving generation).

---

### License Considerations

| Model | License | Commercial Use |
|-------|---------|---------------|
| StyleGAN2/3 (NVIDIA) | NVIDIA Source Code License | **No** — research/personal only |
| FLUX.1 [schnell] | Apache 2.0 | **Yes** |
| InstantID | Apache 2.0 | **Yes** |
| PhotoMaker V2 | Apache 2.0 | **Yes** |
| PuLID | Apache 2.0 | **Yes** |
| InsightFace (code) | MIT | **Yes** |
| InsightFace (training data) | Non-commercial | **No** (for retraining) |
| BigGAN | Apache 2.0 | **Yes** |
| IP-Adapter-FaceID | Non-commercial | **No** |

**Recommendation**: For commercial deployments, use the **Apache 2.0 stack**
(FLUX.1 schnell + InstantID + PhotoMaker V2 + PuLID). Reserve StyleGAN2 for
personal/research use or contact NVIDIA for a commercial license.

---

### ComfyUI Workflow Nodes Required

For identity-preserving avatar generation via ComfyUI, these custom node
packages need to be installed:

| Node Package | Purpose | Install |
|-------------|---------|---------|
| `ComfyUI_InstantID` | InstantID face-identity adapter | `cd custom_nodes && git clone https://github.com/cubiq/ComfyUI_InstantID` |
| `ComfyUI-PhotoMaker-Plus` | PhotoMaker V2 adapter | `cd custom_nodes && git clone https://github.com/shiimizu/ComfyUI-PhotoMaker-Plus` |
| `ComfyUI_IPAdapter_plus` | IP-Adapter FaceID variants | `cd custom_nodes && git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus` |
| `ComfyUI_InsightFace` | Face detection / embedding | `cd custom_nodes && git clone https://github.com/cubiq/ComfyUI_FaceAnalysis` |

---

### Models Already Supported in `modelPresets.ts` (Current)

For reference, these are the text-to-image models already registered:

**SDXL**: `sd_xl_base_1.0`, `ponyDiffusionV6XL`
**Flux**: `flux1-schnell`, `flux1-dev`
**SD 1.5**: `dreamshaper_8`, `epicrealism_pureEvolution`, `abyssOrangeMix3_aom3a1b`,
`realisticVisionV51`, `deliberate_v3`, `cyberrealistic_v42`, `absolutereality_v181`,
`aZovyaRPGArtist_v5`, `unstableDiffusion`, `majicmixRealistic_v7`, `bbmix_v4`,
`realisian_v50`, `counterfeit_v30`, `anything_v5PrtRE`

**Face Restoration (edit_models.py)**: `GFPGANv1.4`, `CodeFormer`

The avatar generator models above are **additive** — they don't replace any
existing models but provide a new specialized pipeline alongside them.

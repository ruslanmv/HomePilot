# Avatar UX Feasibility Analysis

> Technical assessment of live preview, layout optimization, and hybrid avatar architecture
> for the HomePilot Avatar Studio.

---

## 1. Current Architecture (Verified)

The avatar system spans three layers with clear separation of concerns:

```
Frontend (React + Zustand)
  AvatarStudio.tsx          — Hub: tabs, generation modes, gallery
  CharacterWizard.tsx       — 7-step wizard (Identity → Generate)
  AvatarViewer.tsx          — RPG character sheet (split-panel)
  AvatarGallery.tsx         — Persistent filmstrip (localStorage)
        ↓
Backend (FastAPI)
  avatar/router.py          — /v1/avatars/generate, /v1/avatars/packs
  avatar/service.py         — Mode routing orchestrator
  avatar/outfit.py          — /v1/avatars/outfits (face-preserving variations)
  avatar/availability.py    — Runtime mode detection
  personas/avatar_assets.py — Durable project storage + thumbnail gen
        ↓
Generation Engines
  ComfyUI (:8188)           — studio_reference, studio_faceswap, creative
  avatar-service (:TBD)     — studio_random (StyleGAN — NOT YET IMPLEMENTED)
```

### Key files examined

| File | Purpose | Status |
|------|---------|--------|
| `avatar-service/app/stylegan/generator.py` | StyleGAN2 inference | **Placeholder** — raises `NotImplementedError` |
| `backend/app/avatar/service.py` | Mode router | Working — routes to ComfyUI or avatar-service |
| `backend/app/avatar/availability.py` | Capability detection | Working — checks pack markers + model presence |
| `backend/app/avatar/outfit.py` | Outfit variations | Working — uses `studio_reference` with high denoise (0.85) |
| `backend/app/personas/avatar_assets.py` | Persona avatar storage | Working — copies, thumbs, asset registry |
| `frontend/src/ui/avatar/wizard/CharacterWizard.tsx` | 7-step wizard | Working — full prompt assembly pipeline |
| `frontend/src/ui/avatar/wizard/wizardTypes.ts` | Type system + presets | Working — 80+ preset options mapped to SD prompts |
| `backend/app/models/packs/manifests/avatar-basic.json` | Basic pack | Enables: `studio_reference`, `studio_faceswap`, `creative` |
| `backend/app/models/packs/manifests/avatar-full.json` | Full pack | Enables: all modes including `studio_random` |

---

## 2. Generation Modes — Actual Status

| Mode | Engine | Status | Latency |
|------|--------|--------|---------|
| `studio_reference` | ComfyUI (InstantID/PhotoMaker) | **Working** | 5–20s |
| `studio_faceswap` | ComfyUI (face swap + restore) | **Working** | 5–20s |
| `creative` | ComfyUI (text-to-image) | **Working** | 5–20s |
| `studio_random` | avatar-service (StyleGAN2) | **Not implemented** | N/A |

**Evidence** — `avatar-service/app/stylegan/generator.py:12-21`:
```python
def generate_faces(count=4, seeds=None, truncation=0.7):
    raise NotImplementedError(
        "StyleGAN2 inference not yet implemented. "
        "Using placeholder PNG generator instead."
    )
```

The wizard defaults to `studio_random` mode (`wizardTypes.ts:132`), which means
the "Design Character" flow currently remaps to `creative` mode at generation time
(`CharacterWizard.tsx:486`):
```typescript
const apiMode = draft.generationMode === 'studio_random' ? 'creative' : draft.generationMode
```

---

## 3. Wizard State & Prompt Assembly

The wizard accumulates a `CharacterDraft` (27 fields across 7 steps) and builds
a Stable Diffusion prompt from all presets at generation time.

**Prompt assembly pipeline** (`CharacterWizard.tsx:166-280`):
```
portraitType → framing
gender + ageRange → subject
bodyType + posture → build
skinTone → skin (SD prompt fragment)
facePreset + eyes + expression → face
hairStyle + hairColor → hair
outfitStyle + colors + accessories → outfit
pose + background + lighting → scene
nsfwExposure + intensity (gated) → NSFW modifiers
realism → quality suffix
```

Each preset maps to an SD prompt fragment. Example from `wizardTypes.ts`:
- `skinTone: 'porcelain'` → `"porcelain fair skin, luminous complexion"`
- `hairStyle: 'bun'` → `"elegant updo bun hairstyle"`
- `expression: 'professional_smile'` → `"professional confident smile"`

**Current preview**: None during steps 1-6. The user only sees results after
clicking Generate on step 7.

---

## 4. Impact on Live Preview Feasibility

### Why real-time AI preview is impossible

Every generation call hits ComfyUI's diffusion pipeline:

```
backend/avatar/service.py → run_avatar_workflow()
  → ComfyUI HTTP API (:8188)
  → queue prompt → poll for completion → download result
```

Per-generation: **5–20 seconds** depending on resolution, sampler steps, and GPU.

Updating on every slider/pill change would require ~100+ generations during a
typical wizard session. At 10s each, that's 16+ minutes of GPU time for a single
character creation. This is not viable.

### Why parametric preview IS feasible

The wizard already has all the data needed for a layered preview:
- Gender, body type, skin tone, face shape, eye color, hair style/color,
  outfit style, accessories, pose, lighting

A CSS/SVG/Canvas layer compositor can render these instantly (~0.5ms) without
any backend call.

---

## 5. Two UX Strategies Compared

### Option A — AI-Only (Current System)

```
User fills wizard → clicks Generate → ComfyUI processes → result image
```

- Preview: empty placeholder or silhouette until step 7
- Feedback: delayed (5-20s per attempt)
- Pattern: Midjourney / Leonardo AI / Playground AI

### Option B — Hybrid (Recommended)

```
Steps 1-6: Parametric live preview (instant)
Step 7: AI generation via ComfyUI (5-20s, final polish)
```

- Preview: layered composition updates on every change
- Feedback: instant during design, one wait at the end
- Pattern: ReadyPlayerMe / Bitmoji / Meta Avatars

---

## 6. What Already Exists to Support Hybrid Preview

### 6.1 Asset infrastructure

The backend already manages avatar asset packs:

```json
// backend/app/models/packs/manifests/avatar-basic.json
{
  "id": "avatar-basic",
  "modes_enabled": ["studio_reference", "studio_faceswap", "creative"]
}
```

Pack detection is automatic (`availability.py:56-58`) — if model files exist on
disk, the pack marker is auto-created.

### 6.2 Persona avatar storage

`backend/app/personas/avatar_assets.py` provides:
- `commit_persona_avatar()` — copy + top-crop thumbnail + asset registry
- `ensure_thumb_for_selected()` — on-demand thumbnail generation
- `commit_persona_image()` — batch image storage for outfits/siblings

### 6.3 Community avatar assets

Pre-built avatar PNGs exist:
```
community/sample/atlas/assets/avatar_atlas.png
community/sample/diana/assets/avatar_diana.png
community/sample/elena/assets/avatar_elena.png
... (12 sample personas with avatars)
```

### 6.4 Gallery persistence

`useAvatarGallery.ts` manages a localStorage gallery with:
- Anchor + portraits pattern (root character + variations)
- Scenario tagging (business, casual, evening, swimwear, etc.)
- Wizard metadata preservation for persona export

### 6.5 Wizard state is already structured

`CharacterDraft` in `wizardTypes.ts` contains exactly the fields needed
to drive a parametric preview:
```typescript
interface CharacterDraft {
  gender: Gender           // selects base model
  bodyType: BodyType       // body layer variant
  skinTone: string         // color layer
  facePreset: string       // face shape layer
  eyeColor: string         // eye overlay
  hairStyle: string        // hair layer
  hairColor: string        // hair color variant
  outfitStyle: string      // outfit layer
  accessories: string[]    // accessory overlays
  // ... 18 more fields
}
```

---

## 7. Recommended Architecture: Hybrid Preview System

### 7.1 Component design

```tsx
// New component: AvatarPreview.tsx
<AvatarPreviewCanvas>
  <BaseLayer gender={draft.gender} bodyType={draft.bodyType} skinTone={draft.skinTone} />
  <FaceLayer preset={draft.facePreset} eyeColor={draft.eyeColor} expression={draft.expression} />
  <HairLayer style={draft.hairStyle} color={draft.hairColor} />
  <OutfitLayer style={draft.outfitStyle} primaryColor={draft.outfitPrimaryColor} />
  {draft.accessories.map(id => <AccessoryLayer key={id} accessoryId={id} />)}
</AvatarPreviewCanvas>
```

### 7.2 Wizard layout transformation

Current layout (steps 1-6):
```
┌──────────────────────────────────────┐
│  Step Nav  │  Controls (left-heavy)  │
│            │                         │
│            │                         │
│            │     (empty space →)     │
└──────────────────────────────────────┘
```

Proposed layout:
```
┌──────────────────────────────────────────────────┐
│  Step Nav  │  Controls          │  Avatar Preview │
│            │  (pill buttons,    │  (live layered  │
│            │   sliders, etc.)   │   composition)  │
│            │                    │                 │
└──────────────────────────────────────────────────┘
```

This is purely a CSS/layout change — **no backend modifications needed**.

### 7.3 State flow

```
wizardState (CharacterDraft)
    ↓ (React state)
AvatarPreview component
    ↓ (CSS layers / Canvas / SVG)
Instant visual feedback (~0.5ms)
```

At step 7 (Generate):
```
wizardState → buildPrompt() → API call → ComfyUI → final HD image
```

---

## 8. Implementation Requirements

### 8.1 What needs to be built

| Component | Effort | Description |
|-----------|--------|-------------|
| `AvatarPreview.tsx` | Medium | Layer compositor (CSS/Canvas/SVG) |
| Avatar asset sprites | Medium | Layered PNG/SVG assets per preset |
| Wizard layout CSS | Low | 3-column grid for steps + controls + preview |
| State → preview binding | Low | Wire `CharacterDraft` to layer props |

### 8.2 What already exists (no changes needed)

| Component | Location |
|-----------|----------|
| Wizard state management | `CharacterWizard.tsx` (useState + update callback) |
| Preset system | `wizardTypes.ts` (80+ preset options) |
| Prompt builder | `CharacterWizard.tsx:166-280` |
| Generation API | `avatar/router.py`, `avatar/service.py` |
| Gallery persistence | `useAvatarGallery.ts` |
| Asset storage | `personas/avatar_assets.py` |

### 8.3 Asset strategy for preview layers

Three approaches (ascending quality):

1. **CSS-composed placeholders** — Colored silhouettes with overlaid features.
   Fastest to implement, lowest fidelity. Good for MVP.

2. **SVG layer system** — Vector avatar parts (body, face, hair, outfit) composed
   via `<svg>` overlays. Medium effort, scales well, resolution-independent.

3. **Pre-rendered sprite sheets** — Diffusion-generated asset layers for each
   preset combination. Highest fidelity, requires initial generation pass.

**Recommended**: Start with approach 2 (SVG), upgrade to approach 3 later.

---

## 9. Feasibility Matrix

| Feature | Feasible | Effort | Notes |
|---------|----------|--------|-------|
| Wizard layout redesign (3-column) | Yes | Low | Pure CSS change |
| Centered content / reduce empty space | Yes | Low | Layout adjustment |
| Live parametric preview (SVG layers) | Yes | Medium | New component + assets |
| Live parametric preview (sprite sheets) | Yes | High | Requires asset pipeline |
| Real-time AI preview (per-change) | **No** | — | 5-20s latency per call |
| AI final render (step 7) | Yes | — | Already working |
| Hybrid preview → AI final | **Best** | Medium | Recommended approach |
| StyleGAN random mode | No | High | `generator.py` is placeholder |

---

## 10. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| SVG assets don't match AI output | Medium | Use preview as "sketch", AI as "polish" — set user expectation |
| Asset creation is time-consuming | Medium | Start with minimal set (gender × body type × 3 hair = ~18 variants) |
| Preview adds bundle size | Low | Lazy-load preview assets; compress SVGs |
| StyleGAN still unimplemented | Low | Not needed for hybrid approach; creative mode works |

---

## 11. Summary

The user-facing analysis is **confirmed accurate** with the following refinements:

1. **StyleGAN is fully placeholder** — the `studio_random` mode silently falls back to
   `creative` (ComfyUI text-to-image) in the wizard.

2. **ComfyUI generation works** but is inherently slow (5-20s), ruling out per-change preview.

3. **The hybrid approach is the clear winner** — parametric preview for instant feedback,
   AI generation only at the final step.

4. **The biggest missing piece is `AvatarPreview.tsx`** — a layer compositor component
   and its associated SVG/PNG asset library. Everything else (state management, prompt
   building, API, storage) already exists and is production-ready.

5. **Layout changes are trivial** — the wizard already uses Tailwind CSS with a responsive
   grid. Adding a third column for preview is a straightforward CSS modification.

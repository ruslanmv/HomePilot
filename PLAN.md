# Design Plan — Four Additive Features

> **Constraint**: Non-destructive, additive only. No existing behavior is modified.
> Every change is a new file, new type, new prop, new endpoint, or new optional UI section.

---

## Feature 1: Avatar Gallery — Persistent Library Across Sessions

### Why first?
Gallery is the storage foundation that Features 2, 3, and 4 consume. Avatars from AvatarStudio currently vanish on navigation. Gallery gives them a home.

### New files

| File | Purpose |
|------|---------|
| `frontend/src/ui/avatar/galleryTypes.ts` | `GalleryItem` type + storage key constants |
| `frontend/src/ui/avatar/useAvatarGallery.ts` | Hook: load / save / delete from `localStorage` |
| `frontend/src/ui/avatar/AvatarGallery.tsx` | Visual strip below AvatarStudio results grid |

### Types (`galleryTypes.ts`)

```ts
export interface GalleryItem {
  id: string                     // uuid
  url: string                    // full image URL (ComfyUI or backend)
  seed?: number
  prompt?: string
  mode: AvatarMode               // which mode produced this
  referenceUrl?: string          // if identity-based
  createdAt: number              // Date.now()
  tags?: string[]                // optional user labels
  personaProjectId?: string      // set when "Save as Persona Avatar" is used
}

export const GALLERY_STORAGE_KEY = 'homepilot_avatar_gallery'
export const GALLERY_MAX_ITEMS = 200
```

### Hook (`useAvatarGallery.ts`)

```ts
export function useAvatarGallery() {
  const [items, setItems] = useState<GalleryItem[]>(() => loadFromStorage())

  const addItem    = (item: Omit<GalleryItem, 'id' | 'createdAt'>) => { ... }
  const addBatch   = (results: AvatarResult[], mode, prompt, referenceUrl?) => { ... }
  const removeItem = (id: string) => { ... }
  const clearAll   = () => { ... }
  const tagItem    = (id: string, tags: string[]) => { ... }

  // Auto-persist on change
  useEffect(() => {
    localStorage.setItem(GALLERY_STORAGE_KEY, JSON.stringify(items))
  }, [items])

  return { items, addItem, addBatch, removeItem, clearAll, tagItem }
}
```

### Component (`AvatarGallery.tsx`)

- Horizontal scrollable filmstrip (matches Edit history strip aesthetic)
- Appears below the results grid in AvatarStudio
- Each thumbnail shows: image, seed, timestamp
- Hover actions: View (lightbox), Open in Edit, Delete, **Save as Persona Avatar** (Feature 3 button)
- "Clear Gallery" confirmation button
- Empty state: "Generated avatars will appear here"

### Integration into AvatarStudio.tsx (additive only)

Add a single new prop + render the gallery strip:

```tsx
// NEW optional prop on AvatarStudioProps:
onSaveAsPersonaAvatar?: (item: GalleryItem) => void

// After results grid, add:
<AvatarGallery
  items={gallery.items}
  onDelete={gallery.removeItem}
  onOpenLightbox={onOpenLightbox}
  onSendToEdit={onSendToEdit}
  onSaveAsPersonaAvatar={onSaveAsPersonaAvatar}
/>
```

After each successful generation, call `gallery.addBatch(gen.result.results, mode, prompt, referenceUrl)`.

---

## Feature 2: Persona Integration — "Save as Persona Avatar"

### Flow

```
AvatarStudio / Gallery
  └── User clicks "Save as Persona Avatar" on any avatar
        └── Opens PersonaWizard pre-filled:
              - Step 0: skipped (defaults to Custom)
              - Step 2: avatar already selected (no generation needed)
              - Step 3: review → create project
```

### New files

| File | Purpose |
|------|---------|
| `frontend/src/ui/avatar/SaveAsPersonaModal.tsx` | Lightweight modal: pick persona class + name, then auto-create |
| `frontend/src/ui/avatar/personaBridge.ts` | Helper: build a `PersonaWizardDraft` from a `GalleryItem` |

### `personaBridge.ts`

```ts
import type { PersonaWizardDraft, PersonaAppearance, PersonaImageRef } from '../personaTypes'
import type { GalleryItem } from './galleryTypes'

/**
 * Build a PersonaWizardDraft pre-populated with an existing avatar image.
 * The wizard can then skip straight to Step 1 (Identity) or Step 3 (Review).
 */
export function draftFromGalleryItem(
  item: GalleryItem,
  personaName: string,
  classId: PersonaClassId = 'custom',
): PersonaWizardDraft {
  const imageRef: PersonaImageRef = {
    id: item.id,
    url: item.url,
    created_at: new Date(item.createdAt).toISOString(),
    set_id: 'avatar_studio',
    seed: item.seed,
  }

  const appearance: PersonaAppearance = {
    ...defaultAppearance(),
    sets: [{ set_id: 'avatar_studio', images: [imageRef] }],
    selected: { set_id: 'avatar_studio', image_id: item.id },
  }

  return {
    persona_class: classId,
    persona_agent: { ...defaultPersonaAgent(), label: personaName },
    persona_appearance: appearance,
    memory_mode: 'adaptive',
    agentic: { goal: '', capabilities: [] },
  }
}
```

### `SaveAsPersonaModal.tsx`

- Small centered modal (matches cyber-noir aesthetic)
- Fields: **Persona Name** (text), **Class** (dropdown from `PERSONA_BLUEPRINTS`)
- Two buttons: "Open in Wizard" (full customization) / "Quick Create" (auto-create project)
- "Open in Wizard" → opens PersonaWizard with pre-built draft (new optional `initialDraft` prop on PersonaWizard)
- "Quick Create" → calls `createPersonaProject()` directly with the bridge-built draft

### PersonaWizard changes (additive only)

Add ONE new optional prop — no existing logic changes:

```tsx
// New optional prop:
initialDraft?: Partial<PersonaWizardDraft>

// In useState initializer, merge:
const [draft, setDraft] = useState<PersonaWizardDraft>(() => ({
  ...buildDefaultDraft(),
  ...initialDraft,
}))

// If initialDraft has a selected avatar, auto-advance initialStep to 1 or 3
const [step, setStep] = useState(() => {
  if (initialDraft?.persona_appearance?.selected) return 1  // skip to Identity
  return 0
})
```

### App.tsx integration

```tsx
// New state:
const [saveAsPersonaItem, setSaveAsPersonaItem] = useState<GalleryItem | null>(null)

// In AvatarStudio render:
onSaveAsPersonaAvatar={(item) => setSaveAsPersonaItem(item)}

// After AvatarStudio:
{saveAsPersonaItem && (
  <SaveAsPersonaModal
    item={saveAsPersonaItem}
    backendUrl={...}
    apiKey={...}
    onClose={() => setSaveAsPersonaItem(null)}
    onOpenWizard={(draft) => {
      setSaveAsPersonaItem(null)
      // open PersonaWizard with initialDraft
    }}
    onCreated={(project) => {
      setSaveAsPersonaItem(null)
      // navigate to project
    }}
  />
)}
```

---

## Feature 3: Outfit Variations — Wardrobe Changes for an Existing Avatar

### Concept

Given an existing avatar (from Gallery or Persona), generate outfit variations using the same face but different clothing/settings. Uses identity mode (InstantID) when available, or standard prompting as fallback.

### New files

| File | Purpose |
|------|---------|
| `frontend/src/ui/avatar/OutfitPanel.tsx` | Side panel or section within AvatarStudio for outfit generation |
| `frontend/src/ui/avatar/useOutfitGeneration.ts` | Hook wrapping the generation API with outfit-specific defaults |
| `backend/app/outfit_api.py` | New FastAPI router — `/v1/avatars/outfits` endpoint |

### Backend: `outfit_api.py`

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List

router = APIRouter(prefix="/v1/avatars", tags=["avatars"])

class OutfitRequest(BaseModel):
    reference_image_url: str = Field(..., description="Avatar face to preserve")
    outfit_prompt: str = Field(..., description="Clothing/setting description")
    character_prompt: Optional[str] = Field(None, description="Face/body description override")
    count: int = Field(4, ge=1, le=8)
    seed: Optional[int] = None
    generation_mode: str = Field("identity", description="'identity' or 'standard'")

class OutfitResult(BaseModel):
    url: str
    seed: Optional[int] = None

class OutfitResponse(BaseModel):
    results: List[OutfitResult]
    warnings: Optional[List[str]] = None

@router.post("/outfits", response_model=OutfitResponse)
async def generate_outfits(req: OutfitRequest):
    """
    Generate outfit variations for an existing avatar.
    Uses the same generation pipeline as /v1/avatars/generate but with
    the reference image always passed as identity anchor.

    Falls back to standard text-to-image if identity models aren't installed.
    """
    # Implementation delegates to existing avatar generation logic
    # with mode='studio_reference' and outfit_prompt injected
    ...
```

Register in `main.py` (additive):
```python
from app.outfit_api import router as outfit_router
app.include_router(outfit_router)
```

### Frontend: `useOutfitGeneration.ts`

```ts
export function useOutfitGeneration(backendUrl: string, apiKey?: string) {
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<AvatarResult[]>([])
  const [error, setError] = useState<string | null>(null)

  const generate = async (params: {
    referenceImageUrl: string
    outfitPrompt: string
    characterPrompt?: string
    count?: number
  }) => { ... }

  return { loading, results, error, generate }
}
```

### Frontend: `OutfitPanel.tsx`

- Appears as a collapsible section inside AvatarStudio (below results, above gallery)
- Activated when user clicks "Outfit Variations" on any gallery item or result
- Shows:
  - Reference avatar thumbnail (locked — the face anchor)
  - Outfit preset pills (from `OUTFIT_PRESETS` in `personaTypes.ts`)
  - Custom outfit prompt input
  - Generate button + count selector
  - Results grid (same `AvatarCard` component, reused)
- Each outfit result can be: saved to gallery, sent to edit, saved as persona avatar

### AvatarStudio integration (additive)

```tsx
// New state:
const [outfitAnchor, setOutfitAnchor] = useState<GalleryItem | null>(null)

// New hover action on AvatarCard + Gallery items:
onGenerateOutfits={(item) => setOutfitAnchor(item)}

// Render OutfitPanel when anchor is set:
{outfitAnchor && (
  <OutfitPanel
    anchor={outfitAnchor}
    backendUrl={backendUrl}
    apiKey={apiKey}
    nsfwMode={readNsfwMode()}
    onResult={(results) => gallery.addBatch(results, ...)}
    onSendToEdit={onSendToEdit}
    onClose={() => setOutfitAnchor(null)}
  />
)}
```

---

## Feature 4: Face Swap in Edit — Make the Button Functional

### Current state
- Frontend: `IdentityTools.tsx` renders the Face Swap button when `hasFaceSwap=true`
- Frontend: `identityApi.ts` calls `POST /v1/edit/identity` with `tool_type: 'face_swap'`
- Backend: `enhance.py` returns `501 Not Implemented`

### What we add

#### Backend: New file `backend/app/face_swap.py`

```python
"""
Face Swap implementation using InsightFace InSwapper.

Additive — does NOT modify enhance.py. Instead, enhance.py will
call into this module when the face_swap tool is requested.
"""

import os
import uuid
from pathlib import Path
from typing import Optional

async def execute_face_swap(
    source_image_path: str,
    reference_image_path: str,
    output_dir: str,
    comfy_url: str = "http://127.0.0.1:8188",
) -> dict:
    """
    Perform face swap using ComfyUI InSwapper workflow.

    Args:
        source_image_path: Path to the target image (body to keep)
        reference_image_path: Path to the face donor image
        output_dir: Directory to write result
        comfy_url: ComfyUI server URL

    Returns:
        {"images": ["/outputs/face_swap_<uuid>.png"], "seed": int}
    """
    # Build ComfyUI workflow JSON for InSwapper pipeline:
    #   1. Load source image
    #   2. Load reference image
    #   3. InsightFace face detection (AntelopeV2)
    #   4. InSwapper face swap
    #   5. GFPGAN face enhancement (post-swap cleanup)
    #   6. Save output

    workflow = build_face_swap_workflow(
        source_image_path,
        reference_image_path,
    )

    # Queue workflow on ComfyUI and wait for result
    # (reuses existing ComfyUI client pattern from the codebase)
    ...
```

#### Backend: New file `backend/app/workflows/face_swap_workflow.json`

```json
{
  "_comment": "ComfyUI workflow: InsightFace InSwapper face swap",
  "nodes": {
    "load_source": { "class_type": "LoadImage" },
    "load_reference": { "class_type": "LoadImage" },
    "face_analysis": { "class_type": "InsightFaceLoader", "model": "antelopev2" },
    "face_swap": { "class_type": "ReActorFaceSwap" },
    "face_enhance": { "class_type": "GFPGANLoader" },
    "save": { "class_type": "SaveImage" }
  }
}
```

#### Backend: Modify `enhance.py` — Replace 501 with delegation (minimal, surgical)

```python
# In the face_swap branch (line 419-427), replace the HTTPException with:
elif tool == "face_swap":
    if not req.reference_image_url:
        raise HTTPException(400, "Face swap requires a reference_image_url")

    from app.face_swap import execute_face_swap

    source_path = await resolve_image_path(req.image_url, upload_root)
    ref_path = await resolve_image_path(req.reference_image_url, upload_root)

    result = await execute_face_swap(
        source_image_path=str(source_path),
        reference_image_path=str(ref_path),
        output_dir=str(output_root),
        comfy_url=comfy_url,
    )
    images = result.get("images", [])
    return IdentityEditResponse(media={"images": images}, tool_used=tool)
```

#### Frontend: `IdentityTools.tsx` — Add reference image input (additive)

Currently, `IdentityTools` calls `applyIdentityTool()` without a reference image for face swap. We need to add a reference upload UI specifically for face swap:

**New file: `frontend/src/ui/edit/FaceSwapRefInput.tsx`**

```tsx
/**
 * Inline reference image picker that appears when Face Swap is selected.
 * User uploads or pastes URL of the face donor image.
 */
export function FaceSwapRefInput({
  backendUrl,
  apiKey,
  onReferenceReady,
}: {
  backendUrl: string
  apiKey?: string
  onReferenceReady: (url: string) => void
}) {
  // Upload zone + URL input (reuses same pattern as AvatarStudio reference upload)
  // Compact inline variant — sits below the Face Swap button
  ...
}
```

**Modification to `IdentityTools.tsx`** (additive — new state + conditional render):

```tsx
// New state:
const [faceSwapRefUrl, setFaceSwapRefUrl] = useState<string | null>(null)
const [showFaceSwapRef, setShowFaceSwapRef] = useState(false)

// When Face Swap button is clicked:
if (toolType === 'face_swap') {
  if (!faceSwapRefUrl) {
    setShowFaceSwapRef(true)  // Show reference input instead of calling API
    return
  }
}

// Pass referenceImageUrl to applyIdentityTool when calling face_swap

// Render FaceSwapRefInput inline below Face Swap button:
{showFaceSwapRef && (
  <FaceSwapRefInput
    backendUrl={backendUrl}
    apiKey={apiKey}
    onReferenceReady={(url) => {
      setFaceSwapRefUrl(url)
      setShowFaceSwapRef(false)
      // Auto-trigger the swap
      handleTool('face_swap')
    }}
  />
)}
```

---

## Implementation Order

```
Phase 1: Avatar Gallery (foundation)
  ├── galleryTypes.ts
  ├── useAvatarGallery.ts
  ├── AvatarGallery.tsx
  └── Wire into AvatarStudio.tsx

Phase 2: Persona Integration
  ├── personaBridge.ts
  ├── SaveAsPersonaModal.tsx
  ├── Add initialDraft prop to PersonaWizard
  └── Wire into App.tsx

Phase 3: Outfit Variations
  ├── outfit_api.py (backend)
  ├── Register router in main.py
  ├── useOutfitGeneration.ts
  ├── OutfitPanel.tsx
  └── Wire into AvatarStudio.tsx

Phase 4: Face Swap
  ├── face_swap.py (backend)
  ├── face_swap_workflow.json
  ├── Update enhance.py face_swap branch
  ├── FaceSwapRefInput.tsx
  └── Update IdentityTools.tsx
```

## Files Created (all new)

| # | File | Type |
|---|------|------|
| 1 | `frontend/src/ui/avatar/galleryTypes.ts` | Types |
| 2 | `frontend/src/ui/avatar/useAvatarGallery.ts` | Hook |
| 3 | `frontend/src/ui/avatar/AvatarGallery.tsx` | Component |
| 4 | `frontend/src/ui/avatar/personaBridge.ts` | Helper |
| 5 | `frontend/src/ui/avatar/SaveAsPersonaModal.tsx` | Component |
| 6 | `frontend/src/ui/avatar/useOutfitGeneration.ts` | Hook |
| 7 | `frontend/src/ui/avatar/OutfitPanel.tsx` | Component |
| 8 | `backend/app/outfit_api.py` | FastAPI router |
| 9 | `backend/app/face_swap.py` | Backend logic |
| 10 | `backend/app/workflows/face_swap_workflow.json` | ComfyUI workflow |
| 11 | `frontend/src/ui/edit/FaceSwapRefInput.tsx` | Component |

## Files Modified (additive changes only)

| # | File | Change |
|---|------|--------|
| 1 | `frontend/src/ui/avatar/AvatarStudio.tsx` | Add `onSaveAsPersonaAvatar` prop, render Gallery + OutfitPanel |
| 2 | `frontend/src/ui/PersonaWizard.tsx` | Add optional `initialDraft` prop |
| 3 | `frontend/src/ui/App.tsx` | Add `saveAsPersonaItem` state, render `SaveAsPersonaModal` |
| 4 | `frontend/src/ui/edit/IdentityTools.tsx` | Add face swap reference input state + `FaceSwapRefInput` render |
| 5 | `backend/app/main.py` | `app.include_router(outfit_router)` |
| 6 | `backend/app/enhance.py` | Replace 501 block with `face_swap.execute_face_swap()` call |

## Zero breaking changes

- All new props are optional
- All new components are conditionally rendered
- All new backend endpoints are new routes (no existing routes changed)
- The only existing code edit is `enhance.py` line 419-427: replacing a 501 error with actual implementation (strictly an improvement, not a behavior change for working code)
- Gallery uses its own localStorage key (`homepilot_avatar_gallery`), separate from edit items
- PersonaWizard with no `initialDraft` behaves exactly as before

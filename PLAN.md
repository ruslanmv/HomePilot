# Multi-View Pack Feature — Implementation Plan

## Overview
Add a non-destructive, additive "View Pack" feature to the Character Sheet that generates 6 angle views (front, left_45, left, right_45, right, back) of any avatar, preserving identity and outfit. This enables future 3D rotating character previews (MMORPG-style).

## Approach
- **Zero** existing files deleted or renamed
- **Zero** existing UI elements moved or removed
- **4 new files** created
- **1 existing file** edited (AvatarViewer.tsx — additive imports, state, handlers, JSX inserts)
- Old users see their exact same workflow; new features are tucked into small, optional UI sections
- **No backend changes** — reuses existing `POST /v1/avatars/outfits` endpoint

---

## New Files

### 1. `frontend/src/ui/avatar/viewPack.ts` — Types & Constants
- `ViewAngle` type: `'front' | 'left_45' | 'left' | 'right_45' | 'right' | 'back'`
- `ViewSource` type: `'anchor' | 'latest' | 'equipped'`
- `ViewAngleOption` interface with `id`, `label`, `shortLabel`, `prompt`, `icon`
- `VIEW_ANGLE_OPTIONS` array — 6 entries with SD-compatible angle prompts that include identity/outfit preservation phrases
- `ViewResultMap` = `Partial<Record<ViewAngle, AvatarResult>>`
- `ViewPreviewMap` = `Partial<Record<ViewAngle, string>>`
- Helper: `getViewAngleOption(angle)` — lookup by id
- Helper: `extractViewAngle(metadata)` — extract angle tag from result metadata

### 2. `frontend/src/ui/avatar/useViewPackGeneration.ts` — Generation Hook
- Reuses the existing `POST /v1/avatars/outfits` endpoint (no backend changes)
- Builds angle-specific prompts: base prompt + angle descriptor + turntable/identity-lock phrases
- Tracks per-angle loading state (`loadingAngles`), results (`resultsByAngle`), errors
- Exposes: `generateAngle(params)`, `missingAngles()`, `reset()`, `resultsByAngle`, `loadingAngles`, `anyLoading`, `error`
- Sequential generation for "Generate Missing" (one at a time to avoid backend overload)

### 3. `frontend/src/ui/avatar/AvatarStageQuickTools.tsx` — Quick Views Row
- Compact row under the stage (after action buttons, before right panel)
- 6 angle buttons in `grid-cols-3 sm:grid-cols-6`
- Each shows: icon, short label (F/L45/L/R45/R/B), status (Ready/Missing)
- Green when generated, neutral when missing
- Click Ready → open lightbox; Click Missing → generate that angle
- "Generate Missing" button in header
- Uses lucide `Camera`, `Loader2`, `PackagePlus` icons

### 4. `frontend/src/ui/avatar/AvatarViewPackPanel.tsx` — Collapsible Right Panel Section
- Collapsed by default: `View Pack ▸` (Orbit icon)
- Expanded shows:
  - **Source selector**: Anchor / Latest Outfit / Equipped (3 pill buttons)
  - **Angle grid**: 6 cards in `grid-cols-2 sm:grid-cols-3`
  - **Generate Missing Views** gradient CTA button
- Source determines reference image for generation
- Disabled states: "Latest Outfit" disabled when no outfit results; "Equipped" disabled when nothing equipped

---

## Edits to `AvatarViewer.tsx` (6 precise insertions)

### A. Imports — After line 67 (`AvatarGeneratingLoader` import)
```typescript
import { AvatarStageQuickTools } from './AvatarStageQuickTools'
import { AvatarViewPackPanel } from './AvatarViewPackPanel'
import { extractViewAngle, type ViewAngle, type ViewPreviewMap, type ViewSource } from './viewPack'
import { useViewPackGeneration } from './useViewPackGeneration'
```

### B. State — After line 184 (`equippedItem` state)
```typescript
const viewPack = useViewPackGeneration(backendUrl, apiKey)
const [viewSource, setViewSource] = useState<ViewSource>('anchor')
const [showViewPack, setShowViewPack] = useState(false)
```
Note: `selectedPreset` already exists at line 147 — NOT duplicated.

### C. Derived State — After line 295 (`availableTags` memo)
Three `useMemo` blocks:
- `persistedViewPreviews` — scans `outfits` for items with `view_angle` metadata + front=heroUrl
- `generatedViewPreviews` — maps `viewPack.resultsByAngle` to resolved URLs
- `combinedViewPreviews` — merges both (generated overrides persisted)

### D. Handlers — After line 472 (`getTagMeta` function)
Five new declarations:
- `currentViewReferenceUrl` (useMemo) — selects reference URL based on `viewSource`
- `currentViewBasePrompt` (useMemo) — selects base prompt based on `viewSource`
- `handleGenerateViewAngle` (useCallback) — calls `viewPack.generateAngle()`, forwards result to `onOutfitResults`
- `handleGenerateMissingViews` (useCallback) — iterates missing angles sequentially
- `handleOpenGeneratedView` (useCallback) — opens lightbox for generated view

### E. JSX Insert 1 — After line 829 (end of left stage metadata/actions `</div>`)
```tsx
<AvatarStageQuickTools
  previews={combinedViewPreviews}
  loadingAngles={viewPack.loadingAngles}
  busy={viewPack.anyLoading}
  onGenerateAngle={handleGenerateViewAngle}
  onOpenAngle={handleOpenGeneratedView}
  onGenerateMissing={handleGenerateMissingViews}
/>
```

### F. JSX Insert 2 — After line 859 (Identity Anchor mini-preview `</div>`)
```tsx
<AvatarViewPackPanel
  open={showViewPack}
  source={viewSource}
  disableLatest={outfit.results.length === 0}
  disableEquipped={!equippedItem}
  previews={combinedViewPreviews}
  loadingAngles={viewPack.loadingAngles}
  busy={viewPack.anyLoading}
  onToggle={() => setShowViewPack((v) => !v)}
  onSourceChange={setViewSource}
  onGenerateAngle={handleGenerateViewAngle}
  onGenerateMissing={handleGenerateMissingViews}
/>

{viewPack.error && (
  <div className="flex items-center gap-2 rounded-xl border border-red-500/15 bg-red-500/[0.08] px-3 py-2.5 text-xs text-red-300">
    <AlertTriangle size={14} />
    <span>{viewPack.error}</span>
  </div>
)}
```

---

## Data Flow

```
User clicks angle button (Quick Tools or View Pack)
    ↓
handleGenerateViewAngle('left_45')
    ↓
useViewPackGeneration.generateAngle({
  referenceImageUrl: currentViewReferenceUrl,   // from Source selector
  angle: 'left_45',
  characterPrompt: item.prompt,
  basePrompt: currentViewBasePrompt,
  checkpointOverride: checkpoint
})
    ↓
POST /v1/avatars/outfits   (EXISTING endpoint — no backend changes)
{
  reference_image_url: "...",
  outfit_prompt: "portrait photograph, left three-quarter view, rotated 45 degrees..., turntable style pose, consistent studio framing, preserve identity...",
  character_prompt: "...",
  count: 1,
  generation_mode: "identity",
  checkpoint_override: "..."
}
    ↓
Result tagged with metadata: { view_angle: 'left_45', view_source: 'anchor' }
    ↓
Saved to gallery via onOutfitResults → appears in wardrobe
Quick Tools + View Pack UI update to show "Ready" status
```

---

## What Does NOT Change
- Header, left stage, right panel layout
- Anchor Face / Latest Outfit tabs
- Outfit Studio (presets, lingerie builder, colors, accessories, poses)
- Advanced Options, Adult Controls
- Wardrobe Inventory
- All existing props interfaces (AvatarViewerProps unchanged)
- All backend endpoints (no new endpoints, no backend file changes)
- Gallery storage format (GalleryItem.metadata is already `Record<string, unknown>`)

---

## File Summary

| # | File | Action |
|---|------|--------|
| 1 | `frontend/src/ui/avatar/viewPack.ts` | **CREATE** — types, constants, helpers |
| 2 | `frontend/src/ui/avatar/useViewPackGeneration.ts` | **CREATE** — generation hook |
| 3 | `frontend/src/ui/avatar/AvatarStageQuickTools.tsx` | **CREATE** — Quick Views row component |
| 4 | `frontend/src/ui/avatar/AvatarViewPackPanel.tsx` | **CREATE** — collapsible View Pack panel |
| 5 | `frontend/src/ui/avatar/AvatarViewer.tsx` | **EDIT** — 6 additive insertions (imports, state, memos, handlers, 2 JSX) |

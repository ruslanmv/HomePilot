# Implementation Plan: 360° Outfit Views in Chat & Persona System

## Goal
Enable personas to show their outfit from any angle in chat conversations
("show me your back", "turn around") by connecting the existing View Pack
system to the persona inventory, chat pipeline, and .hpersona export.

**Guiding rule**: One outfit owns one optional `view_pack` — not 4 separate photos.

---

## Phase 1 — Data Model (additive optional fields)

### 1a. Frontend: `frontend/src/ui/avatar/viewPack.ts`
Add shared reusable types (ViewAngle already exists):
```ts
export type PersistedViewPack = Partial<Record<ViewAngle, string>>
export function getAvailableViewAngles(vp?: PersistedViewPack): ViewAngle[] {
  if (!vp) return []
  return (['front','left','right','back'] as ViewAngle[]).filter(a => !!vp[a])
}
```

### 1b. Frontend: `frontend/src/ui/personaTypes.ts`
Extend `PersonaOutfit` with optional view_pack fields:
```ts
export type PersonaOutfit = {
  // ... existing fields unchanged ...
  // NEW — additive only
  equipped?: boolean
  interactive_preview?: boolean
  preview_mode?: 'static' | 'view_pack'
  hero_view?: 'front' | 'left' | 'right' | 'back'
  view_pack?: Partial<Record<'front'|'left'|'right'|'back', string>>
}
```

### 1c. Frontend: `frontend/src/ui/inventoryApi.ts`
Extend `InventoryItem` with optional fields:
```ts
  // NEW — additive only
  equipped?: boolean
  interactive_preview?: boolean
  preview_mode?: 'static' | 'view_pack'
  hero_view?: 'front' | 'left' | 'right' | 'back'
  available_views?: Array<'front'|'left'|'right'|'back'>
  view_pack?: Partial<Record<'front'|'left'|'right'|'back', string>>
```
Add `ResolvedPersonaOutfitView` response type.
Add `resolvePersonaOutfitView()` API function.

---

## Phase 2 — Backend Inventory & Resolver

### 2a. `backend/app/inventory.py` — extend `_collect_outfit_items`
After current image extraction (line 219), add view_pack parsing:
```python
VIEW_ANGLES = ("front", "left", "right", "back")

def _normalize_view_pack(raw):
    # extract valid angle→URL mappings from raw dict
    ...

# In _collect_outfit_items, extend each item dict:
view_pack = _normalize_view_pack(o.get("view_pack"))
available_views = [a for a in VIEW_ANGLES if view_pack.get(a)]
items.append({
    ...existing fields...,
    "equipped": bool(o.get("equipped")),
    "interactive_preview": bool(available_views),
    "preview_mode": "view_pack" if available_views else "static",
    "hero_view": "front" if view_pack.get("front") else None,
    "view_pack": view_pack or None,
    "available_views": available_views,
})
```

### 2b. `backend/app/inventory.py` — new resolver endpoint
```python
@router.post("/{project_id}/persona/outfit-view")
async def resolve_persona_outfit_view(project_id, body):
    # 1. Load persona_appearance from project metadata
    # 2. Find equipped outfit (outfit.equipped==True, or first)
    # 3. Normalize its view_pack
    # 4. Return requested angle URL + available_views + metadata
    # 5. If angle missing → 404 with "VIEW_NOT_AVAILABLE"
```

### 2c. `backend/app/inventory.py` — equipped outfit helper
```python
def _get_equipped_outfit(appearance):
    for o in (appearance.get("outfits") or []):
        if o.get("equipped"):
            return o
    outfits = appearance.get("outfits") or []
    return outfits[0] if outfits else None
```

---

## Phase 3 — Chat Integration (the [show:] tag extension)

### 3a. `backend/app/projects.py` — extend photo catalog (build_persona_context)
In the outfit iteration loop (line 534), when an outfit has a `view_pack`,
inject angle-aware labels into the catalog:
```
  Lingerie (4 views + 1 hero):
    #1 Lingerie: delicate lace set ← currently wearing → [show:Lingerie]
    Views: [show:Lingerie Front] [show:Lingerie Left] [show:Lingerie Right] [show:Lingerie Back]
```
The AI now knows it can write `[show:Lingerie Back]` to show the back angle.

### 3b. `backend/app/projects.py` — extend system prompt rules
Add to the RULES section (~line 639):
```
HOW TO SHOW OUTFIT ANGLES:
- If an outfit has Views listed, you can show a specific angle.
- "show me your outfit from the back" → [show:Lingerie Back]
- "turn around" → show the back view of your current outfit
- "show me your side" → show left or right view
- If the requested angle doesn't exist, say so and offer to generate it.
- "turn slowly" → show all available angle views in sequence
```

### 3c. `backend/app/media_resolver.py` — extend `_build_label_index`
Add view_pack angle labels to the label index:
```python
# For each outfit with view_pack:
for angle, url in (outfit.get("view_pack") or {}).items():
    angle_label = f"{outfit_label} {angle.title()}"  # "Lingerie Back"
    index[f"label:{angle_label}"] = abs_url(url)
```
This makes `[show:Lingerie Back]` resolvable through the existing pipeline.

### 3d. `backend/app/projects.py` — extend photo intent detector
In the intent detection (~line 998), add angle keyword detection:
```python
ANGLE_KEYWORDS = {
    "back": "back", "behind": "back", "turn around": "back",
    "side": "left", "profile": "left",
    "front": "front", "facing": "front",
}
# If user requests an angle + the equipped outfit has that view → inject directly
```

---

## Phase 4 — Chat UI: Angle Chips

### 4a. Frontend chat message renderer
When a chat message contains images AND the source outfit has `view_pack`,
render angle chips below the image:
```
[Image]
[Front] [Left] [Back] [Right]  ← clickable chips
```
Clicking a chip fetches that angle via `resolvePersonaOutfitView()` and
swaps the displayed image (no new LLM call needed).

This requires extending the chat media payload:
```ts
type ChatMedia = {
  images: string[]
  // NEW — additive
  view_pack?: Partial<Record<'front'|'left'|'right'|'back', string>>
  active_angle?: 'front' | 'left' | 'right' | 'back'
  available_views?: Array<'front'|'left'|'right'|'back'>
  interactive_preview?: boolean
}
```

### 4b. Backend: attach view_pack to resolved [show:] responses
In `projects.py` line 1060-1086, when resolving `[show:Label]` tags,
if the resolved label belongs to an outfit with a view_pack, include
the view_pack URLs in the response `text_media`:
```python
text_media = {
    "images": resolved,
    "view_pack": outfit_view_pack,  # NEW
    "available_views": ["front","left","right","back"],  # NEW
    "interactive_preview": True,  # NEW
}
```

---

## Phase 5 — .hpersona Export/Import

### 5a. `backend/app/personas/export_import.py` — export view_pack assets
In Strategy 3 (outfit images, line 693), also export view_pack files:
```python
for angle, path_or_url in (outfit.get("view_pack") or {}).items():
    add_asset_by_url(path_or_url)
    add_asset_by_relpath(path_or_url)
```

### 5b. `backend/app/personas/export_import.py` — import view_pack remap
After existing path remapping (line 888), remap outfit view_pack paths:
```python
for outfit in (persona_appearance.get("outfits") or []):
    vp = outfit.get("view_pack") or {}
    for angle, val in vp.items():
        vp[angle] = _remap_rel_asset(val)
```

### 5c. Package structure
```
assets/
  avatar_main.png
  thumb_avatar_main.webp
  outfits/
    outfit_lingerie_01/
      front.png
      left.png
      right.png
      back.png
```
Old importers ignore unknown fields — fully backward-compatible.

---

## Phase 6 — Save View Pack to Outfit

### 6a. Frontend: "Save View Pack to Outfit" action
In the View Pack panel (`AvatarViewPackPanel.tsx`), add an explicit
"Save to Current Outfit" button that:
1. Commits all angle images via `/v1/viewpack/commit`
2. Writes the durable URLs into the outfit's `view_pack` field
3. Persists to `persona_appearance.outfits[].view_pack`

### 6b. Backend: persist equipped flag
When an outfit is equipped/selected, set `equipped: true` on it
and `equipped: false` on all others. Add helper:
```python
def _mark_equipped_outfit(outfits, outfit_id):
    for o in outfits:
        o["equipped"] = (o.get("id") == outfit_id)
    return outfits
```

---

## Phase 7 — Persona Profile Panel

### 7a. `frontend/src/ui/teams/PersonaProfilePanel.tsx`
Add a "Current Look" section below hero/stats:
```
Current Look
  Portrait: Default Portrait
  Outfit: Lingerie [Inspect Outfit]
  Views: [Front] [Left] [Back] [Right]
```
Clicking "Inspect Outfit" opens the existing `AvatarOrbitViewer` with
the outfit's `view_pack` URLs fed as previews.

---

## Non-Goals (explicitly excluded)
- No new top-level inventory type "3D" — view_pack is an outfit capability
- No GIF/animation generation (future enhancement)
- No mesh/3D model rendering — these are 2D angle images
- No changes to AvatarOrbitViewer itself — reuse as-is

## File Change Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `frontend/src/ui/avatar/viewPack.ts` | Add types | `PersistedViewPack`, `getAvailableViewAngles()` |
| `frontend/src/ui/personaTypes.ts` | Extend type | Optional view_pack fields on `PersonaOutfit` |
| `frontend/src/ui/inventoryApi.ts` | Extend type + API | Optional fields on `InventoryItem`, resolver API |
| `backend/app/inventory.py` | Extend + new route | view_pack in `_collect_outfit_items`, resolver endpoint |
| `backend/app/projects.py` | Extend catalog + rules | Angle labels in catalog, angle rules in prompt, angle intent |
| `backend/app/media_resolver.py` | Extend index | Angle labels in `_build_label_index` |
| `backend/app/personas/export_import.py` | Extend export/import | view_pack asset handling |
| `frontend/src/ui/teams/PersonaProfilePanel.tsx` | Add section | "Current Look" with angle chips |
| Chat message renderer | Extend media | Angle chip UI under images |

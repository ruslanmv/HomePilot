# Avatar Studio MMORPG Layout — Design Analysis

## 1. Current Architecture (What We Have)

### View State Machine

```
AvatarStudio (viewMode state)
├── 'gallery'  → AvatarLandingPage  (card grid)
├── 'wizard'   → CharacterWizard    (7-step creator)
├── 'viewer'   → AvatarViewer       (character sheet)
└── 'designer' → inline JSX         (zero-prompt wizard)
```

### Current Layouts — Actual DOM Structure

**CharacterWizard (Studio Mode)** — sidebar + content, NO preview:
```
┌──────────────────────────────────────────────┐
│ HEADER: Avatar Studio  [Quick | Studio]       │
├────────────┬─────────────────────────────────┤
│ Sidebar    │ Step Content                     │
│ w-48       │ flex-1, max-w-2xl               │
│            │                                  │
│ Identity   │  Step 3 of 7: Face              │
│ Body       │                                  │
│ Face  ●    │  [Face presets grid 4-col]       │
│ Hair       │  [Eye color swatches]            │
│ Profession │  [Eye shape pills]              │
│ Outfit     │  [Expression pills]             │
│ Generate   │                                  │
│            │  Back              Next           │
│ Randomize  │                                  │
│ Reset      │                                  │
├────────────┴─────────────────────────────────┤
│                (no preview panel)             │
└──────────────────────────────────────────────┘
```

**Problem**: Line 1602 says `{/* Preview sidebar removed — avatar-only flow */}`.
The right 40% of the screen is wasted. No visual feedback until step 7 (Generate).

**AvatarStudio Designer Mode** — single column, centered:
```
┌──────────────────────────────────────────────┐
│ HEADER: Avatar Studio              [Settings] │
├──────────────────────────────────────────────┤
│              max-w-3xl centered               │
│                                               │
│         "Create Your Avatar"                  │
│  [Design Character] [From Ref] [Face+Style]   │
│                                               │
│  1. Core Identity: [♀ Female] [♂ Male] [⚧]   │
│  2. Genetics & Features (collapsed)           │
│  3. Style & Role: [Standard | Spicy 18+]      │
│     [Executive] [Elegant] [Romantic] [Casual]  │
│  4. Character Description (if enabled)        │
│                                               │
│  ★ Generate (4) ▾         Cancel              │
│                                               │
│  [img1] [img2] [img3] [img4]                 │
│                                               │
│  "Your avatars will appear here"              │
│                                               │
└──────────────────────────────────────────────┘
```

**Problems**:
- Avatar images appear at the bottom after scrolling
- Form dominates; images feel like output, not the hero
- Large empty space around `max-w-3xl` on wide screens
- No continuous visual feedback

**AvatarViewer (Character Sheet)** — closest to MMORPG feel:
```
┌──────────────────────────────────────────────┐
│ HEADER: Character Sheet   [Mode] [Settings]   │
├─────────────────────┬────────────────────────┤
│ LEFT (md:w-[48%])   │ RIGHT (md:flex-1)      │
│                     │                         │
│ [Anchor|Outfit] tab │ Outfit Studio           │
│                     │ [Face locked 🔒]        │
│ ┌─────────────────┐ │                         │
│ │                 │ │ [Anchor mini preview]   │
│ │  HERO IMAGE     │ │                         │
│ │  (stage)        │ │ 1. Choose Scenario      │
│ │                 │ │ [Business] [Casual]     │
│ └─────────────────┘ │ [Evening] [Sporty]      │
│                     │                         │
│ [alt1] [alt2] [alt3]│ 2. Custom Outfit Prompt │
│                     │ [input field]           │
│ metadata + actions  │                         │
│                     │ Qty: [1] [4] [8]        │
│                     │ ★ Generate Outfit (1)   │
├─────────────────────┴────────────────────────┤
│ WARDROBE (190px, horizontal scroll)           │
│ [outfit1] [outfit2] [---] [---] [---]         │
└──────────────────────────────────────────────┘
```

**This is already 70% of the MMORPG pattern!** The AvatarViewer has:
- Stage (hero image) as visual center
- Controls beside it (outfit studio panel)
- Inventory bar at bottom (wardrobe)
- Equip/unequip mechanics
- RPG scenario tags (business, casual, evening)

---

## 2. Gap Analysis — What's Missing

### 2.1 CharacterWizard has NO preview

The 7-step wizard (Identity → Body → Face → Hair → Profession → Outfit → Generate)
occupies the full viewport with a sidebar + content layout.

**Line 1602**: `{/* Preview sidebar removed — avatar-only flow */}`

This means users configure 6 steps of character customization completely blind, then
finally see results at step 7. This is the opposite of every MMORPG character creator.

### 2.2 Designer Mode is single-column with image at bottom

The "zero-prompt wizard" (Design Character mode) stacks everything vertically in
`max-w-3xl`. Results appear below the controls after generation, requiring scroll.

### 2.3 No "Character Stage" during creation

Both creation flows (Wizard + Designer) lack a persistent, prominent preview area.
The avatar only appears as a result — never as a live character on a stage.

### 2.4 Hybrid pipeline not wired to UI

The backend supports `POST /v1/avatars/hybrid/face` and `/fullbody` but there's no
frontend component that calls these endpoints. The `fetchAvatarCapabilities()` API
and `useAvatarCapabilities` hook exist but aren't used in any creation flow.

### 2.5 No Identity Library

There's no concept of "saved identities" that persist across sessions. The gallery
stores results, and `parentId` links outfits to characters, but there's no dedicated
identity browsing/selection UI.

---

## 3. Target Layout — MMORPG Character Creator

### 3.1 The Three-Panel Pattern

Every AAA character creator (WoW, BDO, Cyberpunk, MetaHuman) follows this:

```
┌───────────┬──────────────────────┬───────────┐
│ Category  │   CHARACTER STAGE    │ Controls  │
│ Navigation│   (BIG PREVIEW)      │ (Options) │
│           │                      │           │
│           │                      │           │
├───────────┴──────────────────────┴───────────┤
│ Action Bar / Navigation                       │
└───────────────────────────────────────────────┘
```

### 3.2 Proposed Layout for CharacterWizard (Studio Mode)

```
┌──────────────────────────────────────────────────────────────┐
│ Avatar Studio                    [Quick | Studio] [Settings]  │
├──────────┬───────────────────────────────────┬───────────────┤
│ Steps    │                                   │ Step Options  │
│ w-[180px]│                                   │ w-[320px]     │
│          │                                   │               │
│ Identity │       CHARACTER STAGE              │ Gender        │
│ Body     │                                   │ [♀] [♂] [⚧]  │
│ Face ●   │       ┌─────────────────┐         │               │
│ Hair     │       │                 │         │ Age Range     │
│ Profession       │  AVATAR PREVIEW │         │ [YA] [A] [M]  │
│ Outfit   │       │                 │         │               │
│ Generate │       │  (placeholder   │         │ Skin Tone     │
│          │       │   or last gen)  │         │ [swatches...] │
│ ──────── │       │                 │         │               │
│ Randomize│       └─────────────────┘         │ Face Shape    │
│ Reset    │                                   │ [pills...]    │
│          │       seed: 12345  copy            │               │
├──────────┴──────────┬────────────────────────┴───────────────┤
│ ◄ Back              │                              Next ►     │
└─────────────────────┴────────────────────────────────────────┘
```

**CSS**: `grid grid-cols-[180px_1fr_320px]` (collapses on mobile)

**Key UX principles**:
1. Center panel is the hero — `min-h-[60vh]`, fills vertical space
2. Left sidebar = step navigation (same as current, already built)
3. Right panel = dynamic controls for current step (currently in main content area)
4. Preview shows: placeholder silhouette → first generated face → selected outfit
5. Each option change could trigger a lightweight text overlay showing the prompt change

### 3.3 Proposed Layout for Designer Mode

```
┌──────────────────────────────────────────────────────────────┐
│ Avatar Studio                                     [Settings]  │
├──────────┬───────────────────────────────────┬───────────────┤
│ Modes    │                                   │ Options       │
│          │                                   │               │
│ Design   │       CHARACTER STAGE              │ Gender        │
│  Char ●  │                                   │ [♀] [♂] [⚧]  │
│ From     │       ┌─────────────────┐         │               │
│  Ref     │       │                 │         │ Style & Role  │
│ Face +   │       │  PREVIEW IMAGE  │         │ [Standard|18+]│
│  Style   │       │                 │         │ [grid 2-col]  │
│          │       │  or silhouette  │         │               │
│          │       │                 │         │ Genetics ▼    │
│          │       └─────────────────┘         │ (collapsible) │
│          │                                   │               │
│          │  ┌───┐ ┌───┐ ┌───┐ ┌───┐         │ Description   │
│          │  │ 1 │ │ 2 │ │ 3 │ │ 4 │ results │ (if enabled)  │
│          │  └───┘ └───┘ └───┘ └───┘         │               │
├──────────┴───────────────────────────────────┴───────────────┤
│              ★ Generate (4) ▾              Ctrl+Enter         │
└──────────────────────────────────────────────────────────────┘
```

### 3.4 Proposed Layout for Hybrid Pipeline (StyleGAN + ComfyUI)

This is the biggest new feature. Two-phase creation:

**Phase 1: Face Generation**
```
┌──────────────────────────────────────────────────────────────┐
│ Avatar Studio — Create Identity              [Quick | Studio] │
├──────────┬───────────────────────────────────┬───────────────┤
│ Steps    │                                   │ Face Options  │
│          │                                   │               │
│ Identity │       SELECTED FACE               │ Count: [4]    │
│  ●       │                                   │ Truncation    │
│ Outfit   │       ┌─────────────────┐         │ [0.5 ──●── 1] │
│ Scene    │       │                 │         │               │
│          │       │  (BIG FACE      │         │ Seed: [auto]  │
│          │       │   PREVIEW)      │         │               │
│          │       │                 │         │ ★ Regenerate  │
│          │       └─────────────────┘         │               │
│          │                                   │               │
│          │  ┌───┐ ┌───┐ ┌───┐ ┌───┐  faces  │               │
│          │  │ 1 │ │ 2 │ │ 3 │ │ 4 │  strip  │               │
│          │  └───┘ └───┘ └───┘ └───┘         │               │
├──────────┴───────────────────────────────────┴───────────────┤
│ ★ Generate Faces                    Save Identity & Continue ► │
└──────────────────────────────────────────────────────────────┘
```

**Phase 2: Outfit/Full-Body Generation** (face is locked)
```
┌──────────────────────────────────────────────────────────────┐
│ Avatar Studio — Sophia                    [Face locked 🔒]    │
├──────────┬───────────────────────────────────┬───────────────┤
│ Steps    │                                   │ Outfit Options│
│          │                                   │               │
│ Identity │       FULL BODY PREVIEW           │ Outfit Style  │
│  ✓       │                                   │ [Corporate]   │
│ Outfit ● │       ┌─────────────────┐         │ [Casual]      │
│ Scene    │       │                 │         │ [Sporty]      │
│          │       │  (OUTFIT        │         │               │
│          │       │   RESULT)       │         │ Body Type     │
│          │       │                 │         │ [Slim] [Avg]  │
│          │       └─────────────────┘         │               │
│          │                                   │ Pose          │
│          │  ┌──────┐  ┌──────┐   results    │ [Standing]    │
│          │  │ Out1 │  │ Out2 │   strip      │               │
│          │  └──────┘  └──────┘              │ Background    │
│          │                                   │ [Office]      │
├──────────┴───────────────────────────────────┴───────────────┤
│  ◄ Change Face             ★ Generate Outfit (2) ▾           │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Component Mapping — Existing → New Layout

### What already exists and where it goes:

| Current Component/Section | New Location | Changes Needed |
|---|---|---|
| CharacterWizard sidebar (w-48, step nav) | Left panel (w-[180px]) | Minor: same component, slightly wider |
| CharacterWizard step content (max-w-2xl) | Right panel (w-[320px]) | **Major**: Move from center to right, constrain width |
| CharacterWizard "Preview sidebar removed" | Center panel | **New**: Add preview stage component |
| AvatarViewer left panel (hero image) | Center panel pattern | Reuse: same stage display logic |
| AvatarViewer right panel (Outfit Studio) | Right panel pattern | Reuse: same controls layout |
| AvatarViewer wardrobe (bottom 190px) | Bottom bar | Reuse: same component |
| Designer mode controls | Right panel | Move from center column to right |
| Designer mode results grid | Center panel (below preview) | Move from bottom to filmstrip under preview |
| useAvatarCapabilities hook | Left panel / mode switcher | Wire: show StyleGAN status |
| OutfitPanel | Integrated into right panel | Merge: currently standalone |

### What's NEW (doesn't exist yet):

| Component | Purpose |
|---|---|
| `CharacterStage` | Center panel — shows avatar preview (placeholder → generated) |
| `FaceSelectionStrip` | Horizontal strip of generated faces below stage |
| `HybridFacePanel` | Right panel for hybrid Phase 1 (truncation, seed) |
| `HybridOutfitPanel` | Right panel for hybrid Phase 2 (outfit style, body, scene) |
| `IdentityLibrary` | Left panel section showing saved identities |
| `StageOverlay` | Prompt change indicator overlay on stage |

---

## 5. Implementation Strategy — Additive & Non-Destructive

### 5.1 Principle: New component, old component stays

Create `CharacterCreatorStudio.tsx` as the new MMORPG layout.
`CharacterWizard.tsx`, `AvatarStudio.tsx`, `AvatarViewer.tsx` remain untouched.

The `AvatarStudio` viewMode state machine gains one new case:
```typescript
// Existing (untouched):
viewMode: 'gallery' | 'designer' | 'wizard' | 'viewer'

// Add:
viewMode: 'gallery' | 'designer' | 'wizard' | 'viewer' | 'creator'
```

When `viewMode === 'creator'`, render the new `CharacterCreatorStudio`.
The "New Avatar" button on AvatarLandingPage routes to `'creator'` instead of `'wizard'`.

### 5.2 Phase breakdown

**Phase A: Three-Panel Shell** (layout only)
- Create `CharacterCreatorStudio.tsx` with `grid grid-cols-[180px_1fr_320px]`
- Left panel: reuse WIZARD_STEPS navigation
- Center panel: new `CharacterStage` component (placeholder silhouette)
- Right panel: dynamic controls based on active step
- Bottom bar: navigation (Back/Next/Generate)
- Wire into AvatarStudio viewMode

**Phase B: Move Step Controls to Right Panel**
- Extract each wizard step's controls into standalone sub-components
- IdentityControls, BodyControls, FaceControls, HairControls, etc.
- These are pure presentational — they receive `draft` and `onChange`
- Right panel renders the active step's controls

**Phase C: Character Stage with Preview**
- Stage shows: silhouette placeholder → last generated image → selected face
- Results appear as filmstrip thumbnails below the stage
- Clicking a thumbnail sets it as the main stage image
- Generate button triggers generation; stage updates with result

**Phase D: Wire Hybrid Pipeline**
- Add hybrid mode selector (Classic | Hybrid) in the UI
- Classic mode: existing flow (CharacterWizard prompt → ComfyUI)
- Hybrid mode: Phase 1 (face generation via `/hybrid/face`) → Phase 2 (outfit via `/hybrid/fullbody`)
- Face selection strip uses `HybridFaceResult` data
- Outfit generation uses wizard fields → `HybridFullBodyRequest`
- `useAvatarCapabilities` determines if hybrid mode is available

**Phase E: Identity Library**
- Left panel gains "My Identities" section below step navigation
- Shows saved faces (from gallery items with `role: 'anchor'`)
- Clicking an identity loads it as the face for outfit generation
- Links to AvatarViewer for wardrobe management

---

## 6. CSS Grid Specification

### Desktop (>= 1024px)
```css
.creator-layout {
  display: grid;
  grid-template-columns: 180px 1fr 320px;
  grid-template-rows: auto 1fr auto;
  height: 100%;
}
```

Tailwind equivalent:
```
grid grid-cols-[180px_1fr_320px] grid-rows-[auto_1fr_auto] h-full
```

### Tablet (768px — 1023px)
```
grid grid-cols-[1fr_280px] grid-rows-[auto_1fr_auto]
```
Left sidebar collapses into a horizontal pill strip at the top.

### Mobile (< 768px)
```
flex flex-col
```
Full stack: step indicator → stage (50vh) → controls → bottom nav.

### Panel CSS tokens (matching existing design system):
```
Left:   border-r border-white/[0.06] py-6 px-3 overflow-y-auto
Center: flex items-center justify-center bg-black/20 min-h-[60vh]
Right:  border-l border-white/[0.06] px-5 py-4 overflow-y-auto
Bottom: border-t border-white/[0.06] px-5 py-3 flex-shrink-0
```

---

## 7. Character Stage Behavior

### State machine for the center preview:
```
stage_content =
  | 'empty'      → silhouette placeholder (User icon, 48px, text-white/10)
  | 'generating' → skeleton pulse (same as current gen.loading skeleton)
  | 'face'       → face image from hybrid Phase 1 (with seed overlay)
  | 'outfit'     → full-body image from hybrid Phase 2
  | 'result'     → selected generation result (from classic flow)
  | 'equipped'   → wardrobe item (amber glow border, same as AvatarViewer)
```

### Visual treatment:
```
Center panel:
  - outer: relative, gradient border glow (from-purple-500/20 to-cyan-500/20)
  - inner: rounded-2xl overflow-hidden bg-black/40
  - image: max-w-full max-h-full object-contain (not object-cover)
  - hover: overlay with Maximize2 icon (same as AvatarViewer)
  - empty: subtle dashed border, silhouette, "Your character will appear here"
```

### Result filmstrip (below stage):
```
flex gap-2 overflow-x-auto scrollbar-hide
Each thumb: w-16 h-16 rounded-lg border-2, active = border-purple-500/60
```

---

## 8. Right Panel — Dynamic Controls Per Step

### Step 0: Identity
```
Gender:     [♀ Female] [♂ Male] [⚧ Neutral]   (existing GENDER_OPTIONS)
Age Range:  [Young Adult] [Adult] [Mature]
Role:       [Professional] [Creative] [Technical] [Custom]
```

### Step 1: Body
```
Body Type:  [Slim] [Average] [Athletic] [Curvy]
Height:     [slider 150-200cm]
Posture:    [Upright] [Relaxed] [Confident]
Skin Tone:  [10 color swatches]            (existing SKIN_TONES)
Polish:     [Natural] [Light] [Formal]
```

### Step 2: Face
```
Face Shape: [grid 4-col, 8 presets]        (existing FACE_PRESETS)
Eye Color:  [8 color swatches]             (existing EYE_COLORS)
Eye Shape:  [5 pills]                      (existing EYE_SHAPES)
Expression: [5 pills]                      (existing EXPRESSIONS)
▼ Advanced:
  Jawline:  [slider 0-100]
  Lips:     [slider 0-100]
  Brows:    [slider 0-100]
```

### Step 3: Hair
```
Hair Style: [grid 3-col, 12 options]       (existing HAIR_STYLES)
Hair Color: [11 color swatches]            (existing HAIR_COLORS)
Shine:      [slider 0-100]
```

### Step 4: Profession
```
Search:     [input]
Professions: [scrollable list, ~15 items]  (existing PROFESSIONS)
Selected details: tools, tone, autonomy
```

### Step 5: Outfit
```
[Standard | Romance & Roleplay 18+] tabs
Outfit Style: [grid 2-col]                 (existing SFW/NSFW styles)
Primary:    [12 color swatches]
Secondary:  [12 color swatches]
Accessories: [multi-select pills]          (existing ACCESSORIES)
▼ NSFW Advanced (when spicy):
  Exposure, Intensity, Pose, Dominance, Fantasy
```

### Step 6: Generate
```
Portrait Type: [Headshot] [Half] [Full]
Mode:          [Design] [From Ref] [Face+Style]
Pose:          [6 pills]                   (existing POSES/NSFW_POSES)
Background:    [6 pills]                   (existing BACKGROUNDS/NSFW_BACKGROUNDS)
Lighting:      [5 pills]                   (existing LIGHTING_OPTIONS)
Realism:       [slider 0-100]
Detail:        [slider 0-100]
Count:         [1] [4] [8]
★ Generate
```

All preset data already exists in `wizardTypes.ts`. No new data needed.

---

## 9. Hybrid Pipeline UI Flow

### When hybrid mode is available (StyleGAN loaded):

```
Step sequence:
  1. Identity (gender, age) → right panel
  2. ★ Generate Faces → center stage shows 4 faces in filmstrip
  3. Click face to select → stage shows selected face large
  4. Save Identity → face becomes the locked anchor
  5. Outfit/Scene controls → right panel (wizard fields)
  6. ★ Generate Outfit → center stage shows full-body results
  7. Save / Add to Persona
```

### API calls:
```
Phase 1: POST /v1/avatars/hybrid/face
  body: { count: 4, seed: null, truncation: 0.7 }
  response: { results: [{ url, seed, metadata }], warnings }

Phase 2: POST /v1/avatars/hybrid/fullbody
  body: {
    face_image_url: selected_face.url,
    count: 2,
    outfit_style: "Corporate Formal",
    profession: "Executive Secretary",
    body_type: "average",
    gender: "female",
    age_range: "adult",
    background: "office",
    lighting: "soft",
    identity_strength: 0.75
  }
  response: { results: [{ url, seed, metadata }], used_checkpoint }
```

### Fallback when hybrid NOT available:
- Don't show "Generate Faces" button
- Fall through to classic flow (all 7 steps → single generate at end)
- `useAvatarCapabilities` hook provides `styleganAvailable` boolean

---

## 10. Identity Library Design

### Data model (extends existing GalleryItem):
```typescript
// No schema change needed — use existing fields:
interface GalleryItem {
  id: string          // identity ID
  url: string         // face image URL
  seed?: number       // for reproducibility
  role?: 'anchor'     // marks this as an identity anchor
  parentId?: string   // outfits link here
  tags?: string[]     // e.g., ['identity', 'stylegan']
  wizardMeta?: WizardMeta  // profession, tools, etc.
}
```

### UI in left panel:
```
┌──────────────┐
│ My Identities│
│              │
│ ┌────┐ ┌────┐
│ │Soph│ │Marc│
│ │ia  │ │us  │
│ └────┘ └────┘
│ ┌────┐       │
│ │Elen│ [+]   │
│ │a   │       │
│ └────┘       │
│              │
│ ── Steps ──  │
│ Identity     │
│ Body         │
│ ...          │
└──────────────┘
```

Clicking an identity:
1. Loads its face URL as the stage preview
2. Switches to outfit generation mode
3. Right panel shows outfit/scene controls
4. All generations link to this identity via `parentId`

---

## 11. Migration Path — Zero Breaking Changes

### Week 1: Shell + Stage
- New file: `CharacterCreatorStudio.tsx`
- New file: `CharacterStage.tsx`
- Modify: `AvatarStudio.tsx` — add `'creator'` to viewMode, route to new component
- Modify: `AvatarLandingPage.tsx` — "New Avatar" button routes to `'creator'`
- Existing wizard/designer flows remain accessible via direct URL or settings toggle

### Week 2: Step Controls Extraction
- New files: `steps/IdentityStep.tsx`, `steps/BodyStep.tsx`, etc.
- These are pure extractions from `CharacterWizard.tsx` render methods
- CharacterWizard still works independently (no breaking changes)

### Week 3: Hybrid Pipeline Integration
- New file: `useHybridGeneration.ts` (hook calling hybrid API endpoints)
- Wire `useAvatarCapabilities` to show/hide hybrid mode
- Face generation strip in center panel
- Outfit generation from selected face

### Week 4: Identity Library + Polish
- Left panel identity section
- Gallery filtering by identity
- Animations, transitions, loading states
- Mobile responsive layout

---

## 12. Key Decisions & Trade-offs

### Decision 1: New component vs. refactoring CharacterWizard
**Choice**: New `CharacterCreatorStudio.tsx`
**Reason**: CharacterWizard is 1632 lines with deeply coupled state. Refactoring it
risks breaking the existing flow. The new component can import shared presets and
types from `wizardTypes.ts` without modifying them.

### Decision 2: grid-cols-[180px_1fr_320px] vs. flex layout
**Choice**: CSS Grid
**Reason**: Three fixed-width side panels with a fluid center is exactly what CSS Grid
was designed for. Flex would require manual width calculations and doesn't collapse
as cleanly at breakpoints.

### Decision 3: Where to show generated results
**Choice**: Center stage (large) + filmstrip thumbnails below
**Reason**: MMORPG pattern. The selected character is always the hero. Alternatives
are thumbnails you click to swap. This is the opposite of the current 4-column grid
pattern which treats all results equally.

### Decision 4: Hybrid mode toggle vs. automatic detection
**Choice**: Automatic detection via `useAvatarCapabilities`
**Reason**: If StyleGAN is available, the hybrid flow activates automatically.
Users shouldn't need to know about backend engine details. If StyleGAN is
unavailable, the UI gracefully falls back to the classic 7-step flow.

### Decision 5: Keep AvatarViewer separate vs. merge with creator
**Choice**: Keep separate
**Reason**: AvatarViewer is the post-creation "character sheet" (inspect, outfit,
wardrobe). The creator is the pre-creation flow. They serve different phases
of the user journey. However, the center stage component can be shared.

---

## 13. Performance Considerations

### Image loading
- Thumbnail filmstrip: `loading="lazy"` on all except the selected face
- Stage image: immediate load, `object-contain` for aspect ratio preservation
- Placeholder: pure CSS (no image load) — gradient + icon

### State management
- Creator state lives in the new component (useState)
- No global state store needed (same pattern as existing components)
- Gallery items flow via `useAvatarGallery()` hook (already built)

### Bundle size
- New components add ~15-20KB unminified (mostly JSX + Tailwind classes)
- No new dependencies (reuses lucide-react, existing hooks)
- Code-split: `CharacterCreatorStudio` lazy-loaded when viewMode === 'creator'

---

## 14. Summary of Changes

### Files to CREATE (new, additive):
```
frontend/src/ui/avatar/creator/CharacterCreatorStudio.tsx  (main layout)
frontend/src/ui/avatar/creator/CharacterStage.tsx          (center preview)
frontend/src/ui/avatar/creator/FaceFilmstrip.tsx           (result thumbnails)
frontend/src/ui/avatar/creator/StepControls.tsx            (dynamic right panel)
frontend/src/ui/avatar/creator/IdentityLibrary.tsx         (left panel section)
frontend/src/ui/avatar/creator/useHybridGeneration.ts      (hybrid API hook)
frontend/src/ui/avatar/creator/index.ts                    (barrel export)
```

### Files to MODIFY (minimal, additive):
```
frontend/src/ui/avatar/AvatarStudio.tsx     (+10 lines: import + viewMode case)
frontend/src/ui/avatar/AvatarLandingPage.tsx (+2 lines: button route change)
```

### Files UNTOUCHED:
```
frontend/src/ui/avatar/wizard/CharacterWizard.tsx  (1632 lines — stays as-is)
frontend/src/ui/avatar/AvatarViewer.tsx             (stays as-is)
frontend/src/ui/avatar/OutfitPanel.tsx              (stays as-is)
frontend/src/ui/avatar/AvatarSettingsPanel.tsx      (stays as-is)
frontend/src/ui/avatar/wizard/wizardTypes.ts        (shared presets — stays as-is)
frontend/src/ui/avatar/galleryTypes.ts              (shared types — stays as-is)
All backend files                                    (stays as-is)
```

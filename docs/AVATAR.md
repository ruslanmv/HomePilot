<p align="center">
  <img src="../assets/avatar-studio-flow.svg" alt="Avatar Studio Pipeline" width="820" />
</p>

<p align="center">
  <b>AVATAR STUDIO</b><br>
  <em>Create, dress, and export AI characters in zero prompts.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Status-Shipped-brightgreen?style=for-the-badge" alt="Shipped" />
  <img src="https://img.shields.io/badge/Modes-3-blue?style=for-the-badge" alt="3 Modes" />
  <img src="https://img.shields.io/badge/Wardrobe-RPG_Style-purple?style=for-the-badge" alt="RPG Style" />
  <img src="https://img.shields.io/badge/Export-.hpersona-orange?style=for-the-badge" alt=".hpersona Export" />
</p>

---

## Overview

**Avatar Studio** is HomePilot's visual character creation system. It generates AI portrait avatars from reference photos, random faces, or face+style combinations — all without writing a single text prompt. Generated characters can be dressed in different outfits, equipped on a stage like RPG armor, and exported as portable `.hpersona` packages with all images included.

---

## Creation Modes

### 1. From Reference (InstantID)
Upload a photo and generate identity-consistent portraits. The face is preserved across all generations using InstantID technology.

### 2. Design Character
Build a character from scratch using visual presets:
- **Gender** — Female, Male, or Neutral
- **Style** — 16 character style presets (Executive, Elegant, Casual, Gothic, Cyberpunk, etc.)
- **Vibe** — 16 scene/pose presets (Headshot, Studio, Outdoor, Gala, etc.)

No text prompt needed — pick a gender, choose a style, select a vibe, and generate.

### 3. Face + Style
Combine your face (uploaded reference) with a styled body and scene. The system swaps your face onto a generated portrait while preserving your identity.

---

## The Character Sheet

<p align="center">
  <img src="../assets/avatar-character-sheet.svg" alt="RPG Character Sheet" width="820" />
</p>

Every generated avatar opens into a **Character Sheet** — an RPG-inspired split-panel interface:

### The Stage (Left Panel)
A toggle between two views:
- **Anchor Face** — the original portrait (locked identity reference)
- **Latest Outfit** — the most recently generated or equipped outfit

The stage uses **dynamic height with `object-contain`**, so full-body portraits display completely — no cropped heads or cut-off feet.

### Outfit Studio (Right Panel)
Controls for generating new outfit variations:
- **Scenario Badges** — one-click presets (Business, Casual, Evening, Active, and NSFW options when enabled)
- **Custom Prompt** — free-text outfit description for unique looks
- **Generate Button** — creates new outfit images while preserving the character's face

### Wardrobe Inventory (Bottom)
An MMORPG-style inventory grid where all generated outfits are stored:
- **Click to equip** — loads the outfit on the stage instantly (like equipping armor in an MMO)
- **Unequip button** — returns to the base character
- **Amber glow** — highlights the currently equipped item
- **Empty slots** — visual cue to fill the wardrobe with more outfits
- **Scenario tags** — each outfit is tagged (Business, Casual, Evening, etc.) for organization

---

## Vibe Presets (Zero-Prompt Wizard)

The Zero-Prompt Wizard eliminates the need for text prompts entirely. Users simply pick a vibe and generate:

### Standard Vibes
| Vibe | Description |
|------|-------------|
| Headshot | Professional studio headshot with clean background |
| Studio Portrait | Classic photography studio with dramatic lighting |
| Outdoor Natural | Golden-hour natural light in a park setting |
| Urban Street | City sidewalk with modern architecture |
| Cozy Indoor | Warm living room with soft furnishings |
| Corporate | Executive boardroom, power pose |
| Artistic | Creative studio with paint and canvas |
| Fitness | Athletic wear in a gym or outdoor setting |

### Spicy Vibes (18+ — requires Spice Mode)
| Vibe | Description |
|------|-------------|
| Boudoir | Intimate bedroom setting, sensual lighting |
| Poolside | Luxury poolside, swimwear, sun-drenched |
| Date Night | Cocktail bar, elegant evening wear |
| Fantasy | Exotic costume, mystical or sci-fi setting |
| Intimate | Close-up, warm tones, personal atmosphere |
| Spouse | Solo intimate portrait, personal and warm |
| Cosplay | Anime/gaming costume, vibrant setting |
| Glamour | High-fashion editorial, designer outfit |

All vibes are pre-engineered with `single person, front-facing, looking at camera` qualifiers to ensure consistent portrait results.

---

## Saving to Persona

<p align="center">
  <img src="../assets/avatar-export-persona.svg" alt="Avatar to Persona Export" width="820" />
</p>

Any avatar (with all its outfits) can be saved as a Persona — a persistent AI identity with personality, voice, and memory.

### Two Paths

1. **Quick Create** — enter a name, pick a class (Secretary, Assistant, Companion, etc.), and create instantly
2. **Open in Wizard** — full PersonaWizard with identity, skills, appearance, and memory configuration

### What Gets Exported

When saving an avatar to a persona, **all images are transferred**:

| Content | Included |
|---------|----------|
| Main avatar image | Yes — stored in `persona_appearance.sets` |
| Seed data | Yes — for reproducibility |
| All outfit variations | Yes — each outfit becomes a `PersonaOutfit` entry |
| Outfit labels | Yes — resolved from scenario tags (Business, Casual, etc.) |
| Generation settings | Yes — model, preset, aspect ratio, prompts |

### .hpersona Package Structure

When the persona is later exported as a `.hpersona` file, the ZIP contains:

```
manifest.json                    — version, metadata, content summary
blueprint/
  persona_agent.json             — identity, personality, system prompt
  persona_appearance.json        — appearance settings, outfit definitions
  agentic.json                   — goals, capabilities, tools
dependencies/
  tools.json                     — personality tool manifest
  mcp_servers.json               — MCP server requirements
  models.json                    — image model requirements
assets/
  avatar_main.png                — full-resolution main portrait
  thumb_avatar_main.webp         — 256x256 face-anchored thumbnail
  outfit_business.png            — outfit image #1
  outfit_evening.png             — outfit image #2
  outfit_active.png              — outfit image #3
  ...                            — all wardrobe items included
preview/
  card.json                      — gallery preview card data
```

Images are stored as **real binary files** (not base64) — the package is fully portable across HomePilot instances.

---

## Image Resolution Strategies

The backend resolves images from multiple sources to ensure they're always included in exports:

1. **Committed files** — images already saved to `projects/{id}/persona/appearance/`
2. **Appearance directory scan** — all image files in the project's appearance folder
3. **Outfit image URLs** — extracts filenames from ComfyUI URLs in `outfit.images[].url`
4. **Set image URLs** — extracts filenames from `sets[].images[].url` for the main avatar
5. **Upload root fallback** — checks the ComfyUI output directory for uncommitted files

This multi-strategy approach ensures no images are lost during export, even if they haven't been explicitly committed to project storage.

---

## Gallery Landing Page

The main Avatar Studio view is a responsive gallery grid showing all generated characters:

- **Root characters only** — outfits live inside the Character Sheet, not the gallery
- **Outfit count badge** — shows how many wardrobe items each character has
- **Mode badge** — indicates how the character was created (Reference, Random, Face+Style, Creative)
- **NSFW auto-unblur** — when Spice Mode is globally enabled, images are shown unblurred by default
- **Delete confirmation** — proper modal dialog ("Delete this image? This will remove it from your gallery and database.")
- **Hover actions** — full-size view, edit studio, character sheet, save as persona

---

## Technical Architecture

### Frontend Components

| Component | File | Purpose |
|-----------|------|---------|
| `AvatarStudio` | `avatar/AvatarStudio.tsx` | Main wizard and view router |
| `AvatarLandingPage` | `avatar/AvatarLandingPage.tsx` | Gallery grid with delete confirmation |
| `AvatarViewer` | `avatar/AvatarViewer.tsx` | Character Sheet with stage + wardrobe |
| `AvatarGallery` | `avatar/AvatarGallery.tsx` | Filmstrip gallery in designer view |
| `OutfitPanel` | `avatar/OutfitPanel.tsx` | Outfit generation panel |
| `AvatarSettingsPanel` | `avatar/AvatarSettingsPanel.tsx` | Checkpoint and quality settings |
| `SaveAsPersonaModal` | `avatar/SaveAsPersonaModal.tsx` | Save-to-persona modal with outfit count |
| `personaBridge` | `avatar/personaBridge.ts` | GalleryItem → PersonaWizardDraft converter |

### Backend Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/avatars/generate` | POST | Generate avatar images (4 modes) |
| `/v1/avatars/packs` | GET | Check installed model packs |
| `/v1/avatars/packs/{name}/install` | POST | Install avatar model pack |
| `/projects` | POST | Create persona project with avatar data |
| `/projects/{id}/persona/export` | GET | Export persona as .hpersona ZIP |
| `/projects/{id}/persona/avatar/commit` | POST | Commit avatar to durable storage |

### Data Types

| Type | File | Purpose |
|------|------|---------|
| `GalleryItem` | `galleryTypes.ts` | Avatar image with metadata, parentId for outfit grouping |
| `PersonaOutfit` | `personaTypes.ts` | Outfit definition with images and generation settings |
| `PersonaImageRef` | `personaTypes.ts` | Image reference with URL, seed, and timestamps |
| `AvatarGenerationSettings` | `personaTypes.ts` | Reproducible generation parameters |

---

## Requirements

- **ComfyUI** — image generation backend (required for all modes)
- **Avatar Model Pack** — `make download-avatar-models-basic` for InstantID support
- **GPU** — NVIDIA GPU recommended (6GB+ VRAM for basic, 12GB+ for high quality)
- **Spice Mode** — enable in Settings to access NSFW vibes and outfit presets

# Nexus — avatar assets

| File | Status | Purpose |
|------|--------|---------|
| `avatar_nexus.png` | ✅ shipped (512×512) | The realistic headshot — a **synthetic, AI-generated face**. |
| `thumb_avatar_nexus.webp` | ✅ shipped (256×256) | Gallery thumbnail. |
| `avatar_nexus.svg` | ✅ shipped | Vector portrait fallback that always renders with no dependencies. |

## About the photo

`avatar_nexus.png` is a **fake synthetic photo** — a StyleGAN-generated face
from [thispersondoesnotexist.com](https://thispersondoesnotexist.com). The
person **does not exist**; no real individual is depicted, which is the correct
posture for a fictional AI persona. It was resized to the 512×512 / 256×256
convention used by the other community personas (e.g. Scarlett).

## Regenerating or replacing

The appearance blueprint keeps a photoreal prompt so the image can be
re-synthesized locally at any time:

1. **Auto-generate** — HomePilot's avatar service can render a fresh
   `avatar_nexus.png` from `blueprint/persona_appearance.json → avatar_prompt`
   using your local image model.
2. **Bring your own / regenerate synthetic** — replace `avatar_nexus.png`
   (512×512) and `thumb_avatar_nexus.webp` (256×256). `has_avatar` is `true`
   and `selected_filename` already points at these names.

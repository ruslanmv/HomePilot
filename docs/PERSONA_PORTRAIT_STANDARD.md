# Community Persona Portrait Standard

How to generate the **portrait photo** for a HomePilot **Community Edition /
shared** persona, and the house rule for *where those photos come from*.

> **TL;DR** — Every shared persona ships a **512×512 PNG** avatar + a
> **256×256 WebP** thumbnail of a **fully synthetic** (fake, non‑existent)
> person. Generate it with our **custom local StyleGAN2 generator** when you
> can; **fall back to the thispersondoesnotexist.com API** when you can't
> (CI, containers, the Claude Code sandbox). One command does both:
>
> ```bash
> community/shared/scripts/generate-persona-portrait.sh \
>     community/shared/bundles/<bundle> <prefix> --candidates 6 --contact-sheet /tmp/sheet.png
> ```

This document complements — it does not replace — the existing persona docs:

| Doc | Covers |
|-----|--------|
| [`docs/SHARED_PERSONAS.md`](./SHARED_PERSONAS.md) | The additive shared/community pack model and gallery registry merge. |
| [`docs/COMMUNITY_GALLERY.md`](./COMMUNITY_GALLERY.md) | Publishing `.hpersona` packages to the gallery. |
| [`community/shared/_schema/v3/README.md`](../community/shared/_schema/v3/README.md) | The v3 `.hpersona` bundle schema (blueprint/dependencies/preview). |
| [`community/shared/scripts/generate_bundle.py`](../community/shared/scripts/generate_bundle.py) | Scaffolds a new bundle skeleton. |
| **this file** | The **portrait/avatar photo** standard + generator tooling. |

---

## 1. The portrait standard

Every avatar in `community/shared/bundles/<bundle>/persona/assets/` and
`community/sample/<name>/assets/` follows the same shape:

| File | Format | Size | Notes |
|------|--------|------|-------|
| `avatar_<prefix>.png` | PNG (RGB) | **512 × 512** | Square, **center-cropped** from a 1024² source. |
| `thumb_avatar_<prefix>.webp` | WebP | **256 × 256** | Gallery thumbnail, quality ≈ 88. |
| `avatar_<prefix>.svg` | SVG | — | *Optional* vector fallback that renders with no image at all. |

Content rules:

- **Synthetic only.** The face must be AI‑generated and depict **no real
  person**. Never use a photo of an actual human (living or dead), a celebrity,
  or a stock model. StyleGAN‑class faces are ideal — the person literally does
  not exist.
- **SFW & on‑role.** Neutral, professional framing that matches the persona's
  `blueprint/persona_appearance.json` (`avatar_settings`, `avatar_prompt`).
- **Head‑and‑shoulders**, roughly centered, soft/neutral background.

The bundle is wired to the photo through three fields (all set for you by the
generator):

```jsonc
// persona/manifest.json
"contents": { "has_avatar": true }

// persona/blueprint/persona_appearance.json
"selected_filename":       "avatar_<prefix>.png",
"selected_thumb_filename": "thumb_avatar_<prefix>.webp",
"avatar_synthetic":        true,
"avatar_source":           "StyleGAN2 (local) or thispersondoesnotexist.com — depicts no real person"
```

Keep a photoreal `avatar_prompt` (and optional `avatar_negative_prompt`) in
`persona_appearance.json` so the image can always be re‑synthesized locally.

---

## 2. Where the photo comes from — source priority

### PRIMARY — our custom local generator (StyleGAN2‑FFHQ)

Preferred for maintainers: **offline, deterministic (seeded), reproducible**,
and never calls the network.

1. Download the weights once:
   ```bash
   python avatar-service/scripts/download_models.py --model ffhq-1024
   # → models/…/stylegan2-ffhq-1024x1024.pkl   (NVIDIA, non-commercial)
   ```
2. Generate with the per‑persona local script (the house pattern), e.g.
   [`community/shared/bundles/angel_stylist/generate_angel_avatar_local.py`](../community/shared/bundles/angel_stylist/generate_angel_avatar_local.py):
   ```bash
   python community/shared/bundles/<bundle>/generate_<prefix>_avatar_local.py --seed 42
   ```
   Same seed ⇒ same face, forever. This is the [StyleGAN engine](./design/stylegan-engine-design.md)
   that also powers the avatar‑service.

### FALLBACK — thispersondoesnotexist.com

Zero setup, **no GPU, no API key**, works anywhere — CI, Docker, and the
**Claude Code sandbox**. Each request returns a unique synthetic 1024² face
from `https://thispersondoesnotexist.com/random-person.jpeg`. This is the path
used to create **Nexus**.

> Both sources produce StyleGAN‑class synthetic faces, so the fallback is a
> quality match for the primary — it just isn't seed‑reproducible.

---

## 3. The tooling

Two persona‑agnostic helpers in `community/shared/scripts/`:

| File | What it does |
|------|--------------|
| [`generate_persona_portrait.py`](../community/shared/scripts/generate_persona_portrait.py) | The generator. `--source auto` tries the local generator, then falls back to the web source. Produces the 512/256 standard, updates `persona_appearance.json` + `manifest.json`, and repacks the `.hpersona`. |
| [`generate-persona-portrait.sh`](../community/shared/scripts/generate-persona-portrait.sh) | Thin bash wrapper: bootstraps Pillow and forwards to the Python tool. Start here in a sandbox. |

Common flags: `--candidates N`, `--pick K`, `--use-file PATH`,
`--contact-sheet PATH`, `--seed N`, `--source auto|local|web`, `--flat`,
`--no-repack`.

### Worked example — Nexus

```bash
BUNDLE=community/shared/bundles/nexus_secretary

# 1) fetch 6 synthetic candidates and build a montage
community/shared/scripts/generate-persona-portrait.sh "$BUNDLE" nexus \
    --candidates 6 --contact-sheet /tmp/sheet.png

# 2) open/Read /tmp/sheet.png, choose the on-role face (e.g. candidate_1)

# 3) commit it: crop→512 PNG, 256 WebP thumb, wire metadata, repack .hpersona
community/shared/scripts/generate-persona-portrait.sh "$BUNDLE" nexus \
    --use-file /tmp/persona_faces/candidate_1.jpg
```

---

## 4. Creating images in the Claude Code sandbox (for future AI coders)

The sandbox has **no image libraries and no GPU** preinstalled. What works:

1. **Install Pillow.** `pypi.org` and `files.pythonhosted.org` are in the agent
   proxy's `noProxy` list, so pip reaches them directly:
   ```bash
   pip install Pillow          # the scripts above do this for you
   ```
2. **The LOCAL StyleGAN2 path is usually unavailable in‑sandbox** (no GPU, and
   the weights are ~360 MB). `--source auto` detects this and **falls back to
   the web source automatically** — expected and fine.
3. **Fetch faces** from `thispersondoesnotexist.com/random-person.jpeg`
   (reachable through the proxy; returns a fresh 1024² JPEG each call).
4. **Pick visually.** You cannot "see" a folder of files, so render a **contact
   sheet** (`--contact-sheet`) and open it with the `Read` tool, which shows
   images. Then re‑run with `--use-file` on the winner.
5. **Process & verify.** Crop to 512², write the 256² WebP, then `Read` the
   final `avatar_<prefix>.png` to confirm it's on‑role before committing.
6. **Repack** the `.hpersona` (the tool does this unless `--no-repack`), and
   commit the PNG, WebP, updated `persona_appearance.json` / `manifest.json`,
   and the rebuilt package together.

Minimal from-scratch recipe (what the tool automates), for reference:

```bash
pip install Pillow
mkdir -p /tmp/faces && cd /tmp/faces
for i in 1 2 3 4 5 6; do
  curl -sS -o cand_$i.jpg "https://thispersondoesnotexist.com/random-person.jpeg"; sleep 1
done
python3 - <<'PY'
from PIL import Image, ImageDraw
ims=[Image.open(f"/tmp/faces/cand_{i}.jpg").resize((300,300)) for i in range(1,7)]
sheet=Image.new("RGB",(900,630),"white"); d=ImageDraw.Draw(sheet)
for k,im in enumerate(ims):
    x,y=(k%3)*300,(k//3)*300+30; sheet.paste(im,(x,y)); d.text((x+6,y+6),f"cand_{k+1}",fill="red")
sheet.save("/tmp/faces/sheet.png")
PY
# → Read /tmp/faces/sheet.png, choose, then process the winner to 512 PNG + 256 WebP.
```

---

## 5. Checklist for a new shared persona portrait

- [ ] Face is **synthetic** and depicts no real person.
- [ ] `avatar_<prefix>.png` is **512×512 PNG**, square, on‑role.
- [ ] `thumb_avatar_<prefix>.webp` is **256×256 WebP**.
- [ ] `manifest.json` → `contents.has_avatar = true`.
- [ ] `persona_appearance.json` → `selected_filename` / `selected_thumb_filename`
      set, `avatar_synthetic: true`, and a photoreal `avatar_prompt` retained.
- [ ] `.hpersona` repacked to include the new assets.
- [ ] Final PNG visually verified.

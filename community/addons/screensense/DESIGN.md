# ScreenSense + Nexus — feature design

An **additive, non-destructive** screen-awareness capability for HomePilot, and
a community persona (**Nexus**) built around it. No existing endpoint, schema,
or chat path is modified.

## Why this needed zero backend changes

HomePilot is already multimodal. `backend/app/multimodal.py` runs local Ollama
vision models and is exposed as `POST /v1/multimodal/analyze` (and the agent
tool `vision.analyze`). Vision already fires on *uploaded* images and can
*persist* the result into a conversation. The only missing piece was screen
**capture** — turning "the user uploaded an image" into "the assistant can see
the screen." That is a pure front-end/desktop concern, so the whole feature is
delivered as an addon plus a tiny Electron bridge.

```
                    ┌─────────────── capture (NEW, additive) ───────────────┐
  user asks  ──►    │  desktop:  window.homepilot.captureScreen() (native)  │
                    │  browser:  navigator.mediaDevices.getDisplayMedia()   │
                    │  cloud FB: ask user for a screenshot (file picker)    │
                    └───────────────────────┬───────────────────────────────┘
                                            │  one downscaled JPEG
                                            ▼
        POST /upload  ─────────────►  /files/… URL     (EXISTING endpoint)
                                            ▼
   POST /v1/multimodal/analyze  ─►  local Ollama vision model  (EXISTING)
                                            ▼
             analysis_text  ──►  persisted into conversation  (EXISTING)
                                            ▼
                     persona sees "[Image Analysis] …" as context
```

## The core idea: capture adapts to environment

The user's requirement — *"if we are on a desktop / local computer it takes the
screenshot itself; if I'm on cloud it asks for the picture"* — is implemented
as three auto-detected modes:

| Mode | Detected by | Behavior | Privacy posture |
|------|-------------|----------|-----------------|
| `desktop` | `window.homepilot.isDesktop` + `captureScreen` bridge | Silent native grab of the primary display | Local machine, app already trusted |
| `browser` | `getDisplayMedia` available | OS screen-share picker; user chooses the surface | Explicit per-share consent |
| `upload`  | no screen-share, or user declined | Asks the user to hand over a screenshot image | User selects exactly one image |

In all three, the image goes only to the **local** HomePilot backend and the
**local** vision model. Screen content — the most sensitive data category for a
secretary looking at calendars, email, and contracts — never touches OpenAI or
Anthropic.

## What changed

**Additive files**
- `community/addons/screensense/homepilot-screensense.js` — the addon (dual/tri
  capture, one-line chat hook, self-mounting button).
- `community/addons/screensense/{README,DESIGN}.md`, `toolbar-button.html`.
- `frontend/public/js/homepilot-screensense.js` — served copy.
- `community/shared/bundles/nexus_secretary/**` — the Nexus persona bundle,
  its `.hpersona`, and its avatar assets.

**Additive edits (no behavior removed)**
- `desktop/preload.js` — exposes `isDesktop` + `captureScreen()` on the bridge.
- `desktop/main.js` — `ipcMain.handle("screensense:capture")` via
  `desktopCapturer`; imports `desktopCapturer`, `screen`.
- `frontend/index.html` — one `<script>` line; the addon is inert until called.
- `community/shared/registry/shared_registry.json` — registers the Nexus bundle.

## Nexus, the persona

Nexus is a screen-aware executive secretary (female, realistic **synthetic**
headshot — a StyleGAN-generated face that depicts no real person, shipped as
`avatar_nexus.png` 512×512 + `thumb_avatar_nexus.webp` 256×256, with an SVG
vector fallback). Her system prompt encodes the capture contract directly: on desktop
she may capture the screen when asked; on cloud she *asks* for a screenshot and
waits. She gives the **one** most useful observation in two sentences, never
reads text back verbatim, and treats all screen content as confidential —
declining to comment on personal material (banking, medical, private messages).
Her `dependencies/models.json` declares a required vision model so HomePilot's
importer shows the green/amber/red readiness status.

## Try it

```
ollama pull llava:7b
# import community/shared/bundles/nexus_secretary/nexus_secretary.hpersona
# open the chat page → click 👁, or say:
"Nexus, look at my screen — is this email draft okay to send?"
```

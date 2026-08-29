# HomePilot ScreenSense

**Additive, non-destructive screen awareness for any HomePilot persona.**

ScreenSense lets a persona *see the user's screen* and give one-glance
suggestions — an error to fix, a next step, a draft to tighten, a scheduling
conflict — while keeping everything **100% local**. The frame is uploaded to
*your* HomePilot backend and analyzed by *your* local Ollama vision model
(`llava`, `moondream`, `qwen-VL`, `gemma3`, `minicpm-v`…). Nothing ever leaves
the machine.

It uses **only existing HomePilot endpoints** — no backend changes required:

| Step | Endpoint | Purpose |
|------|----------|---------|
| 1 | `POST /upload` | Store the captured frame → returns a `/files/…` URL |
| 2 | `POST /v1/multimodal/analyze` | Local vision model answers about the frame; result is persisted into the conversation when a `conversationId` is given |

## Adaptive capture — desktop vs. cloud

ScreenSense picks how to obtain the screen based on **where HomePilot is
running**, and this is the whole point of the addon:

| Mode | When | How it captures |
|------|------|-----------------|
| **`desktop`** | HomePilot desktop app (Electron) — *local computer only* | Native, **silent** grab of the primary display via the `window.homepilot.captureScreen()` bridge. No browser "share your screen" dialog — on your own machine you granted trust by installing the app. |
| **`browser`** | Cloud / any browser that supports `getDisplayMedia` | Shows the native **screen-share picker** so the user chooses exactly what the persona may see. |
| **`upload`** | Cloud without screen-share, or the user declines it | Falls back to **asking the user for a screenshot image** (file picker / drag-drop / paste). |

Detection is automatic (`hpScreenSense.mode`). The desktop native bridge is
provided by two additive changes in `desktop/preload.js` and `desktop/main.js`
(an `ipcMain.handle("screensense:capture")` using Electron's
`desktopCapturer`).

## Install

The script is already served by the web UI (one `<script>` line in
`frontend/index.html`, loading `/js/homepilot-screensense.js`). To add it to any
other HomePilot page:

```html
<script src="/js/homepilot-screensense.js"></script>
<!-- or straight from this addon folder -->
<script src="/addons/screensense/homepilot-screensense.js"></script>
```

On load it exposes `window.hpScreenSense` and auto-mounts a small floating
button. Both are inert until invoked, so including the script changes nothing
about existing chat behavior.

## API

```js
hpScreenSense.mode            // 'desktop' | 'browser' | 'upload'

await hpScreenSense.enable(); // browser: opens the share picker once
                              // desktop/upload: no-op that succeeds

await hpScreenSense.ask('is this email draft okay?', {
  conversationId: currentConversationId,  // optional → persists to chat history
  apiKey: HOMEPILOT_API_KEY,               // if your backend requires it
  model: 'llava:7b',                       // optional vision-model override
});
// → { ok, analysis_text, meta, mode }

hpScreenSense.stop();                      // release any browser stream
hpScreenSense.mountButton(opts);           // floating 👁 button (auto-mounted)
```

### One-line chat integration

Drop this into any send handler so screen questions route through ScreenSense:

```js
if (hpScreenSense.isScreenQuery(text))
    return hpScreenSense.ask(text, { conversationId });
```

`isScreenQuery("look at my screen")` → `true`. Everything else flows to your
normal chat path untouched.

### Opting out of the auto-button

Set a flag before the script loads:

```html
<script>window.HOMEPILOT_SCREENSENSE_NO_AUTOBUTTON = true;</script>
```

Then call `hpScreenSense.mountButton()` yourself where you want it, or drive the
API directly. See `toolbar-button.html` for a copy-paste toolbar snippet.

## Pairs with the Nexus persona

`community/shared/bundles/nexus_secretary/` ships **Nexus**, a screen-aware
executive secretary whose system prompt already knows the desktop-vs-cloud
capture contract (capture directly on desktop; ask for a screenshot on cloud)
and enforces a screen-content privacy clause. Import the bundle, `ollama pull
llava:7b`, then say *"Nexus, look at my screen — is this okay to send?"*

## Notes

* `/upload` response field names can vary by build — the addon accepts
  `url` / `file_url` / `path`. Run one round-trip and check the console; a
  differing field name is a one-line fix.
* The vision model must be installed locally. With none present,
  `/v1/multimodal/analyze` returns a helpful "install a vision model" error.

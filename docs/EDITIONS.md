# HomePilot Editions — Cloud & Desktop

HomePilot runs in two production-ready topologies. Pick whichever matches
how you want to host the AI and where the conversation data should live.

| | ☁️ **Cloud Edition** | 🖥️ **Desktop Edition** |
|---|---|---|
| Where HomePilot runs | A public Hugging Face Space | Your own PC |
| Who reaches it | OllaBridge Cloud, directly over HTTPS | OllaBridge Cloud, through an `ollabridge-node` tunnel |
| `ollabridge-node` on your PC | **Not needed** | **Required** (one-time pair) |
| Performance floor | HF Space tier (CPU-basic = slow, paid GPU = fast) | Your hardware — GPU at full speed |
| Biggest model you can run | limited by Space RAM | limited by your RAM/VRAM |
| Privacy | conversation transits OllaBridge Cloud | conversation stays on your device |
| Install effort for end users | zero | install `ollabridge` + pair |
| Good for | public demos, shared-tenant use, "private AI in 2 minutes" | power users, privacy-first, offline capable |

The persona catalog, avatars, system prompts and bootstrap behaviour are
**identical** across both editions — the only thing that differs is who
carries traffic from OllaBridge Cloud to HomePilot.

---

## ☁️ Cloud Edition

HomePilot lives on a Hugging Face Space with a public URL. OllaBridge
Cloud posts directly to `/v1/chat/completions` over HTTPS.

```
Chata UI  ─► Chata backend  ─► OllaBridge Cloud  ─► HomePilot HF Space
  browser       HF Space            ollabridge.cloud     ruslanmv-homepilot.hf.space
                                                         │
                                                         └─► local Ollama
                                                             (qwen2.5 in-pod)
```

### Set-up (end user)

1. Open the one-click installer: <https://huggingface.co/spaces/ruslanmv/HomePilot-Installer>
2. Paste an HF write-token, pick a Space name, click **Install**.
3. Wait ~3 minutes for HF to build. The Space now has:
   * 14 personas auto-imported as Projects
   * OllaBridge Gateway enabled (no API key — public by default)
   * All 14 personas published to `/v1/chat/completions` as `persona:<slug>--<shortid>`
4. That's the whole set-up. Chata, the 3D avatar, or any OpenAI-compat
   client can now chat with every persona.

### Who configures what

| Component | Setting |
|---|---|
| Chata backend | `OLLABRIDGE_URL=https://ollabridge.cloud/v1/chat/completions` |
| OllaBridge Cloud | `HOMEPILOT_BASE_URL=https://<owner>-homepilot.hf.space` |
| HomePilot Space | nothing — the in-container bootstrap handles it |

### Advantages
- **Zero client install.** Works from any browser.
- **Shared tenant.** One Space serves many rooms / many users at once.
- **Free tier viable.** The shipped default model (`qwen2.5:0.5b`) is sized for HF CPU-basic.

### Trade-offs
- Conversations traverse the Cloud gateway (encrypted, but terminated there).
- HF CPU-basic is slow (~60 s first token); upgrade the Space tier for better UX.
- Model size is bounded by Space RAM.

---

## 🖥️ Desktop Edition

HomePilot runs locally on your PC. Because your PC is behind a NAT,
OllaBridge Cloud can't reach it directly — so a small local daemon,
`ollabridge-node`, opens an outbound WebSocket to the Cloud and tunnels
incoming persona requests to your local HomePilot.

```
Chata UI  ─► Chata backend  ─► OllaBridge Cloud
  browser       HF / local         ollabridge.cloud
                                       │
                                       │ WSS (initiated by the node)
                                       ▼
                 ┌──────── YOUR DESKTOP ────────────────┐
                 │  ollabridge-node  ◄─── outbound WSS   │
                 │       │                               │
                 │       ▼  http://127.0.0.1:7860         │
                 │  HomePilot (Tauri / Docker)           │
                 │       │                               │
                 │       ▼  http://127.0.0.1:11434        │
                 │  Local Ollama (your GPU)              │
                 └───────────────────────────────────────┘
```

### Set-up (end user)

1. Install HomePilot on your desktop (Docker Compose or the Tauri app).
2. `pip install ollabridge`
3. `ollabridge-node pair` — prints a one-time code.
4. Paste the code into your OllaBridge account page.
5. `ollabridge-node serve` — keep it running (systemd unit or
   `launchctl` on macOS).
6. That's it. Chata (or any other OpenAI-compat client using the Cloud)
   will route `persona:*` requests to your machine.

### Who configures what

| Component | Setting |
|---|---|
| Chata backend | `OLLABRIDGE_URL=https://ollabridge.cloud/v1/chat/completions` + personal `OLLABRIDGE_API_KEY` issued at pairing |
| OllaBridge Cloud | (no HomePilot env — device route is looked up per user API key) |
| `ollabridge-node` | `pair` once + `serve` in the background |
| HomePilot desktop | nothing — the same bootstrap runs locally |

### Advantages
- **Full privacy.** Request body never leaves your device.
- **Full hardware speed.** Use `qwen2.5:1.5b`, `llama3:8b`, or whatever your GPU can handle.
- **Offline fallback.** A companion "local-only" mode bypasses the Cloud entirely — see below.

### Trade-offs
- Requires installing one extra piece (`ollabridge-node`).
- Requires the node process to be running when you want to chat.
- Not useful for shared / multi-user deployments unless every user runs their own HomePilot.

### Fully offline variant (advanced)

Skip OllaBridge Cloud entirely. Point Chata directly at your local HomePilot:

```
OLLABRIDGE_URL=http://127.0.0.1:7860/v1/chat/completions
```

Chata → HomePilot → Ollama, all on your machine. No Cloud, no node.
Trade-off: only you can use the rooms — no shared public surface.

---

## Which edition should I pick?

| Your goal | Edition |
|---|---|
| Try HomePilot without installing anything | ☁️ Cloud |
| Public demo on your domain | ☁️ Cloud |
| Installer-deployed Space (users click "Install") | ☁️ Cloud (each user's own HF Space) |
| Keep conversations on your gaming PC | 🖥️ Desktop |
| Use a large model that HF free-tier can't host | 🖥️ Desktop |
| Air-gapped / offline | 🖥️ Desktop (local-only variant) |
| Both public Chata surface AND per-user compute | Hybrid — one Chata + Cloud, each user paired with their own node + local HomePilot |

---

## What's the same in both editions

Regardless of where HomePilot runs:

- Same 14 community personas (Starter + Retro pack) auto-import on first boot
- Same StyleGAN avatars, same small-LLM-tuned system prompts with gender + Chata awareness
- OllaBridge Gateway auto-enabled with no API key (the safe default)
- All personas auto-published to `/v1/models` so external clients see them immediately
- Same `persona:<slug>--<shortid>` model routing
- Same bootstrap script (`chata_project_bootstrap.py`), idempotent on every boot

The file you're reading describes the deployment topology only. For the
persona specification itself, see [PERSONA.md](PERSONA.md). For the
community gallery, see [COMMUNITY_GALLERY.md](COMMUNITY_GALLERY.md).

# HomePilot Desktop

Native desktop app for **Windows**, **macOS**, and **Linux**.
Wraps the HomePilot web UI in an Electron shell and manages the Docker container automatically.

---

## How It Works

1. On first launch a **setup wizard** collects your API keys (OpenAI, Anthropic, or Ollama).
2. The app checks that **Docker** is running.
3. If the `ruslanmv/homepilot` image is not cached it pulls it (with a progress bar).
4. A container starts on **port 7860** with GPU support when available.
5. The HomePilot UI opens in a native window.
6. The app lives in the **system tray** — close the window and it keeps running.
7. Each time you open the app, it checks for updates in the background and notifies you if a new version is available.

---

## Download

Pre-built installers are attached to each [GitHub Release](https://github.com/ruslanmv/HomePilot/releases):

| Platform | File | Notes |
|----------|------|-------|
| **Windows** | `HomePilot-Setup-x.x.x.exe` | NSIS installer, x64 |
| **macOS** | `HomePilot-x.x.x.dmg` | Universal (Intel + Apple Silicon) |
| **Linux** | `HomePilot-x.x.x.AppImage` | Portable, runs on any distro |
| **Linux** | `homepilot_x.x.x_amd64.deb` | Debian / Ubuntu package |

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.
- NVIDIA GPU + drivers *(optional, for GPU acceleration)*.

---

## Quick Start

### Option A — Download an installer

1. Go to [Releases](https://github.com/ruslanmv/HomePilot/releases).
2. Download the file for your platform.
3. Run the installer and launch **HomePilot**.

### Option B — Build from source

```bash
# 1. Install dependencies
cd desktop
npm install

# 2. Run in development mode
npm start

# 3. Build an installer for your current OS
npm run build          # auto-detects platform

# Or target a specific platform:
npm run build:win      # Windows  →  .exe
npm run build:mac      # macOS    →  .dmg
npm run build:linux    # Linux    →  .AppImage + .deb
npm run build:all      # All three platforms at once
```

### Option C — Use the Makefile

```bash
make build-installer   # auto-detects OS and builds the right installer
```

Installers are written to `desktop/dist/`.

---

## Configuration

Settings are stored via `electron-store` in the standard app-data directory:

| OS | Path |
|----|------|
| **Windows** | `%APPDATA%/homepilot/config.json` |
| **macOS** | `~/Library/Application Support/homepilot/config.json` |
| **Linux** | `~/.config/homepilot/config.json` |

You can change API keys and LLM backend at any time from the setup wizard or by editing the JSON file directly.

---

## Custom Icons

To replace the default generated icons with your own artwork:

1. Place a `1024x1024` PNG named `icon-1024.png` in `desktop/icons/`.
2. Run `node desktop/scripts/generate-icons.js` to regenerate all platform formats.
3. Rebuild the installer.

---

## Updates

HomePilot follows industry best practices for updates (the same pattern used by VS Code, Slack, and Spotify):

1. **On launch**: The app checks for a newer Docker image in the background (non-blocking).
2. **If available**: A native OS notification appears — "A new version is ready. Click to update."
3. **Your choice**: Click the notification or choose "Update Now" in the dialog. Or dismiss and update later.
4. **Manual check**: Right-click the system tray icon → "Check for Updates" at any time.
5. **No polling**: There are no recurring timers or scheduled checks. Updates are checked once per launch only.

Data and settings are always preserved across updates.

---

## Architecture

```
┌─────────────────────────────────────┐
│         Electron Shell              │
│  ┌──────────┐  ┌────────────────┐  │
│  │  System   │  │  BrowserWindow │  │
│  │   Tray    │  │  localhost:7860│  │
│  └──────────┘  └───────┬────────┘  │
│                        │            │
│  ┌─────────────────────▼─────────┐  │
│  │     DockerManager (dockerode) │  │
│  │  pull · start · stop · update │  │
│  └─────────────────────┬─────────┘  │
└────────────────────────┼────────────┘
                         │
          ┌──────────────▼──────────────┐
          │  homepilot:latest container  │
          │  nginx :7860 → uvicorn :8000│
          │  frontend (static) + backend│
          └─────────────────────────────┘
```

The desktop app does **not** bundle the backend. It manages a Docker container that runs the full HomePilot stack behind a single port.

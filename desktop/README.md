# HomePilot Desktop

Native desktop app for Windows, macOS, and Linux. Wraps the HomePilot web UI in an Electron shell and manages the Docker container automatically.

## How It Works

1. On first launch, the app checks if Docker is running
2. If the HomePilot image isn't cached, it pulls it (with progress bar)
3. Starts the container with GPU support if available
4. Opens the HomePilot UI in a native window
5. Lives in the system tray — close the window, it keeps running

## Download

Pre-built installers are attached to each [GitHub Release](https://github.com/ruslanmv/HomePilot/releases):

| Platform | File | Notes |
|---|---|---|
| Windows | `HomePilot-Setup-x.x.x.exe` | NSIS installer, x64 |
| macOS | `HomePilot-x.x.x.dmg` | Universal (Intel + Apple Silicon) |
| Linux | `HomePilot-x.x.x.AppImage` | Portable, runs on any distro |
| Linux | `homepilot_x.x.x_amd64.deb` | Debian/Ubuntu package |

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) must be installed and running
- NVIDIA GPU + drivers (optional, for GPU acceleration)

## Development

```bash
cd desktop
npm install
npm start        # Launch in dev mode
npm run build    # Build installer for current platform
```

## Custom Icons

Replace the placeholder icons with your own artwork:

1. Create a `1024x1024` PNG named `icon-1024.png` in `desktop/icons/`
2. Run `./icons/generate-icons.sh icon-1024.png`
3. This generates all platform-specific formats (`.ico`, `.icns`, `.png`)

## Configuration

Settings are stored via `electron-store` in the user's app data directory:

- **Windows:** `%APPDATA%/homepilot/config.json`
- **macOS:** `~/Library/Application Support/homepilot/config.json`
- **Linux:** `~/.config/homepilot/config.json`

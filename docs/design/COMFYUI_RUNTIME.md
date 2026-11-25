# Where ComfyUI runs

`scripts/start-comfyui.sh` (used by `make start` and `make start-comfyui`) runs ComfyUI in one
of two runtimes. `COMFY_RUNTIME=auto|linux|windows`, default `auto`.

| Machine | Runtime `auto` picks | Why |
|---|---|---|
| Native Linux, cloud VM, Docker | `linux` | Models are on a Linux filesystem; nothing to do. |
| WSL, models on a Linux path (`~/…`) | `linux` | Same as native Linux. |
| WSL, models on a Windows drive (`/mnt/c/…`), Windows env installed, mirrored networking | `windows` | See below. |
| WSL, anything above missing | `linux` (with a one-line hint) | Never worse than before. |

## Why a Windows runtime exists

Under WSL, a Linux process reading a Windows drive goes through the `/mnt` (9p) bridge.
Measured on a 6.5 GB checkpoint: **2,211 MB/s** read natively on Windows, **64 MB/s** from WSL
(file already in the Windows cache). Every model load paid that, and heavy small-file access
over the bridge (ComfyUI listing its input folder) froze ComfyUI's request thread for minutes.

Running the same ComfyUI checkout with a Windows Python reads the models directly. The code,
custom nodes, models, `input/` and `output/` folders are shared by both runtimes; only the
Python environment differs. The HomePilot backend, frontend and other services stay in WSL
and reach ComfyUI on `localhost:8188`.

## Set up

Nothing extra: in WSL, `make install` and `make start` as usual.

`make install` runs `install-comfyui-windows-auto` after the Linux ComfyUI install. It does
nothing on native Linux, cloud or Docker, nor under WSL when the models are on the Linux
filesystem. Under WSL with the models on a Windows drive it (re-runnable, never fails the
install — on any problem it warns and ComfyUI stays in Linux):

1. sets `networkingMode=mirrored` in `%UserProfile%\.wslconfig` (an existing file is backed
   up to `.wslconfig.homepilot-backup`) so WSL and Windows share `localhost`;
2. builds a Windows venv (~6 GB): `%LOCALAPPDATA%\HomePilot\comfyui-win` when C: has room,
   else `<drive>:\homepilot-envs\comfyui-win` on the fixed drive with the most free space.
   `COMFY_WIN_VENV='E:\path'` chooses it; `COMFY_WINDOWS=0` skips all of this;
3. installs torch matching the Linux venv plus ComfyUI and custom-node requirements
   (insightface compiles with the Visual Studio C++ build tools if no wheel exists);
4. makes `ComfyUI\models` a **directory junction** to `models\comfy`, which Windows, WSL and
   Linux all follow (the old Linux link is renamed, not deleted);
5. records the venv in `backend/data/comfy-windows.env`.

Then restart WSL once so mirrored networking applies (`wsl --shutdown` in Windows), and
`make start` shows `🪟 ComfyUI: running natively on Windows`. Re-running the step alone:
`make install-comfyui-windows`.

To go back to Linux ComfyUI: delete `backend/data/comfy-windows.env`, or `COMFY_RUNTIME=linux`.

### Port reservations under mirrored networking

With `networkingMode=mirrored`, a port that any WSL process has *bound* is reserved on
Windows until WSL restarts — even after the socket is closed, and no Windows tool lists it.
`make start`'s port picker used to bind-test the ComfyUI port, which locked the Windows
ComfyUI out of it ("only one usage of each socket address"). Under mirrored networking it now
checks the ComfyUI port by connecting only (`scripts/pick_ports.py`, `comfy_port_busy`), and
`start-comfyui.ps1` detects a reserved port and says to run `wsl --shutdown` instead of
letting ComfyUI crash. Never bind-test a port that a Windows process is about to use.

## Cloud / native Linux

Nothing changes: no `comfy-windows.env`, no WSL, so `auto` is always `linux`. For best
performance keep models on local NVMe (or a cached volume) rather than a network share;
the same bridge cost applies to any slow filesystem ComfyUI has to read models from.

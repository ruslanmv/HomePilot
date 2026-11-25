#!/usr/bin/env bash
###############################################################################
# stop-windows-comfyui.sh — part of `make stop` under WSL.
#
# 1. Stops the Windows-native ComfyUI this checkout started (see
#    docs/design/COMFYUI_RUNTIME.md). Other Windows programs are never touched.
# 2. Checks that the ComfyUI port is free again on Windows. Under WSL mirrored
#    networking a port that a WSL process once bound stays reserved on Windows
#    until WSL restarts, with nothing listed as holding it; the Windows ComfyUI
#    then cannot start on it. When that is the case it ASKS before restarting
#    WSL (which closes every WSL window, this one included); with no terminal
#    to ask, it only prints the command.
#
# Does nothing on native Linux, or under WSL without the Windows ComfyUI env.
# Options: --yes  restart WSL without asking if a port is stuck
#          --no   never restart (just report)
###############################################################################
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ANSWER=""
case "${1:-}" in --yes) ANSWER=y ;; --no) ANSWER=n ;; esac

grep -qi microsoft /proc/version 2>/dev/null || exit 0
command -v powershell.exe >/dev/null 2>&1 || exit 0
ENV_FILE="${DATA_DIR:-$ROOT/backend/data}/comfy-windows.env"
[ -f "$ENV_FILE" ] || exit 0
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a
COMFY_WIN_VENV="${COMFY_WIN_VENV:-}"; COMFY_WIN_VENV="${COMFY_WIN_VENV%$'\r'}"
PS1_WIN="$(wslpath -w "$ROOT/scripts/start-comfyui.ps1")"
PORT="${COMFY_PORT:-8188}"

echo ""
echo "Windows-native ComfyUI:"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PS1_WIN" -StopAll -Venv "$COMFY_WIN_VENV" 2>&1 | tr -d '\r'

# Port state on Windows: free / held by a listener (named) / reserved with no listener.
state="$(powershell.exe -NoProfile -Command "
  \$p=$PORT; \$l=[System.Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,\$p)
  try { \$l.Start(); \$l.Stop(); 'free' } catch {
    \$c = Get-NetTCPConnection -LocalPort \$p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (\$c) { \$n=(Get-Process -Id \$c.OwningProcess -ErrorAction SilentlyContinue).ProcessName; \"held \$n \$(\$c.OwningProcess)\" } else { 'reserved' }
  }" 2>/dev/null | tr -d '\r' | tail -n1)"

case "$state" in
  free)
    echo "  Port $PORT is free on Windows."
    ;;
  held*)
    set -- $state
    echo "  Port $PORT is in use by another Windows program: ${2:-?} (pid ${3:-?}). HomePilot leaves it alone."
    ;;
  reserved)
    echo "  Port $PORT is still reserved by WSL (mirrored networking) although nothing listens on it."
    echo "  The Windows ComfyUI cannot start on it until WSL restarts."
    if [ -z "$ANSWER" ] && [ -t 0 ] && [ -r /dev/tty ]; then
      printf "  Restart WSL now to release it? This closes every WSL window, this one included. [y/N] "
      read -r ANSWER < /dev/tty || ANSWER=n
    fi
    case "$ANSWER" in
      y|Y|yes|YES)
        echo "  Restarting WSL..."
        powershell.exe -NoProfile -Command "Start-Process wsl.exe -ArgumentList '--shutdown' -WindowStyle Hidden" >/dev/null 2>&1
        ;;
      *)
        echo "  To release it later, run in Windows:  wsl --shutdown"
        ;;
    esac
    ;;
  *)
    echo "  Could not check port $PORT on Windows."
    ;;
esac
exit 0

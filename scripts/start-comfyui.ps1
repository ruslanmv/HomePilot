<#
.SYNOPSIS
  Run HomePilot's ComfyUI natively on Windows (used by scripts/start-comfyui.sh under WSL).

.DESCRIPTION
  Under WSL, ComfyUI reading models from a Windows drive goes through the /mnt bridge at
  ~64 MB/s instead of the disk's ~2,200 MB/s, so loading a checkpoint took minutes and
  heavy file access could freeze ComfyUI. Running the same ComfyUI checkout with a Windows
  Python reads the models directly. Code, custom nodes, models, input and output folders
  are shared with the Linux runtime; only the Python environment differs.

  Native Linux and cloud machines never use this script.

.PARAMETER Port      Port to serve on (default 8188).
.PARAMETER Venv      Windows venv for ComfyUI (default: $env:COMFY_WIN_VENV).
.PARAMETER Listen    Address to bind (default 127.0.0.1; WSL reaches it with mirrored networking).
.PARAMETER Stop      Stop the ComfyUI this script started (reads its pid file) and exit.
#>
param(
  [int]$Port = 8188,
  [string]$Venv = $env:COMFY_WIN_VENV,
  [string]$Listen = $(if ($env:COMFY_WIN_LISTEN) { $env:COMFY_WIN_LISTEN } else { '127.0.0.1' }),
  [switch]$Stop
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$ComfyDir = Join-Path $Root 'ComfyUI'
$PidFile = Join-Path $ComfyDir "user\comfyui-windows-$Port.pid"

if ($Stop) {
  if (Test-Path $PidFile) {
    $procId = [int](Get-Content $PidFile -Raw)
    # A venv's python.exe is a launcher that runs the real interpreter as a child process;
    # stopping only the launcher would leave ComfyUI running and holding the port. End the tree.
    & taskkill.exe /PID $procId /T /F 2>$null | Out-Null
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    Write-Host "ComfyUI (Windows, pid $procId) stopped."
  }
  exit 0
}

if (-not $Venv) { Write-Error 'COMFY_WIN_VENV is not set. Run: make install-comfyui-windows'; exit 1 }
$Python = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $Python)) { Write-Error "No Windows ComfyUI environment at $Venv. Run: make install-comfyui-windows"; exit 1 }
if (-not (Test-Path (Join-Path $ComfyDir 'main.py'))) { Write-Error "ComfyUI not found at $ComfyDir"; exit 1 }

# InstantID and other nodes read ComfyUI\models directly. On Windows it must be a directory
# junction (WSL and Linux follow it like a symlink); a Linux-made symlink is unreadable here.
$Models = Join-Path $ComfyDir 'models'
$item = Get-Item $Models -Force -ErrorAction SilentlyContinue
if (-not $item -or ($item.LinkType -ne 'Junction' -and $item.LinkType -ne 'SymbolicLink' -and -not $item.PSIsContainer)) {
  Write-Error "ComfyUI\models is not a folder or junction Windows can read. Run: make install-comfyui-windows"; exit 1
}

# Already serving on this port? Reuse it rather than starting a second copy.
try {
  $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "http://127.0.0.1:$Port/system_stats"
  if ($r.StatusCode -eq 200) { Write-Host "ComfyUI is already running on port $Port."; exit 0 }
} catch { }

# The port must be free. Right after WSL switches networking mode (or a previous ComfyUI is
# shutting down) a holder can linger for a few seconds; wait for it, then name it instead of
# letting ComfyUI die with a bare "only one usage of each socket address" traceback.
function Get-PortHolder([int]$port) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}
$deadline = (Get-Date).AddSeconds(20)
while (($holder = Get-PortHolder $Port) -and (Get-Date) -lt $deadline) {
  Write-Host "Port $Port is busy (pid $($holder.OwningProcess)); waiting for it to free..."
  Start-Sleep -Seconds 2
}
if ($holder = Get-PortHolder $Port) {
  $proc = Get-Process -Id $holder.OwningProcess -ErrorAction SilentlyContinue
  Write-Error ("Port $Port is held by {0} (pid {1}). Stop it, or start HomePilot with COMFY_PORT=<free port>." -f $(if ($proc) { $proc.ProcessName } else { 'another program' }), $holder.OwningProcess)
  exit 1
}

$extra = @()
if ($env:COMFY_WIN_ARGS) { $extra = $env:COMFY_WIN_ARGS -split '\s+' | Where-Object { $_ } }
$comfyArgs = @('main.py', '--listen', $Listen, '--port', "$Port") + $extra

# Plain text: output is relayed to a WSL terminal, where emoji arrive garbled.
Write-Host "ComfyUI: Windows-native ($Python) on ${Listen}:$Port"
$env:PYTHONUNBUFFERED = '1'
$p = Start-Process -FilePath $Python -ArgumentList $comfyArgs -WorkingDirectory $ComfyDir -NoNewWindow -PassThru
New-Item -ItemType Directory -Force (Split-Path $PidFile) | Out-Null
Set-Content -Path $PidFile -Value $p.Id -NoNewline
try {
  $p.WaitForExit()
  exit $p.ExitCode
} finally {
  Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

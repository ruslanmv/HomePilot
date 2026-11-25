<#
.SYNOPSIS
  Create the Windows Python environment that runs HomePilot's ComfyUI natively on Windows.

.DESCRIPTION
  For WSL installs whose models live on a Windows drive (see scripts/start-comfyui.ps1 for
  why). Shares the existing ComfyUI checkout, custom nodes, models, input and output with the
  Linux runtime; only adds a Windows venv. Native Linux / cloud machines do not need this.

  Normally run by `make install` under WSL (see the Makefile's install-comfyui-windows-auto);
  it does nothing on native Linux.

  Steps (each is idempotent, so re-running resumes):
    0. WSL mirrored networking in %UserProfile%\.wslconfig (existing file backed up), so the
       backend in WSL reaches this ComfyUI on localhost; takes effect after `wsl --shutdown`
    1. venv at -Venv, or chosen automatically: %LOCALAPPDATA%\HomePilot\comfyui-win when C:
       has room, else <drive>:\homepilot-envs\comfyui-win on the fixed drive with the most
       free space (needs ~8 GB free)
    2. torch matching the Linux venv, from the PyTorch CUDA index
    3. ComfyUI and custom-node requirements (insightface is compiled with the installed
       Visual Studio C++ build tools when no wheel exists)
    4. ComfyUI\models: the Linux-made symlink (unreadable on Windows) becomes a directory
       junction to ..\models\comfy, which Windows, WSL and Linux all follow. The old link is
       renamed, not deleted.
    5. backend\data\comfy-windows.env records the venv, so `make start` finds it
    6. a check: CUDA visible, insightface imports

.EXAMPLE
  powershell -File scripts\install-comfyui-windows.ps1 -Venv E:\homepilot-envs\comfyui-win
#>
param(
  [string]$Venv = '',
  [switch]$Auto,
  [string]$PythonVersion = '3.11',
  [string]$TorchSpec = 'torch==2.12.1 torchvision==0.27.1 torchaudio==2.11.0',
  [string]$TorchIndex = 'https://download.pytorch.org/whl/cu130'
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$ComfyDir = Join-Path $Root 'ComfyUI'
$ModelsTarget = Join-Path $Root 'models\comfy'

function Step($n, $text) { Write-Host "`n[$n/6] $text" -ForegroundColor Cyan }
function Skip($why) {
  # -Auto (make install): never fail the whole install; the Linux ComfyUI keeps working.
  if ($Auto) { Write-Host "  ⚠  Windows-native ComfyUI skipped: $why" -ForegroundColor Yellow; Write-Host '     ComfyUI stays in Linux. Fix the above, then: make install-comfyui-windows'; exit 0 }
  throw $why
}
$NeedGB = 8
function Run([string]$exe, [string[]]$argv) {
  & $exe @argv
  if ($LASTEXITCODE -ne 0) { throw "failed ($LASTEXITCODE): $exe $($argv -join ' ')" }
}

if (-not (Test-Path (Join-Path $ComfyDir 'main.py'))) { Skip "ComfyUI not found at $ComfyDir" }
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { Skip "Windows Python launcher (py) not found; install Python $PythonVersion for Windows" }

# Choose where the venv lives (an existing record wins, so re-runs reuse it).
$envFile = Join-Path $Root 'backend\data\comfy-windows.env'
if (-not $Venv -and (Test-Path $envFile)) {
  $line = Get-Content $envFile | Where-Object { $_ -like 'COMFY_WIN_VENV=*' } | Select-Object -First 1
  if ($line) { $Venv = $line.Substring('COMFY_WIN_VENV='.Length).Trim().Trim("'").Trim('"') }
}
if (-not $Venv) {
  $drives = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -gt 0 -and $_.Root -match '^[A-Z]:\\$' }
  $c = $drives | Where-Object { $_.Name -eq 'C' }
  if ($c -and $c.Free / 1GB -ge ($NeedGB + 4)) {
    $Venv = Join-Path $env:LOCALAPPDATA 'HomePilot\comfyui-win'
  } else {
    $best = $drives | Sort-Object Free -Descending | Select-Object -First 1
    if (-not $best -or $best.Free / 1GB -lt $NeedGB) {
      Skip ("no Windows drive has {0} GB free (largest: {1}: {2:N1} GB). Free space, or set COMFY_WIN_VENV" -f $NeedGB, $best.Name, ($best.Free / 1GB))
    }
    $Venv = Join-Path $best.Root 'homepilot-envs\comfyui-win'
  }
}
Write-Host "Windows-native ComfyUI environment: $Venv"

# pip's download cache and build temp default to C: (%LOCALAPPDATA%\pip, %TEMP%); torch alone is
# ~3 GB through both. Keep them on the venv's drive so a nearly full C: is never filled.
$Work = Join-Path (Split-Path $Venv) '.homepilot-cache'
$env:PIP_CACHE_DIR = Join-Path $Work 'pip'
$env:TEMP = Join-Path $Work 'tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:PIP_CACHE_DIR, $env:TEMP | Out-Null
Write-Host "pip cache and build temp: $Work"

# Some requirements are git URLs (Impact Pack -> sam2). On a drive that records no file owners
# (exFAT/FAT32), git refuses the checkout as "dubious ownership". Trust pip's build folders for
# this process only, through git's environment config — the user's global git config is untouched.
$env:GIT_CONFIG_COUNT = '1'
$env:GIT_CONFIG_KEY_0 = 'safe.directory'
$env:GIT_CONFIG_VALUE_0 = '*'

Step 0 'WSL mirrored networking'
$wslcfg = Join-Path $env:USERPROFILE '.wslconfig'
$cfg = if (Test-Path $wslcfg) { Get-Content $wslcfg -Raw } else { '' }
if ($cfg -match '(?im)^\s*networkingMode\s*=\s*mirrored\s*$') {
  Write-Host '  already mirrored'
} else {
  if (Test-Path $wslcfg) { Copy-Item $wslcfg "$wslcfg.homepilot-backup" -Force; Write-Host "  backed up to $wslcfg.homepilot-backup" }
  if ($cfg -match '(?im)^\s*networkingMode\s*=') {
    $cfg = [regex]::Replace($cfg, '(?im)^\s*networkingMode\s*=.*$', 'networkingMode=mirrored')
  } elseif ($cfg -match '(?im)^\s*\[wsl2\]\s*$') {
    $cfg = [regex]::Replace($cfg, '(?im)^(\s*\[wsl2\]\s*)$', "`$1`r`nnetworkingMode=mirrored")
  } else {
    $cfg = ($cfg.TrimEnd() + "`r`n`r`n[wsl2]`r`nnetworkingMode=mirrored`r`n").TrimStart()
  }
  Set-Content -Path $wslcfg -Value $cfg -Encoding ascii
  Write-Host "  set networkingMode=mirrored in $wslcfg"
  Write-Host '  ⚠  Takes effect after WSL restarts: close WSL work, then run  wsl --shutdown  in Windows.' -ForegroundColor Yellow
}

Step 1 "Python $PythonVersion venv at $Venv"
$Py = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $Py)) {
  New-Item -ItemType Directory -Force (Split-Path $Venv) | Out-Null
  Run 'py' @("-$PythonVersion", '-m', 'venv', $Venv)
}
Run $Py @('-m', 'pip', 'install', '--upgrade', 'pip', 'wheel', 'setuptools')

Step 2 "PyTorch ($TorchSpec) from $TorchIndex"
Run $Py (@('-m', 'pip', 'install') + ($TorchSpec -split '\s+') + @('--index-url', $TorchIndex))

Step 3 'ComfyUI and custom-node requirements'
Run $Py @('-m', 'pip', 'install', '-r', (Join-Path $ComfyDir 'requirements.txt'))
Get-ChildItem (Join-Path $ComfyDir 'custom_nodes') -Directory | ForEach-Object {
  $req = Join-Path $_.FullName 'requirements.txt'
  if (Test-Path $req) {
    Write-Host "  - $($_.Name)"
    Run $Py @('-m', 'pip', 'install', '-r', $req)
  }
}

Step 4 "ComfyUI\models -> $ModelsTarget (junction)"
$Models = Join-Path $ComfyDir 'models'
$item = Get-Item $Models -Force -ErrorAction SilentlyContinue
if ($item -and $item.LinkType -eq 'Junction') {
  Write-Host '  already a junction'
} elseif (Test-Path $ModelsTarget) {
  if ($item) {
    $backup = "$Models.linux-link-backup"
    if (Test-Path $backup) { Remove-Item $backup -Force }
    Rename-Item -LiteralPath $Models -NewName (Split-Path $backup -Leaf)
    Write-Host "  old link kept as $backup"
  }
  New-Item -ItemType Junction -Path $Models -Target $ModelsTarget | Out-Null
  Write-Host '  junction created'
} else {
  Write-Host "  $ModelsTarget not found; leaving ComfyUI\models as it is"
}

Step 5 'Recording the environment for make start'
New-Item -ItemType Directory -Force (Split-Path $envFile) | Out-Null
# Read by bash (scripts/start-comfyui.sh): LF line endings, and the path single-quoted so
# its backslashes survive.
$envText = "# Written by scripts/install-comfyui-windows.ps1. Delete this file to run ComfyUI in Linux again.`nCOMFY_WIN_VENV='$Venv'`n"
[IO.File]::WriteAllText($envFile, $envText, [Text.Encoding]::ASCII)
Write-Host "  $envFile"

Step 6 'Checking CUDA and insightface'
Run $Py @('-c', "import torch, insightface, onnxruntime; print('torch', torch.__version__, '| CUDA', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-'); print('insightface', insightface.__version__, '| onnxruntime', onnxruntime.__version__)")

Write-Host "`nDone. make start will run ComfyUI natively on Windows (after WSL has restarted with mirrored networking)." -ForegroundColor Green

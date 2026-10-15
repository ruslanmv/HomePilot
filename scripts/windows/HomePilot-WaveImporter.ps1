<#
.SYNOPSIS
HomePilot Insta360 Wave Importer: copies finished recordings from an Insta360 Wave in USB
File Transfer mode into a folder that HomePilot's Folder Sync watches.

.DESCRIPTION
The Wave keeps every recording on its own 32 GB storage and shows that storage to Windows as a
removable drive while it is in Settings > USB Mode > File Transfer. HomePilot usually runs in
WSL or Docker, which do not see removable drives that appear after start-up, so this small
Windows-side watcher bridges the gap:

  Wave (File Transfer mode) -> this importer -> inbox folder -> HomePilot Folder Sync
      -> meeting in the library -> transcript, summary, insights, visual summary

It is read-only towards the device: it never deletes, renames or writes anything there. Each
recording is copied once (a fingerprint file remembers what was imported, and the inbox itself
is checked too, so a lost state file does not create duplicates). A recording is copied only
when it is complete: the recorder's record_info.json says it ended and the files have stopped
changing. Copies go to a temporary name first and are verified by hash before they get their
final name, so HomePilot never sees a half-written recording.

Two layouts are understood, because the on-device layout differs between Insta360 recorders:
  * AIRecord folders: <name>\.airecord_data\record_info.json beside the audio (the Insta360
    Link Controller layout, which HomePilot already parses);
  * loose audio files (mp3, wav, m4a, ...) with optional sidecars of the same name (.json,
    .txt, .srt, .vtt, .lrc).

.PARAMETER Inbox
Where recordings are copied. Connect this folder in HomePilot's Folder Sync (as a Windows path;
under WSL it is /mnt/c/...). Default: %USERPROFILE%\HomePilot\WaveInbox

.PARAMETER DeviceRoot
Skip detection and treat this folder or drive as the device (for tests, or when detection
fails). Example: E:\

.PARAMETER UsbVendorId
USB vendor id of the device to detect. The Insta360 Wave enumerates as USB\VID_18F0. Detection
walks disk -> partition -> drive letter, so it does not depend on the drive letter or label.

.PARAMETER DeviceLabel
Optional volume label to accept as the device as well (fallback when the vendor id is hidden
behind a USB bridge).

.PARAMETER HomePilotUrl / SyncSourceId
Optional. When both are set, a "Sync now" request is sent to HomePilot after new copies, so the
import starts immediately instead of at the next Folder Sync check.

.PARAMETER Install / Uninstall
Register (or remove) a per-user scheduled task that starts this importer at logon and keeps it
running in the background. No administrator rights are needed.

.PARAMETER Once
Run one detection/copy cycle and exit (used by the tests and by cron-like callers).

.PARAMETER Status
Print what was imported so far and whether a device is visible now, then exit.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\windows\HomePilot-WaveImporter.ps1 -Once
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\windows\HomePilot-WaveImporter.ps1 -Install -HomePilotUrl http://127.0.0.1:8000 -SyncSourceId <id>
#>
[CmdletBinding()]
param(
    [string]$Inbox = (Join-Path $env:USERPROFILE 'HomePilot\WaveInbox'),
    [string]$DeviceRoot = '',
    [string]$UsbVendorId = '18F0',
    [string]$DeviceLabel = '',
    [int]$IntervalSeconds = 20,
    [int]$StabilitySeconds = 15,
    [string]$StateFile = (Join-Path $env:LOCALAPPDATA 'HomePilot\wave-importer\state.json'),
    [string]$LogFile = (Join-Path $env:LOCALAPPDATA 'HomePilot\wave-importer\importer.log'),
    [string]$HomePilotUrl = '',
    [string]$SyncSourceId = '',
    [switch]$Once,
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$Status
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$script:AudioExtensions = @('.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.wma', '.webm')
$script:SidecarExtensions = @('.json', '.txt', '.srt', '.vtt', '.lrc', '.md')
$script:SkipDirs = @('System Volume Information', '$RECYCLE.BIN', 'LOST.DIR', 'Android', 'firmware', 'Firmware', 'update', 'UPDATE', '.Trashes', '.Spotlight-V100')
$script:TaskName = 'HomePilot Wave Importer'
$script:TaskPath = '\HomePilot\'
$script:LastWaitMessage = ''

# ── logging ──────────────────────────────────────────────────────────────────

function Write-Log {
    param([ValidateSet('INFO', 'WARN', 'ERROR', 'DEBUG')][string]$Level, [string]$Message)
    $line = '{0} {1,-5} {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    try {
        $dir = Split-Path -Parent $LogFile
        if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        Add-Content -Path $LogFile -Value $line -Encoding UTF8
    } catch { }
    if ($Level -eq 'ERROR') { Write-Host $line -ForegroundColor Red }
    elseif ($Level -eq 'WARN') { Write-Host $line -ForegroundColor Yellow }
    elseif ($Level -eq 'DEBUG') { Write-Verbose $line }
    else { Write-Host $line }
}

# ── state ────────────────────────────────────────────────────────────────────

function Get-ImporterState {
    $state = @{ imported = @{}; failures = @{}; lastRun = $null }
    if (Test-Path $StateFile) {
        try {
            $raw = Get-Content $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($raw.imported) {
                foreach ($p in $raw.imported.PSObject.Properties) {
                    $state.imported[$p.Name] = @{
                        source = [string]$p.Value.source; dest = [string]$p.Value.dest; kind = [string]$p.Value.kind
                        bytes = [long]$p.Value.bytes; importedAt = [string]$p.Value.importedAt
                    }
                }
            }
            if ($raw.PSObject.Properties['failures'] -and $raw.failures) {
                foreach ($p in $raw.failures.PSObject.Properties) { $state.failures[$p.Name] = [int]$p.Value }
            }
            if ($raw.PSObject.Properties['lastRun']) { $state.lastRun = $raw.lastRun }
        } catch {
            Write-Log WARN ("State file could not be read, starting with an empty one ({0}). The inbox is still checked for duplicates." -f $_.Exception.Message)
        }
    }
    return $state
}

function Save-ImporterState([hashtable]$State) {
    $dir = Split-Path -Parent $StateFile
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $State.lastRun = (Get-Date).ToString('o')
    $tmp = "$StateFile.tmp"
    ($State | ConvertTo-Json -Depth 6) | Set-Content -Path $tmp -Encoding UTF8
    Move-Item -Path $tmp -Destination $StateFile -Force
}

# ── device detection ─────────────────────────────────────────────────────────

function Find-DeviceRoots {
    <# Drive roots that belong to the Wave. By explicit path, else by USB vendor id through
       the disk -> partition -> logical-disk chain (no administrator rights needed), else by
       volume label. Returns an array of objects {Root, Rule}. #>
    $found = @()
    if ($DeviceRoot) {
        if (Test-Path -LiteralPath $DeviceRoot -PathType Container) { $found += [pscustomobject]@{ Root = (Resolve-Path -LiteralPath $DeviceRoot).Path; Rule = 'DeviceRoot' } }
        return $found
    }
    try {
        $disks = Get-CimInstance Win32_DiskDrive -ErrorAction Stop | Where-Object { $_.PNPDeviceID -match ('VID_' + [regex]::Escape($UsbVendorId)) }
        foreach ($disk in $disks) {
            $parts = Get-CimAssociatedInstance -InputObject $disk -ResultClassName Win32_DiskPartition -ErrorAction SilentlyContinue
            foreach ($part in $parts) {
                $logical = Get-CimAssociatedInstance -InputObject $part -ResultClassName Win32_LogicalDisk -ErrorAction SilentlyContinue
                foreach ($ld in $logical) {
                    if ($ld.DeviceID) { $found += [pscustomobject]@{ Root = ($ld.DeviceID + '\'); Rule = ('USB VID_' + $UsbVendorId + ' (' + $disk.Model + ')') } }
                }
            }
        }
    } catch {
        Write-Log DEBUG ("Disk enumeration failed: {0}" -f $_.Exception.Message)
    }
    if ($DeviceLabel) {
        try {
            Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=2' -ErrorAction Stop | Where-Object { $_.VolumeName -eq $DeviceLabel } | ForEach-Object {
                if (-not ($found | Where-Object { $_.Root -eq ($_.DeviceID + '\') })) { $found += [pscustomobject]@{ Root = ($_.DeviceID + '\'); Rule = ('label "' + $DeviceLabel + '"') } }
            }
        } catch { }
    }
    return $found
}

# ── discovery ────────────────────────────────────────────────────────────────

function Test-SkippedDir([System.IO.DirectoryInfo]$Dir) {
    if ($script:SkipDirs -contains $Dir.Name) { return $true }
    if ($Dir.Name.StartsWith('.') -or ($Dir.Attributes -band [IO.FileAttributes]::System)) { return $true }
    return $false
}

function Get-Recordings([string]$Root) {
    <# Candidates on the device: AIRecord folders first, then loose audio files anywhere else,
       each with its sidecars. Hidden and system folders, firmware folders and files that are
       still being written (.tmp/.part) are left alone. #>
    $out = @()
    $airecordDirs = @()
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue([pscustomobject]@{ Dir = (Get-Item -LiteralPath $Root); Depth = 0 })
    while ($queue.Count -gt 0) {
        $item = $queue.Dequeue()
        $dir = $item.Dir
        if ($item.Depth -gt 0 -and (Test-SkippedDir $dir)) { continue }
        $info = Join-Path (Join-Path $dir.FullName '.airecord_data') 'record_info.json'
        if ($item.Depth -gt 0 -and (Test-Path -LiteralPath $info -PathType Leaf)) { $airecordDirs += $dir; continue }
        $children = @()
        try { $children = @(Get-ChildItem -LiteralPath $dir.FullName -Force -ErrorAction Stop) } catch { Write-Log WARN ("Cannot list {0}: {1}" -f $dir.FullName, $_.Exception.Message); continue }
        foreach ($child in $children) {
            if ($child.PSIsContainer) {
                if ($item.Depth -lt 5) { $queue.Enqueue([pscustomobject]@{ Dir = $child; Depth = $item.Depth + 1 }) }
                continue
            }
            if ($child.Name.StartsWith('.') -or $child.Name.StartsWith('~$')) { continue }
            if ($child.Attributes -band [IO.FileAttributes]::System) { continue }
            $ext = $child.Extension.ToLowerInvariant()
            if ($ext -in @('.tmp', '.part', '.partial', '.download', '.crdownload')) { continue }
            if ($script:AudioExtensions -contains $ext) {
                $stem = [IO.Path]::GetFileNameWithoutExtension($child.Name)
                $sidecars = @($children | Where-Object { -not $_.PSIsContainer -and $_.FullName -ne $child.FullName -and [IO.Path]::GetFileNameWithoutExtension($_.Name) -eq $stem -and ($script:SidecarExtensions -contains $_.Extension.ToLowerInvariant()) })
                $out += [pscustomobject]@{
                    Kind = 'audio'; Name = $child.Name; Path = $child.FullName; AudioPath = $child.FullName
                    Files = @($child) + $sidecars; Info = $null
                }
            }
        }
    }
    foreach ($dir in $airecordDirs) {
        $files = @(Get-ChildItem -LiteralPath $dir.FullName -Recurse -File -Force -ErrorAction SilentlyContinue)
        $audio = @($files | Where-Object { $_.DirectoryName -eq $dir.FullName -and ($script:AudioExtensions -contains $_.Extension.ToLowerInvariant()) } | Sort-Object Length -Descending)
        $info = $null
        try { $info = Get-Content -LiteralPath (Join-Path (Join-Path $dir.FullName '.airecord_data') 'record_info.json') -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $info = $null }
        $out += [pscustomobject]@{
            Kind = 'airecord'; Name = $dir.Name; Path = $dir.FullName
            AudioPath = $(if ($audio.Count -gt 0) { $audio[0].FullName } else { $null })
            Files = $files; Info = $info
        }
    }
    return $out
}

# ── completeness, fingerprints ───────────────────────────────────────────────

function Get-Snapshot($Candidate) {
    $bytes = 0; $latest = [datetime]::MinValue
    foreach ($f in $Candidate.Files) { $bytes += $f.Length; if ($f.LastWriteTimeUtc -gt $latest) { $latest = $f.LastWriteTimeUtc } }
    return ('{0}:{1}' -f $bytes, $latest.Ticks)
}

function Test-Complete($Candidate, [hashtable]$Seen) {
    <# True when the recorder says the recording ended and nothing changed for StabilitySeconds. #>
    if (-not $Candidate.AudioPath) { return $false, 'no audio file yet' }
    if ($Candidate.Kind -eq 'airecord') {
        if ($null -eq $Candidate.Info) { return $false, 'record_info.json not readable yet' }
        $ended = 0; $duration = 0
        try { $ended = [double]$Candidate.Info.endTime } catch { }
        try { $duration = [double]$Candidate.Info.duration } catch { }
        if ($ended -le 0 -and $duration -le 0) { return $false, 'recording has not ended (no endTime/duration)' }
    }
    try {
        $fs = [IO.File]::Open($Candidate.AudioPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        $fs.Close()
    } catch { return $false, 'audio file is still in use' }
    $snap = Get-Snapshot $Candidate
    $now = Get-Date
    if (-not $Seen.ContainsKey($Candidate.Path) -or $Seen[$Candidate.Path].snap -ne $snap) {
        $Seen[$Candidate.Path] = @{ snap = $snap; since = $now }
        if ($StabilitySeconds -gt 0) { return $false, 'waiting for the files to stop changing' }
    }
    if (($now - $Seen[$Candidate.Path].since).TotalSeconds -lt $StabilitySeconds) { return $false, 'waiting for the files to stop changing' }
    $age = ($now.ToUniversalTime() - (Get-Item -LiteralPath $Candidate.AudioPath).LastWriteTimeUtc).TotalSeconds
    if ($age -lt $StabilitySeconds) { return $false, 'audio file was written moments ago' }
    return $true, ''
}

function Get-Fingerprint($Candidate) {
    if ($Candidate.Kind -eq 'airecord' -and $Candidate.Info) {
        $id = ''
        try { $id = [string]$Candidate.Info.localMeetingId } catch { }
        if ($id -and $id.ToLowerInvariant() -ne 'none') { return 'airecord:' + $id.Trim() }
    }
    $hash = (Get-FileHash -LiteralPath $Candidate.AudioPath -Algorithm SHA256).Hash.ToLowerInvariant()
    return 'sha256:' + $hash
}

function Get-SafeName([string]$Name) {
    $invalid = [IO.Path]::GetInvalidFileNameChars()
    $chars = $Name.ToCharArray() | ForEach-Object { if ($invalid -contains $_) { '_' } else { $_ } }
    $clean = (-join $chars).Trim().TrimEnd('.')
    if (-not $clean) { $clean = 'recording' }
    return $clean
}

function Find-InInbox($Candidate, [string]$Fingerprint) {
    <# A copy that is already in the inbox with the same recording (same recorder id, or the
       same audio hash), so a lost state file never produces a duplicate. #>
    if (-not (Test-Path -LiteralPath $Inbox)) { return $null }
    $wantHash = $null
    if ($Fingerprint.StartsWith('sha256:')) { $wantHash = $Fingerprint.Substring(7) }
    foreach ($entry in @(Get-ChildItem -LiteralPath $Inbox -Force -ErrorAction SilentlyContinue)) {
        if ($entry.Name.EndsWith('.partial') -or $entry.Name.EndsWith('.part')) { continue }
        if ($entry.PSIsContainer) {
            $info = Join-Path (Join-Path $entry.FullName '.airecord_data') 'record_info.json'
            if ($Fingerprint.StartsWith('airecord:') -and (Test-Path -LiteralPath $info)) {
                try { $id = [string]((Get-Content -LiteralPath $info -Raw -Encoding UTF8 | ConvertFrom-Json).localMeetingId); if (('airecord:' + $id.Trim()) -eq $Fingerprint) { return $entry.FullName } } catch { }
            }
            if ($wantHash) {
                foreach ($f in @(Get-ChildItem -LiteralPath $entry.FullName -File -ErrorAction SilentlyContinue | Where-Object { $script:AudioExtensions -contains $_.Extension.ToLowerInvariant() })) {
                    if ((Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -eq $wantHash) { return $entry.FullName }
                }
            }
        } elseif ($wantHash -and ($script:AudioExtensions -contains $entry.Extension.ToLowerInvariant()) -and $entry.Length -eq (Get-Item -LiteralPath $Candidate.AudioPath).Length) {
            if ((Get-FileHash -LiteralPath $entry.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -eq $wantHash) { return $entry.FullName }
        }
    }
    return $null
}

# ── copying ──────────────────────────────────────────────────────────────────

function Get-FreeName([string]$Base, [string]$Extension) {
    $candidate = Join-Path $Inbox ($Base + $Extension)
    $n = 2
    while (Test-Path -LiteralPath $candidate) { $candidate = Join-Path $Inbox ('{0} ({1}){2}' -f $Base, $n, $Extension); $n++ }
    return $candidate
}

function Copy-Recording($Candidate, [string]$Fingerprint) {
    <# Copy to a temporary name, verify the audio hash, then give it its final name. Returns
       the final path. Throws on any failure, leaving nothing under the final name. #>
    if (-not (Test-Path -LiteralPath $Inbox)) { New-Item -ItemType Directory -Path $Inbox -Force | Out-Null }
    $sourceHash = (Get-FileHash -LiteralPath $Candidate.AudioPath -Algorithm SHA256).Hash
    if ($Candidate.Kind -eq 'airecord') {
        $final = Get-FreeName (Get-SafeName $Candidate.Name) ''
        $tmp = $final + '.partial'
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force }
        New-Item -ItemType Directory -Path $tmp -Force | Out-Null
        foreach ($f in $Candidate.Files) {
            $rel = $f.FullName.Substring($Candidate.Path.Length).TrimStart('\')
            $dest = Join-Path $tmp $rel
            $destDir = Split-Path -Parent $dest
            if (-not (Test-Path -LiteralPath $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
            Copy-Item -LiteralPath $f.FullName -Destination $dest -Force
        }
        $copiedAudio = Join-Path $tmp ($Candidate.AudioPath.Substring($Candidate.Path.Length).TrimStart('\'))
        if ((Get-FileHash -LiteralPath $copiedAudio -Algorithm SHA256).Hash -ne $sourceHash) { Remove-Item -LiteralPath $tmp -Recurse -Force; throw 'copied audio does not match the device (hash mismatch)' }
        Move-Item -LiteralPath $tmp -Destination $final
        return $final
    }
    $audio = Get-Item -LiteralPath $Candidate.AudioPath
    $base = Get-SafeName ([IO.Path]::GetFileNameWithoutExtension($audio.Name))
    $final = Get-FreeName $base $audio.Extension
    $finalBase = [IO.Path]::GetFileNameWithoutExtension($final)
    $tmp = $final + '.part'
    Copy-Item -LiteralPath $audio.FullName -Destination $tmp -Force
    if ((Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash -ne $sourceHash) { Remove-Item -LiteralPath $tmp -Force; throw 'copied audio does not match the device (hash mismatch)' }
    foreach ($f in $Candidate.Files) {
        if ($f.FullName -eq $audio.FullName) { continue }
        Copy-Item -LiteralPath $f.FullName -Destination (Join-Path $Inbox ($finalBase + $f.Extension)) -Force
    }
    Move-Item -LiteralPath $tmp -Destination $final
    return $final
}

function Invoke-HomePilotSync {
    if (-not $HomePilotUrl -or -not $SyncSourceId) { return }
    try {
        $url = '{0}/v1/meetingsense/sync-sources/{1}/scan' -f $HomePilotUrl.TrimEnd('/'), $SyncSourceId
        Invoke-RestMethod -Method Post -Uri $url -TimeoutSec 20 | Out-Null
        Write-Log INFO 'Asked HomePilot to sync the inbox now.'
    } catch {
        Write-Log WARN ("HomePilot sync request failed (it will pick the files up on its own schedule): {0}" -f $_.Exception.Message)
    }
}

# ── one cycle ────────────────────────────────────────────────────────────────

function Invoke-ImportCycle([hashtable]$State, [hashtable]$Seen) {
    $roots = @(Find-DeviceRoots)
    if ($roots.Count -eq 0) {
        $msg = 'No Insta360 Wave storage visible. Put the Wave in Settings > USB Mode > File Transfer while connected by USB-C.'
        if ($script:LastWaitMessage -ne $msg) { Write-Log INFO $msg; $script:LastWaitMessage = $msg }
        return 0
    }
    $script:LastWaitMessage = ''
    $copied = 0
    foreach ($root in $roots) {
        Write-Log DEBUG ("Device storage at {0} (matched by {1})" -f $root.Root, $root.Rule)
        $candidates = @()
        try { $candidates = @(Get-Recordings $root.Root) } catch { Write-Log ERROR ("Could not read {0}: {1}" -f $root.Root, $_.Exception.Message); continue }
        foreach ($c in $candidates) {
            $ok, $why = Test-Complete $c $Seen
            if (-not $ok) { Write-Log DEBUG ("Not yet: {0} ({1})" -f $c.Name, $why); continue }
            $fp = $null
            try { $fp = Get-Fingerprint $c } catch { Write-Log WARN ("Cannot fingerprint {0}: {1}" -f $c.Name, $_.Exception.Message); continue }
            if ($State.imported.ContainsKey($fp)) { continue }
            $existing = Find-InInbox $c $fp
            if ($existing) {
                Write-Log INFO ("Already in the inbox, recorded without copying again: {0} -> {1}" -f $c.Name, $existing)
                $State.imported[$fp] = @{ source = $c.Path; dest = $existing; kind = $c.Kind; bytes = (Get-Item -LiteralPath $c.AudioPath).Length; importedAt = (Get-Date).ToString('o') }
                Save-ImporterState $State
                continue
            }
            try {
                $dest = Copy-Recording $c $fp
                $State.imported[$fp] = @{ source = $c.Path; dest = $dest; kind = $c.Kind; bytes = (Get-Item -LiteralPath $c.AudioPath).Length; importedAt = (Get-Date).ToString('o') }
                if ($State.failures.ContainsKey($fp)) { $State.failures.Remove($fp) }
                Save-ImporterState $State
                $copied++
                Write-Log INFO ("Imported {0} -> {1}" -f $c.Name, $dest)
            } catch {
                $n = 1; if ($State.failures.ContainsKey($fp)) { $n = $State.failures[$fp] + 1 }
                $State.failures[$fp] = $n
                Save-ImporterState $State
                Write-Log ERROR ("Import of {0} failed (attempt {1}): {2}. It will be retried on the next cycle." -f $c.Name, $n, $_.Exception.Message)
            }
        }
    }
    if ($copied -gt 0) { Invoke-HomePilotSync }
    return $copied
}

# ── scheduled task ───────────────────────────────────────────────────────────

function Install-ImporterTask {
    $script = $PSCommandPath
    $args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', ('"{0}"' -f $script), '-Inbox', ('"{0}"' -f $Inbox),
              '-IntervalSeconds', $IntervalSeconds, '-StabilitySeconds', $StabilitySeconds)
    if ($DeviceRoot) { $args += @('-DeviceRoot', ('"{0}"' -f $DeviceRoot)) }
    if ($DeviceLabel) { $args += @('-DeviceLabel', ('"{0}"' -f $DeviceLabel)) }
    if ($HomePilotUrl -and $SyncSourceId) { $args += @('-HomePilotUrl', $HomePilotUrl, '-SyncSourceId', $SyncSourceId) }
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ($args -join ' ')
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $script:TaskName -TaskPath $script:TaskPath -Action $action -Trigger $trigger -Settings $settings -Description 'Copies finished Insta360 Wave recordings into the HomePilot inbox.' -Force | Out-Null
    Start-ScheduledTask -TaskName $script:TaskName -TaskPath $script:TaskPath
    Write-Log INFO ("Scheduled task '{0}{1}' registered and started. Inbox: {2}" -f $script:TaskPath, $script:TaskName, $Inbox)
}

function Uninstall-ImporterTask {
    try { Unregister-ScheduledTask -TaskName $script:TaskName -TaskPath $script:TaskPath -Confirm:$false -ErrorAction Stop; Write-Log INFO 'Scheduled task removed.' }
    catch { Write-Log WARN ("No scheduled task to remove ({0})." -f $_.Exception.Message) }
}

# ── entry point ──────────────────────────────────────────────────────────────

if ($Install) { Install-ImporterTask; exit 0 }
if ($Uninstall) { Uninstall-ImporterTask; exit 0 }

$state = Get-ImporterState
if ($Status) {
    $roots = @(Find-DeviceRoots)
    Write-Host ("Inbox:      {0}" -f $Inbox)
    Write-Host ("State file: {0}" -f $StateFile)
    Write-Host ("Imported:   {0} recording(s); last run {1}" -f $state.imported.Count, $(if ($state.lastRun) { $state.lastRun } else { 'never' }))
    if ($roots.Count -gt 0) { foreach ($r in $roots) { Write-Host ("Device:     {0} ({1})" -f $r.Root, $r.Rule) } } else { Write-Host 'Device:     not visible (File Transfer mode off, or not connected)' }
    foreach ($k in $state.imported.Keys) { Write-Host ("  - {0}  <-  {1}" -f $state.imported[$k].dest, $state.imported[$k].source) }
    exit 0
}

Write-Log INFO ("HomePilot Wave Importer starting. Inbox: {0}; device: {1}; every {2}s." -f $Inbox, $(if ($DeviceRoot) { $DeviceRoot } else { 'USB VID_' + $UsbVendorId }), $IntervalSeconds)
$seen = @{}
do {
    try { Invoke-ImportCycle $state $seen | Out-Null }
    catch { Write-Log ERROR ("Cycle failed: {0}" -f $_.Exception.Message) }
    if (-not $Once) { Start-Sleep -Seconds $IntervalSeconds }
} while (-not $Once)
exit 0

<#
.SYNOPSIS
Fixture test for HomePilot-WaveImporter.ps1: a fake Wave volume in %TEMP% with an AIRecord
folder, a loose recording with a sidecar, an unfinished recording and a system folder.

Checks: detection and copying (bit-exact), the unfinished recording is left alone, a second run
copies nothing, a lost state file still produces no duplicate, and a recording that finishes
later is picked up on the next run. Exit code 0 when every check passes.

Run:  powershell -ExecutionPolicy Bypass -File scripts\windows\Test-WaveImporter.ps1
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$importer = Join-Path $PSScriptRoot 'HomePilot-WaveImporter.ps1'
$work = Join-Path $env:TEMP ('hp-wave-test-' + [guid]::NewGuid().ToString('n').Substring(0, 8))
$device = Join-Path $work 'device'
$inbox = Join-Path $work 'inbox'
$state = Join-Path $work 'state.json'
$log = Join-Path $work 'importer.log'
$failures = 0

function Check([bool]$Condition, [string]$What) {
    if ($Condition) { Write-Host ("  ok   {0}" -f $What) -ForegroundColor Green }
    else { Write-Host ("  FAIL {0}" -f $What) -ForegroundColor Red; $script:failures++ }
}

function Write-Bytes([string]$Path, [int]$Count, [int]$Seed) {
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $rng = New-Object System.Random($Seed)
    $bytes = New-Object byte[] $Count
    $rng.NextBytes($bytes)
    [IO.File]::WriteAllBytes($Path, $bytes)
}

function Write-Text([string]$Path, [string]$Text) {
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Set-Content -LiteralPath $Path -Encoding UTF8 -Value $Text
}

function Run-Importer {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $importer -Once -DeviceRoot $device -Inbox $inbox -StateFile $state -LogFile $log -StabilitySeconds 0 -IntervalSeconds 1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "importer exited with $LASTEXITCODE" }
}

Write-Host "Fixture in $work"
# 1. A finished AIRecord recording (the Insta360 name keeps its U+2236 ratio characters).
$name = '2026_10_15 10' + [char]0x2236 + '00' + [char]0x2236 + '00'
$rec = Join-Path $device ('AIRecord\' + $name)
Write-Bytes (Join-Path $rec ($name + '.mp3')) 200000 1
Write-Bytes (Join-Path $rec '.airecord_data\asr_audio_slice\asr_audio_0.ogg') 3000 2
Write-Text (Join-Path $rec '.airecord_data\record_info.json') (@{
    meetingname = $name; username = 'default'; localMeetingId = '20261015_100000_001_TEST'; meetingId = 'none'
    startTime = 1792051200; endTime = 1792052400; duration = 1200000; project_type = 'record'; description = 'xxxx' } | ConvertTo-Json)
Write-Text (Join-Path $rec '.airecord_data\audio_asr_total.json') '{"SD_info":{"Labels":[],"Speaker_library":{},"Stamps":[]},"Result_info":[{"startTime":0,"endTime":4000,"speaker":"Ebony","text":"We decided to chain the DNS and MX checks."}]}'
# 2. A loose recording with a transcript sidecar.
Write-Bytes (Join-Path $device 'Recordings\2026-10-15 11-30-00.wav') 150000 3
Write-Text (Join-Path $device 'Recordings\2026-10-15 11-30-00.srt') "1`n00:00:01,000 --> 00:00:04,000`nHello from the loose recording.`n"
# 3. An unfinished AIRecord recording (no endTime, duration 0).
$open = Join-Path $device 'AIRecord\2026_10_15 12_00_00'
Write-Bytes (Join-Path $open '2026_10_15 12_00_00.mp3') 50000 4
Write-Text (Join-Path $open '.airecord_data\record_info.json') '{"meetingname":"2026_10_15 12_00_00","localMeetingId":"20261015_120000_002_TEST","startTime":1792058400,"endTime":0,"duration":0}'
# 4. Things that must be ignored.
Write-Bytes (Join-Path $device 'System Volume Information\IndexerVolumeGuid') 100 5
Write-Bytes (Join-Path $device 'firmware\PSP_1.3.0.6.bin') 100 6
Write-Bytes (Join-Path $device 'Recordings\half.mp3.part') 100 7

Write-Host 'Run 1: first import'
Run-Importer
$copiedRec = Join-Path $inbox $name
Check (Test-Path -LiteralPath (Join-Path $copiedRec ($name + '.mp3'))) 'AIRecord folder copied with its audio'
Check (Test-Path -LiteralPath (Join-Path $copiedRec '.airecord_data\record_info.json')) 'record_info.json travelled with it'
Check (Test-Path -LiteralPath (Join-Path $copiedRec '.airecord_data\audio_asr_total.json')) 'device transcript travelled with it'
Check ((Get-FileHash -LiteralPath (Join-Path $copiedRec ($name + '.mp3'))).Hash -eq (Get-FileHash -LiteralPath (Join-Path $rec ($name + '.mp3'))).Hash) 'audio copy is bit-exact'
Check (Test-Path -LiteralPath (Join-Path $inbox '2026-10-15 11-30-00.wav')) 'loose recording copied'
Check (Test-Path -LiteralPath (Join-Path $inbox '2026-10-15 11-30-00.srt')) 'its transcript sidecar copied'
Check (-not (Test-Path -LiteralPath (Join-Path $inbox '2026_10_15 12_00_00'))) 'unfinished recording left alone'
Check (-not (Test-Path -LiteralPath (Join-Path $inbox 'half.mp3'))) 'partial file ignored'
Check (-not (Test-Path -LiteralPath (Join-Path $inbox 'IndexerVolumeGuid'))) 'system folder ignored'
Check (((Get-ChildItem -LiteralPath $inbox -Force | Where-Object { $_.Name -like '*.partial' -or $_.Name -like '*.part' }) | Measure-Object).Count -eq 0) 'no temporary names left in the inbox'
$st = Get-Content $state -Raw | ConvertFrom-Json
Check (($st.imported.PSObject.Properties | Measure-Object).Count -eq 2) 'state records exactly two imports'
Check ($null -ne $st.imported.PSObject.Properties['airecord:20261015_100000_001_TEST']) 'AIRecord fingerprint is the recorder id'
Check (Test-Path -LiteralPath (Join-Path $device ('AIRecord\' + $name + '\' + $name + '.mp3'))) 'device files untouched'

Write-Host 'Run 2: nothing new'
$before = (Get-ChildItem -LiteralPath $inbox -Force | Measure-Object).Count
Run-Importer
Check (((Get-ChildItem -LiteralPath $inbox -Force | Measure-Object).Count) -eq $before) 'second run copies nothing'

Write-Host 'Run 3: state file lost'
Remove-Item -LiteralPath $state -Force
Run-Importer
Check (((Get-ChildItem -LiteralPath $inbox -Force | Measure-Object).Count) -eq $before) 'no duplicate after losing the state file'
$st = Get-Content $state -Raw | ConvertFrom-Json
Check (($st.imported.PSObject.Properties | Measure-Object).Count -eq 2) 'state rebuilt from the inbox'

Write-Host 'Run 4: the unfinished recording ends'
Write-Text (Join-Path $open '.airecord_data\record_info.json') '{"meetingname":"2026_10_15 12_00_00","localMeetingId":"20261015_120000_002_TEST","startTime":1792058400,"endTime":1792059000,"duration":600000}'
Run-Importer
Check (Test-Path -LiteralPath (Join-Path $inbox '2026_10_15 12_00_00\2026_10_15 12_00_00.mp3')) 'finished recording picked up on the next run'
$st = Get-Content $state -Raw | ConvertFrom-Json
Check (($st.imported.PSObject.Properties | Measure-Object).Count -eq 3) 'state now holds three imports'

Write-Host 'Run 5: status'
$status = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $importer -Status -DeviceRoot $device -Inbox $inbox -StateFile $state -LogFile $log
Check (($status -join "`n") -match 'Imported:\s+3 recording') 'status reports three imports'

Write-Host ("Log: {0}" -f $log)
Get-Content $log | Select-Object -Last 6 | ForEach-Object { "    $_" }
if ($failures -eq 0) { Remove-Item -LiteralPath $work -Recurse -Force; Write-Host 'All checks passed.' -ForegroundColor Green; exit 0 }
Write-Host ("{0} check(s) failed; fixture kept at {1}" -f $failures, $work) -ForegroundColor Red
exit 1

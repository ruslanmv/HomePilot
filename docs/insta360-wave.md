# Insta360 Wave → HomePilot

How recordings made with an Insta360 Wave reach the Meetings library on their own, and what
the research behind that choice found. The short version: the Wave keeps every recording on its
own storage and shows that storage to Windows as a drive in **File Transfer** mode; a small
Windows watcher copies finished recordings into an inbox folder; HomePilot's **Folder Sync**
does the rest (import, transcript, summary, insights, visual summary). Nothing leaves the
computer.

```
Insta360 Wave ──(USB-C, Settings › USB Mode › File Transfer)──▶ removable drive on Windows
      │
      ▼
HomePilot-WaveImporter.ps1  (Windows, read-only towards the device; copies finished recordings once)
      │
      ▼
%USERPROFILE%\HomePilot\WaveInbox   ──▶  HomePilot Folder Sync (WSL: /mnt/c/Users/<you>/HomePilot/WaveInbox)
      │
      ▼
Meeting in the library → transcript (device's own, or local speech-to-text) → summary → insights → Visual Summary
```

## What the research established (15 Oct 2026)

Verified on this computer and in Insta360's documentation:

- **Insta360 Wave Controller 1.1.0.3** (Arashi Vision Inc., Qt 6) is a device companion: it
  binds the Insta360 account, manages the device over USB HID (a MAVLink-style control
  protocol), updates firmware, and opens **InSight**. It keeps **no recordings on the PC** —
  its data folder (`%LOCALAPPDATA%\Insta360\Insta360 Wave Controller`) holds logs, caches and
  translations only. Its UI strings speak of "Cloud saved / Local saved", "Syncing…",
  "View recordings" (opens the web), "Failed to enter USB mode" and "Please exit file
  transfer mode and try again".
- **The device** enumerates as `USB\VID_18F0&PID_4E40` (USB audio + HID) with the instance id
  `PSP_<serial>`; the Controller's logs call it `PSP_Wave_<serial>`. **PSP is the Wave's
  internal code name**, so a firmware package named `PSP_1.3.0.6` is a Wave firmware; the
  Controller logs from 10 Oct show it offering device firmware 1.2.2.6 and a "model
  firmware" 3.0.0.1. No public release notes list 1.3.0.6.
- **Recordings live on the device**: "After recording, all audio files are saved locally on
  the device" (MP3 by default, WAV with Lossless Audio on). `Settings › USB Mode › File
  Transfer` exposes the storage to a computer. The on-device folder layout is **not
  documented**; the importer therefore accepts both plain audio files and the AIRecord layout
  (`<name>\.airecord_data\record_info.json`, `audio_asr_total.json`) that the Insta360 Link
  Controller's AI Recording writes and HomePilot already parses.
- **Cloud**: with Cloud Sync on, recordings upload to InSight (`insight.insta360.com`), where
  transcripts and summaries are generated. There is **no documented export or API** for
  InSight. Insta360's Open Platform API is "planned". The **Wave for Business API** is a
  device-control interface (power, start/stop recording, settings, real-time audio upload)
  obtained by contacting Insta360, not a recordings API.
- **No SDK**: the Insta360 developer documentation lists "Wave SDK — not yet available".
  X-series camera APIs (OSC over Wi-Fi, `DCIM/Camera01`) do not apply to the Wave.

Not verified (needs the device in File Transfer mode once): the exact folder and file names
on the Wave's storage, and whether the device's own transcript is stored beside the audio.

## Setup

1. **Allow the inbox for Folder Sync** (server side). In the HomePilot environment set
   `MEETINGS_LIBRARY_UPGRADE=1`, `MEETINGS_INTELLIGENCE=1` and
   `MEETINGS_SYNC_ALLOWED_ROOTS=/mnt/c/Users/<you>/HomePilot` (WSL) or
   `C:\Users\<you>\HomePilot` (native Windows). Restart HomePilot.
2. **Connect the inbox** in Meetings › Folder Sync: path `C:\Users\<you>\HomePilot\WaveInbox`,
   a display name such as "Insta360 Wave", and the project new meetings should belong to.
   Note the source id shown in the API or the page URL if you want immediate syncs (step 4).
3. **Install the importer** once, from a normal PowerShell (no administrator rights):

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\windows\HomePilot-WaveImporter.ps1 -Install
   ```

   This registers the scheduled task `\HomePilot\HomePilot Wave Importer` at logon and starts
   it. Add `-HomePilotUrl http://127.0.0.1:8000 -SyncSourceId <id>` to have it ask HomePilot to
   sync the inbox right after a copy instead of at the next 60-second check.
4. **Each time you want recordings imported**: connect the Wave by USB-C and switch it to
   `Settings › USB Mode › File Transfer`. Within about 20 seconds the importer copies every
   finished recording it has not seen before; HomePilot imports them on its next check.
   Switch the device back when done (it cannot record in File Transfer mode).

Useful commands:

```powershell
# one pass, verbose
powershell -ExecutionPolicy Bypass -File scripts\windows\HomePilot-WaveImporter.ps1 -Once -Verbose
# what was imported, is the device visible
powershell -ExecutionPolicy Bypass -File scripts\windows\HomePilot-WaveImporter.ps1 -Status
# remove the scheduled task
powershell -ExecutionPolicy Bypass -File scripts\windows\HomePilot-WaveImporter.ps1 -Uninstall
```

State lives in `%LOCALAPPDATA%\HomePilot\wave-importer\state.json`, the log beside it.

## What the importer guarantees

- **Read-only towards the device.** It never deletes, renames or writes there.
- **Complete recordings only.** An AIRecord folder is copied once `record_info.json` says the
  recording ended; any recording must have stopped changing for `-StabilitySeconds`
  (default 15) and must not be open for writing.
- **Once.** The fingerprint (the recorder's `localMeetingId`, else the SHA-256 of the audio) is
  remembered; a lost state file is rebuilt from the inbox, so a reinstall does not duplicate.
  HomePilot adds its own second line of defence (recorder id and content hash).
- **No half-written files.** Copies go to `*.partial` / `*.part` names, are verified by hash,
  then renamed. Folder Sync ignores temporary names.
- **Retries.** A failed copy is logged with the attempt count and retried on the next cycle.
  A device that disappears mid-copy leaves nothing under a final name.
- **Detection without drive letters.** The device is found through the USB vendor id
  (`VID_18F0`) via disk → partition → drive letter; `-DeviceLabel` and `-DeviceRoot` are the
  fallbacks.

## What HomePilot does with a recording

Folder Sync imports it as a **meeting** in the library, linked to the project chosen on the
source. The device's own transcript (`audio_asr_total.json`, speaker-labelled) is imported
when it has content; otherwise the recording is transcribed on this computer. Then the summary,
the typed analysis, the Executive Brief (Visual Summary tab) and the suggested questions are
produced automatically. With `MEETINGS_AUTO_TITLE` on (default) a title that is only a
timestamp or a recorder default is replaced by the analysis title once a model has analysed the
meeting; titles a person typed are never changed.

One meeting per recording, not one project per recording: a project in HomePilot groups
meetings, and the meeting page already holds the audio, transcript, summary, decisions,
actions, metadata and the assistant.

## Limitations and next steps

- **One manual step remains**: putting the Wave into File Transfer mode (and back). Insta360
  offers no supported way to read the storage in normal mode; the Controller switches the
  device to USB-disk mode for firmware updates over an undocumented HID protocol, which this
  integration deliberately does not drive.
- **No InSight import.** Cloud transcripts and summaries stay in InSight until Insta360 offers
  an export or API; HomePilot produces its own locally.
- **On-device layout unverified.** First connection in File Transfer mode: run `-Once -Verbose`
  and check the log for what was found; the adapter can be tightened once the layout is known.
- **Firmware 1.3.0.6.** Its File Transfer behaviour was not tested here.
- **Complete automation** would need either Insta360's device-control API (schedule-driven
  recording with real-time upload, enterprise programme) or an InSight API.

Tests: `scripts\windows\Test-WaveImporter.ps1` (fixture volume, 19 checks) and
`backend/tests/meetingsense/test_intelligence.py` (auto-title).

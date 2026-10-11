# Meetings Library

One place for every meeting: the ones HomePilot recorded live, project meetings,
recordings imported from an Insta360 / AIRecord device, audio files you upload,
transcripts with no audio, scheduled meetings still waiting for their recording, and
Teams rooms. It lives in the existing **Meetings** section and looks like **Projects**.

It is **additive and off by default**. With the flag unset, the Meetings section,
its catalog and every existing MeetingSense endpoint behave exactly as before.

![The Meetings library: tabs, search, sort, filters and one card per meeting](assets/meetings-library/library.jpg)

## Turning it on

| Setting | Default | What it does |
|---|---|---|
| `MEETINGS_LIBRARY_UPGRADE` | off | Shows the library in the Meetings section and enables its API. Turning it off again hides it; nothing is deleted. |
| `MEETINGS_LIBRARY_PROCESSING` | on | Background transcription, search indexing and summaries for imported recordings. |
| `MEETINGS_SYNC_ALLOWED_ROOTS` | empty | Folders the server may watch, separated by `;`. Empty means Folder Sync is off. |
| `MEETINGS_IMPORT_MAX_MB` | 2048 | Largest upload (per import). |
| `MEETINGS_STT_CHUNK_S` | 300 | Length of the audio pieces sent to the local speech model. |
| `MEETINGS_SYNC_INTERVAL_S` | 60 | How often a connected folder is checked. **Sync now** checks immediately. |
| `MEETINGS_SYNC_STABILITY_S` | 10 | A file must stop changing for this long before it is imported. |
| `MEETINGS_LIBRARY_DIR` | next to uploads | Where HomePilot keeps its own copies of imported files. |

```bash
# .env (HomePilot running in WSL, recorder files on D:\AIRecord)
MEETINGS_LIBRARY_UPGRADE=1
MEETINGS_SYNC_ALLOWED_ROOTS=/mnt/d/AIRecord
```

Restart the backend. **Meetings** in the sidebar now opens the library.
`MEETINGSENSE_ENABLED` is not required for imports. Live recording still needs it.

## Importing

**Import Files** accepts:

| What | Files |
|---|---|
| Insta360 / AIRecord | A recording folder, or a ZIP of one (the folder with `.airecord_data/record_info.json`) |
| Audio | `.mp3 .m4a .wav .ogg .opus .flac .aac .webm .mp4` |
| Transcripts | `.srt .vtt .txt .md .json` (Whisper JSON, `segments`/`utterances` lists, AIRecord `audio_asr_total.json`) |
| Several at once | A ZIP with any of the above |

Nothing is imported until you confirm the **preview**. For each meeting the preview
shows what was found, what will be done with it (import as new, attach to a scheduled
meeting, or skip), and anything unusual:

![Importing the Insta360 sample: silent recording, empty recorder transcript, inconsistent times](assets/meetings-library/import-airecord.jpg)

What the importer does with an AIRecord folder (checked against a real export):

- **The recorder's transcript is read, not trusted.** An empty `Result_info` means
  *needs transcription*, never "Transcribed".
- **A silent recording says so.** The audio's loudness is measured; a recording that never
  rises above −55 dB is marked *No speech* and is not sent to the speech model.
- **Times that disagree are reported, not hidden.** In the sample, the audio plays for
  7.68 s, `duration` says 7000 ms and the start/end times are 11 s apart. The playable
  length is used, and the original values are kept under **Properties → Original recorder metadata**.
- **The recorder's own names are kept**, including the `∶` (U+2236) characters in
  `2026_10_10 12∶31∶51`. The card title becomes "Imported meeting · Oct 10, 12:31",
  and a placeholder description such as `xxxx会议描述` is dropped.
- **Device working files** (`.airecord_data/asr_audio_slice/…`, `dot.txt`) are listed as
  "not imported".
- **No duplicates.** A meeting is recognised by the recorder's `localMeetingId` and by the
  SHA-256 of its audio, so importing the same ZIP, the same folder again, or the same
  files through Folder Sync reports *Already in your library* instead of making a copy.
- **ZIPs are opened safely**: no paths outside the archive, no links, and limits on entry
  count, total size and compression ratio.

Files are **copied** into HomePilot. The originals are never modified, moved or deleted.

## Folder Sync

**Folder Sync** watches a folder and imports finished recordings by itself, for example
the Insta360 app's `D:\AIRecord`.

![Folder Sync connected to D:\AIRecord: recordings already imported are not duplicated](assets/meetings-library/folder-sync.jpg)

- **The server reads the folder**, not the browser. Typing a path grants nothing: the folder
  must be inside `MEETINGS_SYNC_ALLOWED_ROOTS`, and anything else is refused with a reason.
- **Windows paths work under WSL.** `D:\AIRecord` is read as `/mnt/d/AIRecord`.
- **Where HomePilot runs matters.** HomePilot in WSL or natively on the same Windows
  computer as the recorder can watch its folder. A HomePilot server elsewhere (another
  computer, a container without that drive mounted) cannot see `D:\`. Upload the files
  with **Import Files** instead.
- **Only finished files.** A file is imported once its size and modification time have
  stayed the same for `MEETINGS_SYNC_STABILITY_S`. Files still being written are counted as
  *waiting*.
- **Once.** A file already imported (same recorder id or same content) is skipped, also
  after a rename or a move within the folder.
- **Read-only.** HomePilot never writes to, renames or deletes anything in the folder. If an
  original disappears, the meeting keeps HomePilot's copy and shows "original no longer in the folder".
- **Pause** stops watching; **Disconnect** forgets the folder and keeps its meetings.
- A recording that starts within 45 minutes of exactly one **scheduled** meeting is attached
  to it. With several candidates, it is imported on its own and you choose in the preview.

## Transcription and processing

Recordings are transcribed **on this computer** with the same local speech-to-text provider
MeetingSense uses (`get_meeting_stt_provider()`, local first, e.g. faster-whisper). Audio is
**never sent to a cloud service** by the library. If no local model is installed, the
recording is stored and marked *Needs setup*, with the install hint. **Retry** picks it up afterwards.

- Long recordings are decoded with FFmpeg in pieces (`MEETINGS_STT_CHUNK_S`) with a one-second
  overlap that is removed again, so a word on a boundary is neither lost nor doubled.
- While a live meeting is recording, imports wait, so the two never compete for the model.
- Each transcript is a **version**: imported, transcribed here, recorded live, or corrected by
  hand. **Correct** saves a new version; older versions stay and can be shown again.
- After a transcript arrives the meeting is indexed for search and a summary is written,
  but only if a language model answers. Without one, the meeting says *"No language model
  answered, so no summary was written"*. The Summary tab still keeps an outline assembled
  from the meeting's own words, labelled as such.

The **Processing** tab lists what is queued or running, with progress, **Cancel** and **Retry**.

## Meeting detail

![A meeting with its details panel](assets/meetings-library/detail.jpg)

The main column is the task at hand: **Overview** (recording, overview, key decisions,
transcript preview), **Transcript** (search, click a time to play from there, correct,
versions), **Actions**, and under **More**: Audio, Summary, AI Chat, Properties.

The right column holds supporting details: quick summary, action items, date, duration,
project(s), source, transcription state, participants and files.

- **Hide details / Show details** gives a focus view. The choice is remembered on this device.
- **Drag the panel's edge** to resize it (280–520 px), or focus the edge and use ← →.
- Below 1024 px the panel opens as a **drawer** over the page. Escape or × closes it and
  focus returns to the button.

![Focus view with details hidden](assets/meetings-library/detail-focus.jpg)

A recording transcribed here, with its waveform. Click a time in the transcript to play from it:

![A recording synced from a folder and transcribed locally](assets/meetings-library/detail-transcribed-here.jpg)

**AI Chat** answers only from this meeting. Without a language model it quotes the lines
that match the question, e.g. *"[00:00:20] I will send the updated cost estimate to the
finance team by Wednesday."*

**Export** downloads the transcript as Markdown, text, SRT, VTT or JSON, and **Download**
gives the recording itself (streamed with byte ranges, so seeking a long file is instant).

**Remove from library** hides a meeting and keeps its data. **Delete meeting data…** deletes
HomePilot's copies. Neither touches originals in a synced folder.

## Start a meeting

**New Meeting** opens a four-step wizard: **Setup** (title, project, now or later),
**Recording** (HomePilot Live, External Recorder or Hybrid, plus what to capture),
**Assistant** (note taker, participant, presenter…) and **Summary** (what to produce, and how long).

![Start a meeting: recording source](assets/meetings-library/wizard-recording.jpg)

- **Nothing records until Start meeting**, and only after the consent line is ticked.
- *Schedule for later* creates the meeting in the library right away. Its recording is
  added by upload or Folder Sync and matched by time.
- *External Recorder* creates the meeting and waits for the device's file.
- *Hybrid* records in HomePilot now; the device's file is imported as its own recording.

## On a phone

The grid becomes one column, header actions become icon buttons (with their names for
screen readers), the tabs fit on one line and the details open as a drawer.

![Library, meeting and details drawer on a phone](assets/meetings-library/phone.jpg)

## Projects and permissions

A meeting can belong to several projects. The project shown on a card is its first one,
and **Details → Project → ✎** changes them. Meetings recorded inside a project appear
under **Project Meetings** as before. Imported meetings belong to the account that imported
them; other accounts on the same HomePilot do not see them.

## API

All routes are under `/v1/meetingsense/` and answer `404`/`403` with
`{"detail": {"code", "message", "hint"}}` when the flag is off or access is not allowed.
Existing MeetingSense routes are unchanged.

| Route | |
|---|---|
| `GET library/status` | Always answers: enabled, sync, ffmpeg, local STT |
| `GET library` | List with `tab`, `q`, `source`, `project_id`, `state`, `from`, `to`, `sort`, `cursor` |
| `GET/PATCH/DELETE library/item/{id}` | One meeting, edit title/category/description, remove or delete |
| `PUT library/item/{id}/projects` | Project links |
| `POST library/meetings` | A scheduled meeting |
| `POST imports/preview`, `POST imports`, `GET imports/{id}` | Preview, commit (idempotent), status |
| `GET/POST sync-sources`, `POST sync-sources/{id}/scan`, `PATCH/DELETE sync-sources/{id}` | Folder Sync |
| `GET jobs`, `POST jobs/{id}/cancel`, `POST jobs/{id}/retry` | Processing |
| `POST library/item/{id}/transcriptions`, `…/summarize`, `…/ask` | Transcribe again, summarise, ask |
| `GET/POST library/item/{id}/versions`, `POST …/versions/{vid}/publish` | Transcript versions |
| `GET library/item/{id}/transcript?fmt=txt\|md\|srt\|vtt\|json` | Export |
| `GET library/item/{id}/media/{asset}`, `…/peaks` | Recording (range requests) and waveform |

## Storage

New tables sit beside MeetingSense's (`ms_library_entries`, `_sources`, `_assets`, `_imports`,
`_jobs`, `ms_meeting_project_links`, `ms_library_origin_links`, `ms_transcript_versions`,
`ms_transcript_version_segments`, `ms_library_sync_seen`). `ms_meetings` remains the record
of a meeting; existing rows are never rewritten, and existing project meetings are linked to
their project when the tables are first created.

**Rolling back** is turning `MEETINGS_LIBRARY_UPGRADE` off. The tables and copied files stay
until you remove them, so turning it on again brings everything back.

## Limits

- Speaker names come from the transcript; a recording transcribed here shows
  "Speaker unknown" until it is corrected (no diarisation yet).
- Summaries, decisions and action items need a language model. AI Chat without one quotes
  the transcript.
- A Hybrid meeting's second recording is imported as its own meeting, not merged.
- Teams rooms appear in the library read-only; they open in Teams.
- The desktop app's native folder picker is optional (`window.homepilot.meetings.pickFolder`);
  without it, type the path.

## Tests

- Backend: `backend/tests/meetingsense/test_library.py` covers the flag, AIRecord ZIP/folder
  import, silent audio, timing warnings, duplicates, transcript formats, chunked local
  transcription, needs-setup, range streaming, unsafe ZIPs, the unified list, scheduled
  matching, versions and export, WSL paths and allowed roots, folder sync (once, read-only,
  waiting files, disconnect), summaries without a model, and Ask without a model.
- Frontend: `frontend/src/test/meetingsLibrary.test.tsx` covers status chips, summary
  selection and rendering, waveform resampling, the library grid and tabs, the details
  panel (hide, remember, resize), and the wizard (title required, schedules without recording).

The screenshots use demo meetings. *Budget review* is a synthesized two-voice recording that
was synced from a folder and transcribed locally. The import screenshot is the real Insta360
sample.

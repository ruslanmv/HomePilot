# Batch 2 — Audio as Ground Truth, and Real Captions

**Status:** design only — no implementation in this batch document.
**Depends on:** Batch 0 (`existing_audio_url` on the request; essay text available as `EssaySource`).
**Proves:** scene durations come from the real narration audio, not guesses; captions populate automatically.

---

## 1. Forced alignment

New dependency: **WhisperX** (Whisper + wav2vec2 alignment; Montreal Forced Aligner is a fine alternative if a non-Python toolchain is preferred). Given the essay text and the existing audio file, it produces word-level timestamps. Two things fall out of this almost for free:

- **Real scene durations.** Instead of the wizard's flat `sceneDuration: 5` default (`StudioScene.durationSec`, `models.py:132`), each scene's duration becomes the actual span of its narration in the real audio — cutting on sentence boundaries, not guesses.
- **`CaptionSegment` rows** (`models.py:278`), populated automatically. This model already exists in Creator Studio Pro and today is populated by hand via `POST /projects/{id}/captions` (`routes.py:2097`) — this batch is the thing that fills it. Given the brief's own accessibility requirement (captions always on, large, high-contrast — encoded as `motion.captions: "always_on"` in the `ruslanmv-essays` StyleKit), this isn't a nice-to-have; it's the actual delivery mechanism for that requirement.

Because forced alignment needs a `StudioProject` to attach `CaptionSegment` rows to, the caption-population half of this batch lands fully once Batch 4's `promote-to-project` bridge exists; until then, alignment output is stored on the video's metadata and used for durations only. (Durations alone are enough to prove the batch.)

## 2. Reusing the essay's own audio for the full-length format

When `existing_audio_url` is set (Batch 0), the full-length 16:9 render uses the existing ~9–10 minute Kokoro narration as-is — no new TTS. Forced alignment is what lets scene durations line up with audio that was never chunked into scenes in the first place. This is the cheapest, highest-fidelity path for the flagship format.

## 3. New audio for Shorts and teasers, same voice

The full video reuses existing audio; the Short and teaser (Batch 4) need a condensed script and *new*, shorter audio. Voice consistency across formats matters more than most video decisions here — a Short in a different voice than the full essay reads as off-brand.

**Recommendation: add Kokoro-82M as a second HomePilot voice provider** alongside the existing Piper one (`backend/app/voice/providers.py` — `PiperTTSProvider` at line 57; the new provider follows the same `TTSProvider` ABC at line 25, additive, same pattern as adding a new LLM provider):

- Still Apache-2.0, still one of the more efficient open TTS options as of mid-2026.
- It's the model that already voiced the source essays (the external R2-hosted, Jekyll-integrated pipeline), so reusing it is a one-line "same speaker" decision rather than a new one — pinned via `KOKORO_VOICE_ID`.
- **Piper stays the in-app default for every other project type** — the provider selection logic (`providers.py:217–224`) keeps its current fallback order; only the essay pipeline's voice dropdown defaults to Kokoro.

**Chatterbox** (also already used in Ruslan's own TTS work) is worth keeping as a second option specifically for the punchier, more expressive delivery a 45-second Short benefits from, if Kokoro's flatter documentary tone reads as too dry for that format. Gated behind `CHATTERBOX_ENABLED=false` by default.

Note the boundary being respected: HomePilot's in-app TTS (Piper) and the external Kokoro essay-narration pipeline are two different systems. This batch does *not* merge them — it imports the existing essay audio as an asset (Batch 0/4) and separately adds Kokoro as an in-app provider for the *new* short-form audio, so the voice matches.

## 4. Files touched in this batch

**Modified (additive only):**
- `backend/app/voice/providers.py` — `+KokoroTTSProvider` (and optional `ChatterboxTTSProvider`), existing Piper/Null selection untouched
- `backend/app/studio/routes.py` — alignment step in the script-mode pipeline: when `existing_audio_url` is present, run WhisperX, write per-scene `durationSec`, stash word timestamps in video metadata for Batch 4's caption materialization

**New dependency:** WhisperX (backend), model/device via `WHISPERX_MODEL` / `WHISPERX_DEVICE`.

**Config:** `WHISPERX_MODEL=large-v3`, `WHISPERX_DEVICE=cuda`, `KOKORO_VOICE_ID=...`, `CHATTERBOX_ENABLED=false`

## 5. Acceptance criteria

1. With `existing_audio_url` set, generated scenes' `durationSec` values sum to (approximately) the audio duration and cut on sentence boundaries — no flat 5-second defaults.
2. Without `existing_audio_url`, behavior is identical to Batch 0 (flat `scene_duration` default) — alignment is strictly opt-in.
3. Alignment output (word-level timestamps) is persisted and sufficient to materialize `CaptionSegment` rows in Batch 4 without re-running WhisperX.
4. Kokoro provider passes the same interface tests as Piper; Piper remains the default provider for non-essay project types.

## 6. Risk specific to this batch

**Voice mismatch across formats.** Mitigated by pinning Kokoro (same voice as the source essay) across every variant of a given essay, rather than letting Shorts default to Piper.

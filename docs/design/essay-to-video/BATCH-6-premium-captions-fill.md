# Batch 6 — Word-Level Caption Sync + Premium Still Fill

**Status:** additive, non-destructive. Every change is opt-in and defaults to the
current behavior.
**Depends on:** Batch 2 (WhisperX word timestamps persisted in video metadata),
the existing MP4 export (`render_mp4.py`, `CreatorExportWizard`).
**Delivers:** the two remaining quality gaps that separate "good" shorts from
top-tier ones — CapCut/Submagic **word-by-word active-word captions**, and
**no black bars** on stills.

---

## 1. Problem (from the shorts audit)

Two amateur tells remained in the export:

1. **Captions aren't word-synced.** `_write_srt_for_scene` distributes cues
   *evenly* across a scene's duration. The real WhisperX word timestamps
   (Batch 2, `AlignmentResult.words`, persisted under `metadata.alignment`) are
   never used at render time, so captions drift off the spoken words. Top
   short-form channels highlight the *currently spoken word* — that sync is the
   look.
2. **Stills get black bars.** A non-native-aspect image is `scale=decrease` +
   `pad=color=black` → letterboxed. Black bars read as amateur on a Short.

## 2. Two opt-in knobs (defaults preserve current behavior)

`VideoMp4ExportRequest` gains two fields, both defaulting to today's behavior:

```python
caption_mode: Literal["sentence", "word"] = "sentence"   # "word" = active-word ASS
fill_mode:    Literal["letterbox", "cover", "blur"] = "letterbox"
```

- `caption_mode="sentence"` → the existing SRT chunker, unchanged.
- `caption_mode="word"` → per-word ASS captions with the active word highlighted
  (needs word timings; falls back to sentence cues per-scene when a scene has
  none, so it never fails).
- `fill_mode="letterbox"` → current pad-with-black, unchanged.
- `fill_mode="cover"` → scale-to-fill + centre-crop (no bars; may crop edges).
- `fill_mode="blur"` → the premium option: a blurred, darkened copy of the image
  fills the canvas behind the sharp aspect-fit copy. No bars, nothing cropped.

## 3. Word-level captions (`caption_mode="word"`)

### 3.1 Data path (all additive)

- `SceneInput` gains `word_timings: Optional[List[WordTiming]]` — `(word, start,
  end)` **relative to the scene start**.
- `video_export_mp4` reads `metadata.alignment` (persisted by Batch 2), and for
  each scene uses its `audio_start_sec`/`audio_end_sec` (written by
  `alignment.apply_spans_to_scenes`) to slice the global word list into
  scene-relative timings. No alignment → no `word_timings` → automatic
  fall-back to sentence cues. The export endpoint change is the only wiring;
  Batch 2's persistence is reused as-is.

### 3.2 Render (`_write_ass_word_captions`)

Emits an ASS subtitle (libass, same burn-in filter already in use):

- Words are grouped into short **caption windows** (≤ `_subtitle_max_chars`,
  broken on gaps > 0.6 s) so the viewer reads 1–3 words at a time — the
  short-form standard, not a full sentence.
- Within a window, one Dialogue event **per word**, timed to that word's
  `[start, end]`, shows the whole window with the **active word** in the
  StyleKit accent colour and scaled up ~10 % (the "pop"). Inactive words stay
  white.
- The base `[V4+ Styles]` entry reuses the premium preset-aware sizing from the
  shorts-caption fix (large + bold + heavy outline + Shorts-safe `MarginV`),
  now driven by `PlayResX/Y = canvas`.

Deterministic: the pixels come straight from the timestamps and text — no
sampling, nothing to garble.

## 4. Premium still fill (`fill_mode`)

`_video_fill_chain(in_label, out_label, w, h, fps, fill_mode)` returns the
filter sub-graph for a scene:

- **letterbox** (default): `scale=decrease, pad=color=black` — unchanged.
- **cover**: `scale=increase, crop=w:h` — fills, centre-crops the overflow.
- **blur**: `split` → background (`scale=increase, crop, boxblur, slight
  darken`) + foreground (`scale=decrease`) → `overlay` centred. A premium,
  full-bleed frame with no bars and no lost content.

Only the fill step changes; the fps/sar/format normalization downstream is
identical, so the concat pipeline is untouched.

## 5. Wizard

`CreatorExportWizard` gains two controls, both defaulting to current behavior:
a **"Word-by-word captions (synced)"** toggle and a **background fill** selector
(Letterbox / Cover / Blur). They map 1:1 to the two request fields.

## 6. Files touched (additive only)

```text
backend/app/studio/render_mp4.py    +WordTiming, +SceneInput.word_timings,
                                    +_write_ass_word_captions, +_video_fill_chain,
                                    +caption_mode/fill_mode on render_scenes
backend/app/studio/render_jobs.py   +caption_mode/fill_mode on RenderJob + submit_render
backend/app/studio/routes.py        +caption_mode/fill_mode on VideoMp4ExportRequest,
                                    +per-scene word-timing slicing from metadata.alignment
frontend/.../CreatorExportWizard.tsx +2 controls
```

Nothing is removed or repurposed. With both knobs at their defaults the exported
file is byte-for-byte the current output.

## 7. Acceptance

1. Defaults (`sentence` + `letterbox`) reproduce today's render exactly.
2. `caption_mode="word"` with word timings emits ASS whose per-word events match
   the timestamps and highlight the active word in the accent colour; a scene
   with no timings falls back to sentence cues without error.
3. `fill_mode="blur"`/`"cover"` produce a bar-free filter graph; `letterbox` is
   unchanged.
4. The word/fill sizing stays canvas-proportional (Shorts big, 16:9 comfortable).

# Batch 4 — One Master Scene, Three Aspect Ratios, and the Bridge into Creator Studio Pro

**Status:** design only — no implementation in this batch document.
**Depends on:** Batch 0 (script mode), Batch 1 (Remotion compositions), Batch 2 (alignment output + Kokoro provider), Batch 3 (dual-aspect hero generation).
**Proves:** one essay produces a full-length 16:9 video, a 9:16 Short, and a 1:1 teaser, all landing in Creator Studio Pro as an editable professional project.

---

## 1. `CanvasSpec.safe_margin_pct` is already the right contract

Every `motion_graphic` scene gets authored once, with layout expressed relative to a safe-content box — `safe_margin_pct` already exists on `CanvasSpec` (`backend/app/studio/models.py:176`) for exactly this, and is unused today. Remotion re-renders the *same* composition at three different `width`/`height` props — 1920×1080, 1080×1920, 1080×1080 — and the safe-margin-aware layout reflows correctly at each, because the composition was never authored against a fixed pixel canvas in the first place. This is close to free once the composition is built correctly the first time (Batch 1 authors them this way from the start).

## 2. `diffusion` scenes don't get cropped — they get regenerated at each aspect

Cropping a 16:9 diffusion frame down to 9:16 usually cuts off whatever the shot was about. Batch 3's dual-aspect generation covers this: two native passes from the same seed (and, where supported, the same IPAdapter/reference image) — one 16:9, one 9:16 (1:1 center-crops acceptably from either). Roughly doubles diffusion cost for hero shots only — a minority of scenes given Batch 1's renderer split.

## 3. Two small enum additions

```python
# backend/app/studio/models.py — additive values only
PlatformPreset = Literal["youtube_16_9", "shorts_9_16", "slides_16_9", "social_1_1"]   # +1 value
ProjectType    = Literal["youtube_video", "youtube_short", "slides", "social_teaser"]  # +1 value
```

Today these are `models.py:21` and `models.py:168`. **Sync wrinkle worth flagging:** `PlatformPreset` is declared *independently* in `frontend/src/ui/CreatorStudioHost.tsx:7` and in `backend/app/studio/models.py:21` — not shared through `packages/types`. Both must get the new value; that's a pre-existing wrinkle, not one this design introduces, but it'll bite silently if only one side is updated. (Unifying them through `packages/types` is worthwhile but out of scope — it wouldn't be purely additive.)

## 4. Condensed script for Shorts and the teaser

A small additional LLM pass over the `EssaySource` (not over generated scenes — over the source, so nothing compounds): pick the hook + 1–2 supporting beats + a proof point, matching the "Hook / Problem / Visual / Core idea / Proof / CTA" shape from the source brief. New, shorter audio is generated for it via the Kokoro provider (Batch 2), pinned to `KOKORO_VOICE_ID` so every variant of a given essay stays in the same voice as the full-length narration. Chatterbox remains the opt-in alternative for punchier Short delivery.

## 5. The bridge: `promote-to-project`

One new endpoint connects the two subsystems:

```text
POST /studio/videos/{video_id}/promote-to-project
```

Takes a `StudioVideo` + its `StudioScene`s (finished or in progress) and materializes a `StudioProject` using **entirely existing Pro models**:

- One `CanvasSpec` per target format (16:9 / 9:16 / 1:1).
- `styleKitId = "ruslanmv-essays"` (Batch 0's row).
- `StudioAsset` rows for the essay source text and the original audio file (existing `POST /projects/{id}/assets` machinery, `routes.py:1955`).
- `AudioTrack` rows — `voiceover` (the narration, full or condensed) and optionally `music` (a bed) — existing `TrackKind` covers both (`models.py:257`).
- `CaptionSegment` rows from the WhisperX alignment persisted in Batch 2.

Everything past that point — versioning (`routes.py:2155`), autosave (`:2140`), the shareable read-only preview link (`:2232`) — already works today via the existing Pro endpoints. **This single endpoint is the entire bridge; nothing else in Creator Studio Pro changes.**

## 6. Final assembly

Remotion final assembly, one composition, three canvases: the master timeline composition imports each scene's rendered output (`<OffthreadVideo>` for diffusion clips, nested compositions for motion-graphic scenes), the voiceover `AudioTrack`, and the `CaptionSegment` track (styled per the StyleKit's `captions: "always_on"` motion rule), and renders 16:9 / 9:16 / 1:1 MP4s. Scene selection differs per format: the full scene list for 16:9, the condensed-script subset for 9:16 and 1:1.

## 7. Files touched in this batch

**Modified (additive only):**
- `backend/app/studio/models.py` — `+PlatformPreset."social_1_1"`, `+ProjectType."social_teaser"`
- `backend/app/studio/routes.py` — `+POST /videos/{id}/promote-to-project`; condensed-script pass
- `frontend/src/ui/CreatorStudioHost.tsx` — `+PlatformPreset."social_1_1"` (**keep in sync with models.py**, see §3); "Promote to Pro project" action
- `frontend/src/ui/studio/remotion/` — master assembly composition (extends Batch 1's archetypes)

## 8. Acceptance criteria

1. `promote-to-project` on a finished essay video yields a `StudioProject` whose assets, audio tracks, captions, versions, and share link all behave through the existing, unmodified Pro endpoints.
2. The same `motion_graphic` scene renders legibly at 1920×1080, 1080×1920, and 1080×1080 with no per-format authoring, respecting `safe_margin_pct`.
3. The Short's audio is in the same voice as the full-length narration (Kokoro, same `KOKORO_VOICE_ID`).
4. Existing `PlatformPreset`/`ProjectType` values and every project created before this batch deserialize and behave unchanged.
5. Frontend and backend `PlatformPreset` declarations both contain `social_1_1` (checked in review — no shared type exists yet).

## 9. Out of scope (by request — the series stops here)

Thumbnail generation, YouTube Data API upload, scheduling. This design stops before publish automation.

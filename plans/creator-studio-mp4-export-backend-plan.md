# Creator Studio Backend Upgrade Plan: Additive MP4 Export for YouTube

## 1) Goal and constraints

Build a **backend-only, additive, non-destructive** upgrade that enables real MP4 export for Creator Studio projects while preserving existing routes and current export formats.

### Explicit constraints
- Keep existing API surface (`/studio/projects/{project_id}/exports` and `/studio/projects/{project_id}/export`) intact.
- Add new export kinds instead of replacing old ones.
- Keep existing JSON/PDF/PPTX/ZIP export behavior unchanged.
- Keep orchestration in `backend/app/studio/exporter.py` and isolate rendering internals in a new module.

## 2) Current-state findings (what blocks MP4 today)

1. Project export request kind list only supports metadata/doc/asset pack outputs.
2. `export_project(...)` dispatch only points to placeholder-style exporters.
3. No timeline planning, media normalization, composition, or ffmpeg render path exists for project exports.
4. There is an existing `media/app.py` service suitable for media operations; we can reuse it incrementally.

## 3) Target architecture (additive)

Create a new package:

```text
backend/app/studio/video_export/
├── __init__.py
├── composer.py     # top-level orchestration for final mp4
├── planner.py      # normalize project+assets into timeline manifest
├── presets.py      # output presets (youtube/shorts/generic)
├── fetch.py        # remote URL -> local temp workspace
├── ffmpeg.py       # ffmpeg command wrappers
└── manifest.py     # export run metadata and status
```

### Responsibilities
- `exporter.py`: validate kind, dispatch, return export contract.
- `video_export.composer`: run planning/fetch/render pipeline.
- `video_export.ffmpeg`: codec/filter/concat/mix primitives only.
- `video_export.manifest`: store structured job metadata/logs/outcome for retrieval.

## 4) API and model evolution plan

## 4.1 Extend project export request kinds
Add project export kinds:
- `video_mp4` (generic final MP4)
- `youtube_mp4` (16:9 optimized preset)
- `shorts_mp4` (9:16 optimized preset)

## 4.2 Extend `get_project_available_exports`
Add availability rules:
- Always offer `video_mp4`.
- Offer `youtube_mp4` for `youtube_video` and convertible projects.
- Offer `shorts_mp4` for `youtube_short` and convertible projects.
- Keep existing exports exactly as-is.

## 4.3 Preserve route contracts
Do not add a new frontend flow. Keep:
- `GET /studio/projects/{project_id}/exports`
- `POST /studio/projects/{project_id}/export`

Only extend accepted `kind` values and exporter dispatch.

## 5) Project-type normalization plan

Because frontend names (`video`, `slideshow`, `video_series`) differ from backend project types (`youtube_video`, `youtube_short`, `slides`), add an internal normalization layer:

- `video` -> `youtube_video`
- `slideshow` -> `slides`
- `video_series` -> `youtube_video` + metadata tag `projectType:video_series`

Normalization should be additive and backward compatible; no destructive schema migration required.

## 6) Timeline planning design

`planner.py` should output a normalized render spec:

- Canvas: width/height/fps
- Ordered scenes with per-scene source kind (`video` or `image`)
- Duration resolution (scene-level override, fallback defaults)
- Audio tracks (voice/music) and mix intent
- Caption events/subtitles (optional in v1, required hooks)

### Scene resolution rules
1. If scene video exists: prefer video clip.
2. Else if scene image exists: synthesize motion clip from still image.
3. Else: produce a deterministic planner warning/error.

## 7) Rendering strategy by project type

### 7.1 Video Project
- Use scene `videoUrl` when present.
- Fallback to image clip generation when only `imageUrl` exists.
- Concat clips in scene order.
- Optional voice/music mix in phase 2.

### 7.2 Slideshow
- Convert each still into timed clip (hold or Ken Burns).
- Apply optional transitions and concat.
- Produce MP4 via same finalizer as other types.

### 7.3 Video Series
- v1: export current project into one MP4 via same pipeline.
- v2+: episode-aware batch and compilation exports.

## 8) ffmpeg/preset standards (YouTube-safe defaults)

For v1 output:
- Video codec: H.264 (`libx264`)
- Audio codec: AAC
- Pixel format: `yuv420p`
- Fast start: `+faststart`
- FPS normalization: 30 (configurable)

Preset examples:
- `youtube_mp4`: 1920x1080
- `shorts_mp4`: 1080x1920
- `video_mp4`: project canvas or safe fallback (e.g., 1280x720)

## 9) Execution phases

## Phase 1 (MVP: real MP4 export)
1. Add new export kinds to project request model/route.
2. Add new exporters in `exporter.py` and dispatch wiring.
3. Implement `video_export` package with planner/fetch/ffmpeg/composer.
4. Render scenes -> concat -> output MP4 file and URL.
5. Record manifest (status, output path/url, basic logs).

**Exit criteria:** A project can be exported as a playable MP4 via `POST /studio/projects/{id}/export`.

## Phase 2 (quality + narration)
1. Add narration/music mix support.
2. Add subtitle generation hooks (sidecar `.srt`, optional burn-in).
3. Add thumbnail generation and richer export metadata.

**Exit criteria:** MP4 includes optional mixed audio and richer artifacts.

## Phase 3 (series + scale)
1. Add episode/batch series export modes.
2. Add async/background job execution for long renders.
3. Add retry and resumable workflow for fetch/render steps.

**Exit criteria:** Reliable long-form/series exports with job lifecycle controls.

## 10) Data contracts and observability

Manifest fields to persist per export:
- `exportId`, `projectId`, `kind`, `preset`, `status`
- timestamps (`createdAt`, `startedAt`, `completedAt`)
- derived media info (`durationSec`, resolution, fileSizeBytes)
- output location (`outputPath`, `outputUrl`)
- diagnostics (`warnings`, `logs`, `error`)

Add audit events for start/success/failure with kind + project type.

## 11) Testing and validation plan

### Unit tests
- Planner: scene fallback precedence, duration defaults, type normalization.
- Presets: dimensions/fps/codec correctness.
- Export dispatch: new kinds routed correctly.

### Integration tests
- API: `POST /studio/projects/{id}/export` for all 3 new kinds.
- End-to-end with mixed scene assets (video + image-only fallback).
- Failure handling for unreachable asset URLs.

### Output validation checks
- MP4 playable in common players.
- `ffprobe` confirms codec/pixel format/fps.
- Fast-start metadata present for streaming.

## 12) Risk controls (non-destructive rollout)

- Feature flag gate for MP4 export kinds in initial deployment.
- Keep existing export kinds untouched and regression-tested.
- Add clear error payloads when media dependencies are unavailable.
- Support partial fallback behavior (e.g., image hold clip) instead of hard fail where possible.

## 13) Immediate next implementation slice

Start with **`youtube_mp4` only**, but implement reusable internals so `video_mp4` and `shorts_mp4` are thin preset variants.

This gives one clear backend contract quickly while avoiding duplicate logic.

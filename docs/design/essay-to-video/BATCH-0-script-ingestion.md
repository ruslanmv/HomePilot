# Batch 0 — Bring Your Own Script (Essay Ingestion + Script Mode)

**Status:** design only — no implementation in this batch document.
**Depends on:** nothing. This is the smallest possible first PR.
**Proves:** "the essay's own words become the narration," end to end, using the *existing* SDXL/SVD path — no Remotion, no WhisperX, no Civitai, no new models.

---

## 1. Problem

Today, `Video Project` takes a short "Description" (`StudioVideo.logline`) and the LLM *invents* the narration and scene beats from it (`POST /videos/{id}/generate-outline`, `backend/app/studio/routes.py:970`). An essay isn't a topic to riff on — it's a finished script that needs to be segmented and timed, not rewritten.

## 2. New source mode, additive to the existing request

`GenerateOutlineRequest` is defined in `backend/app/studio/routes.py:941` (not `models.py`). The `SourceMode` type alias goes in `backend/app/studio/models.py` next to the other governance aliases; the request fields extend the class where it lives:

```python
# backend/app/studio/models.py — additive alias, nothing removed
SourceMode = Literal["topic", "script"]          # NEW

# backend/app/studio/routes.py — additive fields on the existing class
class GenerateOutlineRequest(BaseModel):
    target_scenes: int = Field(8, ge=4, le=24)
    scene_duration: int = Field(5, ge=3, le=15)
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None
    source_mode: SourceMode = "topic"            # NEW, default preserves old behavior
    script_text: Optional[str] = None            # NEW — full essay body when source_mode="script"
    existing_audio_url: Optional[str] = None     # NEW — the Kokoro-narrated mp3, if reusing it
```

`source_mode="topic"` is the existing behavior, byte-for-byte untouched. `source_mode="script"` changes what the LLM is asked to do: **segment, don't invent.**

## 3. `EssaySource` — the ingestion object

A new small module, `backend/app/studio/essay_import.py`, responsible only for turning either a ruslanmv.com URL or pasted markdown into a structured object:

```python
class EssaySection(BaseModel):
    heading: str
    body: str                       # the essay's own words, verbatim
    is_thesis_line: bool = False    # bolded/blockquote lines the essay itself calls out

class EssaySource(BaseModel):
    title: str
    subtitle: str = ""
    author: str = "Ruslan Magana Vsevolodovna"
    sections: List[EssaySection]
    existing_audio_url: Optional[str] = None
    existing_audio_duration_sec: Optional[float] = None
    source_links: List[str] = Field(default_factory=list)   # for the CTA scene
```

Two ways to populate it, both worth having:

- **URL mode** (general, works for the in-app "paste a link" flow): fetch the rendered page, parse by the CSS structure the essay index already exposes — category label, title, subtitle, author card, `<nav>`/TOC, section headings, audio player `src`, closing links. This is the flexible path and the one a wizard field maps to directly.
- **Repo mode** (more robust, worth it if this becomes a recurring publish step): read the Jekyll markdown source directly from the ruslanmv.com repo instead of scraping rendered HTML. No markup fragility, exact section boundaries for free. Natural fit for a GitHub Action that runs on every new essay and calls HomePilot's API directly rather than going through the browser wizard.

Either path produces the same `EssaySource`, so the rest of the pipeline doesn't care which one ran. Selected via `ESSAY_IMPORT_SOURCE=url|repo`.

## 4. What the LLM is asked to do differently in script mode

Today's outline prompt (topic mode) asks the model to *write* narration for `target_scenes` beats about a described subject. The script-mode prompt instead runs once per `EssaySection` and asks for **segmentation and shot-planning**, not prose generation:

- Split this section's body into 1–3 narration beats, using the section's own sentences (light trimming for pacing is fine; inventing new sentences is not).
- For each beat, classify a `scene_kind`: `hero` / `diagram` / `quote` / `proof` / `cta` / `transition` (this classification is what Batch 1 uses to pick a renderer; in Batch 0 it's stored but everything still renders through diffusion).
- For each beat, produce `image_prompt` / `negative_prompt` exactly as today's `SceneOutline` (`routes.py:949`) already expects — the output shape doesn't change, only how `narration` gets populated changes.

This means `scenes/generate-from-outline` (`routes.py:1545`) and everything downstream of it needs **zero changes** — it already consumes a `SceneOutline` list, and script mode just produces that list a different way.

## 5. Reusing the essay's own audio for the full-length video

When `existing_audio_url` is set, the full-length (16:9) render doesn't need new TTS at all — the ~9–10 minute Kokoro narration already exists. This is the cheapest, highest-fidelity path for the flagship format. In Batch 0 the URL is simply stored on the video's metadata; Batch 2's forced alignment is what lets scene *durations* line up with audio that was never chunked into scenes in the first place.

## 6. A StyleKit for the channel

`StyleKit` already exists (`palette`, `fonts`, `spacing`, `motion` — `models.py:179`) and is already served via `/library/style-kits` (`routes.py:1827`). This is one new row, not new code:

```python
StyleKit(
    id="ruslanmv-essays",
    name="RuslanMV Essays",
    description="Calm, technical, diagram-driven. Matches the ruslanmv.com essay identity.",
    palette={
        "background": "#0a0a0a", "text_primary": "#ffffff", "text_secondary": "#94a3b8",
        "accent_start": "#00d4ff", "accent_mid": "#0f62fe", "accent_end": "#8a3ffc",
    },
    fonts={"heading": "IBM Plex Sans", "mono": "IBM Plex Mono"},
    motion={"pace": "slow", "transitions": ["fade", "slide"], "flashing": False,
            "captions": "always_on"},
)
```

(Palette matches the cyan → blue → violet system already used elsewhere in Ruslan's own decks, so this reads as continuation of an existing identity rather than a new one.)

## 7. A fourth visual style in the wizard

Paired with the StyleKit: a fourth `visualStyle` option in the wizard, alongside the existing `Cinematic` / `Digital Art` / `Anime`. None of the three current options fit editorial/technical content — `Cinematic` implies photoreal footage, `Anime` and `Digital Art` are the wrong register entirely. Add `"Technical / Editorial"`, mapped to the `ruslanmv-essays` `StyleKit` and a tuned negative-prompt addendum (no photoreal faces, no stock-footage clichés, no visual clutter).

One small UI conditional worth adding alongside it: when `source_mode="script"` is active, only this fourth option is offered — an essay import shouldn't present Anime as a plausible choice.

## 8. Files touched in this batch

**New:** `backend/app/studio/essay_import.py`
**Modified (additive only):**
- `backend/app/studio/models.py` — `+SourceMode` alias
- `backend/app/studio/routes.py` — `+3` optional fields on `GenerateOutlineRequest`, `+source_mode` branch in `generate_story_outline`
- `frontend/src/ui/CreatorStudioHost.tsx` — `+"Technical / Editorial"` visualStyle, `+` script-mode input (URL/markdown paste field)

**Config:** `ESSAY_IMPORT_SOURCE=url`

## 9. Acceptance criteria

1. A topic-mode `generate-outline` request with no new fields behaves identically to today (regression guarantee — defaults preserve old behavior).
2. Given a ruslanmv.com essay URL or pasted markdown, the resulting `SceneOutline[]` narration consists of the essay's own sentences (verifiable by substring match against the source), not invented prose.
3. Each outline entry carries a `scene_kind` classification (stored, unused until Batch 1).
4. The full existing SDXL/SVD render path produces a video from that outline with zero downstream changes.
5. The `ruslanmv-essays` StyleKit is returned by `GET /studio/library/style-kits`.

## 10. Out of scope for this batch

Renderer split (Batch 1), forced alignment and captions (Batch 2), model manager and model-list fixes (Batch 3), multi-aspect output and the Pro bridge (Batch 4).

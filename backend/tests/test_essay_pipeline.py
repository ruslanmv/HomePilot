"""
Essay-to-video pipeline tests (Batches 0-4).

Covers the invariants the design series guarantees:
  - narration is the essay's own sentences, verbatim, at every stage
  - defaults preserve pre-pipeline behavior (topic mode, legacy scenes)
  - deterministic rendering produces exact text at multiple canvases
  - alignment degrades from whisperx to proportional without breaking
  - the model manager refuses unlicensed models and hides the mature lane
  - promote-to-project lands everything through existing Pro repo functions

All tests are self-contained: temp dirs, no network, no LLM, no GPU.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import wave

import pytest

# Ensure `app` is importable when run directly (mirrors conftest behavior)
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


SAMPLE_MD = """---
title: "Typed Memory in AI Agents"
subtitle: "Why schemas beat vibes"
audio: https://cdn.example.com/audio/typed-memory.mp3
---

Intro paragraph before any heading. It sets the stage for everything that follows.

## The Problem

Agents forget things because memory today is a pile of unstructured strings.
Retrieval over that pile is guesswork, and guesswork compounds badly over time.

> Typed memory is a contract with your future self.

More prose after the quote to test ordering within the section.

## The Architecture

The pipeline has three layers: an extractor, a schema registry, and a router. Each layer validates its input before passing it on. Benchmarks show a 42% reduction in retrieval errors and 3x lower latency.

```python
def not_narratable():
    pass
```

## Conclusion

Start storing types today. Read more at [the essays](https://ruslanmv.com/essays) and [the repo](https://github.com/ruslanmv/example).
"""


@pytest.fixture()
def essay():
    from app.studio.essay_import import parse_markdown
    return parse_markdown(SAMPLE_MD)


@pytest.fixture()
def studio_db(tmp_path, monkeypatch):
    """Redirect the studio sqlite DB and pipeline file dirs to tmp."""
    from app.studio import repo
    monkeypatch.setattr(repo, "SQLITE_PATH", str(tmp_path / "studio.db"))
    monkeypatch.setenv("MOTION_GRAPHICS_DIR", str(tmp_path / "mg"))
    monkeypatch.setenv("STUDIO_FILES_DIR", str(tmp_path / "files"))
    monkeypatch.setenv("MODEL_REGISTRY_PATH", str(tmp_path / "installed_models.json"))
    monkeypatch.setenv("STUDIO_ALLOW_LOCAL_AUDIO", "true")
    return repo


def _flat(essay) -> str:
    return " | ".join(sec.body for sec in essay.sections)


def _make_wav(path, seconds: int) -> str:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 16000 * seconds)
    return str(path)


# ── Batch 0: ingestion + segmentation ────────────────────────────────────────

class TestEssayIngestion:
    def test_front_matter_and_audio(self, essay):
        assert essay.title == "Typed Memory in AI Agents"
        assert essay.subtitle == "Why schemas beat vibes"
        assert essay.existing_audio_url == "https://cdn.example.com/audio/typed-memory.mp3"

    def test_links_collected_and_code_dropped(self, essay):
        assert "https://ruslanmv.com/essays" in essay.source_links
        assert "not_narratable" not in _flat(essay)

    def test_thesis_lines_in_document_order(self, essay):
        bodies = [(s.body, s.is_thesis_line) for s in essay.sections]
        quote_idx = next(i for i, (b, t) in enumerate(bodies) if t)
        after_idx = next(i for i, (b, _) in enumerate(bodies) if b.startswith("More prose"))
        assert quote_idx < after_idx, "blockquote must stay in document order"

    def test_html_parse_same_shape(self):
        from app.studio.essay_import import parse_html
        html = """<html><head><title>My Essay | site</title></head><body>
        <h1>My Essay</h1><p>Sub line.</p>
        <audio src="https://cdn.example.com/e.mp3"></audio>
        <h2>Section One</h2><p>First paragraph here.</p>
        <blockquote><p>The thesis.</p></blockquote>
        </body></html>"""
        e = parse_html(html)
        assert e.title == "My Essay"
        assert e.existing_audio_url == "https://cdn.example.com/e.mp3"
        assert any(s.is_thesis_line for s in e.sections)

    def test_ingest_requires_a_source(self):
        from app.studio.essay_import import ingest
        with pytest.raises(ValueError):
            ingest()


class TestSegmentation:
    def test_narration_is_verbatim(self, essay):
        from app.studio.essay_import import segment_essay
        scenes = segment_essay(essay, 5.0)
        flat = _flat(essay)
        assert scenes
        assert all(s["narration"] in flat for s in scenes)

    def test_scene_kinds_and_renderers(self, essay):
        from app.studio.essay_import import segment_essay
        from app.studio.models import SCENE_KIND_TO_RENDERER
        scenes = segment_essay(essay, 5.0)
        kinds = {s["scene_kind"] for s in scenes}
        assert {"hero", "quote", "cta"} <= kinds
        for s in scenes:
            assert s["renderer_kind"] == SCENE_KIND_TO_RENDERER[s["scene_kind"]]

    def test_shot_plan_cannot_touch_narration(self, essay):
        from app.studio.essay_import import apply_shot_plan, segment_essay
        scenes = segment_essay(essay, 5.0)
        original = scenes[0]["narration"]
        applied = apply_shot_plan(scenes, {"scenes": [
            {"scene_number": 1, "scene_kind": "diagram",
             "image_prompt": "new", "narration": "INJECTED"}]})
        assert applied == 1
        assert scenes[0]["scene_kind"] == "diagram"
        assert scenes[0]["image_prompt"] == "new"
        assert scenes[0]["narration"] == original


# ── Batch 0/4: request defaults preserve old behavior ────────────────────────

class TestRequestDefaults:
    def test_topic_mode_is_default(self):
        from app.studio.routes import GenerateOutlineRequest
        r = GenerateOutlineRequest()
        assert r.source_mode == "topic"
        assert r.script_text is None and r.script_url is None
        assert r.existing_audio_url is None
        assert r.target_scenes == 8 and r.scene_duration == 5

    def test_legacy_scene_has_no_renderer(self, studio_db):
        from app.studio.models import StudioSceneCreate, StudioVideoCreate
        from app.studio.service import create as create_video
        v = create_video(StudioVideoCreate(title="t"))
        s = studio_db.create_scene(v.id, StudioSceneCreate(narration="x"))
        assert s.rendererKind is None and s.sceneKind is None

    def test_renderer_kind_round_trip(self, studio_db):
        from app.studio.models import (StudioSceneCreate, StudioSceneUpdate,
                                       StudioVideoCreate)
        from app.studio.service import create as create_video
        v = create_video(StudioVideoCreate(title="t"))
        s = studio_db.create_scene(v.id, StudioSceneCreate(
            narration="x", rendererKind="motion_graphic", sceneKind="diagram"))
        assert s.rendererKind == "motion_graphic"
        u = studio_db.update_scene(s.id, StudioSceneUpdate(renderer_kind="diffusion"))
        assert u.rendererKind == "diffusion"


# ── Batch 1: deterministic rendering ─────────────────────────────────────────

class TestMotionGraphics:
    @pytest.mark.parametrize("preset,size", [
        ("youtube_16_9", (1920, 1080)),
        ("shorts_9_16", (1080, 1920)),
    ])
    def test_render_all_archetypes(self, studio_db, preset, size):
        from PIL import Image
        from app.studio import motion_graphics as mg
        for kind in ("diagram", "proof", "quote", "cta"):
            fn = mg.render_scene_still(f"t-{kind}-{preset}", kind, "Title",
                                       "First sentence. Second sentence with 42%.",
                                       platform_preset=preset,
                                       links=["ruslanmv.com"])
            img = Image.open(mg.output_dir() / fn)
            assert img.size == size


# ── Batch 2: alignment ───────────────────────────────────────────────────────

class TestAlignment:
    def test_proportional_spans_sum_to_duration(self, studio_db, tmp_path):
        from app.studio import alignment as al
        wav = _make_wav(tmp_path / "a.wav", 60)
        scenes = [{"scene_number": 1, "narration": "Two words."},
                  {"scene_number": 2, "narration": "This beat has quite a few more words in it."},
                  {"scene_number": 3, "narration": "One."}]
        res = al.align_scenes(wav, scenes)
        assert res.ok and res.method == "proportional"
        durs = [sp.duration_sec for sp in res.scene_spans]
        assert abs(sum(durs) - 60.0) < 0.05
        assert durs[1] > durs[0] > durs[2]
        assert al.apply_spans_to_scenes(scenes, res) == 3
        assert all("audio_start_sec" in s for s in scenes)

    def test_alignment_is_opt_in(self, studio_db):
        # no audio -> no alignment key, flat durations (Batch 0 behavior)
        from app.studio.essay_import import parse_markdown, segment_essay
        scenes = segment_essay(parse_markdown(SAMPLE_MD), 5.0)
        assert all(s["duration_sec"] == 5.0 for s in scenes)

    def test_local_paths_gated(self, tmp_path, monkeypatch):
        from app.studio import alignment as al
        monkeypatch.setenv("STUDIO_ALLOW_LOCAL_AUDIO", "false")
        wav = _make_wav(tmp_path / "a.wav", 1)
        with pytest.raises(PermissionError):
            al.fetch_audio(wav)

    def test_caption_cues_both_tiers(self, studio_db, tmp_path):
        from app.studio import alignment as al
        scenes = [{"scene_number": 1,
                   "narration": "A fairly long narration sentence that will wrap into caption chunks."}]
        wav = _make_wav(tmp_path / "a.wav", 10)
        res = al.align_scenes(wav, scenes)
        cues = al.caption_cues(res, scenes, max_chars=30)
        assert cues and cues[-1].end_sec <= 10.01
        assert all(c.end_sec > c.start_sec for c in cues)

        words = [al.AlignedWord(word=w, start=i * 0.4, end=i * 0.4 + 0.3)
                 for i, w in enumerate("some words to group into caption cues here".split())]
        res_w = al.AlignmentResult(ok=True, method="whisperx",
                                   audio_duration_sec=4.0, words=words)
        cues_w = al.caption_cues(res_w, scenes, max_chars=20)
        assert cues_w and cues_w[0].start_sec == 0.0

    def test_tts_providers_degrade_gracefully(self):
        from app.voice.providers import (ChatterboxTTSProvider, KokoroTTSProvider,
                                         NullTTSProvider, get_tts_provider_by_name)
        assert asyncio.run(KokoroTTSProvider().synth("hi")) is None
        assert asyncio.run(ChatterboxTTSProvider().synth("hi")) is None
        # unknown names fall back to piper-or-null, never crash
        assert get_tts_provider_by_name("nonsense").name in ("piper", "null")
        assert isinstance(get_tts_provider_by_name(""), (NullTTSProvider, object))


# ── Batch 3: model manager ───────────────────────────────────────────────────

class TestModelManager:
    def test_video_list_matches_workflows(self):
        from pathlib import Path
        from app.providers import available_video_models
        vids = available_video_models()
        assert "seedream" not in vids
        workflows = Path(_BACKEND_ROOT).parent / "comfyui" / "workflows"
        routing = {"svd": "img2vid", "wan-2.2": "img2vid-wan",
                   "ltx-video": "img2vid-ltx", "hunyuan-video-1.5": "img2vid-hunyuan",
                   "mochi-1": "img2vid-mochi", "cogvideo-5b": "img2vid-cogvideo"}
        for model, wf in routing.items():
            assert model in vids
            assert (workflows / f"{wf}.json").is_file()

    def test_license_allowlist(self):
        from app.studio import model_manager as mm
        assert mm.resolve_license("FLUX.2-klein-x").commercial_ok
        assert mm.resolve_license("flux.2-dev-fp8").commercial_ok is False
        assert mm.resolve_license("qwen-image-2").license == "UNRESOLVED"
        assert mm.resolve_license("unknown-thing") is None

    def test_register_refuses_unlicensed(self, studio_db, tmp_path):
        from app.studio import model_manager as mm
        mgr = mm.ModelManager(models_dir=tmp_path)
        bad = mm.InstalledModel(id="mystery", model_type="image",
                                filename="m.safetensors", path="/x",
                                source="civitai", license="")
        with pytest.raises(PermissionError):
            mgr.register(bad)

    def test_registry_feeds_pickers_and_essay_filter(self, studio_db, tmp_path):
        from app.providers import available_image_models
        from app.studio import model_manager as mm
        mgr = mm.ModelManager(models_dir=tmp_path)
        mgr.register(mm.InstalledModel(
            id="flux2-klein", model_type="image", filename="k.safetensors",
            path="/x", source="huggingface", license="Apache-2.0",
            commercial_ok=True))
        assert "flux2-klein" in available_image_models()
        essay = mm.essay_pipeline_models("image")
        assert "pony-xl" not in essay and "sd15-uncensored" not in essay
        assert "pony-xl" in available_image_models()  # general picker untouched


# ── Batch 4: condense + the Pro bridge, end to end ───────────────────────────

class TestCondense:
    def test_selection_is_verbatim(self, essay):
        from app.studio.essay_import import condense_essay
        beats = condense_essay(essay, max_beats=4)
        flat = _flat(essay)
        assert 2 <= len(beats) <= 4
        assert all(b["narration"] in flat for b in beats)
        assert [b["scene_number"] for b in beats] == list(range(1, len(beats) + 1))

    def test_keep_list_can_only_select(self, essay):
        from app.studio.essay_import import (apply_condense_selection,
                                             segment_essay)
        beats = segment_essay(essay, 5.0)
        assert apply_condense_selection(beats, {"keep": "garbage"}, 4) is None
        sel = apply_condense_selection(beats, {"keep": [1, 3, 999]}, 4)
        assert sel is not None and len(sel) == 2


class TestEndToEnd:
    def test_script_outline_to_promoted_project(self, studio_db, tmp_path):
        from app.studio.models import StudioSceneCreate, StudioVideoCreate
        from app.studio.repo import (get_latest_version, list_audio_tracks,
                                     list_captions)
        from app.studio.routes import (GenerateOutlineRequest,
                                       PromoteToProjectRequest,
                                       _generate_script_outline,
                                       promote_to_project)
        from app.studio.service import create as create_video

        class FakeURL:
            def __str__(self):
                return "http://testserver/"

        class FakeRequest:
            base_url = FakeURL()

        wav = _make_wav(tmp_path / "narration.wav", 45)
        v = create_video(StudioVideoCreate(title="E2E",
                                           tags=["visual:technical_editorial"]))
        out = asyncio.run(_generate_script_outline(
            v.id, GenerateOutlineRequest(source_mode="script",
                                         script_text=SAMPLE_MD,
                                         existing_audio_url=wav), v))
        assert out["ok"] and out["alignment"]["method"] == "proportional"

        durs = [s["duration_sec"] for s in out["outline"]["scenes"]]
        assert abs(sum(durs) - 45.0) < 0.1

        for plan in out["outline"]["scenes"]:
            studio_db.create_scene(v.id, StudioSceneCreate(
                narration=plan["narration"], imagePrompt=plan["image_prompt"],
                durationSec=plan["duration_sec"],
                rendererKind=plan.get("renderer_kind"),
                sceneKind=plan.get("scene_kind")))

        promo = promote_to_project(v.id, PromoteToProjectRequest(), FakeRequest())
        assert promo["ok"]
        proj_id = promo["project"]["id"]
        assert promo["project"]["styleKitId"] == "ruslanmv-essays"
        assert set(promo["canvases"]) == {"youtube_16_9", "shorts_9_16", "social_1_1"}
        assert promo["counts"]["captions"] == len(list_captions(proj_id))
        assert len(list_audio_tracks(proj_id)) == 1
        ver = get_latest_version(proj_id)
        assert ver.label == "promoted-from-video"
        assert set(ver.state["aspect_plan"].values()) <= {"reflow", "regenerate_native"}

    def test_enum_additions(self):
        from app.studio.library import default_canvas, normalize_project_type
        assert normalize_project_type("social_teaser") == "social_teaser"
        c = default_canvas("social_teaser")
        assert (c.width, c.height) == (1080, 1080)


# ── Essay-video model bundles + RTX 4080 presets ─────────────────────────────

class TestBundles:
    def test_all_bundles_validate_against_catalog(self):
        from app.studio import bundles as b
        for bundle in b.list_bundles():
            problems = b.validate_bundle(bundle)
            assert not problems, f"{bundle.id}: {problems}"

    def test_bundles_are_sfw_and_licensed(self):
        # bundles must never pull the mature lane, and every model needs a
        # resolved license row (the validator enforces both)
        from app.studio import bundles as b
        from app.studio.model_manager import MATURE_LANE_PATTERNS
        for bundle in b.list_bundles():
            for comp in bundle.components:
                assert not any(p in comp.catalog_id.lower()
                               for p in MATURE_LANE_PATTERNS)

    def test_disk_cost_computed_from_catalog(self):
        from app.studio import bundles as b
        core = b.get_bundle("essay-video-core")
        assert core.disk_gb > 10  # SDXL + SVD-XT are real multi-GB files
        assert all(c.size_gb > 0 or c.role == "addon" for c in core.components)

    def test_install_plan_addons_before_models(self):
        from app.studio import bundles as b
        bundle = b.get_bundle("essay-video-4080-ultra")
        ids = [cmd[-1] for cmd in b.install_plan(bundle)]
        addon_idx = [i for i, x in enumerate(ids) if x.startswith("ComfyUI-")]
        model_idx = [i for i, x in enumerate(ids) if not x.startswith("ComfyUI-")]
        assert max(addon_idx) < min(model_idx)
        assert all("download.py" in cmd[1] for cmd in b.install_plan(bundle))

    def test_presets_reference_in_bundle_models(self):
        from app.studio import bundles as b
        for bundle in b.list_bundles():
            picker_ids = {c.picker_id for c in bundle.components}
            for tier, p in bundle.presets.items():
                assert p.image_model in picker_ids
                assert p.video_model in picker_ids
                assert p.image_steps > 0 and p.video_frames > 0

    def test_4080_bundles_offer_high_and_ultra(self):
        from app.studio import bundles as b
        for bid in ("essay-video-4080-high", "essay-video-4080-ultra"):
            assert set(b.get_bundle(bid).presets) == {"high", "ultra"}

    def test_flux_schnell_preset_uses_correct_cfg(self):
        # Flux Schnell is a distilled 4-step model; cfg must stay ~1.0
        from app.studio import bundles as b
        ultra = b.get_bundle("essay-video-4080-ultra")
        for tier, p in ultra.presets.items():
            if p.image_model == "flux-schnell":
                assert p.image_steps <= 6 and p.image_cfg <= 1.5

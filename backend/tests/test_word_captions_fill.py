"""
Batch 6 — word-level captions + premium still fill.

Verifies the two additive knobs: CapCut-style active-word ASS captions from
forced-alignment word timestamps, and the no-black-bars fill modes. Both
default to the current behavior. No ffmpeg needed — we assert the generated
ASS and the ffmpeg filtergraph strings, which are what the render burns/uses.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app.studio import render_mp4 as r


def _words(*triples):
    return [r.WordTiming(word=w, start=s, end=e) for (w, s, e) in triples]


# ── ASS active-word captions ─────────────────────────────────────────────────

class TestWordCaptions:
    def test_emits_one_event_per_word_with_timestamps(self):
        d = pathlib.Path(tempfile.mkdtemp())
        wt = _words(("Typed", 0.0, 0.4), ("memory", 0.4, 0.9), ("wins", 0.9, 1.3))
        ok = r.write_ass_word_captions(wt, d / "c.ass", 1080, 1920,
                                       duration_sec=2.0, max_chars=20)
        assert ok
        text = (d / "c.ass").read_text()
        # one Dialogue per word
        assert text.count("Dialogue:") == 3
        # the ASS header declares the canvas + a Caption style
        assert "PlayResX: 1080" in text and "PlayResY: 1920" in text
        assert "Style: Caption" in text

    def test_active_word_is_highlighted(self):
        d = pathlib.Path(tempfile.mkdtemp())
        wt = _words(("alpha", 0.0, 0.5), ("beta", 0.5, 1.0))
        r.write_ass_word_captions(wt, d / "c.ass", 1080, 1920,
                                  duration_sec=1.5, max_chars=20)
        lines = [l for l in (d / "c.ass").read_text().splitlines()
                 if l.startswith("Dialogue:")]
        # first event highlights alpha (accent + pop), leaves beta plain
        assert "\\c" in lines[0] and "fscx110" in lines[0]
        assert "alpha" in lines[0] and "beta" in lines[0]

    def test_grouping_breaks_on_silent_gap(self):
        d = pathlib.Path(tempfile.mkdtemp())
        # 1s gap between the two words -> two windows, but still 2 events total
        wt = _words(("one", 0.0, 0.3), ("two", 1.6, 1.9))
        r.write_ass_word_captions(wt, d / "c.ass", 1080, 1920,
                                  duration_sec=2.5, max_chars=40)
        # a window never spans the gap: the first event shows only "one"
        first = next(l for l in (d / "c.ass").read_text().splitlines()
                     if l.startswith("Dialogue:"))
        assert "one" in first and "two" not in first

    def test_empty_timings_returns_false(self):
        d = pathlib.Path(tempfile.mkdtemp())
        assert r.write_ass_word_captions([], d / "c.ass", 1080, 1920,
                                         duration_sec=2.0, max_chars=20) is False

    def test_style_is_canvas_proportional(self):
        d = pathlib.Path(tempfile.mkdtemp())
        wt = _words(("x", 0.0, 0.4))
        r.write_ass_word_captions(wt, d / "s.ass", 1080, 1920, duration_sec=1, max_chars=20)
        r.write_ass_word_captions(wt, d / "w.ass", 1920, 1080, duration_sec=1, max_chars=42)

        def fontsize(p):
            line = next(l for l in p.read_text().splitlines() if l.startswith("Style: Caption"))
            return int(line.split(",")[2])
        assert fontsize(d / "s.ass") > fontsize(d / "w.ass")  # Shorts bigger


# ── Premium fill graph ───────────────────────────────────────────────────────

class TestFillChain:
    def test_letterbox_default_unchanged(self):
        chain = r._video_fill_chain("0:v", "v0", 1080, 1920, 30, "letterbox")
        assert "pad=1080:1920" in chain and "color=black" in chain
        assert "force_original_aspect_ratio=decrease" in chain

    def test_cover_crops_no_bars(self):
        chain = r._video_fill_chain("0:v", "v0", 1080, 1920, 30, "cover")
        assert "force_original_aspect_ratio=increase" in chain
        assert "crop=1080:1920" in chain
        assert "pad=" not in chain  # no black bars

    def test_blur_fill_is_full_bleed(self):
        chain = r._video_fill_chain("0:v", "v0", 1080, 1920, 30, "blur")
        assert "split=2" in chain and "boxblur" in chain and "overlay=" in chain
        assert "pad=" not in chain  # background fills the frame, no bars
        # ends at the expected output label for the concat pipeline
        assert chain.strip().endswith("[v0]")

    def test_all_modes_end_with_normalization(self):
        for mode in ("letterbox", "cover", "blur"):
            chain = r._video_fill_chain("0:v", "v0", 1920, 1080, 30, mode)
            assert "setsar=1" in chain and "fps=30" in chain and "format=yuv420p" in chain


# ── Defaults preserve current behavior ───────────────────────────────────────

class TestBackwardCompatible:
    def test_scene_input_defaults(self):
        s = r.SceneInput(idx=0)
        assert s.word_timings is None  # opt-in only

    def test_render_scenes_accepts_new_kwargs_with_defaults(self):
        import inspect
        sig = inspect.signature(r.render_scenes)
        assert sig.parameters["caption_mode"].default == "sentence"
        assert sig.parameters["fill_mode"].default == "letterbox"


# ── Per-scene word-timing slicing from persisted alignment ───────────────────

class TestSceneSlicing:
    def test_slices_and_rebases_to_scene(self):
        from app.studio.routes import _slice_scene_word_timings

        class V:
            metadata = {
                "alignment": {"words": [
                    {"word": "a", "start": 10.0, "end": 10.3},
                    {"word": "b", "start": 10.3, "end": 10.7},
                    {"word": "c", "start": 20.1, "end": 20.5},  # scene 2
                ]},
                "story_outline": {"scenes": [
                    {"narration": "a b", "audio_start_sec": 10.0, "audio_end_sec": 11.0},
                    {"narration": "c",   "audio_start_sec": 20.0, "audio_end_sec": 21.0},
                ]},
            }

        class Scene:
            def __init__(self, narration):
                self.narration = narration

        out = _slice_scene_word_timings(V(), [Scene("a b"), Scene("c")])
        # scene 0 gets a,b rebased so first word starts at ~0
        assert [w.word for w in out[0]] == ["a", "b"]
        assert abs(out[0][0].start - 0.0) < 1e-6
        # scene 1 gets c rebased relative to its own 20.0 start
        assert [w.word for w in out[1]] == ["c"]
        assert abs(out[1][0].start - 0.1) < 1e-6

    def test_no_alignment_returns_empty(self):
        from app.studio.routes import _slice_scene_word_timings

        class V:
            metadata = {}
        assert _slice_scene_word_timings(V(), []) == {}

"""
Premium burn-in caption tests — YouTube Shorts quality.

Verifies the subtitle layer meets top short-form standards: large,
high-contrast, canvas-proportional, and positioned above the platform's
bottom UI on Shorts (not a fixed tiny font). No ffmpeg needed — we assert
the generated libass style + SRT, which is what the render burns in.
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


def _kv(style: str, key: str) -> str:
    for part in style.split(","):
        if part.startswith(f"{key}="):
            return part.split("=", 1)[1]
    raise KeyError(key)


class TestPremiumCaptionStyle:
    def test_shorts_caption_is_large_and_high(self):
        s = r._subtitle_force_style(1080, 1920)
        assert int(_kv(s, "Fontsize")) >= 90          # was a fixed 28
        assert int(_kv(s, "MarginV")) >= 200          # above the Shorts UI zone
        assert _kv(s, "Bold") == "1"
        assert _kv(s, "Alignment") == "2"             # bottom-centre
        assert _kv(s, "BorderStyle") == "1"           # bold outline, no box
        assert int(_kv(s, "Outline")) >= 4            # high contrast on any bg

    def test_shorts_bigger_than_landscape(self):
        short = int(_kv(r._subtitle_force_style(1080, 1920), "Fontsize"))
        wide = int(_kv(r._subtitle_force_style(1920, 1080), "Fontsize"))
        assert short > wide
        assert (int(_kv(r._subtitle_force_style(1080, 1920), "MarginV"))
                > int(_kv(r._subtitle_force_style(1920, 1080), "MarginV")))

    def test_landscape_still_readable(self):
        s = r._subtitle_force_style(1920, 1080)
        assert int(_kv(s, "Fontsize")) >= 30 and _kv(s, "Bold") == "1"

    def test_font_scales_with_canvas(self):
        small = int(_kv(r._subtitle_force_style(540, 960), "Fontsize"))
        big = int(_kv(r._subtitle_force_style(1080, 1920), "Fontsize"))
        assert big > small  # proportional, not fixed


class TestPresetAwareWrap:
    def test_shorts_wrap_shorter(self):
        assert r._subtitle_max_chars(1080, 1920) == 20
        assert r._subtitle_max_chars(1920, 1080) == 42

    def test_shorter_wrap_makes_more_cues(self):
        narration = ("Typed memory is not a database feature it is a contract "
                     "with your future self and it changes how agents remember.")
        d = pathlib.Path(tempfile.mkdtemp())
        assert r._write_srt_for_scene(narration, 6.0, d / "s.srt", max_chars=20)
        assert r._write_srt_for_scene(narration, 6.0, d / "w.srt", max_chars=42)
        short_cues = (d / "s.srt").read_text().count("-->")
        wide_cues = (d / "w.srt").read_text().count("-->")
        assert short_cues > wide_cues

    def test_empty_narration_writes_no_srt(self):
        d = pathlib.Path(tempfile.mkdtemp())
        assert r._write_srt_for_scene("", 5.0, d / "e.srt") is False


class TestEncodeProfileIsYouTubeSpec:
    def test_youtube_profile_matches_upload_spec(self):
        args = r._encode_args_for_kind("mp4_youtube", "shorts_9_16")
        joined = " ".join(args)
        assert "-crf 18" in joined and "libx264" in joined
        assert "high" in joined and "yuv420p" in joined
        assert "-b:a 192k" in joined and "-ar 48000" in joined
        assert "+faststart" in joined

    def test_shorts_canvas_is_1080x1920_30fps(self):
        assert r._resolution_for_preset("shorts_9_16") == (1080, 1920, 30)

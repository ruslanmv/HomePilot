"""
Background music track selection.

Placeholder for phase-1: returns a deterministic track id per
(mode, mood) pair. Phase 2 loads a real music library.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MusicTrack:
    """Minimal track descriptor — the player needs only id + url."""
    id: str
    url: str
    mood: str
    duration_sec: float = 0.0


_PLACEHOLDER_TRACKS = {
    ("sfw_general", "warm"): MusicTrack("t_sfw_warm", "/static/music/warm.mp3", "warm", 60),
    ("sfw_education", "neutral"): MusicTrack("t_edu_neutral", "/static/music/study.mp3", "neutral", 90),
    ("language_learning", "warm"): MusicTrack("t_lang_warm", "/static/music/lesson.mp3", "warm", 90),
    ("enterprise_training", "neutral"): MusicTrack("t_ent_neutral", "/static/music/corp.mp3", "neutral", 120),
    ("social_romantic", "warm"): MusicTrack("t_soc_warm", "/static/music/romance.mp3", "warm", 120),
    ("mature_gated", "playful"): MusicTrack("t_mat_playful", "/static/music/mature.mp3", "playful", 120),
}


def pick_music_track(mode: str, mood: str = "neutral") -> MusicTrack:
    """Return a track for the given (mode, mood) combination.

    Falls back to (mode, 'neutral') then to a hard default so the
    caller always gets something.
    """
    return (
        _PLACEHOLDER_TRACKS.get((mode, mood))
        or _PLACEHOLDER_TRACKS.get((mode, "neutral"))
        or MusicTrack("t_default", "/static/music/default.mp3", "neutral", 60.0)
    )

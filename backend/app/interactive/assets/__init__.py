"""
Asset adapter subsystem.

Wires scene plans to HomePilot's existing generation stack
(studio image/video, voice_call TTS, file_assets registration).
Every adapter here is a thin translator between the interactive
service's domain types and the external APIs — NO writes back to
non-interactive tables beyond ``file_assets`` (which accepts
arbitrary ``kind`` strings).

Submodules:

  avatar.py    Register an existing studio video for use as an
               interactive segment; placeholder for new generation.
  voice.py     Produce TTS clips; registers output in file_assets
               with ``kind='interactive_voice'``.
  music.py     Background audio selection from asset library.
  library.py   Seed + query the ix_character_assets library.
"""
from .avatar import attach_existing_asset, register_interactive_segment
from .library import (
    query_library,
    register_library_asset,
    seed_library_defaults,
)
from .music import MusicTrack, pick_music_track
from .voice import VoiceClip, synthesize_voice_clip

__all__ = [
    "attach_existing_asset",
    "register_interactive_segment",
    "query_library",
    "register_library_asset",
    "seed_library_defaults",
    "MusicTrack",
    "pick_music_track",
    "VoiceClip",
    "synthesize_voice_clip",
]

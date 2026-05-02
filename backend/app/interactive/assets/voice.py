"""
TTS adapter.

Phase 1: synthesize_voice_clip is a placeholder that returns a
``VoiceClip`` descriptor WITHOUT actually calling a TTS engine.
It registers a placeholder row in ``file_assets`` so the downstream
pipeline (ix_character_assets, node.audio_asset_id) can reference
an id that exists in the schema.

Phase 2: swap the placeholder body for a real call to
``voice_call.turn.run_turn`` / the SpeechService shim — same
signature, no call-site changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class VoiceClip:
    """Descriptor returned by synthesize_voice_clip."""
    asset_id: str
    rel_path: str
    duration_sec: float
    voice: str
    language: str


def synthesize_voice_clip(
    *,
    text: str,
    voice: str = "default",
    language: str = "en",
    user_id: str = "",
) -> VoiceClip:
    """Produce a ``VoiceClip`` for the given text.

    Phase 1 is a placeholder — it registers a file_assets row with
    a fake rel_path so tests + downstream code have an asset_id to
    reference. No actual audio is produced.

    The ``user_id`` is used for data-layer scoping — matches the
    rest of HomePilot's asset-ownership model.
    """
    # Lazy import so test collectors that don't touch voice don't
    # need to resolve this module's dependency.
    try:
        from ..._safe_file_insert import insert_asset  # type: ignore[import-not-found]
    except Exception:
        try:
            from ...files import insert_asset  # type: ignore[no-redef]
        except Exception:
            insert_asset = None  # type: ignore[assignment]

    est_sec = max(1.0, len((text or "").split()) / 2.5)
    rel_path = f"interactive/placeholder/{voice}_{language}.mp3"

    asset_id = ""
    if insert_asset:
        try:
            asset_id = insert_asset(
                user_id=user_id,
                kind="interactive_voice",
                rel_path=rel_path,
                mime="audio/mpeg",
                size_bytes=0,
                original_name=f"voice_{voice}_{language}.mp3",
            )
        except Exception:
            # Insert failing shouldn't prevent planning — return a
            # descriptor with an empty asset_id so the caller knows
            # the persistence step was a no-op.
            asset_id = ""

    return VoiceClip(
        asset_id=asset_id,
        rel_path=rel_path,
        duration_sec=est_sec,
        voice=voice,
        language=language,
    )

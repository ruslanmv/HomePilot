"""Regression tests for ``_media_kind_from_url``.

The initial-scene payload in the play route uses this helper to tell the
player whether to mount <img> or <video>. Before the AVIF entry was
added, AVIF scene assets landed as ``media_kind='unknown'`` and the
Standard player fell through to "Scene not available yet." — this file
guards that fix.
"""
from app.interactive.routes.play import _media_kind_from_url


def test_media_kind_from_url_detects_avif_as_image():
    assert _media_kind_from_url("/files/scene.avif") == "image"
    assert (
        _media_kind_from_url("https://cdn.example.com/scene.avif?sig=abc")
        == "image"
    )


def test_media_kind_from_url_detects_standard_image_extensions():
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        assert _media_kind_from_url(f"/files/scene{ext}") == "image"
        assert (
            _media_kind_from_url(f"https://cdn.example.com/scene{ext}?v=1")
            == "image"
        )


def test_media_kind_from_url_detects_video_extensions():
    for ext in (".mp4", ".webm", ".mov", ".mkv", ".m4v"):
        assert _media_kind_from_url(f"/files/clip{ext}") == "video"


def test_media_kind_from_url_unknown_when_no_known_extension():
    assert _media_kind_from_url("https://cdn.example.com/assets/123") == "unknown"
    assert _media_kind_from_url("") == "unknown"
    assert _media_kind_from_url("/files/no-extension") == "unknown"

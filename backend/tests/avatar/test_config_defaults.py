"""The ``avatar:`` config block ships off, and its key set is frozen.

Spec v1.1 §1 kill switch: ``avatar.enabled=false`` makes every new server path inert.
Spec v1.1 §0.5: flags default off, and a default is never flipped in the PR that
introduces the feature. This file is what makes both statements checkable rather than
aspirational, from B0 onward.

The module under test has no FastAPI dependency and no side effects, so these tests run
without the backend requirements installed — deliberately, because a config block nobody
can check without a full environment is a config block nobody checks.
"""

from __future__ import annotations

from app.avatar_director import load_config
from app.avatar_director.config import AvatarDirectorConfig

# Every environment variable the block reads. Cleared before each test so a developer's
# shell cannot make an "off by default" assertion pass or fail by accident.
AVATAR_ENV_VARS = [
    "AVATAR_ENABLED",
    "AVATAR_VISION_MODEL",
    "AVATAR_VISION_MAX_IMAGE_PX",
    "AVATAR_FRAMES_RETENTION",
    "AVATAR_CURIOSITY_SESSION_BUDGET",
    "AVATAR_CURIOSITY_MIN_GAP_MS",
    "AVATAR_CURIOSITY_MIN_SESSION_AGE_MS",
    "AVATAR_VOICE_ENABLED",
    "AVATAR_VOICE_MODEL",
    "AVATAR_VOICE_MEDIA",
    "AVATAR_KB_MANIFEST",
    "AVATAR_ADULT_ENABLED",
    "AVATAR_ADULT_PROVIDER",
    "AVATAR_REDACTION_ENABLED",
]


def _clean_env(monkeypatch):
    for name in AVATAR_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_ships_disabled(monkeypatch):
    _clean_env(monkeypatch)
    cfg = load_config()
    assert cfg.enabled is False
    assert cfg.adult.enabled is False
    assert cfg.voice.enabled is False


def test_adult_is_a_second_gate_never_implied_by_enabled(monkeypatch):
    """Turning the director on must not turn the adult tier on with it (addendum §16.1)."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("AVATAR_ENABLED", "true")
    cfg = load_config()
    assert cfg.enabled is True
    assert cfg.adult.enabled is False


def test_privacy_defaults(monkeypatch):
    """§6.13 retention 0, §6.13 768 px cap, §16.5 redaction on."""
    _clean_env(monkeypatch)
    cfg = load_config()
    assert cfg.frames.retention == 0
    assert cfg.vision.max_image_px == 768
    assert cfg.redaction.enabled is True


def test_curiosity_budget_default(monkeypatch):
    """§6.12: a bounded per-session initiative budget, not an unbounded one."""
    _clean_env(monkeypatch)
    assert load_config().curiosity.session_budget == 4


def test_owner_attest_is_the_default_verification_provider(monkeypatch):
    """Addendum §16.2. B28 makes this provider refuse to load on a multi-user instance."""
    _clean_env(monkeypatch)
    assert load_config().adult.provider == "owner-attest"
    monkeypatch.setenv("AVATAR_ADULT_PROVIDER", "   ")
    assert load_config().adult.provider == "owner-attest"


def test_key_set_is_frozen():
    """Batches add keys; they do not rename them. A rename breaks every later batch."""
    assert sorted(AvatarDirectorConfig().as_dict()) == sorted(
        [
            "enabled",
            "vision.model",
            "vision.max_image_px",
            "frames.retention",
            "curiosity.session_budget",
            "curiosity.min_gap_ms",
            "curiosity.min_session_age_ms",
            "voice.enabled",
            "voice.model",
            "voice.media",
            "kb.manifest",
            "adult.enabled",
            "adult.provider",
            "redaction.enabled",
        ]
    )


def test_flags_read_the_environment_but_only_recognisable_truths(monkeypatch):
    _clean_env(monkeypatch)
    for truthy in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("AVATAR_ENABLED", truthy)
        assert load_config().enabled is True, truthy
    for falsey in ("0", "false", "no", "off", "", "maybe"):
        monkeypatch.setenv("AVATAR_ENABLED", falsey)
        assert load_config().enabled is False, falsey


def test_malformed_numbers_fall_back_to_the_safe_default(monkeypatch):
    """A typo in the environment must not silently widen a privacy limit."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("AVATAR_FRAMES_RETENTION", "lots")
    monkeypatch.setenv("AVATAR_VISION_MAX_IMAGE_PX", "")
    cfg = load_config()
    assert cfg.frames.retention == 0
    assert cfg.vision.max_image_px == 768


def test_importing_the_package_mounts_nothing():
    """Importing the package costs a dataclass and some ``os.getenv`` calls.

    B0 asserted ``register`` did not exist yet; B8 added it, and the claim that matters is
    now stronger than "the entry point is absent": the entry point is present, and importing
    it still drags in no transport. ``tests/avatar/test_registration.py`` holds the other
    half — that calling it while disabled imports nothing either.
    """
    import sys

    import app.avatar_director as pkg

    assert callable(pkg.register)
    assert pkg.__all__ == ["AvatarDirectorConfig", "load_config", "register"]
    assert "app.avatar_director.session" not in sys.modules

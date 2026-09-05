"""Local speech, and where a meeting's audio is allowed to go (LS1, LS2).

Two defects, one of them a privacy defect that nobody could see.

**LS1 — "Not configured" was a packaging state, not a configuration one.**
``requirements.txt`` never installed ``faster-whisper``, and ``WhisperLocalSTTProvider``
reports itself available only when the package imports *and* ``WHISPER_MODEL`` is set. So a
normal install said "Meeting transcription — Not configured" however it was configured, and
the Settings card taught an environment variable to somebody who wanted to record a meeting.

**LS2 — a configured remote endpoint silently won.** ``_build_stt_provider`` returns the
OpenAI-compatible provider before it constructs the local one. That is defensible for voice
calls. For a meeting recorder it means somebody who set ``STT_BASE_URL`` months ago for calls
has had every hour of meeting audio shipped there, with nothing in the product saying so.

The load-bearing test is the last one: **a meeting must not reach a remote endpoint that is
configured, working, and not chosen.** Everything else here is the behaviour that makes that
safe to ship.
"""

from __future__ import annotations

import pytest

from app.voice import providers as vp


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("STT_BASE_URL", "STT_API_KEY", "WHISPER_MODEL", "MEETINGSENSE_STT_POLICY"):
        monkeypatch.delenv(name, raising=False)
    vp.reset_stt_provider_cache()
    vp.reset_meeting_stt_provider_cache()
    yield
    vp.reset_stt_provider_cache()
    vp.reset_meeting_stt_provider_cache()


def _local_is(monkeypatch, available: bool):
    """Pretend faster-whisper is (or is not) installed, without installing it."""
    monkeypatch.setattr(
        vp.WhisperLocalSTTProvider, "available", property(lambda self: available)
    )


def _remote_is(monkeypatch, available: bool):
    monkeypatch.setattr(
        vp.OpenAICompatSTTProvider, "available", property(lambda self: available)
    )


# ── LS1: packaging ──────────────────────────────────────────────────────────


def test_a_model_no_longer_has_to_be_named_by_hand():
    # The whole of what a person does is install the speech package. Requiring an environment
    # variable on top of that is what produced "Not configured" on a working install.
    assert vp.WhisperLocalSTTProvider().model_name == vp.WhisperLocalSTTProvider.DEFAULT_MODEL


def test_an_explicit_model_still_wins(monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL", "large-v3-turbo")
    assert vp.WhisperLocalSTTProvider().model_name == "large-v3-turbo"


def test_the_speech_requirements_stay_pinned():
    # This is the layer where "it worked last week" goes wrong quietly: CTranslate2 carries a
    # native ABI, and a range would let that change arrive on its own.
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2] / "requirements"
    for name in ("speech-cpu.txt", "speech-cuda12.txt"):
        text = (root / name).read_text()
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-r "):
                continue
            assert re.match(r"^[A-Za-z0-9._-]+==\d", line), f"{name}: {line!r} is not pinned"


def test_the_whisper_extra_matches_the_cpu_requirements():
    # Two ways in — `pip install .[whisper]` and the requirements file the docs point at —
    # and they have to install the same thing or one of them is a trap.
    import pathlib
    import re
    import tomllib

    backend = pathlib.Path(__file__).resolve().parents[2]
    extra = set(tomllib.loads((backend / "pyproject.toml").read_text())["project"]["optional-dependencies"]["whisper"])
    pinned = {
        line.strip()
        for line in (backend / "requirements" / "speech-cpu.txt").read_text().splitlines()
        if re.match(r"^[A-Za-z0-9._-]+==\d", line.strip())
    }
    assert extra == pinned


# ── LS2: whose speech service ───────────────────────────────────────────────


def test_a_meeting_prefers_local_even_when_a_remote_endpoint_is_configured(monkeypatch):
    monkeypatch.setenv("STT_BASE_URL", "https://speech.example")
    _local_is(monkeypatch, True)
    _remote_is(monkeypatch, True)
    assert vp.get_meeting_stt_provider().name == "whisper-local"


def test_voice_calls_keep_the_behaviour_they_had(monkeypatch):
    # LS2 changes what a *meeting* does. A voice call that has always used a configured
    # endpoint must go on using it, or this batch breaks a working feature to fix another.
    monkeypatch.setenv("STT_BASE_URL", "https://speech.example")
    _local_is(monkeypatch, True)
    _remote_is(monkeypatch, True)
    assert vp.get_stt_provider().name == "openai-compat"


def test_a_meeting_never_falls_back_to_the_cloud_when_local_is_missing(monkeypatch):
    # The load-bearing claim. A CUDA library failing, or a package not installed, is not
    # consent — a privacy boundary must not be crossed as error recovery.
    monkeypatch.setenv("STT_BASE_URL", "https://speech.example")
    _local_is(monkeypatch, False)
    _remote_is(monkeypatch, True)
    provider = vp.get_meeting_stt_provider()
    assert provider.name == "null"
    assert provider.available is False


def test_choosing_remote_is_something_the_user_says(monkeypatch):
    monkeypatch.setenv("STT_BASE_URL", "https://speech.example")
    monkeypatch.setenv("MEETINGSENSE_STT_POLICY", "remote")
    _local_is(monkeypatch, True)
    _remote_is(monkeypatch, True)
    assert vp.get_meeting_stt_provider().name == "openai-compat"


def test_remote_chosen_but_unreachable_prefers_local_over_silence(monkeypatch):
    # They asked for a remote service, not for the meeting to go untranscribed.
    monkeypatch.setenv("MEETINGSENSE_STT_POLICY", "remote")
    _local_is(monkeypatch, True)
    _remote_is(monkeypatch, False)
    assert vp.get_meeting_stt_provider().name == "whisper-local"


def test_auto_restores_the_old_precedence_for_an_operator_who_asks(monkeypatch):
    monkeypatch.setenv("STT_BASE_URL", "https://speech.example")
    monkeypatch.setenv("MEETINGSENSE_STT_POLICY", "auto")
    _local_is(monkeypatch, True)
    _remote_is(monkeypatch, True)
    assert vp.get_meeting_stt_provider().name == "openai-compat"


def test_an_unrecognised_policy_is_the_safe_one(monkeypatch):
    monkeypatch.setenv("MEETINGSENSE_STT_POLICY", "whatever")
    assert vp.meeting_stt_policy() == "local"


def test_flipping_the_policy_takes_effect_without_a_restart(monkeypatch):
    monkeypatch.setenv("STT_BASE_URL", "https://speech.example")
    _local_is(monkeypatch, True)
    _remote_is(monkeypatch, True)
    assert vp.get_meeting_stt_provider().name == "whisper-local"
    monkeypatch.setenv("MEETINGSENSE_STT_POLICY", "remote")
    assert vp.get_meeting_stt_provider().name == "openai-compat"


# ── what the UI is told ─────────────────────────────────────────────────────


def test_status_reports_the_policy_and_whether_a_remote_is_actually_in_use(monkeypatch):
    from app.meetingsense import routes

    monkeypatch.setenv("STT_BASE_URL", "https://speech.example")
    _local_is(monkeypatch, True)
    _remote_is(monkeypatch, True)
    info = routes.stt_capability()
    assert info["policy"] == "local"
    # `remote` used to mean "one is configured somewhere". It now means "this meeting is
    # using one", which is the question the consent sheet is actually asking.
    assert info["remote"] is False
    assert info["remote_configured"] is True


def test_status_offers_the_configured_remote_rather_than_silently_dropping_it(monkeypatch):
    from app.meetingsense import routes

    monkeypatch.setenv("STT_BASE_URL", "https://speech.example")
    _local_is(monkeypatch, False)
    _remote_is(monkeypatch, True)
    info = routes.stt_capability()
    assert info["available"] is False
    assert info["offer_remote"] is True
    assert "unless you say so" in info["hint"]


def test_with_nothing_configured_the_hint_names_the_install_not_a_variable(monkeypatch):
    from app.meetingsense import routes

    _local_is(monkeypatch, False)
    _remote_is(monkeypatch, False)
    info = routes.stt_capability()
    assert info["offer_remote"] is False
    assert "WHISPER_MODEL" not in info["hint"]
    assert "speech-cpu.txt" in info["hint"]

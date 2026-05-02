"""
Tests for playback_config — env-driven feature flags + knobs.
"""
from __future__ import annotations

from app.interactive.playback.playback_config import load_playback_config


def test_defaults_are_on(monkeypatch):
    """Batteries-included: both LLM + render default to True
    when env unset, so a fresh install with Ollama + ComfyUI
    running locally works out of the box. Explicit opt-out still
    works (tested below)."""
    for key in [
        "INTERACTIVE_PLAYBACK_LLM",
        "INTERACTIVE_PLAYBACK_RENDER",
        "INTERACTIVE_PLAYBACK_LLM_TIMEOUT_S",
        "INTERACTIVE_PLAYBACK_LLM_MAX_TOKENS",
        "INTERACTIVE_PLAYBACK_LLM_TEMPERATURE",
        "INTERACTIVE_PLAYBACK_RENDER_WORKFLOW",
        "INTERACTIVE_PLAYBACK_RENDER_TIMEOUT_S",
    ]:
        monkeypatch.delenv(key, raising=False)
    cfg = load_playback_config()
    assert cfg.llm_enabled is True
    assert cfg.render_enabled is True
    assert cfg.llm_timeout_s == 12.0
    assert cfg.llm_max_tokens == 350
    assert abs(cfg.llm_temperature - 0.65) < 1e-9
    assert cfg.render_workflow == "animate"
    assert cfg.render_timeout_s == 180.0


def test_truthy_strings_enable_flags(monkeypatch):
    for value in ["1", "true", "True", "YES", "on", "y"]:
        monkeypatch.setenv("INTERACTIVE_PLAYBACK_LLM", value)
        monkeypatch.setenv("INTERACTIVE_PLAYBACK_RENDER", value)
        cfg = load_playback_config()
        assert cfg.llm_enabled is True, value
        assert cfg.render_enabled is True, value


def test_falsy_strings_explicitly_disable_flags(monkeypatch):
    """Users who don't want scene rendering can opt out via the
    canonical falsy tokens. Unknown tokens (e.g. "2", "nope")
    fall back to the default (True) rather than silently
    disabling, so a typo doesn't surprise-flip behaviour."""
    for value in ["0", "false", "off", "n", "no"]:
        monkeypatch.setenv("INTERACTIVE_PLAYBACK_LLM", value)
        monkeypatch.setenv("INTERACTIVE_PLAYBACK_RENDER", value)
        cfg = load_playback_config()
        assert cfg.llm_enabled is False, value
        assert cfg.render_enabled is False, value


def test_unknown_values_fall_back_to_default(monkeypatch):
    """Unknown tokens (neither truthy nor falsy) fall through to
    the built-in default — True, since these are the defaults."""
    for value in ["nope", "2", "dunno"]:
        monkeypatch.setenv("INTERACTIVE_PLAYBACK_LLM", value)
        monkeypatch.setenv("INTERACTIVE_PLAYBACK_RENDER", value)
        cfg = load_playback_config()
        assert cfg.llm_enabled is True, value
        assert cfg.render_enabled is True, value


def test_blank_env_treated_as_unset(monkeypatch):
    """A cleared Settings field (empty string) means "use the
    built-in default" — True today — not "force off"."""
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_LLM", "")
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_RENDER", "")
    cfg = load_playback_config()
    assert cfg.llm_enabled is True
    assert cfg.render_enabled is True


def test_numeric_overrides(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_LLM_TIMEOUT_S", "5.5")
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_LLM_MAX_TOKENS", "512")
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_LLM_TEMPERATURE", "0.2")
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_RENDER_TIMEOUT_S", "240")
    cfg = load_playback_config()
    assert cfg.llm_timeout_s == 5.5
    assert cfg.llm_max_tokens == 512
    assert abs(cfg.llm_temperature - 0.2) < 1e-9
    assert cfg.render_timeout_s == 240.0


def test_invalid_numeric_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_LLM_TIMEOUT_S", "not-a-number")
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_LLM_MAX_TOKENS", "")
    cfg = load_playback_config()
    assert cfg.llm_timeout_s == 12.0
    assert cfg.llm_max_tokens == 350


def test_workflow_name_override(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_RENDER_WORKFLOW", "animate_v2")
    cfg = load_playback_config()
    assert cfg.render_workflow == "animate_v2"


def test_workflow_empty_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_RENDER_WORKFLOW", "   ")
    cfg = load_playback_config()
    assert cfg.render_workflow == "animate"

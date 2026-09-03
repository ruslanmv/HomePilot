"""The MeetingSense config block ships off, and its key set is frozen (batch MS0).

Two statements the design makes that would otherwise be aspirational:

* every flag defaults off, and **none of the six sub-flags is implied by the master** — so
  turning MeetingSense on never turns on a capability a later wave built;
* a default is never flipped in the batch that introduces the feature.

The module under test imports no FastAPI and touches no disk, so these run without the
backend requirements installed — deliberately, because a config block nobody can check
without a full environment is a config block nobody checks.
"""

from __future__ import annotations

import pytest

from app.meetingsense.config import (
    RETENTION_MODES,
    MeetingSenseConfig,
    load_config,
)

#: Every environment variable the block reads. Cleared before each test so a developer's
#: shell cannot make an "off by default" assertion pass or fail by accident.
MS_ENV_VARS = [
    "MEETINGSENSE_ENABLED",
    "MEETINGSENSE_REMOTE",
    "MEETINGSENSE_TOGETHER",
    "MEETINGSENSE_CATALOG",
    "MEETINGSENSE_MCP",
    "MEETINGSENSE_AGENT",
    "MEETINGSENSE_MODES",
    "MEETINGSENSE_RETENTION",
    "MEETINGSENSE_NOTES_INTERVAL_S",
    "MEETINGSENSE_NOTES_MAX_WORDS",
    "MEETINGSENSE_NOTES_MODEL",
    "MEETINGSENSE_VISION_MODEL",
    "MEETINGSENSE_MAX_KEYFRAMES_PER_HOUR",
    "MEETINGSENSE_PANEL_MAX_KB",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in MS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# ── off, and off in every direction ─────────────────────────────────────────


def test_everything_ships_off():
    cfg = load_config()
    assert cfg.enabled is False
    assert cfg.flags.as_dict() == {
        "remote": False,
        "together": False,
        "catalog": False,
        "mcp": False,
        "agent": False,
        "modes": False,
    }


def test_the_master_flag_implies_no_sub_flag(monkeypatch):
    # The property that lets a wave land its code before its capability is wanted: enabling
    # the recorder must not silently enable the agent, the modes, or the remote transport.
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
    cfg = load_config()
    assert cfg.enabled is True
    assert not any(cfg.flags.as_dict().values())


@pytest.mark.parametrize(
    "name,attr",
    [
        ("MEETINGSENSE_REMOTE", "remote"),
        ("MEETINGSENSE_TOGETHER", "together"),
        ("MEETINGSENSE_CATALOG", "catalog"),
        ("MEETINGSENSE_MCP", "mcp"),
        ("MEETINGSENSE_AGENT", "agent"),
        ("MEETINGSENSE_MODES", "modes"),
    ],
)
def test_each_sub_flag_turns_on_only_itself(monkeypatch, name, attr):
    monkeypatch.setenv(name, "true")
    flags = load_config().flags.as_dict()
    assert flags[attr] is True
    assert sum(flags.values()) == 1


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
def test_recognised_true_values(monkeypatch, raw):
    monkeypatch.setenv("MEETINGSENSE_ENABLED", raw)
    assert load_config().enabled is True


@pytest.mark.parametrize("raw", ["0", "false", "off", "no", "", "  ", "maybe"])
def test_anything_else_is_false(monkeypatch, raw):
    # Including "maybe": an unreadable flag must not enable a recorder.
    monkeypatch.setenv("MEETINGSENSE_ENABLED", raw)
    assert load_config().enabled is False


# ── retention fails toward keeping less ─────────────────────────────────────


def test_retention_defaults_to_text_only():
    assert load_config().retention == "text"


@pytest.mark.parametrize("mode", RETENTION_MODES)
def test_every_documented_retention_mode_is_accepted(monkeypatch, mode):
    monkeypatch.setenv("MEETINGSENSE_RETENTION", mode)
    assert load_config().retention == mode


@pytest.mark.parametrize("raw", ["everything", "TEXT+AUDIO", "", "keep-it-all"])
def test_an_unreadable_retention_keeps_the_least(monkeypatch, raw):
    # The direction matters. Falling back to "all" would mean a typo in an env file causes a
    # machine to start keeping meeting audio nobody asked it to keep.
    monkeypatch.setenv("MEETINGSENSE_RETENTION", raw)
    assert load_config().retention == "text"


def test_retention_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("MEETINGSENSE_RETENTION", "  Text+Frames  ")
    assert load_config().retention == "text+frames"


# ── tuning knobs ────────────────────────────────────────────────────────────


def test_tuning_defaults_match_the_design():
    cfg = load_config()
    assert cfg.notes.interval_s == 60
    assert cfg.notes.max_words == 400
    assert cfg.vision.max_keyframes_per_hour == 60
    # Mirrors avatar_director.panels.DEFAULT_MAX_KB — the two must stay equal, because a
    # card that passes one side's check and fails the other renders as a blank screen.
    assert cfg.panels.max_kb == 64


def test_the_panel_limit_matches_the_avatar_panel_limit():
    from app.avatar_director.panels import DEFAULT_MAX_KB

    assert load_config().panels.max_kb == DEFAULT_MAX_KB


@pytest.mark.parametrize("raw", ["not-a-number", "", "12.5"])
def test_a_junk_integer_falls_back_rather_than_raising(monkeypatch, raw):
    monkeypatch.setenv("MEETINGSENSE_NOTES_INTERVAL_S", raw)
    assert load_config().notes.interval_s == 60


def test_models_are_empty_until_configured():
    cfg = load_config()
    assert cfg.notes.model == ""
    assert cfg.vision.model == ""


# ── the key set is the contract ─────────────────────────────────────────────


def test_the_key_set_is_frozen():
    # Batches add keys; they do not rename them. A rename is a silently ignored env var on
    # every machine that already set the old name, which is the worst kind of config bug.
    assert set(load_config().as_dict()) == {
        "enabled",
        "retention",
        "flags.remote",
        "flags.together",
        "flags.catalog",
        "flags.mcp",
        "flags.agent",
        "flags.modes",
        "notes.interval_s",
        "notes.max_words",
        "notes.model",
        "vision.model",
        "vision.max_keyframes_per_hour",
        "panels.max_kb",
        "resume.grace_s",
        "resume.max_replay",
    }


def test_the_config_is_immutable():
    cfg = load_config()
    with pytest.raises(Exception):
        cfg.enabled = True  # type: ignore[misc]


def test_load_config_reads_the_environment_each_call(monkeypatch):
    # Not module-level state: the status route calls this per request, and an operator who
    # edits .env and restarts should not need to reason about import order.
    assert load_config().enabled is False
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
    assert load_config().enabled is True


def test_a_default_constructed_config_is_the_off_config():
    # The dataclass defaults and the env defaults must agree, or "ships off" depends on
    # which of the two a reader happens to look at.
    assert MeetingSenseConfig().as_dict() == load_config().as_dict()

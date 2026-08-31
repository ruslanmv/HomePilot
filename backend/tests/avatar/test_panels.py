"""The panel channel, server side (B20).

This side owns two things: what a `display` may contain, and how big it may be. The
rendering is the client's, and the size limit is deliberately *not* also enforced there —
two ceilings eventually differ, and the one that can refuse is this one.

The acceptance sentence tested here is the second: **oversized payloads are rejected rather
than silently truncated.** A truncated agenda is an agenda with the afternoon missing, drawn
as confidently as a complete one, and the user has no way to tell. A refusal is legible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.avatar_director.config import AvatarDirectorConfig, PanelsConfig
from app.avatar_director.panels import (
    DEFAULT_MAX_KB,
    KINDS,
    MAX_ROWS,
    PanelError,
    build,
    measure,
    truncatable,
    validate,
)
from app.avatar_director.protocol import ProtocolHandler

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "protocol" / "s2c-display.json").read_text(encoding="utf-8")
)


def agenda(rows: int = 2, what: str = "Standup") -> dict:
    return {"title": "Today", "items": [{"at": f"{9 + i:02d}:30", "what": what} for i in range(rows)]}


# ── the shape ────────────────────────────────────────────────────────────────


class TestValidate:
    def test_the_shared_fixture_is_valid(self):
        message = FIXTURE["message"]
        assert validate(message["kind"], message["data"]) == []

    def test_every_kind_the_module_declares_is_accepted(self):
        for kind in KINDS:
            assert validate(kind, {"title": "x", "items": []}) == [], kind

    def test_an_unknown_kind_is_named_in_the_refusal(self):
        problems = validate("hologram", {})
        assert any("hologram" in p for p in problems)
        assert any("agenda" in p for p in problems), "the refusal should say what is allowed"

    def test_data_must_be_an_object(self):
        assert "data must be an object" in validate("agenda", "today")
        assert "data must be an object" in validate("agenda", ["a", "b"])

    def test_too_many_rows_is_refused_with_both_numbers(self):
        problems = validate("agenda", agenda(rows=MAX_ROWS["agenda"] + 5))
        assert len(problems) == 1
        assert str(MAX_ROWS["agenda"] + 5) in problems[0]
        assert str(MAX_ROWS["agenda"]) in problems[0]

    def test_exactly_the_limit_is_fine(self):
        assert validate("agenda", agenda(rows=MAX_ROWS["agenda"])) == []

    def test_each_kind_has_its_own_row_limit(self):
        # A panel is a screen, not a document. Twelve cards and forty tool-result rows are
        # different amounts of readable, which is why the limits are not one number.
        assert set(MAX_ROWS) == set(KINDS)
        assert MAX_ROWS["cards"] < MAX_ROWS["tool_result"]

    def test_validation_never_raises(self):
        for kind, data in [(None, None), ("agenda", None), ("", []), ("agenda", {"items": [1, 2]})]:
            assert isinstance(validate(kind, data), list)

    def test_a_row_that_is_neither_object_nor_string_is_named(self):
        problems = validate("agenda", {"items": [{"at": "9"}, 42]})
        assert any("row 1" in p for p in problems)


# ── the size limit ───────────────────────────────────────────────────────────


class TestSizeLimit:
    def test_a_normal_agenda_is_nowhere_near_it(self):
        message = build("agenda", agenda())
        assert measure(message) < 1024

    def test_an_oversized_payload_is_rejected(self):
        with pytest.raises(PanelError) as raised:
            build("agenda", {"title": "x", "items": [{"at": "09:00", "what": "y" * 100_000}]})
        assert raised.value.code == "panel_too_large"

    def test_and_the_refusal_names_the_size_in_both_units(self):
        # "68210 bytes" and "over 64 KB" answer different questions, and a sender needs both
        # to decide what to cut.
        with pytest.raises(PanelError) as raised:
            build("agenda", {"title": "x", "items": [{"at": "09:00", "what": "y" * 100_000}]})
        detail = raised.value.detail
        assert "bytes" in detail
        assert "64 KB" in detail

    def test_nothing_is_ever_truncated(self):
        """The acceptance sentence. A refusal is legible; a silent trim is a lie the screen
        tells, and the user cannot tell a shortened agenda from a short day."""
        big = agenda(rows=4, what="z" * 30_000)
        original = json.dumps(big, sort_keys=True)

        with pytest.raises(PanelError):
            build("agenda", big)

        # The caller's own object is untouched — not shortened, not copied-and-shortened.
        assert json.dumps(big, sort_keys=True) == original
        assert len(big["items"]) == 4
        assert len(big["items"][0]["what"]) == 30_000

    def test_the_limit_is_on_the_wire_shape_not_the_data(self):
        # A small object with one enormous string in it costs what a large object costs, so
        # the check is on the serialised message.
        one_field = {"title": "x" * 70_000, "items": []}
        with pytest.raises(PanelError) as raised:
            build("agenda", one_field)
        assert raised.value.code == "panel_too_large"

    def test_the_limit_comes_from_config(self):
        small = {"title": "x" * 3000, "items": []}
        assert build("agenda", small, max_kb=64)
        with pytest.raises(PanelError):
            build("agenda", small, max_kb=1)

    def test_a_nonsense_limit_does_not_become_no_limit(self):
        for bad in (0, -5):
            with pytest.raises(PanelError):
                build("agenda", {"title": "x" * 5000, "items": []}, max_kb=bad)

    def test_shape_is_reported_before_size(self):
        # A malformed panel that is also too large should be reported as malformed: that is
        # the fault the sender can act on.
        with pytest.raises(PanelError) as raised:
            build("hologram", {"title": "x" * 100_000, "items": []})
        assert raised.value.code == "panel_invalid"

    def test_the_default_matches_the_client_config(self):
        assert DEFAULT_MAX_KB == 64
        assert AvatarDirectorConfig().panels.max_kb == 64

    def test_the_config_key_is_readable_and_typo_safe(self, monkeypatch):
        from app.avatar_director import load_config

        monkeypatch.setenv("AVATAR_PANEL_MAX_KB", "128")
        assert load_config().panels.max_kb == 128
        monkeypatch.setenv("AVATAR_PANEL_MAX_KB", "lots")
        assert load_config().panels.max_kb == 64


class TestTruncatableIsAdviceNotAction:
    """`truncatable` tells a caller what would have to go. It does not do it — nothing in
    this module shortens anything, which is the whole point of the batch."""

    def test_a_panel_that_fits_says_so(self):
        assert truncatable("agenda", agenda()) == (True, None)

    def test_one_that_does_not_says_roughly_how_much_would_have_to_go(self):
        fits, advice = truncatable("agenda", {"title": "x", "items": [{"at": "9", "what": "y" * 4000} for _ in range(20)]})
        assert fits is False
        assert "rows would have to go" in advice

    def test_it_changes_nothing(self):
        data = agenda(rows=20, what="y" * 4000)
        before = json.dumps(data, sort_keys=True)
        truncatable("agenda", data)
        assert json.dumps(data, sort_keys=True) == before

    def test_a_payload_with_no_rows_to_drop_says_that_instead(self):
        fits, advice = truncatable("agenda", {"title": "x" * 100_000, "items": []})
        assert fits is False
        assert "no rows to drop" in advice

    def test_an_invalid_panel_reports_the_invalidity_rather_than_advice(self):
        fits, advice = truncatable("hologram", {})
        assert fits is False
        assert "hologram" in advice


# ── the one door ─────────────────────────────────────────────────────────────


class TestOneDoor:
    def test_the_handler_builds_a_display_through_the_validator(self):
        handler = ProtocolHandler()
        message = handler.display("agenda", agenda())
        assert message["type"] == "display"
        assert message["kind"] == "agenda"
        assert message["v"] == 1

    def test_and_refuses_an_oversized_one_rather_than_emitting_it(self):
        handler = ProtocolHandler()
        with pytest.raises(PanelError):
            handler.display("agenda", {"title": "x" * 100_000, "items": []})

    def test_the_built_message_matches_the_shared_fixture_shape(self):
        handler = ProtocolHandler()
        built = handler.display(FIXTURE["message"]["kind"], FIXTURE["message"]["data"])
        assert sorted(built) == sorted(FIXTURE["required"])
        assert built == FIXTURE["message"]

    def test_display_is_a_declared_server_type(self):
        from app.avatar_director.protocol import SERVER_TYPES

        assert "display" in SERVER_TYPES

    def test_the_module_shortens_nothing(self):
        """The structural half. If a later batch wants a trimming panel it has to get past
        this test to add one — which is the moment to have the argument, not afterwards."""
        source = (Path(__file__).resolve().parents[2] / "app" / "avatar_director" / "panels.py").read_text(
            encoding="utf-8"
        )
        body = source.split('"""', 2)[2]
        for forbidden in ("[:max", "[: max", ".pop(", "del data", "slice("):
            assert forbidden not in body, f"panels.py names {forbidden}"

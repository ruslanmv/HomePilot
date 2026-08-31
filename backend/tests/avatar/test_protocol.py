"""Session protocol contract tests (spec v1.1 §6.9, batch B8).

Driven by ``backend/tests/fixtures/protocol/*.json`` — the same bytes the client repo holds
— because the point of a shared fixture set is that neither side gets to be the one that
decides what a message looks like. The mock and these tests were written before the
endpoint, per the batch plan.

Nothing here needs a socket: ``protocol.py`` is where the decisions are, and the transport
only moves bytes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.avatar_director.protocol import (
    CLIENT_TYPES,
    EMOTE_WHITELIST,
    PROTOCOL_VERSION,
    SERVER_TYPES,
    ProtocolHandler,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "protocol"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture()
def index() -> dict:
    return load("index.json")


@pytest.fixture()
def handler() -> ProtocolHandler:
    return ProtocolHandler(authenticate=lambda token: token == "good-token")


def hello(handler: ProtocolHandler) -> None:
    replies = handler.handle({"v": 1, "type": "hello", "client": "3dac", "caps": [], "auth": "good-token"})
    assert handler.state.authenticated, replies


# ── every message shape round-trips ──────────────────────────────────────────


def test_every_client_fixture_is_handled(index, handler):
    """The acceptance criterion: every shape in the fixture set is understood."""
    hello(handler)
    for entry in index["fixtures"]:
        if entry["direction"] != "client->server":
            continue
        fixture = load(entry["file"])
        replies = handler.handle(fixture["message"])
        # A reply is optional; not raising and not erroring on a known type is the contract.
        for reply in replies:
            assert reply["type"] in SERVER_TYPES, f"{entry['name']} produced an unknown reply"
            assert reply["v"] == PROTOCOL_VERSION


def test_every_server_fixture_matches_what_the_server_can_build(index, handler):
    builders = {
        "intent": lambda f: handler.intent(f["message"]["name"], f["message"]["intensity"], f["message"]["source"]),
        "say": lambda f: handler.say(f["message"]["text"], f["message"]["source"]),
        "scene": lambda f: handler.scene(f["message"]["id"]),
        "ping": lambda f: handler.ping(),
        "error": lambda f: handler.error(f["message"]["code"], f["message"]["msg"]),
    }
    for entry in index["fixtures"]:
        if entry["direction"] != "server->client":
            continue
        fixture = load(entry["file"])
        build = builders.get(fixture["name"])
        if build is None:
            continue  # display / adult_ack / vision_insight arrive with B15, B20, B28
        assert build(fixture) == fixture["message"], fixture["name"]


def test_the_fixture_set_covers_every_type_this_server_knows(index):
    named = {entry["name"] for entry in index["fixtures"]}
    missing = (CLIENT_TYPES | SERVER_TYPES) - named
    assert not missing, f"no fixture for {sorted(missing)}"


# ── forward compatibility ────────────────────────────────────────────────────


def test_an_unknown_type_is_ignored_silently(handler):
    """The rule that lets addendum v1.2 add message types without a version bump."""
    hello(handler)
    fixture = load("s2c-unknown_type.json")
    assert handler.handle(fixture["message"]) == []
    assert handler.ignored == [fixture["message"]["type"]]


def test_ignoring_is_not_the_same_as_accepting_a_wrong_version(handler):
    hello(handler)
    replies = handler.handle({"v": 99, "type": "ctx"})
    assert replies[0]["code"] == "bad_version"


@pytest.mark.parametrize("junk", [None, [], "hello", 42, {}, {"type": 7}])
def test_malformed_input_never_raises(handler, junk):
    hello(handler)
    replies = handler.handle(junk)
    assert all(reply["type"] == "error" for reply in replies)


# ── auth ─────────────────────────────────────────────────────────────────────


def test_pairing_is_required_before_anything_else(handler):
    replies = handler.handle({"v": 1, "type": "ctx", "mode": "together"})
    assert replies[0]["code"] == "unauthenticated"


def test_a_bad_token_is_refused(handler):
    replies = handler.handle({"v": 1, "type": "hello", "client": "x", "caps": [], "auth": "wrong"})
    assert replies[0]["code"] == "unauthorized"
    assert not handler.state.authenticated


# ── a server intent gets no special powers ───────────────────────────────────


def test_the_server_may_not_invent_an_emote(handler):
    """§6.8. The client checks again; this is the belt, and the client is the braces."""
    with pytest.raises(ValueError):
        handler.intent("backflip")
    assert handler.intent("lean_in")["name"] in EMOTE_WHITELIST


def test_context_updates_are_recorded_for_the_curiosity_scheduler(handler):
    hello(handler)
    handler.handle(load("c2s-ctx.json")["message"])
    assert handler.state.mode == "together"
    assert handler.state.attention == pytest.approx(0.8)

    handler.handle(load("c2s-user_event.json")["message"])
    assert handler.state.last_event == "media:paused"


def test_streaks_are_kept_for_the_focus_activity(handler):
    hello(handler)
    handler.handle(load("c2s-streak.json")["message"])
    assert handler.state.streaks == {"focus": 4}


# ── the stubs refuse rather than lie ─────────────────────────────────────────


def test_vision_is_refused_until_b15_rather_than_left_hanging(handler):
    hello(handler)
    replies = handler.handle(load("c2s-vision_ask.json")["message"])
    assert replies[0]["code"] == "vision_unavailable"


def test_adult_verification_refuses_by_default(handler):
    """A placeholder that answered "verified" would be the failure §16.2 forbids."""
    hello(handler)
    replies = handler.handle(load("c2s-adult_verify_request.json")["message"])
    assert replies[0]["code"] == "adult_unavailable"

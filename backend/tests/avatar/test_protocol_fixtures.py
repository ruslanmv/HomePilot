"""Session-protocol fixtures — the cross-repo contract, checked from the server side.

``backend/tests/fixtures/protocol/`` is byte-identical to the client's
``tests/fixtures/protocol/`` in ruslanmv/3D-Avatar-Chatbot. Neither repo can see the
other, so byte-identity is held by ``CHECKSUMS.txt``: both repos carry the same manifest,
each verifies its own copy against it, and a fixture edited on one side goes red on that
side immediately and shows up as a checksum diff in review.

These assertions are deliberately the same ones the client's Jest suite makes. Two
runners, one contract: if the two suites ever disagree about what a message looks like,
that disagreement is the bug B8's mock server would otherwise ship.

Spec v1.1 §5.P6 and Appendix A: build the fixtures and the contract tests *before* the
endpoints. B8 writes ``session.py`` against these files, not the other way round.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "protocol"

# The forward-compatibility case deliberately carries a type no peer knows.
FORWARD_COMPAT = "unknown_type"

EXPECTED_NAMES = {
    # v1.1 §6.9 client -> server
    "hello",
    "ctx",
    "user_event",
    "vision_ask",
    "chat_meta",
    "pong",
    # v1.1 §6.9 server -> client
    "intent",
    "say",
    "vision_insight",
    "scene",
    "error",
    "ping",
    # addendum v1.2 §14.3
    "adult_verify_request",
    "streak",
    "display",
    "adult_ack",
    # v1.1 §6.10, batch B10 — the voice uplink
    "voice_offer",
    "voice_ice",
    "voice_transcript",
    "voice_end",
    "voice_answer",
    "voice_state",
    # forward compatibility
    FORWARD_COMPAT,
}


def _read(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index() -> dict:
    return _read("index.json")


@pytest.fixture(scope="module")
def fixtures(index) -> list[dict]:
    return [_read(entry["file"]) for entry in index["fixtures"]]


def test_index_and_directory_agree(index):
    on_disk = sorted(p.name for p in FIXTURE_DIR.glob("*.json") if p.name != "index.json")
    assert sorted(entry["file"] for entry in index["fixtures"]) == on_disk


def test_covers_every_message_type(index):
    assert {entry["name"] for entry in index["fixtures"]} == EXPECTED_NAMES


def test_protocol_version_is_one_everywhere(index, fixtures):
    assert index["protocolVersion"] == 1
    assert all(f["message"]["v"] == 1 for f in fixtures)


def test_every_required_field_is_present(fixtures):
    for f in fixtures:
        missing = [key for key in f["required"] if key not in f["message"]]
        assert not missing, f"{f['name']} is missing {missing}"


def test_type_matches_name_except_the_forward_compatibility_case(fixtures):
    for f in fixtures:
        if f["name"] == FORWARD_COMPAT:
            # The whole point: a type neither peer knows, which both must ignore silently
            # and keep the session open. Adding a message type is never a version bump.
            assert f["message"]["type"] != f["name"]
            assert "ignore it silently" in f["note"]
        else:
            assert f["message"]["type"] == f["name"]


def test_directions_are_declared_and_consistent(index, fixtures):
    for entry, f in zip(index["fixtures"], fixtures):
        assert f["direction"] == entry["direction"]
        assert f["direction"] in {"client->server", "server->client"}
        prefix = "c2s-" if f["direction"] == "client->server" else "s2c-"
        assert entry["file"].startswith(prefix)


def test_server_sent_intents_carry_a_source(fixtures):
    """§6.8: server intents get no special powers, and the client needs to know whose they
    are — the adult tier's source rule (addendum §16.4) turns on exactly this field."""
    by_name = {f["name"]: f for f in fixtures}
    assert by_name["intent"]["message"]["source"] == "curiosity"
    assert by_name["say"]["message"]["source"] == "curiosity"


def test_byte_identity_with_the_client_copy():
    manifest = (FIXTURE_DIR / "CHECKSUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    for line in manifest:
        expected, name = line.split()
        actual = hashlib.sha256((FIXTURE_DIR / name).read_bytes()).hexdigest()
        assert actual == expected, f"{name} differs from the shared manifest"


def test_manifest_covers_every_fixture():
    manifest = (FIXTURE_DIR / "CHECKSUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    hashed = sorted(line.split()[1] for line in manifest)
    assert hashed == sorted(p.name for p in FIXTURE_DIR.glob("*.json"))

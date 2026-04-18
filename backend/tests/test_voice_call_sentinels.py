"""
Protocol-sentinel drop contract for ``voice_call.ws``.

The frontend sends ``[phone-call-open]`` (and will send
``[phone-call-close]`` in a future commit) as a ``transcript.final``
payload to signal call-lifecycle transitions to backend state
machines. These strings MUST NOT reach the turn runner — otherwise
the LLM would produce a confused "I'm not sure what that means"
reply and the user would hear a double-greet.

This test pins the sentinel set + the contract that membership is
enforced at the TOP of the handler, before any LLM call.
"""
from __future__ import annotations

from app.voice_call import ws as _vc_ws


def test_protocol_sentinels_include_phone_call_open():
    """Frontend currently sends this exact literal. If either side
    changes the spelling both sides must agree — this test fails
    loudly on drift rather than letting the frontend's sentinel
    leak through as a literal LLM user turn."""
    assert "[phone-call-open]" in _vc_ws._PROTOCOL_SENTINELS


def test_protocol_sentinels_include_phone_call_close():
    """Reserved for the symmetric close-handshake signal the
    frontend is expected to send on end-of-call. Prevents it from
    leaking through before the client side ships."""
    assert "[phone-call-close]" in _vc_ws._PROTOCOL_SENTINELS


def test_protocol_sentinels_frozen():
    """The sentinel set is immutable at runtime — prevents a future
    caller from mutating it and sneaking new sentinels past review.
    ``frozenset`` is the canonical choice."""
    assert isinstance(_vc_ws._PROTOCOL_SENTINELS, frozenset)


def test_protocol_sentinels_do_not_match_blank_or_whitespace():
    """Defensive guard — a blank / whitespace-only text_in is
    already short-circuited by the ``if not text_in: continue``
    that precedes the sentinel check. If someone ever deletes that
    guard, the sentinel frozenset must NOT accidentally match a
    bare string."""
    assert "" not in _vc_ws._PROTOCOL_SENTINELS
    assert " " not in _vc_ws._PROTOCOL_SENTINELS
    assert "\n" not in _vc_ws._PROTOCOL_SENTINELS

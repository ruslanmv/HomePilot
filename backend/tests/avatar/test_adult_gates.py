"""B28 — the adult tier's gates, as invariants.

§16.7 asks for these to be written **before** the feature, and they are written the way
invariants are rather than the way features are: each one names a thing that must never
happen, and most of them would pass on an empty repository. That is the point — they are
still passing in a year, when somebody has added a batch nobody here anticipated.

The six, in §16.7's order:

  1. no path sets ``adultVerified`` client-side;
  2. an nsfw clip is selectable only with all three gates, a user source, and the ceiling;
  3. curiosity, vision and MCP sources can never select one;
  4. the recorder is torn down in adult mode;
  5. exits work from any state within one scheduler tick;
  6. minors are excluded by verification, not by honour.

Invariants 2, 3, 4 and 5 are client-side and live in ``tests/behavior/adult.test.js``.
This file owns 1 and 6, and the redaction fixtures §16.5 asks for.
"""

from __future__ import annotations

import inspect
import json
import re
import time

import pytest

from app.avatar_director import redaction, verification
from app.avatar_director.config import AdultConfig, AvatarDirectorConfig
from app.avatar_director.protocol import ProtocolHandler


def codeof(module) -> str:
    text = inspect.getsource(module)
    text = re.sub(r'"""[\s\S]*?"""', " ", text)
    text = re.sub(r"(^|[^:])#.*$", r"\1", text, flags=re.MULTILINE)
    return text


def enabled(provider: str = "owner-attest") -> AvatarDirectorConfig:
    return AvatarDirectorConfig(enabled=True, adult=AdultConfig(enabled=True, provider=provider))


def disabled() -> AvatarDirectorConfig:
    return AvatarDirectorConfig(enabled=True, adult=AdultConfig(enabled=False, provider="owner-attest"))


def hello(handler: ProtocolHandler) -> ProtocolHandler:
    handler.handle({"v": 1, "type": "hello", "client": "test", "auth": "token"})
    return handler


# ── invariant 1 · the server is the only thing that can verify ───────────────


class TestOnlyTheServerVerifies:
    def test_an_ack_is_produced_in_exactly_one_place(self):
        # A second emitter would be a second way to verify, and one of them would
        # eventually be reachable without a provider.
        from app.avatar_director import protocol

        source = codeof(protocol)
        assert source.count('"type": "adult_ack"') == 1

    def test_a_socket_with_no_attestation_session_refuses(self):
        handler = hello(ProtocolHandler())
        out = handler.handle({"v": 1, "type": "adult_verify_request"})
        assert out[0]["type"] == "error"
        assert out[0]["code"] == "adult_unavailable"
        assert handler.state.adult_verified is False

    def test_a_client_cannot_assert_its_way_in(self):
        # The frame carries no field the client could set to make this true. Sending one
        # anyway changes nothing.
        handler = hello(ProtocolHandler())
        handler.handle({"v": 1, "type": "adult_verify_request", "verified": True, "exp": 1e12})
        assert handler.state.adult_verified is False

    def test_a_forged_adult_ack_from_a_client_is_not_even_a_message_type(self):
        # `adult_ack` is server → client only. A client sending one is an unknown type and
        # is ignored, per §6.9 — it is not a message this server has a handler for.
        handler = hello(ProtocolHandler())
        assert handler.handle({"v": 1, "type": "adult_ack", "verified": True}) == []
        assert "adult_ack" in handler.ignored
        assert handler.state.adult_verified is False

    def test_verification_survives_no_reconnect(self):
        session = verification.Session(verification.OwnerAttestProvider(count_users=lambda: 1))
        session.request()
        assert session.verified is True
        session.reconnect()
        assert session.verified is False

    def test_an_expired_attestation_is_not_verified(self):
        # Checked on read, never a stored boolean: an expiry only checked when it is set is
        # an expiry that never fires.
        clock = [1000.0]
        session = verification.Session(
            verification.OwnerAttestProvider(ttl=60, count_users=lambda: 1), now=lambda: clock[0]
        )
        session.request()
        assert session.verified is True
        clock[0] += 61
        assert session.verified is False

    def test_revoking_is_immediate_and_cheap(self):
        session = verification.Session(verification.OwnerAttestProvider(count_users=lambda: 1))
        session.request()
        assert session.revoke("user") is True
        assert session.verified is False

    def test_an_attestation_carries_no_identity(self):
        attestation = verification.OwnerAttestProvider(count_users=lambda: 1).verify("someone")
        assert set(attestation.as_ack().keys()) == {"verified", "exp", "provider"}
        assert "someone" not in json.dumps(attestation.as_ack())


# ── invariant 6 · excluded by verification, not by honour ────────────────────


class TestOwnerAttestRefusesAMultiUserInstance:
    def test_it_loads_on_a_single_user_instance(self):
        provider = verification.OwnerAttestProvider(count_users=lambda: 1).load()
        assert provider.verify().verified is True

    def test_a_fresh_install_with_no_users_yet_is_still_one_person(self):
        assert verification.OwnerAttestProvider(count_users=lambda: 0).load()

    def test_it_refuses_two_accounts(self):
        # The owner attesting for everybody is attesting for people they have never met,
        # which is worse than no gate because it looks like one.
        with pytest.raises(verification.VerificationError) as caught:
            verification.OwnerAttestProvider(count_users=lambda: 2).load()
        assert caught.value.code == "provider_refuses_multi_user"

    def test_and_a_store_that_will_not_answer_is_not_a_yes(self):
        def broken():
            raise RuntimeError("the database is gone")

        with pytest.raises(verification.VerificationError) as caught:
            verification.OwnerAttestProvider(count_users=broken).load()
        assert caught.value.code == "provider_unavailable"

    def test_the_factory_degrades_to_a_refusing_provider_rather_than_raising(self):
        provider = verification.build_provider(enabled(), count_users=lambda: 5)
        assert isinstance(provider, verification.DisabledProvider)
        assert provider.verify().verified is False
        assert "single-user provider" in provider.verify().reason

    def test_a_click_yes_dialog_is_nowhere_in_this_module(self):
        source = codeof(verification)
        for token in ["confirm", "dialog", "prompt(", "checkbox", "i_am_18", "self_attest"]:
            assert token not in source

    def test_the_stripper_is_not_vacuous(self):
        assert "class OwnerAttestProvider" in codeof(verification)


class TestTheTierIsUnactivatableWhileDisabled:
    def test_a_disabled_tier_never_consults_the_named_provider(self):
        # Not "it is not advertised" — it cannot be reached. The factory returns a refusing
        # provider without asking the configured one anything.
        consulted = []

        def count():
            consulted.append(1)
            return 1

        provider = verification.build_provider(disabled(), count_users=count)
        assert isinstance(provider, verification.DisabledProvider)
        assert consulted == []

    def test_and_answers_no_to_every_request(self):
        session = verification.Session(verification.build_provider(disabled()))
        for _ in range(5):
            assert session.request().verified is False
        assert session.verified is False

    def test_an_unknown_provider_name_is_refused_not_defaulted(self):
        # Silently defaulting when somebody typos their real provider is how an instance
        # ends up with no gate and no warning.
        provider = verification.build_provider(enabled(provider="acme-id"), count_users=lambda: 1)
        assert isinstance(provider, verification.DisabledProvider)
        assert "acme-id" in provider.verify().reason

    def test_the_known_provider_set_is_closed(self):
        assert verification.PROVIDERS == ("owner-attest",)

    def test_the_disabled_provider_is_a_provider_not_a_none(self):
        # A null provider means every caller writes its own "if configured" branch, and one
        # of them eventually gets it wrong.
        assert isinstance(verification.build_provider(disabled()), verification.Provider)

    def test_a_disabled_instance_refuses_over_the_socket(self):
        session = verification.Session(verification.build_provider(disabled()))
        handler = hello(ProtocolHandler(adult=session))
        out = handler.handle({"v": 1, "type": "adult_verify_request"})
        assert out[0]["type"] == "adult_ack"
        assert out[0]["verified"] is False
        assert handler.state.adult_verified is False


class TestTheHappyPath:
    def test_an_enabled_single_user_instance_verifies(self):
        session = verification.Session(verification.build_provider(enabled(), count_users=lambda: 1))
        handler = hello(ProtocolHandler(adult=session))
        out = handler.handle({"v": 1, "type": "adult_verify_request"})
        assert out[0]["type"] == "adult_ack"
        assert out[0]["verified"] is True
        assert out[0]["provider"] == "owner-attest"
        assert handler.state.adult_verified is True

    def test_the_ack_expires(self):
        session = verification.Session(verification.build_provider(enabled(), count_users=lambda: 1))
        handler = hello(ProtocolHandler(adult=session))
        ack = handler.handle({"v": 1, "type": "adult_verify_request"})[0]
        assert ack["exp"] > time.time()
        assert ack["exp"] <= time.time() + verification.DEFAULT_TTL_SECONDS + 1

    def test_nothing_is_written_anywhere(self):
        # An attestation is a fact about a session. It has no storage, so revoking is
        # closing the tab.
        source = codeof(verification)
        for token in ["open(", "sqlite", "Path(", "upsert", "json.dump", "write"]:
            assert token not in source


# ── §16.5 · redaction ────────────────────────────────────────────────────────


#: What a curiosity write would look like without redaction. Deliberately written the way a
#: model would write it — prose, in fields the store already has.
EXPLICIT_RECORD = {
    "topic": "user.intimate.tuesday",
    "summary": "Recounted in detail what happened during the candlelit scene on Tuesday, "
    "including the specific things said and the sequence of events.",
    "quote": "a verbatim line from the evening",
    "curiosity": 0.8,
    "warmth": "positive",
    "pacing": "slow",
    "checkins": 3,
    "transcript": ["line one", "line two"],
    "sourceMsgIds": ["m-1", "m-2"],
}


class TestRedaction:
    def test_it_applies_in_adult_mode_and_only_there(self):
        assert redaction.should_redact("adult") is True
        assert redaction.should_redact("ADULT") is True
        assert redaction.should_redact("companion") is False
        assert redaction.should_redact(None) is False

    def test_warmth_signals_are_kept(self):
        # These are what make the next evening feel like a relationship rather than a script.
        safe = redaction.redact(EXPLICIT_RECORD)
        assert safe["warmth"] == "positive"
        assert safe["pacing"] == "slow"
        assert safe["checkins"] == 3

    def test_explicit_detail_is_not(self):
        safe = redaction.redact(EXPLICIT_RECORD)
        for field in ("summary", "quote", "transcript", "sourceMsgIds"):
            assert field not in safe

    def test_nothing_from_the_input_survives_into_the_output(self):
        # The blunt version, and the one that matters: not "these phrases were removed" but
        # "nothing the caller wrote is in there". A redactor that passed a phrasing this
        # test file had never seen would fail here.
        assert redaction.leaks(EXPLICIT_RECORD, redaction.redact(EXPLICIT_RECORD)) == []

    def test_the_leak_detector_is_not_vacuous(self):
        # It has to be able to find something, or the test above passes for free.
        assert redaction.leaks(EXPLICIT_RECORD, {"summary": EXPLICIT_RECORD["summary"]})

    def test_it_is_constructive_rather_than_subtractive(self):
        # A field this module has never heard of cannot appear in the output, which is what
        # makes it hold for the fields a future batch invents.
        invented = dict(EXPLICIT_RECORD, somethingNew="a detail nobody anticipated")
        assert "somethingNew" not in redaction.redact(invented)
        assert redaction.leaks(invented, redaction.redact(invented)) == []

    def test_free_text_in_a_known_field_is_clamped_to_the_vocabulary(self):
        safe = redaction.redact({"warmth": "she said something specific", "pacing": "and so did I"})
        assert safe["warmth"] in redaction.WARMTH
        assert safe["pacing"] in redaction.PACING

    def test_the_topic_key_is_fixed(self):
        # `user.intimate.<something they said>` would leak through the key itself.
        assert redaction.redact(EXPLICIT_RECORD)["topic"] == redaction.TOPIC
        write = redaction.redact_write("adult", "interest", "user.intimate.tuesday", json.dumps(EXPLICIT_RECORD))
        assert write["key"] == redaction.TOPIC

    def test_duration_is_bucketed_rather_than_recorded(self):
        # "47 minutes" is a fact about an evening; "short" is a fact about a preference.
        safe = redaction.redact({"durationBucket": 47})
        assert safe["durationBucket"] in redaction.DURATION_BUCKETS

    def test_a_write_outside_the_interest_store_is_refused_rather_than_reshaped(self):
        # Guessing what a category the tier does not own is for is how detail escapes.
        assert redaction.redact_write("adult", "fact", "k", "v") is None
        assert redaction.redact_write("adult", "summary", "k", "v") is None

    def test_outside_adult_mode_a_write_passes_through_untouched(self):
        write = redaction.redact_write("companion", "fact", "user.name", "Ruslan")
        assert write == {"category": "fact", "key": "user.name", "value": "Ruslan"}

    def test_a_value_that_will_not_parse_still_redacts_to_something_safe(self):
        write = redaction.redact_write("adult", "interest", "k", "{not json")
        assert json.loads(write["value"])["warmth"] == "neutral"

    def test_the_redacted_value_is_json_an_operator_can_read(self):
        payload = json.loads(redaction.redact_write("adult", "interest", "k", EXPLICIT_RECORD)["value"])
        assert set(payload) <= set(redaction.ALLOWED_FIELDS)

    def test_the_module_filters_nothing_it_only_allow_lists(self):
        # A filter is a blocklist wearing a hat, and a blocklist on natural language loses.
        source = codeof(redaction)
        for token in ["BANNED", "BLOCKLIST", "profanity", "replace("]:
            assert token not in source
        assert "ALLOWED_FIELDS" in source

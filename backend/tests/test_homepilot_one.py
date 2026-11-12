"""HomePilot One — the HomePilot half of the routing contract.

HomePilot decides policy (who, which strategy, privacy, spending); OllaBridge
decides execution. These tests stand a scripted gateway in for OllaBridge and
check what HomePilot sends it and what HomePilot does with the answer.
"""

from __future__ import annotations

import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import pytest

SECRET = "hp-one-test-secret"
MSG = [{"role": "user", "content": "hi"}]


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _claims(request: httpx.Request) -> dict:
    return json.loads(_b64d(request.headers["x-homepilot-policy"].split(".")[0]))


def _prov(**kw) -> dict:
    base = {
        "provider": "huggingface-free", "provider_kind": "huggingface",
        "model": "openai/gpt-oss-120b", "tier": "huggingface", "billing": "included",
        "credential": "operator", "execution": "hosted", "strategy": "hf_first",
        "request_id": "rid", "fell_back": False, "fallback_reason": None, "attempts": [],
        "cost": {"estimated_usd": 0.0004, "actual_usd": 0.0003, "known": True},
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
    base.update(kw)
    return base


def _ok(provenance: dict | None = None, text: str = "real answer") -> httpx.Response:
    return httpx.Response(200, json={
        "id": "x", "object": "chat.completion", "model": "openai/gpt-oss-120b",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                     "finish_reason": "stop"}],
        "ollabridge": provenance or _prov(),
    })


class Gateway:
    """A scripted OllaBridge. Records every request it receives."""

    def __init__(self, handler=None):
        self.requests: list[httpx.Request] = []
        self.handler = handler or (lambda request: _ok())

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


@pytest.fixture
def one(compute_db, monkeypatch):
    """Hosted web edition, one signed-in user, a scripted gateway, and a local
    executor that records whether it was ever asked."""
    import app.config as config
    from app.compute import routing
    from app.compute.providers.hosted import HostedGatewayProvider
    from app.connectors import context
    from app import llm

    monkeypatch.setattr(config, "HOMEPILOT_EDITION", "web", raising=False)
    monkeypatch.setattr(config, "OLLABRIDGE_CLOUD_TOKEN", "operator-cloud-token", raising=False)
    for name in ("HOMEPILOT_ROUTING_STRATEGY", "HOMEPILOT_ALLOW_PAID_FALLBACK",
                 "HOMEPILOT_MAX_REQUEST_COST_USD", "HOMEPILOT_DAILY_BUDGET_USD",
                 "HOMEPILOT_MONTHLY_BUDGET_USD", "HOMEPILOT_HF_INCLUDED_USD",
                 "HOMEPILOT_OPERATOR_INFERENCE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOMEPILOT_POLICY_SECRET", SECRET)

    state = {"user": "alice", "local_calls": []}
    monkeypatch.setattr(context, "current_user_id", lambda: state["user"])

    gateway = Gateway()
    monkeypatch.setattr(HostedGatewayProvider, "default_transport", httpx.MockTransport(gateway))

    async def local_chat(messages, **kwargs):
        state["local_calls"].append(kwargs)
        return {"choices": [{"message": {"role": "assistant", "content": "local answer"}}]}

    async def local_stream(messages, **kwargs):
        state["local_calls"].append(kwargs)
        yield "local "
        yield "stream"

    monkeypatch.setattr(llm, "chat", local_chat)
    monkeypatch.setattr(llm, "stream_chat", local_stream)
    routing.note_provenance(None)
    routing.set_inbound_hop(0)
    state["gateway"] = gateway
    return state


# ── defaults ─────────────────────────────────────────────────────────


def test_web_edition_defaults_to_hf_first_and_local_install_stays_legacy(one, monkeypatch):
    import app.config as config
    from app.compute import policies, routing

    assert routing.default_strategy() == "hf_first"
    assert policies.resolve_targets("chat", None) == ["provider:homepilot-auto", "local"]
    assert policies.resolve_targets("multimodal", None) == ["provider:homepilot-vision", "local"]

    monkeypatch.setattr(config, "HOMEPILOT_EDITION", "local", raising=False)
    assert routing.default_strategy() == "legacy"
    assert policies.resolve_targets("chat", None) == ["local"]     # exactly as before


# ── Test A: chat goes through the gateway, provenance comes back ─────


async def test_chat_is_served_through_the_gateway_with_provenance(one):
    from app.compute import routing
    from app.compute.router import build_diagnostics, route_chat

    report: dict = {}
    out = await route_chat(MSG, provider="huggingface", model=None, report=report)

    assert out["choices"][0]["message"]["content"] == "real answer"
    assert one["local_calls"] == []
    request = one["gateway"].requests[0]
    assert request.url.path == "/v1/chat/completions"
    assert json.loads(request.content)["model"] == "homepilot-auto"
    claims = _claims(request)
    assert claims["strategy"] == "hf_first" and claims["sub"] == "alice"
    assert claims["allow_paid"] is False
    assert request.headers["x-ollabridge-origin"] == "homepilot"

    assert out["answered_by"]["provider"] == "huggingface"
    assert out["answered_by"]["via"] == "ollabridge" and out["answered_by"]["tier"] == "huggingface"
    served = build_diagnostics(report)["served_by"]
    assert served["model"] == "openai/gpt-oss-120b" and served["fell_back"] is False

    summary = routing.usage_summary("alice")
    assert summary["this_month"][0]["provider"] == "huggingface-free"
    assert summary["this_month"][0]["requests"] == 1
    assert summary["paid_spent_month_usd"] == 0          # included allowance is not spend


async def test_a_fallback_reported_by_the_gateway_reaches_the_user(one):
    from app.compute.router import build_diagnostics, route_chat

    one["gateway"].handler = lambda r: _ok(_prov(
        provider="groq-free", provider_kind="groq", tier="free", billing="free",
        fell_back=True, fallback_reason="quota_exhausted"))
    report: dict = {}
    out = await route_chat(MSG, provider="huggingface", report=report)
    assert out["answered_by"]["provider"] == "groq"
    assert out["answered_by"]["fell_back"] is True
    assert out["answered_by"]["reason"] == "Hugging Face credits ran out"
    assert build_diagnostics(report)["fell_back"] is True


def test_the_signed_policy_is_accepted_by_the_gateways_own_parser(one):
    """Producer and consumer of the contract, verified together."""
    rp = pytest.importorskip("ollabridge_cloud.addons.providers.policy")
    from app.compute import routing
    from app.connectors import store

    store.save("alice", "huggingface", "hf_alice_token", "alice")
    call = routing.build_gateway_call("alice", require=("vision",))
    policy, credentials = rp.parse_policy(call.headers, SECRET)
    assert policy.signed and policy.subject == "alice" and policy.require == ("vision",)
    assert credentials == {"huggingface": "hf_alice_token"}

    tampered = dict(call.headers)
    tampered[rp.CREDENTIALS_HEADER] = rp.encode_credentials({"huggingface": "hf_someone_else"})
    with pytest.raises(rp.PolicyError):
        rp.parse_policy(tampered, SECRET)


def test_policy_signature_matches_the_shared_test_vector(one):
    from app.compute import routing
    header = routing.sign_policy({"strategy": "hf_first", "sub": "u1"}, secret="vector-secret", now=1700000000)
    assert header == (
        "eyJleHAiOjE3MDAwMDAxMjAsImlhdCI6MTcwMDAwMDAwMCwic3RyYXRlZ3kiOiJoZl9maXJzdCIsInN1YiI6InUxIn0"
        "." + __import__("hmac").new(b"vector-secret", header.split(".")[0].encode(), "sha256").hexdigest()
    )


# ── Test J: tenant isolation ─────────────────────────────────────────


async def test_each_user_gets_only_their_own_credentials(one):
    from app import cloud_tokens
    from app.compute.router import route_chat
    from app.connectors import store

    store.save("alice", "huggingface", "hf_alice_token", "alice")
    cloud_tokens.set_cloud_token("alice", "alice-cloud-token")

    await route_chat(MSG, provider="huggingface")
    alice = one["gateway"].requests[-1]
    creds = json.loads(_b64d(alice.headers["x-homepilot-provider-credentials"]))
    assert creds == {"huggingface": "hf_alice_token"}
    assert alice.headers["authorization"] == "Bearer alice-cloud-token"
    assert _claims(alice)["allow_relay"] is True          # her own account ⇒ her own PCs

    one["user"] = "bob"                                   # no linked accounts at all
    await route_chat(MSG, provider="huggingface")
    bob = one["gateway"].requests[-1]
    assert "x-homepilot-provider-credentials" not in bob.headers
    assert "hf_alice_token" not in str(bob.headers) and "alice-cloud-token" not in str(bob.headers)
    assert bob.headers["authorization"] == "Bearer operator-cloud-token"
    claims = _claims(bob)
    assert claims["sub"] == "bob"
    # The operator's token is never an authorisation to reach devices.
    assert claims["allow_relay"] is False


def test_device_targets_are_not_built_from_the_operator_token_on_the_hosted_edition(one):
    from app import cloud_tokens
    from app.compute import providers

    assert providers.build_target("device:somebodys-pc") is None
    assert providers.build_target("ollabridge_cloud") is None

    cloud_tokens.set_cloud_token("alice", "alice-cloud-token")
    built = providers.build_target("device:alices-pc")
    assert built is not None and built.provider.token == "alice-cloud-token"

    one["user"] = "bob"
    assert providers.build_target("device:alices-pc") is None


def test_routing_preferences_are_stored_per_user(one):
    from app.compute import routing

    routing.save_prefs("alice", {"strategy": "private_local", "monthly_budget_usd": 5})
    assert routing.load_prefs("alice").strategy == "private_local"
    assert routing.load_prefs("bob").strategy == "hf_first"
    assert routing.load_prefs("bob").monthly_budget_usd is None
    with pytest.raises(ValueError):
        routing.save_prefs("alice", {"strategy": "anything_goes"})


async def test_one_users_refusal_does_not_trip_the_breaker_for_everyone(one):
    from app.compute.router import route_chat

    def handler(request):
        if _claims(request)["sub"] == "alice":
            return httpx.Response(402, json={"detail": {
                "error": "budget_exceeded", "message": "over budget", "attempts": []}})
        return _ok()

    one["gateway"].handler = handler
    out = await route_chat(MSG, provider="huggingface")       # alice → emergency local
    assert out["choices"][0]["message"]["content"] == "local answer"
    one["user"] = "bob"
    out = await route_chat(MSG, provider="huggingface")
    assert out["choices"][0]["message"]["content"] == "real answer"


# ── Tests C/D: spending ──────────────────────────────────────────────


def test_the_operator_kill_switch_overrides_a_users_paid_preference(one, monkeypatch):
    from app.compute import routing

    routing.save_prefs("alice", {"allow_paid": True, "max_request_cost_usd": 0.5})
    assert routing.build_gateway_call("alice").claims["allow_paid"] is False

    monkeypatch.setenv("HOMEPILOT_ALLOW_PAID_FALLBACK", "true")
    claims = routing.build_gateway_call("alice").claims
    assert claims["allow_paid"] is True and claims["max_cost_usd"] == 0.5


def test_daily_and_monthly_budgets_shrink_the_per_request_ceiling(one, monkeypatch):
    from app.compute import routing

    monkeypatch.setenv("HOMEPILOT_ALLOW_PAID_FALLBACK", "true")
    routing.save_prefs("alice", {"allow_paid": True, "max_request_cost_usd": 0.5,
                                 "monthly_budget_usd": 1.0})
    paid = _prov(provider="openai", provider_kind="openai_compatible", tier="paid",
                 billing="paid", cost={"estimated_usd": 0.9, "actual_usd": 0.9, "known": True})
    routing.record_usage("alice", paid)
    assert routing.build_gateway_call("alice").claims["max_cost_usd"] == pytest.approx(0.1)

    routing.record_usage("alice", paid)
    assert routing.build_gateway_call("alice").claims["max_cost_usd"] == 0.0
    assert routing.usage_summary("alice")["budget_exhausted"] is True
    # Bob's budget is untouched by Alice's spending.
    assert routing.build_gateway_call("bob").claims["max_cost_usd"] is None


def test_hugging_face_allowance_is_tracked_only_when_the_operator_states_it(one, monkeypatch):
    from app.compute import routing

    assert "hf_included_remaining_usd" not in routing.build_gateway_call("alice").claims
    monkeypatch.setenv("HOMEPILOT_HF_INCLUDED_USD", "2.00")
    routing.record_usage("alice", _prov(cost={"estimated_usd": 0.5, "actual_usd": 0.5, "known": True}))
    assert routing.build_gateway_call("alice").claims["hf_included_remaining_usd"] == pytest.approx(1.5)
    # The operator's token is one allowance shared by everyone who relies on it.
    assert routing.build_gateway_call("bob").claims["hf_included_remaining_usd"] == pytest.approx(1.5)


# ── Test I: private_local ────────────────────────────────────────────


async def test_private_local_never_falls_back_to_anything_hosted(one):
    from app.compute import policies, routing
    from app.compute.providers.hosted import GatewayError
    from app.compute.router import route_chat

    routing.save_prefs("alice", {"strategy": "private_local"})
    assert policies.resolve_targets("chat", None) == ["provider:homepilot-auto"]
    assert policies.resolve_targets("image", None) == ["ollabridge_cloud"]

    one["gateway"].handler = lambda r: httpx.Response(503, json={"detail": {
        "error": "device_offline", "message": "none of your paired computers is online",
        "attempts": []}})
    with pytest.raises(GatewayError) as err:
        await route_chat(MSG, provider="huggingface")
    assert err.value.code == "device_offline"
    assert one["local_calls"] == []                       # the Space's own HF/Ollama: untouched
    claims = _claims(one["gateway"].requests[-1])
    assert claims["strategy"] == "private_local" and claims["privacy"] == "private_local"


async def test_private_local_on_a_local_install_refuses_a_hosted_llm_provider(one, monkeypatch):
    import app.config as config
    from app.compute import policies, routing
    from app.compute.router import route_chat

    monkeypatch.setattr(config, "HOMEPILOT_EDITION", "local", raising=False)
    routing.save_prefs("alice", {"strategy": "private_local"})
    assert policies.resolve_targets("chat", None) == ["local"]

    with pytest.raises(routing.PrivacyRestricted):
        await route_chat(MSG, provider="huggingface")
    with pytest.raises(routing.PrivacyRestricted):
        await route_chat(MSG, provider="openai_compat", base_url="https://api.example.com/v1")
    assert one["local_calls"] == [] and one["gateway"].requests == []

    out = await route_chat(MSG, provider="ollama")
    assert out["choices"][0]["message"]["content"] == "local answer"
    await route_chat(MSG, provider="openai_compat", base_url="http://localhost:8000/v1")


# ── Test H: gateway unreachable → emergency executor ─────────────────


async def test_when_the_gateway_is_unreachable_homepilot_answers_itself(one):
    from app.compute.router import route_chat

    def down(request):
        raise httpx.ConnectError("gateway unreachable")

    one["gateway"].handler = down
    report: dict = {}
    out = await route_chat(MSG, provider="huggingface", report=report)
    assert out["choices"][0]["message"]["content"] == "local answer"
    assert report["target"] == "local" and report["fell_back"] is True


# ── Test K: no routing loop ──────────────────────────────────────────


async def test_a_request_forwarded_by_the_gateway_is_not_sent_back_to_it(one):
    from app.compute import routing
    from app.compute.router import route_chat

    routing.set_inbound_hop(1)                              # came via OllaBridge once
    await route_chat(MSG, provider="huggingface")
    assert one["gateway"].requests[-1].headers["x-ollabridge-hop"] == "2"

    routing.set_inbound_hop(routing.MAX_HOPS - 1)           # one more hop would hit the limit
    before = len(one["gateway"].requests)
    out = await route_chat(MSG, provider="huggingface")
    assert len(one["gateway"].requests) == before          # terminal: executed here
    assert out["choices"][0]["message"]["content"] == "local answer"


# ── Test L: streaming ────────────────────────────────────────────────


def _sse(*lines: str, headers: dict | None = None) -> httpx.Response:
    encoded = base64.urlsafe_b64encode(json.dumps(_prov()).encode()).decode()
    return httpx.Response(
        200, content="".join(line + "\n\n" for line in lines).encode(),
        headers={"content-type": "text/event-stream", "x-ollabridge-provenance": encoded,
                 **(headers or {})},
    )


def _chunk(text: str) -> str:
    return "data: " + json.dumps({"object": "chat.completion.chunk",
                                  "choices": [{"index": 0, "delta": {"content": text}}]})


async def test_streaming_relays_tokens_and_records_the_final_cost(one):
    from app.compute import routing
    from app.compute.router import build_diagnostics, route_chat_stream

    final = _prov(cost={"estimated_usd": 0.01, "actual_usd": 0.002, "known": True})
    one["gateway"].handler = lambda r: _sse(
        _chunk("Hel"), _chunk("lo"), ": ollabridge " + json.dumps(final), "data: [DONE]")
    report: dict = {}
    text = "".join([d async for d in route_chat_stream(MSG, provider="huggingface", report=report)])
    assert text == "Hello"
    assert json.loads(one["gateway"].requests[-1].content)["stream"] is True
    assert build_diagnostics(report)["served_by"]["provider"] == "huggingface"
    rows = routing.usage_summary("alice")["this_month"]
    assert rows[0]["cost_usd"] == pytest.approx(0.002)


async def test_a_stream_interrupted_after_output_is_not_restarted_locally(one):
    from app.compute.providers.hosted import GatewayError
    from app.compute.router import route_chat_stream

    one["gateway"].handler = lambda r: _sse(
        _chunk("partial"),
        "data: " + json.dumps({"error": {"type": "stream_interrupted",
                                         "code": "provider_unavailable", "message": "lost"}}))
    seen: list[str] = []
    with pytest.raises(GatewayError):
        async for delta in route_chat_stream(MSG, provider="huggingface"):
            seen.append(delta)
    assert seen == ["partial"] and one["local_calls"] == []


async def test_a_stream_refused_before_output_falls_back(one):
    from app.compute.router import route_chat_stream

    one["gateway"].handler = lambda r: httpx.Response(503, json={"detail": {
        "error": "all_providers_unavailable", "message": "nothing", "attempts": []}})
    text = "".join([d async for d in route_chat_stream(MSG, provider="huggingface")])
    assert text == "local stream"


# ── Test E: vision ───────────────────────────────────────────────────


async def test_an_image_request_keeps_its_image_and_requires_vision(one):
    from app.compute.router import route_chat

    url = "data:image/png;base64,iVBORw0KGgo="
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "what is this?"},
        {"type": "image_url", "image_url": {"url": url}}]}]
    await route_chat(messages, provider="huggingface", modality="multimodal")
    request = one["gateway"].requests[-1]
    body = json.loads(request.content)
    assert body["model"] == "homepilot-vision"
    assert body["messages"][0]["content"][1]["image_url"]["url"] == url
    assert _claims(request)["require"] == ["vision"]


async def test_a_hub_model_the_user_picked_is_sent_as_a_preference(one):
    from app.compute.router import route_chat

    await route_chat(MSG, provider="huggingface", model="meta-llama/Llama-3.3-70B-Instruct")
    request = one["gateway"].requests[-1]
    assert json.loads(request.content)["model"] == "homepilot-auto"
    assert _claims(request)["prefer_model"] == "meta-llama/Llama-3.3-70B-Instruct"


# ── the direct Hugging Face path obeys the same switches ─────────────


def test_operator_token_is_not_used_when_operator_inference_is_off(one, monkeypatch):
    from app.connectors import huggingface as hf

    monkeypatch.setenv("HF_TOKEN", "hf_space_token")
    assert hf.shared_token() == "hf_space_token"
    monkeypatch.setenv("HOMEPILOT_OPERATOR_INFERENCE", "false")
    assert hf.shared_token() == ""

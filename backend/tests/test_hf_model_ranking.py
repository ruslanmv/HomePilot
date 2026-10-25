"""
Models → Hugging Face lists the hosted models HomePilot can run, ranked by what people like
(FitLab's inference lane, mirrored in app/model_advisor/inference.py):

  * only models a provider serves live for the task HomePilot calls; adapters excluded;
  * orders: popular (likes, downloads, trend, freshness), likes, trending, newest, rising;
  * live from the Hub, cached; FitLab's published ranking stands in when the Hub is down;
  * the mirrored rules match what FitLab publishes.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

SNAPSHOT = Path(__file__).resolve().parents[1] / "app" / "model_advisor" / "data" / "fitlab_inference.snapshot.json"


def _hf():
    return sys.modules["app.connectors.huggingface"]


def _lane():
    import importlib
    return importlib.import_module("app.model_advisor.inference")


def _user(client):
    r = client.post("/v1/auth/register", json={"username": f"k{uuid.uuid4().hex[:10]}"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def hub(repo, likes, *, downloads=1000, trending=1, status="live", task="text-to-image",
        created="2025-03-01T00:00:00.000Z", tags=()):
    return {"id": repo, "likes": likes, "downloads": downloads, "trendingScore": trending,
            "createdAt": created, "lastModified": created, "tags": list(tags), "library_name": "diffusers",
            "inferenceProviderMapping": [{"provider": "fal-ai", "status": status, "task": task}]}


POOL = [
    hub("black-forest-labs/FLUX.1-dev", 15000, downloads=600_000, trending=50),
    hub("stabilityai/sdxl", 8000, downloads=4_000_000, trending=10),
    hub("new/rising-star", 120, trending=280, created="2026-10-01T00:00:00.000Z"),
    hub("someone/style-lora", 30000, tags=["lora"]),          # an adapter, never suggested
    hub("down/everywhere", 50000, status="error"),             # no live provider
]


@pytest.fixture
def hub_pool(monkeypatch):
    hf = _hf()
    calls = []
    monkeypatch.setattr(hf, "_cache", {})
    monkeypatch.setattr(hf, "_list", lambda task, secret: calls.append(task) or list(POOL))
    return calls


def _rank(client, h, sort, model_type="image"):
    r = client.get(f"/v1/connectors/huggingface/models?type={model_type}&sort={sort}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_most_liked_order_is_ranked_by_the_people(client, hub_pool):
    body = _rank(client, _user(client), "likes")
    assert body["source"] == "live" and body["sort"] == "likes"
    assert [m["name"] for m in body["models"]] == ["black-forest-labs/FLUX.1-dev", "stabilityai/sdxl", "new/rising-star"]
    top = body["models"][0]
    assert top["id"] == "hf:black-forest-labs/FLUX.1-dev" and top["likes"] == 15000
    assert top["provider_label"] == "Black Forest Labs" and top["live_providers"] == ["fal-ai"]
    assert "Popular is not always best" in body["note"]


def test_adapters_and_models_nobody_serves_are_never_listed(client, hub_pool):
    h = _user(client)
    for sort in ("popular", "likes", "trending", "newest", "rising"):
        names = [m["name"] for m in _rank(client, h, sort)["models"]]
        assert "someone/style-lora" not in names and "down/everywhere" not in names


def test_trending_and_rising_surface_new_models(client, hub_pool):
    h = _user(client)
    assert _rank(client, h, "trending")["models"][0]["name"] == "new/rising-star"
    assert [m["name"] for m in _rank(client, h, "rising")["models"]] == ["new/rising-star"]


def test_the_hub_is_asked_once_per_type_then_cached(client, hub_pool):
    h = _user(client)
    for sort in ("popular", "likes", "trending"):
        _rank(client, h, sort)
    assert hub_pool == ["image"]


def test_fitlabs_ranking_stands_in_when_the_hub_is_down(client, monkeypatch):
    hf = _hf()
    monkeypatch.setattr(hf, "_cache", {})

    def down(task, secret):
        raise RuntimeError("the Hugging Face Hub could not be reached")
    monkeypatch.setattr(hf, "_list", down)
    body = _rank(client, _user(client), "likes", model_type="image")
    assert body["source"].startswith("fitlab-")
    assert body["models"] and all(m["id"].startswith("hf:") for m in body["models"])
    likes = [m["likes"] for m in body["models"]]
    assert likes == sorted(likes, reverse=True)


def test_an_unknown_order_is_refused(client, hub_pool):
    r = client.get("/v1/connectors/huggingface/models?type=image&sort=random", headers=_user(client))
    assert r.status_code == 400


def test_the_mirrored_rules_match_what_fitlab_publishes():
    published = json.loads(SNAPSHOT.read_text())
    lane = _lane()
    assert published["ranking_version"] == lane.RANKING_VERSION
    assert published["scoring"]["weights"] == lane.WEIGHTS
    assert set(published["kinds"]) == set(lane.KINDS)
    feed = sys.modules.get("app.model_advisor.feed") or __import__("app.model_advisor.feed", fromlist=["feed"])
    assert feed.valid("inference", published)

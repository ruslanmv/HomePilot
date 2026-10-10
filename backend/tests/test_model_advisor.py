# backend/tests/test_model_advisor.py
"""
Model Advisor: FitLab suggestions for this machine.

Offline and deterministic — the network is replaced, the bundled snapshots are the data.
"""
import json

import pytest


@pytest.fixture()
def advisor(tmp_path, monkeypatch):
    from app.model_advisor import feed, hardware, ranking, routes
    monkeypatch.setenv("FITLAB_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("FITLAB_ENABLED", raising=False)
    monkeypatch.delenv("FITLAB_OFFLINE", raising=False)
    monkeypatch.delenv("FITLAB_REGISTRY_URL", raising=False)
    monkeypatch.delenv("FITLAB_MEDIA_URL", raising=False)
    # Never touch the real network, GPU, Ollama or ComfyUI from a test.
    monkeypatch.setattr(feed, "_read_url", lambda url, etag=None: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(hardware, "_nvidia", lambda: None)
    monkeypatch.setattr(hardware, "_apple", lambda: None)
    monkeypatch.setattr(hardware, "_total_ram_gb", lambda: 32.0)

    async def no_ollama():
        return set()
    monkeypatch.setattr(routes, "_installed_ollama", no_ollama)
    monkeypatch.setattr(routes, "_installed_comfy", lambda: set())
    return feed, hardware, ranking, routes


def snapshot(feed, kind):
    return json.loads(feed.SNAPSHOTS[kind].read_text())


# ── where the data comes from ───────────────────────────────────────────────


def test_without_network_or_cache_the_bundled_snapshot_is_used(advisor):
    feed = advisor[0]
    for kind in ("llm", "media"):
        f = feed.load(kind)
        assert f.source == "bundled" and f.doc["models"]


def test_fetch_uses_the_live_document_and_caches_it(advisor, monkeypatch):
    feed = advisor[0]
    live = snapshot(feed, "llm")
    live["generated_at"] = "2099-01-01"
    seen = []

    def read(url, etag=None):
        seen.append(url)
        return live
    monkeypatch.setattr(feed, "_read_url", read)
    f = feed.load("llm", refresh=True)
    assert f.source == "live" and f.doc["generated_at"] == "2099-01-01"
    assert seen[0].endswith("/registry-latest/data/registry.json")   # freshest ref first

    # Offline afterwards: the cached copy, not the older bundled one.
    monkeypatch.setattr(feed, "_read_url", lambda url, etag=None: (_ for _ in ()).throw(OSError("offline")))
    again = feed.load("llm", refresh=True)
    assert again.source == "cache" and again.doc["generated_at"] == "2099-01-01"
    assert again.errors  # the failed attempts are reported, not hidden


def test_an_unchanged_feed_is_not_downloaded_again(advisor, monkeypatch):
    # The automatic daily check sends the ETag; FitLab answers 304 and nothing is re-read.
    feed = advisor[0]
    live = snapshot(feed, "llm")
    calls = []

    def first(url, etag=None):
        calls.append(etag)
        feed._read_url.etag = '"v1"'
        return live
    monkeypatch.setattr(feed, "_read_url", first)
    a = feed.load("llm", refresh=True)
    assert a.changed is True

    def second(url, etag=None):
        calls.append(etag)
        return feed.NOT_MODIFIED
    second.etag = None
    monkeypatch.setattr(feed, "_read_url", second)
    b = feed.load("llm", refresh=True)
    assert calls == [None, '"v1"']
    assert b.source == "live" and b.changed is False and b.doc == live
    assert b.checked_at >= a.checked_at


def test_a_malformed_document_is_never_used(advisor, monkeypatch):
    feed = advisor[0]
    monkeypatch.setattr(feed, "_read_url", lambda url, etag=None: {"models": "nope"})
    f = feed.load("media", refresh=True)
    assert f.source == "bundled"
    assert any("not a FitLab media document" in e for e in f.errors)


def test_only_https_or_file_urls_are_read(advisor, monkeypatch):
    feed = advisor[0]
    monkeypatch.undo()  # the real reader
    with pytest.raises(ValueError):
        feed._read_url("http://example.com/registry.json")


def test_offline_mode_never_calls_the_network(advisor, monkeypatch):
    feed = advisor[0]
    monkeypatch.setenv("FITLAB_OFFLINE", "true")
    monkeypatch.setattr(feed, "_read_url", lambda url, etag=None: pytest.fail("network used"))
    assert feed.load("llm", refresh=True).source == "bundled"


def test_a_mirror_url_is_tried_first_and_serves_both_feeds(advisor, monkeypatch):
    feed = advisor[0]
    monkeypatch.setenv("FITLAB_REGISTRY_URL", "https://mirror.example/fitlab/registry.json")
    assert feed.urls("llm")[0] == "https://mirror.example/fitlab/registry.json"
    assert feed.urls("media")[0] == "https://mirror.example/fitlab/media_registry.json"


# ── the arithmetic is FitLab's ──────────────────────────────────────────────


def test_fit_matches_fitlab_for_qwen3_8b_on_a_3060():
    # fitlab check --gpu rtx3060-12: Qwen3-8B, Q4_K_M, 8K → 7.2 GB, FITS, ~44.8 tok/s.
    from app.model_advisor.ranking import fit_llm
    qwen = {"params_b": 8.2, "arch": {"n_layers": 36, "n_kv_heads": 8, "head_dim": 128}}
    f = fit_llm(qwen, 12.0, 360)
    assert f["verdict"] == "fits" and f["est_gb"] == 7.2 and f["est_tps"] == 44.8


def test_media_scores_reproduce_the_published_lists(advisor):
    feed, _, ranking, _ = advisor
    media = snapshot(feed, "media")
    for cid, cat in media["categories"].items():
        vram = {"rtx3060-12": 12, "rtx4060ti-16": 16, "rtx4090-24": 24}[cat["reference_gpu"]]
        mine = {s["id"]: s["score"] for s in ranking.rank_media(media, cat["task"], vram, set(), 50)}
        for top in cat["top"]:
            if media["models"][top["id"]].get("homepilot"):
                assert mine[top["id"]] == pytest.approx(top["score"], abs=1e-3), (cid, top["id"])


def test_nothing_that_cannot_run_or_be_installed_is_suggested(advisor):
    feed, _, ranking, _ = advisor
    media = snapshot(feed, "media")
    for s in ranking.rank_media(media, "video", 8, set(), 10):
        assert s["verdict"] != "no" and s["install"]["provider"] == "comfyui"
    assert ranking.rank_media(media, "image", 2, set(), 10) == []
    llm = snapshot(feed, "llm")
    hw = {"bandwidth_gbs": 360, "profile_id": None}
    for s in ranking.rank_llm(llm, "chat", hw, 12, set(), 10):
        assert s["install"]["provider"] == "ollama" and s["install"]["model_id"]


def test_a_cpu_only_machine_gets_chat_models_that_answer_at_reading_speed(advisor):
    feed, hardware, ranking, _ = advisor
    hw = hardware.detect()
    assert hw["kind"] == "cpu"
    top = ranking.rank_llm(snapshot(feed, "llm"), "chat", hw, hardware.chat_memory_gb(hw), set(), 3)
    assert top and all(s["tokens_per_s"] >= ranking.MIN_USABLE_TPS for s in top)


def test_installed_models_are_marked(advisor):
    feed, _, ranking, _ = advisor
    llm = snapshot(feed, "llm")
    hw = {"bandwidth_gbs": 360, "profile_id": None}
    first = ranking.rank_llm(llm, "chat", hw, 12, set(), 1)[0]
    tag = first["install"]["model_id"]
    again = ranking.rank_llm(llm, "chat", hw, 12, {tag if ":" in tag else f"{tag}:latest"}, 1)[0]
    assert again["installed"] is True


# ── the endpoints ───────────────────────────────────────────────────────────


def test_get_returns_five_per_kind_with_provenance(advisor, client):
    r = client.get("/v1/model-advisor", params={"vram_gb": 12})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True and body["fetch"] is None
    assert set(body["suggestions"]) == {"chat", "vision", "image", "video"}
    assert all(1 <= len(v) <= 5 for v in body["suggestions"].values())
    assert body["feeds"]["llm"]["source"] == "bundled" and body["feeds"]["llm"]["generated_at"]
    assert body["hardware"]["vram_gb"] == 12 and "CC BY 4.0" in body["attribution"]


def test_fetch_offline_falls_back_and_says_so(advisor, client):
    r = client.post("/v1/model-advisor/fetch", params={"kind": "chat"})
    assert r.status_code == 200
    body = r.json()
    assert body["fetch"]["ok"] is False and body["fetch"]["errors"]
    assert body["feeds"]["llm"]["source"] == "bundled"
    assert len(body["suggestions"]["chat"]) == 5


def test_disabled_means_off(advisor, client, monkeypatch):
    monkeypatch.setenv("FITLAB_ENABLED", "false")
    assert client.get("/v1/model-advisor").json() == {"ok": True, "enabled": False}
    assert client.post("/v1/model-advisor/fetch").status_code == 404


def test_an_upgrade_is_reported_when_a_clearly_better_model_fits(advisor, client):
    body = client.get("/v1/model-advisor", params={"vram_gb": 12, "kind": "chat", "limit": 10}).json()
    ranked = body["suggestions"]["chat"]
    weaker = ranked[-1]["install"]["model_id"]
    up = client.get("/v1/model-advisor", params={"vram_gb": 12, "current_chat": weaker}).json()["upgrades"]
    assert up["chat"]["current"]["model_id"] == weaker
    assert up["chat"]["better"]["id"] == ranked[0]["id"]
    assert up["chat"]["better"]["score"] - up["chat"]["current"]["score"] >= 0.03


def test_no_upgrade_for_the_best_model_or_one_fitlab_does_not_rank(advisor, client):
    best = client.get("/v1/model-advisor", params={"vram_gb": 12, "kind": "chat"}).json()["suggestions"]["chat"][0]
    for current in (best["install"]["model_id"], "my-private-finetune:7b"):
        r = client.get("/v1/model-advisor", params={"vram_gb": 12, "current_chat": current}).json()
        assert "chat" not in r["upgrades"]

"""ComfyUI images are served from disk first (no 30 s wait on ComfyUI), with thumbnails."""
import io
import sys

from PIL import Image


def _main():
    return sys.modules["app.main"]


def _png(path, size=(800, 600)):
    Image.new("RGB", size, (200, 50, 50)).save(path, "PNG")


def test_served_from_disk_without_asking_comfyui(app, client, tmp_path, monkeypatch):
    main = _main()
    _png(tmp_path / "avatar_00001_.png")
    monkeypatch.setattr("app.comfy._get_comfyui_output_dir", lambda: tmp_path)

    class Boom:
        def __init__(self, *a, **k):
            raise AssertionError("ComfyUI must not be contacted when the file is on disk")

    monkeypatch.setattr(main.httpx, "AsyncClient", Boom)
    r = client.get("/comfy/view/avatar_00001_.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_thumbnail_is_small_webp_and_cached(app, client, tmp_path, monkeypatch):
    _png(tmp_path / "avatar_00002_.png")
    monkeypatch.setattr("app.comfy._get_comfyui_output_dir", lambda: tmp_path)
    r = client.get("/comfy/view/avatar_00002_.png?thumb=300")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(r.content)) as im:
        assert max(im.size) == 256  # 300 snaps to the nearest allowed size
    again = client.get("/comfy/view/avatar_00002_.png?thumb=300")
    assert again.content == r.content


def test_path_tricks_are_not_served_from_disk(app, client, tmp_path, monkeypatch):
    main = _main()
    out = tmp_path / "out"
    out.mkdir()
    _png(tmp_path / "secret.png")
    monkeypatch.setattr("app.comfy._get_comfyui_output_dir", lambda: out)
    assert main._local_comfy_output_file("../secret.png", "") is None
    assert main._local_comfy_output_file("secret.png", "..") is None


def test_warm_thumbnails_makes_them_ahead_of_time(app, tmp_path, monkeypatch):
    thumbs = sys.modules.get("app.comfy_thumbs") or __import__("app.comfy_thumbs", fromlist=["x"])
    _png(tmp_path / "avatar_00009_.png")
    monkeypatch.setattr("app.comfy._get_comfyui_output_dir", lambda: tmp_path)
    cache = tmp_path / "thumbcache"
    monkeypatch.setattr(thumbs, "_cache_dir", lambda: cache)
    thumbs.warm_thumbnails([("avatar_00009_.png", ""), ("missing.png", "")]).join(timeout=30)
    made = list(cache.glob("*.webp"))
    assert len(made) == 1

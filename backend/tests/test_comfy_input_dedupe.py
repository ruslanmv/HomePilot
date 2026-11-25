"""ComfyUI input copies are stored once per image and old ones are pruned."""
import os
import time

from app import comfy


def test_same_image_is_stored_once(tmp_path):
    a = comfy._place_in_comfy_input(tmp_path, b"same bytes", ".png")
    b = comfy._place_in_comfy_input(tmp_path, b"same bytes", ".png")
    c = comfy._place_in_comfy_input(tmp_path, b"other bytes", ".png")
    assert a == b != c
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted({a, c})


def test_old_copies_are_pruned_but_user_files_are_not(tmp_path):
    old = tmp_path / "hp_old.png"
    old.write_bytes(b"x")
    past = time.time() - comfy._HP_INPUT_KEEP_SECONDS - 60
    os.utime(old, (past, past))
    mine = tmp_path / "my_photo.png"
    mine.write_bytes(b"y")
    os.utime(mine, (past, past))
    kept = comfy._place_in_comfy_input(tmp_path, b"new", ".png")
    names = {p.name for p in tmp_path.iterdir()}
    assert "hp_old.png" not in names
    assert "my_photo.png" in names and kept in names


def test_copies_are_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(comfy, "_HP_INPUT_MAX_FILES", 5)
    for i in range(12):
        comfy._place_in_comfy_input(tmp_path, f"img {i}".encode(), ".png")
    assert len([p for p in tmp_path.iterdir() if p.name.startswith("hp_")]) <= 5


def test_controlnets_use_single_node_info_not_full_list(monkeypatch):
    import httpx
    comfy._node_info_cache.clear()
    monkeypatch.setattr(comfy._object_info_cache, "get_raw", lambda **kw: None)
    seen = []

    def fake_get(url, timeout=None):
        seen.append(url)
        body = {"ControlNetLoader": {"input": {"required": {"control_net_name": [["a.safetensors", "openpose_sdxl.safetensors"]]}}}}
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(comfy.httpx, "get", fake_get)
    assert comfy.get_available_controlnets() == ["a.safetensors", "openpose_sdxl.safetensors"]
    assert comfy.openpose_available() is True
    assert seen and all(u.endswith("/object_info/ControlNetLoader") for u in seen)
    assert len(seen) == 1  # second call served from the cache

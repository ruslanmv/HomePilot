"""Workflow model paths match the target ComfyUI's spelling (Windows lists 'a\\b', Linux 'a/b')."""
import httpx

from app.comfy_utils import model_paths as mp


def _serve(monkeypatch, infos):
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        cls = url.rsplit("/", 1)[-1]
        return httpx.Response(200, json={cls: infos.get(cls, {})}, request=httpx.Request("GET", url))

    mp.clear_cache()
    monkeypatch.setattr(mp.httpx, "get", fake_get)
    return calls


WIN_CN = {"input": {"required": {"control_net_name": [[
    "InstantID\\diffusion_pytorch_model.safetensors", "control_v11p_sd15_inpaint.safetensors"]]}}}
LINUX_CN = {"input": {"required": {"control_net_name": [[
    "InstantID/diffusion_pytorch_model.safetensors", "control_v11p_sd15_inpaint.safetensors"]]}}}


def test_forward_slash_becomes_backslash_on_windows_comfyui(monkeypatch):
    _serve(monkeypatch, {"ControlNetLoader": WIN_CN})
    g = {"13": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": "InstantID/diffusion_pytorch_model.safetensors"}}}
    assert mp.align_model_paths(g, "http://c") == 1
    assert g["13"]["inputs"]["control_net_name"] == "InstantID\\diffusion_pytorch_model.safetensors"


def test_backslash_becomes_forward_slash_on_linux_comfyui(monkeypatch):
    _serve(monkeypatch, {"ControlNetLoader": LINUX_CN})
    g = {"1": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": "InstantID\\diffusion_pytorch_model.safetensors"}}}
    assert mp.align_model_paths(g, "http://c") == 1
    assert g["1"]["inputs"]["control_net_name"] == "InstantID/diffusion_pytorch_model.safetensors"


def test_correct_values_urls_and_text_are_untouched_and_no_needless_requests(monkeypatch):
    calls = _serve(monkeypatch, {"ControlNetLoader": WIN_CN})
    g = {
        "1": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": "control_v11p_sd15_inpaint.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "a red/blue dress"}},
        "3": {"class_type": "LoadImage", "inputs": {"image": "http://x/view?a=b/c"}},
        "4": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": "InstantID\\diffusion_pytorch_model.safetensors"}},
    }
    assert mp.align_model_paths(g, "http://c") == 0
    assert g["2"]["inputs"]["text"] == "a red/blue dress"
    # Only nodes with a path-like value are looked up; the ControlNetLoader answer is cached.
    assert all("/object_info/" in u for u in calls)
    assert not any(u.endswith("/LoadImage") for u in calls)
    assert sum(u.endswith("/ControlNetLoader") for u in calls) == 1


def test_combo_options_format(monkeypatch):
    info = {"input": {"required": {"ckpt_name": ["COMBO", {"options": ["sdxl\\base.safetensors"]}]}}}
    _serve(monkeypatch, {"CheckpointLoaderSimple": info})
    g = {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sdxl/base.safetensors"}}}
    assert mp.align_model_paths(g, "http://c") == 1
    assert g["4"]["inputs"]["ckpt_name"] == "sdxl\\base.safetensors"

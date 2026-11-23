"""Spicy mode's local model set: the catalog, the workflows that run it, and the defaults.

What these tests stand guard over, and why each matters:

- Every Spicy default is a real catalog entry, marked adult-capable, under the capability it is
  used for. A typo in ``spicy_defaults`` would otherwise mean "no default" and nothing would say so.
- Each new workflow loads exactly the files its catalog pack installs. The Wan 2.2 5B workflow
  this batch replaced loaded files the pack never downloaded, so it could not have run on any
  machine that installed it through HomePilot; this test is what stops that happening again.
- Every node link points at a node that exists, and every ``{{placeholder}}`` is one the caller
  fills in, so ComfyUI is never sent a literal ``{{…}}`` string.
- Defaults fill gaps only: a model the person chose is never replaced, and nothing is chosen
  outside Spicy mode or when the default is not installed.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "backend" / "app" / "model_catalog_data.json"
WORKFLOWS = ROOT / "comfyui" / "workflows"

# capability -> where its models live in the catalog
CAPABILITY_SECTIONS = {
    "chat": ("ollama", "chat"),
    "multimodal": ("ollama", "multimodal"),
    "image": ("comfyui", "image"),
    "edit": ("comfyui", "edit"),
    "video": ("comfyui", "video"),
}

# (catalog section, catalog id, workflow, variables the caller supplies to that workflow)
IMAGE_VARS = {"prompt", "negative_prompt", "width", "height", "seed", "steps", "cfg"}
VIDEO_VARS = {"image_path", "prompt", "negative_prompt", "width", "height", "frames", "fps",
              "seed", "steps", "cfg", "denoise", "motion", "seconds"}
EDIT_VARS = {"image_path", "prompt", "negative_prompt", "seed", "steps", "cfg", "denoise",
             "sampler_name", "scheduler", "filename_prefix", "ckpt_name"}
PACKS = [
    ("image", "Chroma1-HD.safetensors", "txt2img-chroma", IMAGE_VARS),
    ("edit", "qwen-image-edit-2511-Q4_K_M.gguf", "edit-qwen", EDIT_VARS),
    ("video", "wan2.2_i2v_14b_fp8_pack", "img2vid-wan22-14b", VIDEO_VARS),
    ("video", "wan2.2_5b_fp16_pack", "img2vid-wan", VIDEO_VARS),
]

# Inputs that name a model file, per loader node.
FILE_INPUTS = {"unet_name", "clip_name", "clip_name1", "clip_name2", "vae_name", "lora_name", "ckpt_name"}


def _catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _entry(section: str, model_id: str) -> dict:
    cat = _catalog()
    prov, cap = CAPABILITY_SECTIONS[section]
    for e in cat["providers"][prov][cap]:
        if e["id"] == model_id:
            return e
    raise AssertionError(f"{model_id} is not in providers.{prov}.{cap}")


def _workflow(name: str) -> dict:
    data = json.loads((WORKFLOWS / f"{name}.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


# ── the catalog ──────────────────────────────────────────────────────


def test_every_spicy_default_is_an_adult_capable_entry_of_its_capability():
    defaults = _catalog()["spicy_defaults"]
    for cap in CAPABILITY_SECTIONS:
        assert defaults.get(cap), f"spicy_defaults has no {cap} models"
        for model_id in defaults[cap]:
            e = _entry(cap, model_id)
            assert e.get("nsfw") is True or e.get("adult_capable") is True, (
                f"{model_id} is a Spicy default but marked neither nsfw nor adult_capable"
            )


@pytest.mark.parametrize("cap,model_id", [
    ("image", "Chroma1-HD.safetensors"),
    ("edit", "qwen-image-edit-2511-Q4_K_M.gguf"),
    ("video", "wan2.2_i2v_14b_fp8_pack"),
    ("video", "wan2.2_5b_fp16_pack"),
    ("video", "hunyuanvideo_t2v_720p_gguf_q4_k_m_pack"),
])
def test_general_purpose_models_stay_visible_outside_spicy_mode(cap, model_id):
    # `nsfw: true` hides a model when Spicy mode is off (Models.tsx) and bars it from the essay
    # pipeline. These are general-purpose models that can *also* follow adult prompts, so they
    # carry adult_capable instead; marking them nsfw removed Wan and Hunyuan from essay video.
    e = _entry(cap, model_id)
    assert e.get("adult_capable") is True
    assert e.get("nsfw") is False


@pytest.mark.parametrize("section,model_id,_wf,_vars", PACKS)
def test_new_packs_name_every_file_with_a_source_and_a_destination(section, model_id, _wf, _vars):
    install = _entry(section, model_id)["install"]
    assert install["type"] == "hf_files"
    for f in install["files"]:
        assert f["repo_id"] and f["filename"] and f["dest"]
        assert "/" in f["dest"], "dest is relative to ComfyUI's models folder, with a subfolder"


@pytest.mark.parametrize("section,model_id,workflow,_vars", PACKS)
def test_each_workflow_loads_only_files_its_pack_installs(section, model_id, workflow, _vars):
    installed = {Path(f["dest"]).name for f in _entry(section, model_id)["install"]["files"]}
    wanted = {
        str(v)
        for node in _workflow(workflow).values()
        for k, v in node.get("inputs", {}).items()
        if k in FILE_INPUTS and isinstance(v, str) and "{{" not in v
    }
    assert wanted, f"{workflow} loads no model files"
    missing = wanted - installed
    assert not missing, f"{workflow} loads {sorted(missing)}, which the {model_id} pack never installs"


# ── the workflows ────────────────────────────────────────────────────


@pytest.mark.parametrize("_section,_id,workflow,variables", PACKS)
def test_workflow_links_point_at_existing_nodes(_section, _id, workflow, variables):
    wf = _workflow(workflow)
    for node_id, node in wf.items():
        assert "class_type" in node, f"{workflow} node {node_id} has no class_type"
        for name, value in node.get("inputs", {}).items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                assert value[0] in wf, f"{workflow} node {node_id}.{name} links to missing node {value[0]}"


@pytest.mark.parametrize("_section,_id,workflow,variables", PACKS)
def test_workflow_placeholders_are_all_supplied_by_the_caller(_section, _id, workflow, variables):
    used = {m for s in _strings(_workflow(workflow)) for m in re.findall(r"\{\{(\w+)\}\}", s)}
    assert used <= variables, f"{workflow} expects {sorted(used - variables)} that the caller never sets"


def test_the_wan_5b_workflow_starts_from_the_uploaded_image():
    wf = _workflow("img2vid-wan")
    latent = [n for n in wf.values() if n["class_type"] == "Wan22ImageToVideoLatent"]
    assert latent and "start_image" in latent[0]["inputs"]
    assert not any(n["class_type"] == "EmptyLatentVideo" for n in wf.values())


def test_the_wan_14b_workflow_hands_the_latent_from_the_high_noise_to_the_low_noise_expert():
    wf = _workflow("img2vid-wan22-14b")
    samplers = sorted(
        (n for n in wf.values() if n["class_type"] == "KSamplerAdvanced"),
        key=lambda n: n["inputs"]["start_at_step"],
    )
    high, low = samplers
    assert high["inputs"]["end_at_step"] == low["inputs"]["start_at_step"]
    assert high["inputs"]["return_with_leftover_noise"] == "enable"
    assert low["inputs"]["add_noise"] == "disable"
    high_model = wf[wf[high["inputs"]["model"][0]]["inputs"]["model"][0]]
    assert "high_noise" in wf[high_model["inputs"]["model"][0]]["inputs"]["unet_name"]


# ── architecture and dispatch ────────────────────────────────────────


def test_chroma_is_its_own_architecture_with_real_cfg():
    from app.model_config import detect_architecture_from_filename, get_model_settings

    settings = get_model_settings("Chroma1-HD.safetensors", "1:1", "med")
    assert settings["architecture"] == "chroma"
    assert settings["cfg"] > 1.0, "Chroma uses a real CFG and negative prompt, unlike Flux schnell"
    assert detect_architecture_from_filename("chroma-unlocked-v50-flux.safetensors") == "chroma"


def test_every_image_dispatch_table_sends_chroma_to_its_workflow():
    from app.interactive.playback.render_adapter import _IMAGE_WORKFLOW_BY_ARCH

    assert _IMAGE_WORKFLOW_BY_ARCH["chroma"] == "txt2img-chroma"
    app = ROOT / "backend" / "app"
    assert (app / "orchestrator.py").read_text().count('"chroma": "txt2img-chroma"') == 2
    assert '"chroma": "txt2img-chroma"' in (app / "warmup.py").read_text()


def test_the_wan_14b_pack_is_dispatched_before_the_generic_wan_match():
    from app.interactive.playback.render_adapter import _VIDEO_WORKFLOW_BY_MODEL

    order = [needle for needle, _ in _VIDEO_WORKFLOW_BY_MODEL]
    assert order.index("wan2.2_i2v_14b") < order.index("wan")
    assert dict(_VIDEO_WORKFLOW_BY_MODEL)["wan2.2_i2v_14b"] == "img2vid-wan22-14b"


def test_installed_packs_are_detected_by_their_last_file(monkeypatch, tmp_path):
    from app import providers

    monkeypatch.setattr(providers, "get_comfy_models_path", lambda: tmp_path)
    assert "wan2.2_i2v_14b_fp8_pack" not in providers.scan_installed_models("video")
    for cap, model_id in (("video", "wan2.2_i2v_14b_fp8_pack"), ("edit", "qwen-image-edit-2511-Q4_K_M.gguf")):
        last = _entry(cap, model_id)["install"]["files"][-1]["dest"]
        (tmp_path / last).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / last).write_bytes(b"x")
        assert model_id in providers.scan_installed_models(cap)


# ── the defaults ─────────────────────────────────────────────────────


def _have(*ids):
    return lambda _cap: list(ids)


def test_a_model_the_person_chose_is_kept():
    from app.spicy_defaults import resolve

    assert resolve("video", "svd_xt.safetensors", True, installed=_have("wan2.2_5b_fp16_pack")) == "svd_xt.safetensors"


def test_nothing_is_chosen_outside_spicy_mode():
    from app.spicy_defaults import resolve

    assert resolve("video", None, False, installed=_have("wan2.2_5b_fp16_pack")) is None


def test_spicy_mode_picks_the_best_installed_default():
    from app.spicy_defaults import resolve

    both = _have("wan2.2_5b_fp16_pack", "wan2.2_i2v_14b_fp8_pack")
    assert resolve("video", "", True, installed=both) == "wan2.2_i2v_14b_fp8_pack"
    assert resolve("video", "none", True, installed=_have("wan2.2_5b_fp16_pack")) == "wan2.2_5b_fp16_pack"
    assert resolve("image", None, True, installed=_have("Chroma1-HD.safetensors")) == "Chroma1-HD.safetensors"


def test_with_no_default_installed_the_old_behaviour_stands():
    from app.spicy_defaults import resolve

    assert resolve("video", None, True, installed=_have("svd_xt.safetensors")) is None


def test_the_qwen_editor_is_chosen_only_where_it_can_do_the_job():
    from app.spicy_defaults import use_qwen_edit

    qwen = _have("qwen-image-edit-2511-Q4_K_M.gguf")
    assert use_qwen_edit(has_mask=False, named_model=None, nsfw_mode=True, installed=qwen)
    assert not use_qwen_edit(has_mask=True, named_model=None, nsfw_mode=True, installed=qwen), "a mask needs inpaint"
    assert not use_qwen_edit(has_mask=False, named_model=None, nsfw_mode=False, installed=qwen)
    assert not use_qwen_edit(has_mask=False, named_model=None, nsfw_mode=True, installed=_have())
    assert not use_qwen_edit(
        has_mask=False, named_model="ponyDiffusionV6XL.safetensors", nsfw_mode=True, installed=qwen
    ), "an explicitly named checkpoint wins"
    assert use_qwen_edit(
        has_mask=False, named_model="qwen-image-edit-2511-Q4_K_M.gguf", nsfw_mode=False, installed=_have()
    ), "naming the editor selects it in any mode"

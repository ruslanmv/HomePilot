"""POST /models/install runs the download script with the backend's own Python, off the loop.

Installing a suggested image model failed with "Missing required packages: pip install requests
tqdm": the endpoint started `python3` from PATH — the system Python, without the venv's
packages. And it ran the download inline, so a 4 GB checkpoint froze every other request until
it finished. Both are pinned here, with the subprocess stubbed (nothing is downloaded).
"""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

import pytest


@pytest.fixture()
def main_module():
    from app import main

    return main


def test_the_download_script_runs_with_the_backends_python_on_a_worker_thread(main_module, monkeypatch):
    seen = {}
    loop_thread = threading.get_ident()

    def fake_run(cmd, env=None, logger=None, on_line=None):
        seen["cmd"] = cmd
        seen["thread"] = threading.get_ident()
        on_line("sd15.safetensors:  50%|█████     | 2.00G/4.00G [01:00<01:00, 33.3MB/s]")
        seen["midway"] = dict(main_module._INSTALL_PROGRESS["sd15.safetensors"])
        return 0, ["Downloaded sd15.safetensors (4067.6 MB)"]

    monkeypatch.setattr(main_module, "_run_streaming", fake_run)
    req = main_module.ModelInstallRequest(provider="comfyui", model_id="sd15.safetensors", model_type="image")
    res = asyncio.run(main_module.install_model(req))

    assert res.status_code == 200
    assert seen["cmd"][0] == sys.executable
    assert seen["cmd"][1].endswith("download.py")
    assert seen["cmd"][2:] == ["--model", "sd15.safetensors"]
    assert seen["thread"] != loop_thread
    # The Models page reads this while the request is still running…
    assert seen["midway"]["state"] == "running" and seen["midway"]["percent"] == 50
    # …and sees it finish.
    assert main_module._INSTALL_PROGRESS["sd15.safetensors"]["state"] == "done"


def test_progress_is_read_from_the_scripts_own_lines(main_module):
    """The exact lines an SDXL install printed, and an Ollama pull."""
    key = "sd_xl_base_1.0.safetensors"
    main_module._start_install_progress(key)
    main_module._note_install_progress(key, "[3/3] ⬇️  Downloading model...")
    assert main_module._INSTALL_PROGRESS[key]["stage"] == "Downloading model"
    main_module._note_install_progress(key, "sd_xl_base_1.0.safetensors:   0%|          | 2.48M/6.46G [00:00<19:53, 5.81MB/s]")
    entry = main_module._INSTALL_PROGRESS[key]
    assert (entry["percent"], entry["done"], entry["total"], entry["rate"]) == (0, "2.48M", "6.46G", "5.81MB/s")
    main_module._note_install_progress(key, "sd_xl_base_1.0.safetensors:  42%|████▏     | 2.71G/6.46G [08:01<11:05, 5.63MB/s]")
    assert main_module._INSTALL_PROGRESS[key]["percent"] == 42

    main_module._start_install_progress("llama3.2:3b")
    main_module._note_install_progress("llama3.2:3b", "pulling dde5aa3fc5ff:  42% ▕██████      ▏ 845 MB/2.0 GB   25 MB/s   45s")
    pull = main_module._INSTALL_PROGRESS["llama3.2:3b"]
    assert (pull["percent"], pull["done"], pull["total"], pull["rate"]) == (42, "845 MB", "2.0 GB", "25 MB/s")

    from fastapi.testclient import TestClient

    body = TestClient(main_module.app).get("/models/install/progress", params={"model_id": key}).json()
    assert body["state"] == "running" and body["percent"] == 42
    assert TestClient(main_module.app).get("/models/install/progress", params={"model_id": "nope"}).json()["state"] == "idle"


def test_a_failed_download_reports_the_scripts_last_lines(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "_run_streaming", lambda cmd, env=None, logger=None, on_line=None: (1, ["boom", "HTTP 404"]))
    req = main_module.ModelInstallRequest(provider="comfyui", model_id="sd15.safetensors", model_type="image")
    res = asyncio.run(main_module.install_model(req))
    assert res.status_code == 500
    assert b"HTTP 404" in res.body


def test_the_script_starts_without_tqdm():
    """A Python without tqdm still runs it (plain percentages instead of a bar)."""
    import subprocess
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "download.py"
    code = (
        "import builtins, runpy, sys\n"
        "real = builtins.__import__\n"
        "def fake(name, *a, **k):\n"
        "    if name == 'tqdm' or name.startswith('tqdm.'):\n"
        "        raise ImportError('no tqdm')\n"
        "    return real(name, *a, **k)\n"
        "builtins.__import__ = fake\n"
        f"sys.argv = [{str(script)!r}, '--help']\n"
        f"runpy.run_path({str(script)!r}, run_name='__main__')\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert "Missing required" not in out.stdout + out.stderr
    assert "usage: download.py" in out.stdout


# ── where the script is (app/download_script.py) ────────────────────────────


def test_an_ollama_pull_never_needs_the_download_script(main_module, monkeypatch):
    """The Hugging Face Space had no scripts/ folder, and every install there — Ollama pulls
    included, which never run the script — failed with "Download script not found"."""
    seen = {}

    def fake_run(cmd, env=None, logger=None, on_line=None):
        seen["cmd"] = cmd
        return 0, ["success"]

    monkeypatch.setattr(main_module, "download_script", lambda: Path("/nowhere/scripts/download.py"))
    monkeypatch.setattr(main_module, "_run_streaming", fake_run)
    req = main_module.ModelInstallRequest(provider="ollama", model_id="llama3.2:3b", model_type="chat")
    res = asyncio.run(main_module.install_model(req))
    assert res.status_code == 200
    assert seen["cmd"] == ["ollama", "pull", "llama3.2:3b"]


def test_a_comfyui_install_without_the_script_says_where_it_looked(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "download_script", lambda: Path("/nowhere/scripts/download.py"))
    monkeypatch.setattr(main_module, "_run_streaming", lambda *a, **k: pytest.fail("must not run"))
    req = main_module.ModelInstallRequest(provider="comfyui", model_id="sd15.safetensors", model_type="image")
    res = asyncio.run(main_module.install_model(req))
    assert res.status_code == 500
    assert b"script_not_found" in res.body and b"/nowhere/scripts/download.py" in res.body
    assert b"HOMEPILOT_DOWNLOAD_SCRIPT" in res.body


def test_the_script_is_found_in_the_repo_and_in_a_packaged_image(tmp_path, monkeypatch):
    from app.download_script import download_script

    monkeypatch.delenv("HOMEPILOT_DOWNLOAD_SCRIPT", raising=False)
    assert download_script().is_file()                                       # <repo>/scripts/download.py
    # The Space image: backend/app at /app/app, the script copied to /app/scripts.
    image = tmp_path / "app"
    (image / "app").mkdir(parents=True)
    (image / "scripts").mkdir()
    (image / "scripts" / "download.py").write_text("")
    assert download_script(image / "app") == image / "scripts" / "download.py"
    # Named outright.
    monkeypatch.setenv("HOMEPILOT_DOWNLOAD_SCRIPT", str(tmp_path / "elsewhere" / "download.py"))
    assert download_script() == tmp_path / "elsewhere" / "download.py"

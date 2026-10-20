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

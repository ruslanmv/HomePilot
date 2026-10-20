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

    def fake_run(cmd, env=None, logger=None):
        seen["cmd"] = cmd
        seen["thread"] = threading.get_ident()
        return 0, ["Downloaded sd15.safetensors (4067.6 MB)"]

    monkeypatch.setattr(main_module, "_run_streaming", fake_run)
    req = main_module.ModelInstallRequest(provider="comfyui", model_id="sd15.safetensors", model_type="image")
    res = asyncio.run(main_module.install_model(req))

    assert res.status_code == 200
    assert seen["cmd"][0] == sys.executable
    assert seen["cmd"][1].endswith("download.py")
    assert seen["cmd"][2:] == ["--model", "sd15.safetensors"]
    assert seen["thread"] != loop_thread


def test_a_failed_download_reports_the_scripts_last_lines(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "_run_streaming", lambda cmd, env=None, logger=None: (1, ["boom", "HTTP 404"]))
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

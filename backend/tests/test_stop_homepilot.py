"""``scripts/stop-homepilot.sh`` stops this checkout's processes and nothing else.

Regression: ``make stop`` force-killed whatever listened on 8000/8010/3000 and every
``uvicorn app.main:app`` — on a machine where another project runs a ``kubectl
port-forward`` on 8000 and its own uvicorn, that took the other project down.
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "stop-homepilot.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not shutil.which("bash") or not shutil.which("pgrep"),
    reason="needs bash and pgrep (Linux, macOS, WSL)",
)


def _outside_python():
    """An interpreter that does not live in this checkout (the venv one does, and a
    process running HomePilot's own Python rightly counts as HomePilot's)."""
    for candidate in ("/usr/bin/python3", "/usr/local/bin/python3", "/bin/python3"):
        if Path(candidate).exists() and not str(Path(candidate).resolve()).startswith(str(ROOT)):
            return candidate
    pytest.skip("no system python3 outside the checkout")


def _sleeper(cwd, marker, python=None):
    # The marker is on the command line so --only can select exactly these processes.
    return subprocess.Popen(
        [python or _outside_python(), "-c", f"import time; time.sleep(60)  # {marker}"],
        cwd=str(cwd),
    )


def _alive(proc):
    return proc.poll() is None


def test_only_processes_inside_the_checkout_are_stopped(tmp_path):
    marker = f"hp-stop-test-{os.getpid()}"
    ours = _sleeper(ROOT, marker)
    theirs = _sleeper(tmp_path, marker)
    try:
        time.sleep(0.3)
        out = subprocess.run(
            ["bash", str(SCRIPT), "--only", marker, "--label", "test sleepers"],
            capture_output=True, text=True, timeout=30,
        )
        assert out.returncode == 0, out.stderr
        assert f"Stopping {ours.pid}" in out.stdout
        assert str(theirs.pid) not in out.stdout
        ours.wait(timeout=10)
        assert not _alive(ours)
        assert _alive(theirs), "a process outside the checkout must never be touched"
    finally:
        for proc in (ours, theirs):
            if _alive(proc):
                proc.kill()
                proc.wait(timeout=10)


def test_dry_run_stops_nothing(tmp_path):
    marker = f"hp-stop-dry-{os.getpid()}"
    ours = _sleeper(ROOT, marker)
    try:
        time.sleep(0.3)
        out = subprocess.run(
            ["bash", str(SCRIPT), "--only", marker, "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        assert f"Stopping {ours.pid}" in out.stdout
        assert _alive(ours)
    finally:
        ours.kill()
        ours.wait(timeout=10)


def test_the_shell_that_runs_it_is_never_stopped():
    """Regression: a shell whose working directory was the checkout and whose command text
    happened to match was stopped by `make stop` itself."""
    marker = f"hp-stop-self-{os.getpid()}"
    out = subprocess.run(
        ["bash", "-c", f'cd "{ROOT}" && bash scripts/stop-homepilot.sh --only "{marker}" >/dev/null; echo survived  # {marker}'],
        capture_output=True, text=True, timeout=30,
    )
    assert "survived" in out.stdout


def test_a_terminal_sitting_in_the_checkout_is_not_a_service(tmp_path):
    """Default matching is on service commands, not on any word in a command line."""
    idle = subprocess.Popen(
        [_outside_python(), "-c", "import time; time.sleep(60)  # editing ComfyUI and vite notes"],
        cwd=str(ROOT),
    )
    try:
        time.sleep(0.3)
        out = subprocess.run(["bash", str(SCRIPT), "--dry-run"], capture_output=True, text=True, timeout=30)
        assert str(idle.pid) not in out.stdout
    finally:
        idle.kill()
        idle.wait(timeout=10)


def test_nothing_running_is_a_clean_exit():
    out = subprocess.run(
        ["bash", str(SCRIPT), "--only", "no-such-process-hp-xyz", "--label", "nothing"],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0
    assert "No nothing running." in out.stdout


def test_the_makefile_no_longer_kills_by_port_or_by_name():
    makefile = (ROOT / "Makefile").read_text()
    stop = makefile[makefile.index("\nstop: ##"):]
    stop = stop[: stop.index("\n\n")]
    assert "stop-homepilot.sh" in stop
    assert "lsof -ti" not in stop and "pkill" not in stop

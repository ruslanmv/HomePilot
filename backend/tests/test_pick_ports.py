"""``scripts/pick_ports.py`` — HomePilot moves to free ports instead of failing.

Regression: with a ``kubectl port-forward`` on 8000 and a container on 8010, ``make start``
printed "Address already in use" twice, the backend and edit-session never started, and the
browser talked to the other program on 8000 ("Health check failed: Failed to fetch").
"""
import importlib.util
import json
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pick_ports.py"


@pytest.fixture(scope="module")
def pp():
    spec = importlib.util.spec_from_file_location("pick_ports", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _listen():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", 0))
    sock.listen(1)
    return sock, sock.getsockname()[1]


def _serve(payloads):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = payloads.get(self.path)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_a_busy_port_moves_to_the_next_free_one(pp):
    sock, port = _listen()
    try:
        assert pp.port_busy(port)
        exports, notes = pp.pick([("HOMEPILOT_BACKEND_PORT", port, "homepilot")], owner=lambda p: "kubectl (pid 1)")
        chosen = int(exports["HOMEPILOT_BACKEND_PORT"])
        assert chosen > port and not pp.port_busy(chosen)
        assert notes == [f"Port {port} is used by kubectl (pid 1); HOMEPILOT_BACKEND_PORT uses {chosen} instead."]
    finally:
        sock.close()


def test_a_free_preferred_port_is_kept_and_ports_never_collide(pp):
    busy = {8000, 8010}
    exports, notes = pp.pick(
        [("A", 8000, None), ("B", 8001, None), ("C", 8010, None)],
        busy=lambda p: p in busy, homepilot=lambda p: False, comfy=lambda p: False, owner=lambda p: "",
    )
    # A moves to 8001, so B (which preferred 8001) moves on to 8002.
    assert exports == {"A": "8001", "B": "8002", "C": "8011"}
    assert len(set(exports.values())) == 3
    assert notes[0] == "Port 8000 is in use by another program; A uses 8001 instead."


def test_a_running_comfyui_is_reused_not_duplicated(pp):
    server, port = _serve({"/system_stats": {"system": {"os": "posix"}, "devices": []}})
    try:
        exports, notes = pp.pick([("COMFY_PORT", port, "comfy")])
        assert exports == {"COMFY_PORT": str(port), "COMFY_PORT_REUSE": "1"}
        assert "already running" in notes[0]
    finally:
        server.shutdown()


def test_a_second_homepilot_backend_is_refused(pp):
    server, port = _serve({"/health": {"ok": True, "service": "homepilot-backend"}})
    try:
        with pytest.raises(pp.AlreadyRunning):
            pp.pick([("HOMEPILOT_BACKEND_PORT", port, "homepilot")])
    finally:
        server.shutdown()


def test_a_homepilot_that_was_already_moved_is_found_too(pp):
    """8000 held by kubectl, and an earlier `make start` put HomePilot on 8001: a second
    start must stop instead of starting another copy on 8002."""
    with pytest.raises(pp.AlreadyRunning, match="port 8001"):
        pp.pick(
            [("HOMEPILOT_BACKEND_PORT", 8000, "homepilot")],
            busy=lambda p: p in (8000, 8001), homepilot=lambda p: p == 8001,
            comfy=lambda p: False, owner=lambda p: "kubectl (pid 1)",
        )


def test_a_moved_comfyui_is_reused_too(pp):
    exports, notes = pp.pick(
        [("COMFY_PORT", 8188, "comfy")],
        busy=lambda p: p in (8188, 8189), homepilot=lambda p: False,
        comfy=lambda p: p == 8189, owner=lambda p: "",
    )
    assert exports == {"COMFY_PORT": "8189", "COMFY_PORT_REUSE": "1"}


def test_another_program_answering_health_is_not_mistaken_for_homepilot(pp):
    server, port = _serve({"/health": {"error": {"code": "http_404"}}})
    try:
        exports, _ = pp.pick([("HOMEPILOT_BACKEND_PORT", port, "homepilot")], owner=lambda p: "")
        assert int(exports["HOMEPILOT_BACKEND_PORT"]) != port
    finally:
        server.shutdown()


def test_cli_prints_exports_for_eval_and_notes_on_stderr(pp):
    sock, port = _listen()
    try:
        out = subprocess.run(
            [sys.executable, str(SCRIPT), f"HOMEPILOT_EDIT_PORT={port}"],
            capture_output=True, text=True, timeout=30, check=True,
        )
        line = out.stdout.strip()
        assert line.startswith("export HOMEPILOT_EDIT_PORT=")
        assert int(line.split("=", 1)[1]) != port
        assert f"Port {port}" in out.stderr
    finally:
        sock.close()


def test_cli_rejects_bad_specs(pp):
    out = subprocess.run([sys.executable, str(SCRIPT), "lower=1"], capture_output=True, text=True, timeout=30)
    assert out.returncode == 2 and "bad port spec" in out.stderr

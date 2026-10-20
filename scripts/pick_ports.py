#!/usr/bin/env python3
"""Choose free local ports for ``make start`` so HomePilot runs next to anything else.

Other tools on a developer machine commonly hold HomePilot's default ports — a
``kubectl port-forward`` on 8000, a container on 8010, Langfuse on 3000 — and
HomePilot must never touch them. Instead each HomePilot service moves to the
next free port, and ``make start`` passes the chosen addresses to the backend,
the edit-session service, ComfyUI and the browser.

Usage::

    pick_ports.py NAME=PREFERRED[:KIND] ...

KIND is optional:

``homepilot``  If the preferred port already answers ``/health`` as a HomePilot
               backend, stop with an error instead of starting a second copy.
``comfy``      If the preferred port already answers ``/system_stats`` as
               ComfyUI, reuse it (prints ``NAME_REUSE=1``) rather than loading a
               second copy of the models into the GPU.

stdout: ``export NAME=PORT`` lines for ``eval``. stderr: one line per port that
had to move, naming the program that holds it when the OS says so.
Exit 3 when another HomePilot backend is already running.
"""
from __future__ import annotations

import errno
import json
import re
import shutil
import socket
import subprocess
import sys
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

MAX_TRIES = 100
_SPEC = re.compile(r"^([A-Z][A-Z0-9_]*)=(\d{1,5})(?::(homepilot|comfy))?$")


def _bind_busy(family: int, host: str, port: int) -> bool:
    try:
        sock = socket.socket(family, socket.SOCK_STREAM)
    except OSError:
        return False  # address family not available here: nothing can hold it
    try:
        # Same option uvicorn and Vite use, so a port in TIME_WAIT is not "busy".
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if family == socket.AF_INET6:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        sock.bind((host, port))
        return False
    except OSError as exc:
        return exc.errno in (errno.EADDRINUSE, errno.EACCES)
    finally:
        sock.close()


def _accepts(port: int, timeout: float = 0.3) -> bool:
    """Something answers on loopback. Catches listeners a bind test can miss, such as a
    Windows program seen through WSL mirrored networking."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def port_busy(port: int) -> bool:
    return (
        _bind_busy(socket.AF_INET, "0.0.0.0", port)
        or _bind_busy(socket.AF_INET6, "::", port)
        or _accepts(port)
    )


def http_json(url: str, timeout: float = 1.5) -> Optional[dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 — loopback only
            if resp.status != 200:
                return None
            data = json.loads(resp.read(65536).decode("utf-8", "ignore") or "null")
            return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 — any failure means "not that service"
        return None


def is_homepilot_backend(port: int, fetch: Callable[[str], Optional[dict]] = http_json) -> bool:
    data = fetch(f"http://127.0.0.1:{port}/health")
    return bool(data) and data.get("service") == "homepilot-backend"


def is_comfyui(port: int, fetch: Callable[[str], Optional[dict]] = http_json) -> bool:
    data = fetch(f"http://127.0.0.1:{port}/system_stats")
    return bool(data) and isinstance(data.get("system"), dict)


def owner_of(port: int) -> str:
    """'kubectl (pid 250045)' when ``ss`` can tell, else ''. Never raises."""
    if not shutil.which("ss"):
        return ""
    try:
        out = subprocess.run(
            ["ss", "-ltnpH", f"( sport = :{port} )"],
            capture_output=True, text=True, timeout=2, check=False,
        ).stdout
    except Exception:  # noqa: BLE001
        return ""
    match = re.search(r'users:\(\("([^"]+)",pid=(\d+)', out)
    return f"{match.group(1)} (pid {match.group(2)})" if match else ""


class AlreadyRunning(RuntimeError):
    pass


def pick(
    specs: List[Tuple[str, int, Optional[str]]],
    *,
    busy: Callable[[int], bool] = port_busy,
    homepilot: Callable[[int], bool] = is_homepilot_backend,
    comfy: Callable[[int], bool] = is_comfyui,
    owner: Callable[[int], str] = owner_of,
) -> Tuple[Dict[str, str], List[str]]:
    """Return ``(exports, notes)``. Ports are distinct across all specs."""
    exports: Dict[str, str] = {}
    notes: List[str] = []
    taken: Dict[int, str] = {}  # port -> the HomePilot service it was given to
    for name, preferred, kind in specs:
        port = preferred
        reused = False
        for _ in range(MAX_TRIES):
            if port in taken:
                port += 1
                continue
            if not busy(port):
                break
            # A busy port may be HomePilot's own: a backend from an earlier `make start`
            # (possibly already moved off its default), or a ComfyUI worth reusing.
            if kind == "homepilot" and homepilot(port):
                raise AlreadyRunning(
                    f"HomePilot is already running on port {port}. Stop it first "
                    f"(Ctrl+C in its terminal, or: make stop), then run make start again."
                )
            if kind == "comfy" and comfy(port):
                reused = True
                break
            port += 1
        else:
            raise RuntimeError(f"No free port found for {name} between {preferred} and {preferred + MAX_TRIES}.")
        if reused:
            exports[name] = str(port)
            exports[f"{name}_REUSE"] = "1"
            taken[port] = name
            notes.append(f"ComfyUI is already running on port {port}; HomePilot uses it.")
            continue
        if port != preferred:
            if preferred in taken:
                notes.append(f"Port {preferred} went to {taken[preferred]}; {name} uses {port} instead.")
            else:
                who = owner(preferred)
                held = f"used by {who}" if who else "in use by another program"
                notes.append(f"Port {preferred} is {held}; {name} uses {port} instead.")
        exports[name] = str(port)
        taken[port] = name
    return exports, notes


def parse(argv: List[str]) -> List[Tuple[str, int, Optional[str]]]:
    specs = []
    for arg in argv:
        match = _SPEC.match(arg)
        if not match or not (1 <= int(match.group(2)) <= 65535):
            raise ValueError(f"bad port spec {arg!r} (expected NAME=PORT or NAME=PORT:homepilot|comfy)")
        specs.append((match.group(1), int(match.group(2)), match.group(3)))
    return specs


def main(argv: List[str]) -> int:
    try:
        specs = parse(argv)
        exports, notes = pick(specs)
    except AlreadyRunning as exc:
        print(f"  ✗ {exc}", file=sys.stderr)
        return 3
    except (ValueError, RuntimeError) as exc:
        print(f"  ✗ {exc}", file=sys.stderr)
        return 2
    for note in notes:
        print(f"  ↪ {note}", file=sys.stderr)
    for name, value in exports.items():
        print(f"export {name}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

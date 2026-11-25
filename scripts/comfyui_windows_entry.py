"""
Entry point for the Windows-native ComfyUI (scripts/start-comfyui.ps1).

Runs ComfyUI's own ``main.py`` unchanged, after one fix for a Python bug on Windows:
asyncio's Proactor transport calls ``socket.shutdown()`` while tearing down a connection
the client already reset. Python 3.11 lets that ``ConnectionResetError`` escape, which

  * prints "Exception in callback _ProactorBasePipeTransport._call_connection_lost ...
    ConnectionResetError: [WinError 10054]" for every such connection (the WSL backend
    closes connections abruptly over mirrored networking, so this was frequent), and
  * skips the rest of the teardown, so the socket is never closed.

The replacement below is Python 3.11's method with the ``shutdown()`` guarded: a peer that
already reset or closed the connection just means there is nothing left to shut down.
ComfyUI's files are not modified, so upgrading ComfyUI keeps working.
"""
from __future__ import annotations

import os
import runpy
import socket
import sys


def _patch_proactor_connection_lost() -> None:
    try:
        from asyncio import proactor_events
    except ImportError:  # not Windows
        return
    transport = getattr(proactor_events, "_ProactorBasePipeTransport", None)
    if transport is None or not hasattr(transport, "_call_connection_lost"):
        return

    def _call_connection_lost(self, exc):
        if self._called_connection_lost:
            return
        try:
            self._protocol.connection_lost(exc)
        finally:
            # Shut down first (as CPython does), but a peer that already reset or closed
            # the connection is not an error here — and must not skip the close below.
            if hasattr(self._sock, "shutdown") and self._sock.fileno() != -1:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                    pass
            self._sock.close()
            self._sock = None
            server = self._server
            if server is not None:
                server._detach()
                self._server = None
            self._called_connection_lost = True

    transport._call_connection_lost = _call_connection_lost


if sys.platform == "win32":
    _patch_proactor_connection_lost()


if __name__ == "__main__":
    # Windows starts child processes by re-importing the main script (as __mp_main__);
    # only the real start runs ComfyUI. The launcher sets the working folder to ComfyUI.
    comfy_dir = os.getcwd()
    main_py = os.path.join(comfy_dir, "main.py")
    if not os.path.isfile(main_py):
        sys.exit(f"ComfyUI main.py not found in {comfy_dir}")
    sys.path.insert(0, comfy_dir)
    sys.argv = [main_py] + sys.argv[1:]
    runpy.run_path(main_py, run_name="__main__")

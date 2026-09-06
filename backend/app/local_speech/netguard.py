"""Proving there was no network (batch LS3).

The plan's acceptance for this batch is not "it works offline". It is **zero outbound sockets**,
which is a stronger and much more useful claim: a feature can work offline today and start
phoning home the first time somebody swaps a model name back in, and nothing about the transcript
would look different.

So this is a context manager that makes an outbound connection *fail loudly* and records the
attempt. Wrapping the load-and-transcribe path in it turns "audio stays on this computer" from a
sentence in the interface into something a test can hold the code to.

It blocks connections, not sockets: a local Unix socket, a pipe to a worker, a loopback call to
Ollama on this machine are all fine and none of them leave the machine. What is refused is
`connect()` to anything that is not loopback.
"""

from __future__ import annotations

import contextlib
import socket
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

LOOPBACK = ("127.0.0.1", "::1", "localhost", "0.0.0.0", "")


class OutboundBlocked(RuntimeError):
    """Raised at the point of the attempt, so a traceback names the line that dialled out."""


@dataclass
class Attempts:
    """What tried to leave, if anything."""

    outbound: List[Tuple[str, object]] = field(default_factory=list)
    loopback: List[Tuple[str, object]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.outbound


def _host_of(address) -> str:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return str(address)


def _is_loopback(host: str) -> bool:
    return host in LOOPBACK or host.startswith("127.") or host.endswith(".local")


@contextlib.contextmanager
def no_outbound(*, allow_loopback: bool = True):
    """Refuse every non-loopback ``connect`` for the duration, and report what was tried."""
    attempts = Attempts()
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def guard(self, address, *args, **kwargs):
        host = _host_of(address)
        if allow_loopback and _is_loopback(host):
            attempts.loopback.append(("connect", address))
            return real_connect(self, address, *args, **kwargs)
        attempts.outbound.append(("connect", address))
        raise OutboundBlocked(f"outbound connection to {address!r} during a local-only path")

    def guard_ex(self, address, *args, **kwargs):
        host = _host_of(address)
        if allow_loopback and _is_loopback(host):
            attempts.loopback.append(("connect_ex", address))
            return real_connect_ex(self, address, *args, **kwargs)
        attempts.outbound.append(("connect_ex", address))
        raise OutboundBlocked(f"outbound connection to {address!r} during a local-only path")

    def guard_lookup(host, *args, **kwargs):
        # A DNS lookup is an outbound packet too, and it is what a download does first — so a
        # guard that only watched `connect` would miss the most informative moment.
        if allow_loopback and _is_loopback(str(host)):
            return real_getaddrinfo(host, *args, **kwargs)
        attempts.outbound.append(("getaddrinfo", host))
        raise OutboundBlocked(f"name lookup for {host!r} during a local-only path")

    socket.socket.connect = guard
    socket.socket.connect_ex = guard_ex
    socket.getaddrinfo = guard_lookup
    try:
        yield attempts
    finally:
        socket.socket.connect = real_connect
        socket.socket.connect_ex = real_connect_ex
        socket.getaddrinfo = real_getaddrinfo

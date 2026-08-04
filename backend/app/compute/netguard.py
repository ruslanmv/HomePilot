"""
SSRF guard for custom compute endpoints (security hardening).

A ``ComputeSource`` can point HomePilot at an arbitrary ``base_url`` (an
OpenAI-compatible endpoint, a remote ComfyUI). Before the server makes an
outbound request there — at save time and again before each probe/call — we
validate the URL so a user (or a compromised setting) can't turn the backend
into an SSRF proxy.

Policy, tuned for *this* product:
  * scheme MUST be http/https (no file://, gopher://, …);
  * the **cloud metadata service** (169.254.169.254, fd00:ec2::254) and other
    link-local / loopback-as-metadata addresses are always blocked;
  * private LAN ranges (RFC1918, ULA) are **allowed by default** — self-hosted
    GPU nodes legitimately live at 10.x / 192.168.x / a ``.local`` host. Operators
    who want a stricter posture set ``HOMEPILOT_COMPUTE_BLOCK_PRIVATE=true``.

Hostnames are resolved and *every* resolved address is checked, so a name that
maps to a blocked IP is rejected too. Resolution failures don't hard-block
(the real request will simply fail) — we only block on a positive match.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse


class UnsafeEndpointError(ValueError):
    """Raised when a compute endpoint URL is not allowed to be contacted."""


# Link-local (169.254/16, fe80::/10) covers the 169.254.169.254 metadata IP.
_METADATA_HOSTS = {"169.254.169.254", "fd00:ec2::254", "metadata.google.internal"}


def _block_private() -> bool:
    return os.getenv("HOMEPILOT_COMPUTE_BLOCK_PRIVATE", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _ip_is_blocked(ip: ipaddress._BaseAddress) -> bool:
    # Always block link-local (covers the 169.254.169.254 metadata IP),
    # multicast, and the unspecified address — regardless of policy.
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return True
    # Loopback (a local Ollama/ComfyUI on 127.0.0.1 / ::1) and private LAN
    # (a self-hosted vLLM on 10.x / 192.168.x) are legitimate targets by
    # default; only blocked when the operator opts into the strict policy.
    # NB: is_link_local is checked first, so metadata (which is also is_private
    # per RFC) is already blocked above and never reaches this allowance.
    if ip.is_loopback or ip.is_private:
        return _block_private()
    return False


def _resolve(host: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return []
    out: list[ipaddress._BaseAddress] = []
    for info in infos:
        addr = info[4][0]
        try:
            out.append(ipaddress.ip_address(addr.split("%")[0]))
        except ValueError:
            continue
    return out


def validate_outbound_url(url: str | None) -> None:
    """Raise ``UnsafeEndpointError`` if ``url`` must not be contacted. No-op for
    an empty URL (nothing to dial)."""
    if not url:
        return
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeEndpointError(f"Only http/https endpoints are allowed (got {parsed.scheme or 'no'} scheme).")
    host = (parsed.hostname or "").strip()
    if not host:
        raise UnsafeEndpointError("Endpoint URL has no host.")
    if host.lower() in _METADATA_HOSTS:
        raise UnsafeEndpointError("Cloud metadata endpoints are not allowed.")

    # Literal IP → check directly; hostname → check every resolved address.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    candidates = [literal] if literal is not None else _resolve(host)
    for ip in candidates:
        if ip is None:
            continue
        # The metadata IP is link-local; always blocked regardless of policy.
        if str(ip) in _METADATA_HOSTS or ip.is_link_local:
            raise UnsafeEndpointError("Endpoint resolves to a blocked link-local/metadata address.")
        if _ip_is_blocked(ip):
            raise UnsafeEndpointError(f"Endpoint resolves to a blocked address ({ip}).")


def is_safe_outbound_url(url: str | None) -> bool:
    try:
        validate_outbound_url(url)
        return True
    except UnsafeEndpointError:
        return False

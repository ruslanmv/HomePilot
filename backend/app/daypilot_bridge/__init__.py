"""DayPilot bridge — HomePilot side of the agents integration (Batch A5).

DayPilot connects to HomePilot personas over the OpenAI-compatible
``/v1/chat/completions`` API in *propose-only* mode: the persona reasons with
its full identity/memory but must NOT perform external writes itself. Instead it
proposes structured operations, which HomePilot returns to DayPilot in the
``x_directives`` field. DayPilot validates every directive and routes external
actions through its own Approval Center.

This package is self-contained: it owns HomePilot's copy of the contract
constants and does not import from DayPilot. It never mutates a persona's own
system prompt — the propose-mode instruction is appended as a *separate* system
message and is gone when the turn ends.
"""
from .bridge import (
    BRIDGE_VERSION,
    BridgeContext,
    build_x_homepilot,
    capabilities_document,
    extract_directives,
    parse_bridge_headers,
    propose_system_suffix,
)

__all__ = [
    "BRIDGE_VERSION",
    "BridgeContext",
    "build_x_homepilot",
    "capabilities_document",
    "extract_directives",
    "parse_bridge_headers",
    "propose_system_suffix",
]

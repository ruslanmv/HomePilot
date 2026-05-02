"""
Package an experience into a content-addressable artifact.

A ``PackagedExperience`` pairs the manifest dict with a stable
SHA-256 digest of its canonical JSON form, so:

- The publish flow can detect "manifest unchanged since last
  publish" and skip emitting a duplicate channel record.
- A future signed-distribution channel can hash + sign the same
  bytes the consumer would verify.

Determinism: ``json.dumps(..., sort_keys=True, separators=(",", ":"))``
is the canonical form. Pydantic's model_dump produces dict-of-
primitives so this round-trips cleanly.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict

from ..models import Experience
from .manifest import build_manifest


@dataclass(frozen=True)
class PackagedExperience:
    """Manifest + canonical digest."""

    experience_id: str
    manifest: Dict[str, Any]
    digest: str  # hex SHA-256 of canonical JSON
    canonical_bytes: bytes


def _canonical_json(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def package_experience(experience: Experience) -> PackagedExperience:
    """Build the manifest + digest for an experience.

    Pure read — no DB writes. Safe to call repeatedly; same input
    rows produce the same digest.
    """
    manifest = build_manifest(experience)
    blob = _canonical_json(manifest)
    digest = hashlib.sha256(blob).hexdigest()
    return PackagedExperience(
        experience_id=experience.id,
        manifest=manifest,
        digest=digest,
        canonical_bytes=blob,
    )

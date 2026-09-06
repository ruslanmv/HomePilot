"""Finding the pack, and never fetching one (batch LS3).

The resolver's contract is one sentence: **it returns a directory or it returns nothing.** It
never returns a model name, because a name handed to faster-whisper is a download, and a download
during a meeting is a network dependency in a feature sold as local.

Where it looks, in order — first match wins, and each has a reason:

1. ``HOMEPILOT_SPEECH_PACK`` — an explicit directory. An operator who has staged packs on a
   shared volume should not have to move them.
2. ``HOMEPILOT_SPEECH_DIR`` or the default ``~/.homepilot/speech/`` — where LS4's installer puts
   them, one subdirectory per pack id.
3. Nothing. Which is a supported outcome with its own sentence, not an error.

There is no fourth entry, and adding one that resolves a name would undo the batch.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .manifest import PACKS, PACKS_BY_ID, Pack, Verification, verify

#: An explicit directory holding one pack, checked before anything else.
PACK_DIR_ENV = "HOMEPILOT_SPEECH_PACK"
#: The root holding packs by id.
ROOT_ENV = "HOMEPILOT_SPEECH_DIR"
#: Which pack to prefer when several are installed.
PREFER_ENV = "HOMEPILOT_SPEECH_PACK_ID"

DEFAULT_ROOT = Path.home() / ".homepilot" / "speech"

#: Preference among installed packs, best first. Turbo is the design's eventual default and is
#: ranked first *among what is installed* — which is never a claim that it should be downloaded,
#: and never a claim that it keeps up on this machine. LS5's benchmark answers that.
PREFERENCE = ("whisper-large-v3-turbo", "whisper-small", "whisper-base")


@dataclass
class Resolved:
    """A pack that can be loaded, or the reason there isn't one."""

    pack: Optional[Pack]
    directory: Optional[Path]
    verification: Optional[Verification]
    reason: str = "not-installed"

    @property
    def ok(self) -> bool:
        return self.directory is not None

    def as_dict(self) -> Dict[str, object]:
        return {
            "pack": self.pack.id if self.pack else None,
            "label": self.pack.label if self.pack else None,
            "directory": str(self.directory) if self.directory else None,
            "reason": self.reason,
            "verified": bool(self.verification and self.verification.verified),
            "unverified": bool(self.verification and self.verification.unverified),
            "license": self.pack.license if self.pack else None,
            "source_model": self.pack.source_model if self.pack else None,
        }


def root(environ=None) -> Path:
    env = environ if environ is not None else os.environ
    configured = (env.get(ROOT_ENV) or "").strip()
    return Path(configured) if configured else DEFAULT_ROOT


def _pack_for_directory(directory: Path, environ=None) -> Optional[Pack]:
    """Which manifest entry a directory claims to be — by its own name, then by preference."""
    named = PACKS_BY_ID.get(directory.name)
    if named:
        return named
    env = environ if environ is not None else os.environ
    preferred = (env.get(PREFER_ENV) or "").strip()
    return PACKS_BY_ID.get(preferred)


def installed(environ=None) -> List[Resolved]:
    """Every pack present under the root, verified, best first."""
    out: List[Resolved] = []
    base = root(environ)
    for pack in PACKS:
        directory = base / pack.id
        report = verify(directory, pack)
        if report.present:
            out.append(Resolved(
                pack=pack,
                directory=directory if report.usable else None,
                verification=report,
                reason=report.reason(),
            ))
    order = {pack_id: index for index, pack_id in enumerate(PREFERENCE)}
    out.sort(key=lambda item: order.get(item.pack.id if item.pack else "", len(order)))
    return out


def resolve(environ=None) -> Resolved:
    """The pack to load, as a **directory**, or a reason there is none.

    Never a model name. If this function ever returns something faster-whisper would treat as a
    name, it will download it, and the feature stops being local at the worst possible moment.
    """
    env = environ if environ is not None else os.environ

    explicit = (env.get(PACK_DIR_ENV) or "").strip()
    if explicit:
        directory = Path(explicit)
        pack = _pack_for_directory(directory, env)
        report = verify(directory, pack)
        return Resolved(
            pack=pack,
            directory=directory if report.usable else None,
            verification=report,
            reason=report.reason(),
        )

    wanted = (env.get(PREFER_ENV) or "").strip()
    candidates = installed(env)
    if wanted:
        candidates = [item for item in candidates if item.pack and item.pack.id == wanted] or candidates

    for item in candidates:
        if item.ok:
            return item
    if candidates:
        # Present but unusable: incomplete or corrupt. Say which, rather than "not installed",
        # because the fix is different — one is a finished download, the other is a broken one.
        return candidates[0]
    return Resolved(pack=None, directory=None, verification=None, reason="not-installed")

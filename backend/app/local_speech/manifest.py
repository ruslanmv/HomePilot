"""What a local speech pack *is* (batch LS3).

A pack is a directory of files with a pinned identity: which upstream model it was converted
from, at which revision, under which license, and the SHA-256 of every file in it. Not a model
name. The distinction is the whole batch.

``WhisperModel("small")`` is a **download**. It resolves a name against Hugging Face, fetches a
few hundred megabytes, and caches it — which is fine on a laptop with a browser open and is a
network dependency in a feature sold as "audio stays on this computer". Worse, it is a network
dependency that fires *at the moment somebody starts a meeting*, because that is when the model
loads. The first time it happens on a train, the feature does not degrade; it fails, in front of
people, for a reason nobody can act on.

So the resolver in :mod:`models` hands faster-whisper a **directory**, and a directory cannot
download anything. This module is what says whether that directory is the one it should be.

The manifest is code rather than JSON on purpose: a pack description that ships with the code is
reviewed with the code, and cannot be edited on a running install to point somewhere else.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: Files CTranslate2 needs to load a converted Whisper model. A pack missing any of them is not a
#: pack; a pack with extra files is fine, because quantisation variants and tokenizer spellings
#: differ between conversions and refusing an unknown *extra* file would break packs that work.
REQUIRED = ("model.bin", "config.json", "tokenizer.json", "vocabulary.json")

#: Alternates the conversion tool has used for the same role, newest spelling first. Checked only
#: when the canonical name is absent.
ALTERNATES: Dict[str, Tuple[str, ...]] = {
    "vocabulary.json": ("vocabulary.txt",),
    "tokenizer.json": ("tokenizer_config.json",),
}


@dataclass(frozen=True)
class Pack:
    """A pinned, named, licensed model directory."""

    id: str
    #: The name a person reads. Not a filename and not a model id.
    label: str
    #: What it was converted from, and at which upstream revision. A pack whose provenance is
    #: "whisper, probably" is a pack nobody can reproduce or audit.
    source_model: str
    source_revision: str
    license: str
    #: Approximate installed size. The UI must read this rather than hard-code a figure:
    #: CTranslate2 conversion and quantisation change the footprint, so any number written into
    #: the interface is wrong the first time the pack is rebuilt (LS4).
    size_mb: int
    #: Languages the pack is good for. ``None`` means multilingual. An English-only pack must
    #: never become a silent default, so this is checked rather than assumed.
    languages: Optional[Tuple[str, ...]] = None
    #: ``{filename: sha256}``. Empty means "this build has not been hashed yet" — a pack can be
    #: used without hashes and is reported as unverified, which is a different thing from
    #: verified-and-wrong and must not be collapsed into it.
    digests: Dict[str, str] = field(default_factory=dict)

    @property
    def multilingual(self) -> bool:
        return self.languages is None


#: The packs this build knows about.
#:
#: `large-v3-turbo` is named the eventual default by the design and is listed first, but LS1's
#: `small` remains what an unconfigured install uses until LS5's hardware profile can say whether
#: turbo keeps up on the machine in front of it. Choosing a default from a datasheet is what this
#: series keeps refusing to do.
PACKS: Tuple[Pack, ...] = (
    Pack(
        id="whisper-large-v3-turbo",
        label="Whisper Turbo",
        source_model="openai/whisper-large-v3-turbo",
        source_revision="",
        license="MIT",
        size_mb=1620,
    ),
    Pack(
        id="whisper-small",
        label="Whisper Small",
        source_model="openai/whisper-small",
        source_revision="",
        license="MIT",
        size_mb=484,
    ),
    Pack(
        id="whisper-base",
        label="Whisper Base",
        source_model="openai/whisper-base",
        source_revision="",
        license="MIT",
        size_mb=145,
    ),
)

PACKS_BY_ID: Dict[str, Pack] = {pack.id: pack for pack in PACKS}


@dataclass
class Verification:
    """What a directory turned out to be."""

    pack: Optional[Pack]
    path: Optional[Path]
    present: bool = False
    complete: bool = False
    #: True only when every digest in the manifest matched. False when one did not.
    verified: bool = False
    #: True when the manifest carries no digests to check against — not the same as a failure,
    #: and reported separately so a build that has not been hashed cannot masquerade as verified.
    unverified: bool = False
    missing: List[str] = field(default_factory=list)
    mismatched: List[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Whether this directory can be handed to the engine.

        Complete and either verified or honestly unverified. A *mismatched* digest is never
        usable: a file that is not the file the manifest names is either a broken download or
        something worse, and both want the same answer.
        """
        return self.complete and not self.mismatched

    def reason(self) -> str:
        if not self.present:
            return "not-installed"
        if self.missing:
            return "incomplete"
        if self.mismatched:
            return "corrupt"
        if self.unverified:
            return "unverified"
        return "ok"


def sha256(path: Path, *, chunk: int = 1 << 20) -> str:
    """Streamed, because a pack file is hundreds of megabytes and this runs at startup."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_required(directory: Path) -> Tuple[List[Path], List[str]]:
    found: List[Path] = []
    missing: List[str] = []
    for name in REQUIRED:
        candidate = directory / name
        if candidate.is_file():
            found.append(candidate)
            continue
        alternate = next((directory / alt for alt in ALTERNATES.get(name, ()) if (directory / alt).is_file()), None)
        if alternate is not None:
            found.append(alternate)
        else:
            missing.append(name)
    return found, missing


def verify(directory: Path, pack: Optional[Pack] = None) -> Verification:
    """Inspect *directory* against *pack*. Never raises; an unreadable pack is a reported one."""
    directory = Path(directory)
    if not directory.is_dir():
        return Verification(pack=pack, path=directory, present=False)

    found, missing = _resolve_required(directory)
    result = Verification(
        pack=pack,
        path=directory,
        present=True,
        complete=not missing,
        missing=missing,
    )
    digests = dict(pack.digests) if pack else {}
    if not digests:
        result.unverified = True
        return result

    for name, expected in digests.items():
        candidate = directory / name
        if not candidate.is_file():
            result.missing.append(name)
            result.complete = False
            continue
        try:
            if sha256(candidate) != expected:
                result.mismatched.append(name)
        except OSError:
            result.mismatched.append(name)
    result.verified = not result.mismatched and result.complete
    return result

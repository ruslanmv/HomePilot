"""Transcription that is local because it cannot be anything else (batches LS3–LS8).

"Audio stays on this computer" is a promise, and a promise in a docstring is worth what a promise
in marketing copy is worth. This package is the arrangement that makes it structural.

**A directory, never a name** (`models.py`, `manifest.py`). `WhisperModel("small")` is a download
— of a few hundred megabytes, at the moment the model loads, which is the moment somebody starts a
meeting. The resolver returns a pinned pack directory or it returns nothing, and a directory
cannot fetch anything. Packs carry provenance, licence and per-file digests; *incomplete*,
*corrupt* and *unverified* are three states with three different fixes and are never collapsed.

**Proved rather than documented** (`netguard.py`). The acceptance is zero outbound sockets, not
"works offline" — a feature can work offline today and phone home the first time somebody swaps a
name back in for a directory, and the transcript would look identical. The guard fails a
non-loopback `connect` *or* a DNS lookup at the moment it happens, and a test drives it with the
exact call a download makes, so an assertion of "no sockets" is one that could have failed.

**The device it got, not the device it asked for** (`hardware.py`, `benchmark.py`). `auto` falls
back to CPU silently when CUDA is present but unusable, and an install running ten times slower
than its budget while the interface says GPU is worse than one that says CPU. The profile records
what the engine reported back, measured once against a short sample and cached. Nothing here
decides which runtime is fastest on which vendor: the benchmark decides, which is the plan's rule
and the reason `candidates()` is a search order rather than a verdict.

**Keeping up is the certification** (`keepup.py`). Not "can it load" — those are different
machines and only one is usable. When it cannot: a lighter *local* model first, and only one
already installed; remote only to somebody who had already enabled it, and only ever as a
question. The default answer to "your computer is slow" is never "so let us send your meeting
somewhere else".

**Six failure modes, kept apart** (`status.py`). Model not found, cold load, wrong device, decode
failure, empty response, remote in use. `not installed` is a button and `not loaded yet` is a
wait; a status endpoint that merges them sends somebody to install what they already have.

**And nothing changes the default without data from here** (`bench.py`). Thirteen metrics, the
decoding parameters that make a comparison a comparison, and an empty result table — because this
repository has no licensed corpus and no GPU, and a table nobody measured would be worse than
none.
"""

from .hardware import Hardware, detect  # noqa: F401
from .manifest import PACKS, Pack, Verification, verify  # noqa: F401
from .models import Resolved, installed, resolve  # noqa: F401
from .netguard import OutboundBlocked, no_outbound  # noqa: F401
from .provider import HomePilotLocalSTTProvider  # noqa: F401

__all__ = [
    "Hardware", "HomePilotLocalSTTProvider", "OutboundBlocked", "PACKS", "Pack", "Resolved",
    "Verification", "detect", "installed", "no_outbound", "resolve", "verify",
]

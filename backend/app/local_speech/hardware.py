"""What this machine actually has, and what the model actually loaded on (batch LS3/LS5).

Two questions that look like one and are not:

* **what is available** — is there a CUDA device, is this Apple silicon, how many cores;
* **what did the model load on** — which is the only one worth showing a person.

The second is why this module exists. faster-whisper's ``device="auto"`` falls back to CPU
silently when CUDA is present but unusable: a mismatched ctranslate2 wheel, a missing cuDNN. The
install then runs ten times slower than the budget assumed while the interface says GPU, and the
operator is left with a mystery instead of a cause. LS5's acceptance is exactly this case, and it
is invisible without a place to read the answer back from.

Nothing here decides which runtime is fastest. That is a measurement (`benchmark.py`), not a
lookup, and hard-coding it from documentation is what the plan explicitly forbids.
"""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Hardware:
    """What was detected. Every field is an observation, none is a recommendation."""

    system: str = ""
    machine: str = ""
    cpu_count: int = 0
    apple_silicon: bool = False
    cuda: bool = False
    cuda_devices: List[str] = field(default_factory=list)
    #: Present but unusable is its own state: the reason a "GPU" install runs at CPU speed.
    cuda_reason: str = ""
    total_ram_gb: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

    def candidate_devices(self) -> List[str]:
        """Devices worth *trying*, best first. Not a claim that any of them is faster."""
        out: List[str] = []
        if self.cuda:
            out.append("cuda")
        out.append("cpu")
        return out


def _ram_gb() -> Optional[float]:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
        return round(pages * size / (1024 ** 3), 1)
    except (ValueError, OSError, AttributeError):
        return None


def _cuda() -> tuple:
    """``(available, devices, reason)``. Never raises and never imports torch.

    ctranslate2 is what actually runs the model, so it is what gets asked. Importing torch to
    answer a question about ctranslate2 would be both slower and wrong.
    """
    try:
        import ctranslate2  # noqa: PLC0415
    except Exception as exc:
        return False, [], f"ctranslate2-unavailable: {type(exc).__name__}"
    try:
        count = int(ctranslate2.get_cuda_device_count())
    except Exception as exc:
        return False, [], f"cuda-query-failed: {type(exc).__name__}"
    if count <= 0:
        # A driver present with no usable device is the silent-fallback case; say so.
        reason = "no-cuda-device" if shutil.which("nvidia-smi") is None else "driver-present-no-device"
        return False, [], reason
    return True, [f"cuda:{index}" for index in range(count)], ""


def detect() -> Hardware:
    """Look once. Cheap enough to call at startup, and never fatal."""
    system = platform.system()
    machine = platform.machine()
    cuda, devices, reason = _cuda()
    return Hardware(
        system=system,
        machine=machine,
        cpu_count=os.cpu_count() or 0,
        apple_silicon=system == "Darwin" and machine in ("arm64", "aarch64"),
        cuda=cuda,
        cuda_devices=devices,
        cuda_reason=reason,
        total_ram_gb=_ram_gb(),
    )

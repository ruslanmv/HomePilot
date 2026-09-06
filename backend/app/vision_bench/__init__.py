"""The bench set (batch V8).

Twenty cases, generated as code rather than committed as PNGs, run through the adapter and
measured. It answers two questions nothing else in this repository could:

**Did the resize destroy the text?** `metrics.py` measures stroke survival — a bar `w` source
pixels wide scaled by `s` lands on `w × s` output pixels, and below about one it averages into
the ground. The answer comes back in source pixels ("at 3840 wide, strokes under 3px are gone"),
which is a sentence about the user's screen and the thing that says whether a crop is needed.

**Which of the six failure modes was it?** `failures.py` keeps them apart: the model answered
with nothing, the bytes would not decode, the image was past the ceiling, the resize took the
text, a different model ran than the one chosen, the provider refused. They all used to arrive as
the same empty string, and the product answered every one of them by suggesting a larger model —
though two are not the model's fault at all, and one of those two is the most common.

Run it: `python -m app.vision_bench`. No Ollama, no GPU, no download.

## What it found

Two gaps on the first run, both now fixed in `vision_adapter`:

* the **decompression bomb decoded**. 315 KB on disk, a hundred megapixels in memory, and no
  complaint — "the image exceeded a safety limit" was a failure mode with nothing behind it,
  because nothing enforced a limit. There is a pre-decode ceiling now (`MAX_PIXELS`), checked
  against the header so refusing costs nothing, and a typed `image_too_large` above it;
* **animated files passed through silently**. The model is handed one frame of several and has no
  way to say so, which made "she described the wrong moment" indistinguishable from "she misread
  it". Recorded as `animated:N` rather than refused — the first frame of a screen recording is
  still an answer.

## What it cannot do from here

Run a model. This repository has no Ollama, so every row is the adapter's half of the story. That
is precisely why V5's verified multi-image set and V7's `vision_input` metadata are both still
empty: filling them is a measurement somebody takes on hardware, and this is the harness that
takes it — `run(analyze=...)` accepts a real one.
"""

from .corpus import Case, by_name, cases  # noqa: F401
from .failures import MODES, classify, distinguishable  # noqa: F401
from .metrics import Survival, stroke_survival  # noqa: F401
from .runner import Row, run, run_case, summary, table  # noqa: F401

__all__ = [
    "Case", "MODES", "Row", "Survival",
    "by_name", "cases", "classify", "distinguishable", "run", "run_case",
    "stroke_survival", "summary", "table",
]

"""Six failure modes, and keeping them apart (batch V8).

The plan's requirement is exact: *report adapter details in ``meta`` so the six failure modes
stay distinguishable*. They are

    ``empty_model_response``  the model answered, with nothing in it
    ``decode_failed``         the bytes were not an image this can read
    ``over_limit``            the image was past a safety ceiling and was never decoded
    ``ocr_damaged``           the resize took the text with it
    ``selection_ignored``     the model that ran is not the model that was chosen
    ``provider_rejected``     the provider would not take the request or the format

Before this series, all six arrived as the same shrug — an empty ``analysis_text``, and a product
that answered every one of them by suggesting a larger model. Two of them are not even the
model's fault, and one of those two (``ocr_damaged``) is the most common of the lot.

:func:`classify` is a pure function of what a request already reports, so it can be tested
without a model and read off a log afterwards. It returns **every** mode that applies, because a
request can have more than one and picking a winner is how a report loses the interesting half.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

EMPTY_MODEL_RESPONSE = "empty_model_response"
DECODE_FAILED = "decode_failed"
OVER_LIMIT = "over_limit"
OCR_DAMAGED = "ocr_damaged"
SELECTION_IGNORED = "selection_ignored"
PROVIDER_REJECTED = "provider_rejected"

MODES = (
    EMPTY_MODEL_RESPONSE,
    DECODE_FAILED,
    OVER_LIMIT,
    OCR_DAMAGED,
    SELECTION_IGNORED,
    PROVIDER_REJECTED,
)

#: One sentence each, in the register the product uses: what happened, and whose problem it is.
EXPLAIN = {
    EMPTY_MODEL_RESPONSE: "the model answered and said nothing",
    DECODE_FAILED: "the bytes were not an image this can read",
    OVER_LIMIT: "the image was past the pixel ceiling and was never decoded",
    OCR_DAMAGED: "the resize left no legible strokes — the model never had the text",
    SELECTION_IGNORED: "a different model ran than the one that was chosen",
    PROVIDER_REJECTED: "the provider refused the request or the format",
}


def classify(
    result: Dict[str, Any],
    *,
    requested_model: Optional[str] = None,
    finest_stroke: Optional[int] = None,
    strokes_offered: Sequence[int] = (),
) -> List[str]:
    """Every failure mode this result exhibits, in the order they are declared.

    ``finest_stroke`` is :mod:`metrics`' answer — the narrowest source stroke still legible after
    the adapter, or ``None`` when none survived. It is the only input that does not come from the
    request itself, because it is the only one nothing in the request can know.
    """
    meta = result.get("meta") or {}
    adapter = meta.get("adapter") or {}
    warnings = list(adapter.get("warnings") or [])
    code = str(result.get("error_code") or "")
    found: List[str] = []

    if any(w.startswith("over-limit") for w in warnings) or code == "image_too_large":
        found.append(OVER_LIMIT)

    if "unmeasured" in warnings or "empty" in warnings or "adapt-failed" in warnings:
        found.append(DECODE_FAILED)

    if code in ("empty_model_response",) or (result.get("ok") and not str(result.get("analysis_text") or "").strip()):
        found.append(EMPTY_MODEL_RESPONSE)

    if requested_model and meta.get("model") and meta["model"] != requested_model:
        found.append(SELECTION_IGNORED)

    if code in ("provider_rejected", "model_not_found", "rung_failed") or (
        not result.get("ok") and code not in ("empty_model_response", "image_too_large", "")
        and OVER_LIMIT not in found
    ):
        found.append(PROVIDER_REJECTED)

    # Only meaningful where the case actually drew strokes and the image survived to be measured.
    if strokes_offered and OVER_LIMIT not in found and DECODE_FAILED not in found:
        if finest_stroke is None:
            found.append(OCR_DAMAGED)

    # Declared order, and no duplicates — a report that lists a mode twice reads as two problems.
    return [mode for mode in MODES if mode in found]


def distinguishable(observations: Dict[str, List[str]]) -> List[str]:
    """Modes that never appear on their own across ``observations`` — the ones that have collapsed.

    A status field that cannot separate two failures has failed at the one job it has, so the
    bench asserts this rather than trusting the classifier's shape.
    """
    alone = {mode for modes in observations.values() if len(modes) == 1 for mode in modes}
    return [mode for mode in MODES if mode not in alone]

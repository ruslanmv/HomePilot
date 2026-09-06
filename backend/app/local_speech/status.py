"""Status worth reading (batch LS7).

The plan's acceptance is a property, not a field list: **six failure modes must be
distinguishable from the status payload alone** — empty model response, decode failure, wrong
device, cold load, remote in use, model not found. *A status endpoint that collapses any two of
those has failed at the one job it has.*

It is worth being concrete about why each of those matters, because the temptation with a status
endpoint is always to answer `{"ok": false}` and let somebody read the logs:

* **model not found** — nothing is installed. One button fixes it.
* **cold load** — installed, not warmed. The first line will be slow and then it will be fine;
  telling somebody their transcription is broken here would be wrong.
* **wrong device** — it asked for CUDA and got CPU. Everything works and runs ten times slower
  than the budget assumed. This is the one that is invisible without being asked for by name.
* **decode failure** — the audio was not audio. Nothing about the model is wrong.
* **empty model response** — it ran, and said nothing.
* **remote in use** — it is working, and it is not local. Whatever else is true, somebody who
  chose this feature for privacy needs to see that sentence.

The last one is why `local` is a field rather than an inference. A payload where "local" has to be
deduced from which provider name happens to be set is a payload that will eventually say the
wrong thing about the only question that matters here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

MODEL_NOT_FOUND = "model_not_found"
COLD_LOAD = "cold_load"
WRONG_DEVICE = "wrong_device"
DECODE_FAILURE = "decode_failure"
EMPTY_MODEL_RESPONSE = "empty_model_response"
REMOTE_IN_USE = "remote_in_use"

MODES = (
    MODEL_NOT_FOUND,
    COLD_LOAD,
    WRONG_DEVICE,
    DECODE_FAILURE,
    EMPTY_MODEL_RESPONSE,
    REMOTE_IN_USE,
)

EXPLAIN = {
    MODEL_NOT_FOUND: "no local pack is installed",
    COLD_LOAD: "installed, not loaded yet — the first line will be slow",
    WRONG_DEVICE: "asked for one device and got another; it works, and slowly",
    DECODE_FAILURE: "the audio could not be decoded",
    EMPTY_MODEL_RESPONSE: "it ran and returned nothing",
    REMOTE_IN_USE: "transcription is not local right now",
}


def payload(
    *,
    provider=None,
    profile=None,
    keepup=None,
    remote_in_use: bool = False,
    remote_configured: bool = False,
    last_error: str = "",
    last_result_empty: bool = False,
) -> Dict[str, Any]:
    """The status body. Every field is something a person or a test can act on."""
    base: Dict[str, Any] = {
        "available": False,
        "local": not remote_in_use,
        "engine": None,
        "model": None,
        "device": None,
        "requested_device": None,
        "compute": None,
        "warm": False,
        "supports_segments": False,
        "supports_word_timestamps": False,
        "pack": None,
        "benchmark": None,
        "keepup": None,
        "remote": remote_in_use,
        "remote_configured": remote_configured,
        "last_error": last_error,
    }

    if provider is not None:
        detail = provider.status() if hasattr(provider, "status") else {}
        base.update({
            "available": bool(detail.get("available")),
            "engine": detail.get("engine"),
            "model": (detail.get("pack") or {}).get("pack"),
            "device": detail.get("device"),
            "requested_device": detail.get("requested_device"),
            "compute": detail.get("compute"),
            "warm": bool(detail.get("warm")),
            "supports_segments": bool(detail.get("supports_segments")),
            "supports_word_timestamps": bool(detail.get("supports_word_timestamps")),
            "pack": detail.get("pack"),
            "last_error": last_error or detail.get("load_error") or "",
        })

    if profile is not None:
        base["benchmark"] = profile.as_dict() if hasattr(profile, "as_dict") else dict(profile)
    if keepup is not None:
        base["keepup"] = keepup.stats() if hasattr(keepup, "stats") else dict(keepup)

    base["last_result_empty"] = bool(last_result_empty)
    base["modes"] = classify(base)
    base["label"] = label(base)
    return base


def classify(status: Dict[str, Any]) -> List[str]:
    """Every failure mode this payload exhibits, in declared order.

    Pure, and computed from the payload rather than alongside it, so a consumer that only has the
    JSON reaches the same conclusion the server did. A status field nobody can recompute is a
    status field that will drift.
    """
    found: List[str] = []
    error = str(status.get("last_error") or "")

    if status.get("remote"):
        found.append(REMOTE_IN_USE)
    if not status.get("available") or error.startswith("pack-"):
        found.append(MODEL_NOT_FOUND)
    elif not status.get("warm"):
        # Only meaningful once there is something to warm — "not installed" and "not loaded yet"
        # are different sentences with different buttons.
        found.append(COLD_LOAD)

    requested = str(status.get("requested_device") or "")
    actual = str(status.get("device") or "")
    if actual and requested and requested not in ("auto", "") and actual != requested:
        found.append(WRONG_DEVICE)
    elif actual and requested == "auto":
        benchmark = status.get("benchmark") or {}
        hardware = benchmark.get("hardware") or {}
        # `auto` that landed on CPU while CUDA was detected is the silent fallback. It is not an
        # error anywhere in the stack, which is exactly why it needs naming here.
        if hardware.get("cuda") and actual == "cpu":
            found.append(WRONG_DEVICE)

    if "decode" in error or "transcribe-failed" in error:
        found.append(DECODE_FAILURE)
    if status.get("last_result_empty"):
        found.append(EMPTY_MODEL_RESPONSE)

    return [mode for mode in MODES if mode in found]


def label(status: Dict[str, Any]) -> str:
    """The recording pill's line: `Transcription — Local · Whisper Turbo`."""
    if status.get("remote"):
        return "Transcription — Remote"
    model = status.get("model") or ""
    from .manifest import PACKS_BY_ID  # noqa: PLC0415 — avoids a cycle at import time

    pack = PACKS_BY_ID.get(model)
    name = pack.label if pack else (model or "not installed")
    return f"Transcription — Local · {name}"


def distinguishable(observations: Dict[str, List[str]]) -> List[str]:
    """Modes that never appear alone — the ones that have collapsed."""
    alone = {mode for modes in observations.values() if len(modes) == 1 for mode in modes}
    return [mode for mode in MODES if mode not in alone]

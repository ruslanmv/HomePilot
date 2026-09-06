"""Running the corpus and reporting what happened (batch V8).

Two modes, and the first is the one that matters day to day:

**Without a model.** Every case goes through :func:`vision_adapter.adapt` and the result is
measured — what it became, what it cost, and how much of the text survived. No Ollama, no
download, no GPU: it runs in CI and it is what tunes the caps. Nothing in `profiles.py` was
chosen from a datasheet, and this is the file that turns those numbers from defensible guesses
into measured ones.

**With a model**, by passing an ``analyze``. Then the response joins the report and the failure
classification has all six modes to work with instead of four. Nothing here has been run against
a real model — this repository has no Ollama — which is exactly why V5's verified multi-image set
and V7's ``vision_input`` metadata are both still empty. This is the harness that fills them, and
filling them is a measurement somebody has to take on hardware, not a judgement anybody can make
from here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .. import vision_adapter
from . import failures as _failures
from . import metrics as _metrics
from .corpus import Case, cases


@dataclass
class Row:
    """One case, run."""

    case: str
    asks: str
    ok: bool
    strategy: str = ""
    profile: str = ""
    source: str = ""
    output: str = ""
    scale: float = 1.0
    parts: int = 1
    bytes_in: int = 0
    bytes_out: int = 0
    finest_stroke: Optional[int] = None
    #: What the best detail crop keeps, when one exists. Lower is better and the gap is V6's case.
    finest_stroke_tiled: Optional[int] = None
    warnings: List[str] = field(default_factory=list)
    modes: List[str] = field(default_factory=list)
    ms: int = 0
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def run_case(
    case: Case,
    *,
    model: Optional[str] = None,
    analyze: Optional[Callable[..., Any]] = None,
    environ=None,
) -> Row:
    """Adapt one case, measure it, and classify whatever failed."""
    started = time.monotonic()
    raw = case.bytes()

    adapted = vision_adapter.adapt(
        raw, mime_type=case.mime, model=model, purpose=case.purpose, mode=case.mode, environ=environ
    )
    meta = adapted.meta()

    finest = None
    if case.strokes and adapted.data:
        survival = _metrics.stroke_survival(
            adapted.data, source_widths=case.strokes, scale=adapted.scale
        )
        finest = survival.finest

    # What a crop would recover. Measured separately from `adapt`, because `vision_adapter.crops`
    # does not consult the multi-image gate — the crops exist whether or not this model may be
    # sent several at once, and V6's ladder sends them one at a time regardless. This column is
    # the argument for that ladder, in the only unit that settles it.
    finest_tiled = None
    if case.strokes and adapted.data:
        for part in vision_adapter.crops(
            raw, mime_type=case.mime, purpose=case.purpose, mode=case.mode
        ):
            reading = _metrics.stroke_survival(
                part.data, source_widths=case.strokes, scale=part.scale
            )
            if reading.finest is not None and (finest_tiled is None or reading.finest < finest_tiled):
                finest_tiled = reading.finest

    result: Dict[str, Any] = {"ok": True, "analysis_text": "(not run)", "meta": {"model": model, "adapter": meta}}
    note = ""
    if analyze is not None:
        try:
            result = analyze(adapted=adapted, case=case, model=model)
        except Exception as exc:  # a harness that dies on one case reports nothing about the rest
            result = {"ok": False, "error_code": "rung_failed", "error": str(exc),
                      "analysis_text": "", "meta": {"model": model, "adapter": meta}}
            note = str(exc)[:80]
        result.setdefault("meta", {}).setdefault("adapter", meta)

    modes = _failures.classify(
        result,
        requested_model=model,
        finest_stroke=finest,
        strokes_offered=case.strokes if analyze is not None or case.strokes else (),
    )

    return Row(
        case=case.name,
        asks=case.asks,
        ok=bool(result.get("ok")) and not modes,
        strategy=meta.get("strategy", ""),
        profile=meta.get("profile", ""),
        source=f"{meta.get('original_width')}x{meta.get('original_height')}",
        output=f"{meta.get('width')}x{meta.get('height')}",
        scale=meta.get("scale", 1.0),
        parts=meta.get("tiles", 1),
        bytes_in=meta.get("original_bytes", 0),
        bytes_out=meta.get("bytes", 0),
        finest_stroke=finest,
        finest_stroke_tiled=finest_tiled,
        warnings=list(meta.get("warnings") or []),
        modes=modes,
        ms=int((time.monotonic() - started) * 1000),
        note=note,
    )


def run(
    *,
    model: Optional[str] = None,
    analyze: Optional[Callable[..., Any]] = None,
    only: Optional[List[str]] = None,
    environ=None,
) -> List[Row]:
    """The whole corpus, or the cases named in ``only``."""
    wanted = [case for case in cases() if not only or case.name in only]
    return [run_case(case, model=model, analyze=analyze, environ=environ) for case in wanted]


def table(rows: List[Row]) -> str:
    """The report, as something a person reads in a terminal."""
    head = (f"{'case':<20} {'strategy':<11} {'source':>11} {'output':>11} {'scale':>6} "
            f"{'whole':>6} {'crop':>5}  notes")
    lines = [head, "-" * len(head)]
    for row in rows:
        stroke = "-" if row.finest_stroke is None else f"{row.finest_stroke}px"
        tiled = "-" if row.finest_stroke_tiled is None else f"{row.finest_stroke_tiled}px"
        notes = ", ".join(row.modes + [w for w in row.warnings if not w.startswith("tiling-unavailable")])
        lines.append(
            f"{row.case:<20} {row.strategy:<11} {row.source:>11} {row.output:>11} "
            f"{row.scale:>6.3f} {stroke:>6} {tiled:>5}  {notes}"
        )
    return "\n".join(lines)


def summary(rows: List[Row]) -> Dict[str, Any]:
    """The numbers worth carrying forward, including the ones that tune the caps."""
    strokes = {row.case: row.finest_stroke for row in rows if row.finest_stroke is not None}
    observed: Dict[str, List[str]] = {row.case: row.modes for row in rows}
    gains = {
        row.case: row.finest_stroke - row.finest_stroke_tiled
        for row in rows
        if row.finest_stroke is not None and row.finest_stroke_tiled is not None
    }
    return {
        "cases": len(rows),
        "clean": sum(1 for row in rows if row.ok),
        "modes_seen": sorted({mode for row in rows for mode in row.modes}),
        "modes_never_alone": _failures.distinguishable(observed),
        "finest_stroke_by_case": strokes,
        "worst_stroke": max(strokes.values()) if strokes else None,
        # The measured case for tiling: source pixels of stroke fidelity a crop recovers.
        "crop_gain_by_case": {case: gain for case, gain in gains.items() if gain},
        "cases_a_crop_helps": sum(1 for gain in gains.values() if gain > 0),
    }

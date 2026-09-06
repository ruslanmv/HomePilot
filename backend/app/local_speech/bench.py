"""Benchmark before introducing another ASR family (batch LS8).

The rule this file exists to enforce, from the plan: **no default changes without data from this
repository.** Whisper ``large-v3-turbo`` through ``faster-whisper`` stays the default until
something beats it *here*.

That is not conservatism for its own sake. Every ASR family arrives with a benchmark showing it
winning, measured on a corpus its authors chose, with decoding parameters they chose and rarely
publish. A comparison that does not record beam size and thread counts is not a comparison — the
same model is two different products at beam 1 and beam 5, and one of those two is being quoted.

So a :class:`Run` carries its parameters, and :func:`compare` refuses to rank runs that were not
measured the same way.

## The metrics, and why each is here

| Metric | Why |
|---|---|
| WER | correctness |
| p50 / p95 utterance latency | live UX |
| Real-time factor | can it keep up |
| Cold model load | first-meeting UX |
| RAM / VRAM peak | stability |
| Timestamp error | citations and transcript navigation |
| Proper names, numbers | whether the transcript is useful |
| Silence hallucination | trust |
| Noisy / overlapping speech | real meetings |
| Long-session drift | reliability |

A family that wins on WER and hallucinates through silence is not better. A family that wins on
everything and cannot be given word timestamps breaks transcript navigation, which is most of
what MeetingSense is for.

## What has been measured here

Nothing yet. This repository has no licensed speech corpus and no GPU, so :data:`RESULTS` is
empty and stays empty until somebody runs this on hardware with audio they are allowed to use.
That is the same discipline that keeps the vision series' verified multi-image set empty: the
harness is the deliverable, and the numbers are a measurement somebody takes.

The candidates the plan names — whisper.cpp, Distil-large-v3 (English only, and it must never
become the silent default), Parakeet TDT 0.6B v3, Qwen3-ASR with or without its separate forced
aligner — are listed in :data:`CANDIDATES` so the shape of the comparison is fixed before anyone
is invested in a result.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

#: Every metric a run must carry to be comparable. A run missing one is not ranked.
METRICS = (
    "wer",
    "p50_latency_s",
    "p95_latency_s",
    "rtf",
    "cold_load_s",
    "peak_ram_mb",
    "peak_vram_mb",
    "timestamp_error_s",
    "proper_noun_error_rate",
    "number_error_rate",
    "silence_hallucination_rate",
    "noisy_wer",
    "drift_s_per_hour",
)

#: Lower is better for all of them, which is why the comparison can be written once.
LOWER_IS_BETTER = set(METRICS)

#: Decoding parameters that change the answer and must travel with it.
PARAMETERS = ("beam_size", "best_of", "temperature", "cpu_threads", "num_workers", "vad", "compute")


@dataclass
class Run:
    """One family, on one machine, with the settings it was measured at."""

    family: str
    model: str
    device: str
    corpus: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, float] = field(default_factory=dict)
    notes: str = ""

    @property
    def complete(self) -> bool:
        return all(metric in self.metrics for metric in METRICS)

    @property
    def documented(self) -> bool:
        """Whether the decoding parameters that change the answer were written down."""
        return all(name in self.parameters for name in PARAMETERS)

    def missing(self) -> Dict[str, List[str]]:
        return {
            "metrics": [metric for metric in METRICS if metric not in self.metrics],
            "parameters": [name for name in PARAMETERS if name not in self.parameters],
        }

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


#: The families to compare, once there is a corpus. English-only entries are flagged, because an
#: English-only model that becomes a silent default is a regression for everybody else and the
#: flag is what stops it happening by accident.
CANDIDATES: Tuple[Dict[str, Any], ...] = (
    {"family": "faster-whisper", "model": "large-v3-turbo", "english_only": False, "role": "incumbent"},
    {"family": "whisper.cpp", "model": "large-v3-turbo", "english_only": False, "role": "challenger"},
    {"family": "faster-whisper", "model": "distil-large-v3", "english_only": True, "role": "challenger"},
    {"family": "parakeet", "model": "tdt-0.6b-v3", "english_only": True, "role": "challenger"},
    {"family": "qwen3-asr", "model": "qwen3-asr", "english_only": False, "role": "challenger",
     "notes": "needs a separate forced aligner for word timestamps; measure both ways"},
)

#: Measured in this repository. Empty, and honestly so — see the module docstring.
RESULTS: Tuple[Run, ...] = ()

#: The current default, which nothing here may change without a complete, comparable run.
INCUMBENT = ("faster-whisper", "large-v3-turbo")


class NotComparable(ValueError):
    """Raised when a ranking was asked for over runs that cannot be ranked."""


def comparable(runs: List[Run]) -> Tuple[bool, str]:
    """Whether these runs can be ranked against each other, and why not when they cannot."""
    if len(runs) < 2:
        return False, "need at least two runs"
    incomplete = [run.family for run in runs if not run.complete]
    if incomplete:
        return False, f"incomplete metrics: {', '.join(sorted(set(incomplete)))}"
    undocumented = [run.family for run in runs if not run.documented]
    if undocumented:
        return False, f"undocumented parameters: {', '.join(sorted(set(undocumented)))}"
    corpora = {run.corpus for run in runs}
    if len(corpora) > 1:
        return False, f"different corpora: {', '.join(sorted(corpora))}"
    devices = {run.device for run in runs}
    if len(devices) > 1:
        return False, f"different devices: {', '.join(sorted(devices))}"
    return True, ""


def compare(runs: List[Run]) -> Dict[str, Any]:
    """Rank runs on every metric. Raises :class:`NotComparable` rather than guessing."""
    ok, why = comparable(runs)
    if not ok:
        raise NotComparable(why)
    table: Dict[str, List[Tuple[str, float]]] = {}
    for metric in METRICS:
        ordered = sorted(((f"{run.family}/{run.model}", run.metrics[metric]) for run in runs),
                         key=lambda pair: pair[1])
        table[metric] = ordered
    wins: Dict[str, int] = {}
    for ordered in table.values():
        wins[ordered[0][0]] = wins.get(ordered[0][0], 0) + 1
    return {"table": table, "wins": wins, "metrics": len(METRICS)}


def may_replace_default(challenger: Run, incumbent: Optional[Run] = None) -> Tuple[bool, str]:
    """Whether *challenger* has earned the default. The plan's rule, as a function.

    Three gates, and the third is the one that is easy to forget: a model that only handles
    English must never become the silent default, however well it scores, because the people it
    stops working for are exactly the people who will not be running the benchmark.
    """
    if incumbent is None:
        return False, "no incumbent run to beat — measure the current default first"
    ok, why = comparable([challenger, incumbent])
    if not ok:
        return False, why

    english_only = next(
        (entry.get("english_only") for entry in CANDIDATES
         if entry["family"] == challenger.family and entry["model"] == challenger.model),
        None,
    )
    if english_only:
        return False, "English-only models are opt-in, never the default"

    losses = [metric for metric in METRICS if challenger.metrics[metric] > incumbent.metrics[metric]]
    if losses:
        return False, f"loses on {', '.join(losses)}"
    return True, "beats the incumbent on every metric, on the same corpus and device"

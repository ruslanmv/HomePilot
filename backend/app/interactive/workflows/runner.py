"""
WorkflowRunner — the in-house orchestrator that chains small,
single-decision prompts into an end-to-end workflow (stage-1
autoplan, stage-2 autogen, etc.).

Why not LangChain / LangGraph / CrewAI?

* LangChain adds a ~40 MB dependency tree for what is, at its
  core, a `for step in steps: call_llm(step); validate; retry`
  loop. Its retry + output-parsing abstractions would still need
  a shim to talk to our Enterprise Settings resolver and our
  YAML prompt library.
* LangGraph's strength is cyclical graphs with conditional
  branching; our workflows are straight DAGs (mostly linear,
  occasionally a fan-out over scenes). The framework tax isn't
  justified for 7 nodes.
* CrewAI is multi-agent-role oriented; we have one role ("the
  planner") running seven specialised prompts, not seven agents
  collaborating. Using CrewAI would force us to pretend each
  prompt is an agent, which just obscures the data flow.

What this module does
---------------------

Given a list of ``Step``s and a starting context dict:

  1. For each step, build the prompt variables by calling
     ``step.build_vars(context)``.
  2. Render the prompt via ``PromptLibrary``.
  3. Dispatch via ``llm_router.call_prompt`` (Enterprise Settings
     chat model, policy-driven timeout).
  4. Parse the assistant content with ``step.parse``.
  5. Validate the parsed value with ``step.validate``.
  6. On parse/validate failure, retry up to ``policy.retries``.
  7. On final failure, consult ``policy.fallback``:
        'abort'    → raise StepFailure (workflow halts)
        other str  → let ``step.on_fallback`` interpret (returns
                     a safe default, or raises if step.build_vars
                     can't cope).
  8. Store the value under ``step.output_key`` in the context so
     later steps can read it.
  9. Emit events via ``on_event`` hook so the frontend spinner
     can display real progress (REV-5 wires this to SSE).

Events
------

The runner emits four event kinds:

    workflow_started     {workflow, step_ids, started_at_ms}
    step_started         {step_id, prompt_id, attempt=1}
    step_completed       {step_id, prompt_id, attempt, duration_ms,
                          preview}   # first 80 chars of output
    step_failed          {step_id, prompt_id, attempt, reason,
                          fatal}     # fatal=True only if abort
    workflow_completed   {workflow, duration_ms, ok}

``preview`` is a short string derived from ``str(value)[:80]`` so
operators can eyeball "did the LLM actually say something sensible?"
without exposing full content.

Design choices
--------------

* **Pure Python, no framework tax.** ~180 LoC, no extra deps.
* **Context is a plain dict.** Steps read/write it freely. No
  immutable-state ceremony; this module is intentionally small.
* **No global state.** The runner holds no caches. Same library,
  same context, same result — easy to test.
* **Parallel fan-out is deferred.** Today each Step runs
  sequentially (simplest, deterministic). REV-4 introduces a
  ``ParallelFanout`` wrapper when per-scene script generation
  needs it. Premature abstraction risk is not worth it now.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import (
    Any, Awaitable, Callable, Dict, List, Mapping,
    Optional, Sequence,
)

from ..llm_router import call_prompt
from ..prompts import (
    PromptLibrary,
    PromptLibraryError,
    PromptPolicy,
    RenderedPrompt,
    default_library,
)


log = logging.getLogger(__name__)


# ── Errors ─────────────────────────────────────────────────────

class StepFailure(Exception):
    """Raised when a step exhausts retries and its fallback is
    ``abort``. Carries enough context for the route layer to
    produce a useful error payload.
    """

    def __init__(
        self,
        *,
        step_id: str,
        prompt_id: str,
        reason: str,
        attempts: int,
    ) -> None:
        self.step_id = step_id
        self.prompt_id = prompt_id
        self.reason = reason
        self.attempts = attempts
        super().__init__(
            f"Step {step_id!r} ({prompt_id}) failed after {attempts} attempt(s): {reason}"
        )


# ── Data shapes ────────────────────────────────────────────────

@dataclass(frozen=True)
class WorkflowEvent:
    """Structured telemetry emitted per step transition.

    The frontend SSE stream serialises these to JSON; tests assert
    on the ``kind`` + payload keys. Payloads are plain dicts so
    we don't leak dataclass types across the wire.
    """

    kind: str                      # 'workflow_started' | 'step_started' | ...
    ts_ms: int                     # epoch-relative-ish, for ordering
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StepResult:
    """Outcome of one completed step. Stored on the WorkflowResult
    so tests can introspect the full trace.
    """

    step_id: str
    prompt_id: str
    value: Any
    attempts: int
    used_fallback: bool
    duration_ms: int


@dataclass
class WorkflowResult:
    """Final context + per-step trace for a completed run.

    ``aborted`` is True if a StepFailure halted the workflow — in
    that case ``steps`` contains every step that *did* run up to
    and including the failing one.
    """

    context: Dict[str, Any]
    steps: List[StepResult] = field(default_factory=list)
    events: List[WorkflowEvent] = field(default_factory=list)
    aborted: bool = False
    error: Optional[str] = None
    started_at_ms: int = 0
    duration_ms: int = 0


# ── Step definition ────────────────────────────────────────────

# Type aliases keep the Step signature readable.
VarBuilder = Callable[[Mapping[str, Any]], Mapping[str, Any]]
Parser = Callable[[str], Any]
Validator = Callable[[Any], Optional[str]]      # returns err msg or None
FallbackFn = Callable[[Mapping[str, Any], Optional[str]], Any]
                                                # (context, policy.fallback) -> value


@dataclass(frozen=True)
class Step:
    """One prompt in a workflow.

    Fields
    ------
    step_id
        Stable ID for logs/events (often equals the prompt id's
        trailing segment, e.g. ``classify_mode``).
    prompt_id
        Full library id (``autoplan.classify_mode``).
    output_key
        Where in ``context`` the validated value lands.
    build_vars
        ``context -> variables dict`` for the prompt renderer.
        Keep it pure — no I/O.
    parse
        ``raw content -> parsed value``. Raise ValueError on
        parse failure; the runner treats it like a validation
        miss and retries.
    validate
        ``value -> None | error message``. Returning a string
        triggers retry (and eventually fallback).
    fallback
        ``(context, fallback_token) -> default value``. Called
        only when retries are exhausted AND the policy fallback
        is NOT ``abort``. Raise StepFailure if no safe default
        is producible.
    temperature, max_tokens
        Per-step generation knobs. Short enums want temp=0.0;
        creative prose wants 0.5ish.
    """

    step_id: str
    prompt_id: str
    output_key: str
    build_vars: VarBuilder
    parse: Parser = field(default=lambda s: s.strip())
    validate: Validator = field(default=lambda v: None)
    fallback: Optional[FallbackFn] = None
    temperature: float = 0.3
    max_tokens: int = 350


# ── Event hook type ────────────────────────────────────────────

EventHook = Callable[[WorkflowEvent], None]


# ── Helper: content extractor ──────────────────────────────────

def extract_content(response: Any) -> str:
    """Pull the assistant content out of an OpenAI-style envelope.

    Returns empty string on any shape we don't recognise — the
    caller's validator then produces the "empty output" retry.
    """
    if not isinstance(response, dict):
        return ""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    msg = first.get("message") or {}
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
    return ""


# ── Runner ─────────────────────────────────────────────────────

class WorkflowRunner:
    """Sequentially run a list of ``Step``s against a shared
    context. Stateless across runs — instantiate once per
    process is fine.
    """

    def __init__(
        self,
        *,
        library: Optional[PromptLibrary] = None,
    ) -> None:
        self._library = library or default_library()

    async def run(
        self,
        *,
        workflow: str,
        steps: Sequence[Step],
        context: Optional[Dict[str, Any]] = None,
        on_event: Optional[EventHook] = None,
    ) -> WorkflowResult:
        """Execute ``steps`` in order. Returns a ``WorkflowResult``
        with the final context, per-step trace, and event log.

        A StepFailure is caught: the workflow is marked aborted
        and returned (instead of raised). Callers that want the
        exception style should check ``result.aborted`` and re-raise.
        """
        ctx: Dict[str, Any] = dict(context or {})
        events: List[WorkflowEvent] = []

        def _emit(ev: WorkflowEvent) -> None:
            events.append(ev)
            if on_event is not None:
                try:
                    on_event(ev)
                except Exception:  # noqa: BLE001
                    # Hooks must never break the workflow.
                    log.exception("workflow event hook raised — ignored")

        started = _now_ms()
        result = WorkflowResult(
            context=ctx, steps=[], events=events,
            started_at_ms=started,
        )

        _emit(WorkflowEvent(
            kind="workflow_started", ts_ms=_now_ms(),
            payload={
                "workflow": workflow,
                "step_ids": [s.step_id for s in steps],
                "started_at_ms": started,
            },
        ))

        try:
            for step in steps:
                step_result = await self._run_step(step, ctx, _emit)
                result.steps.append(step_result)
                ctx[step.output_key] = step_result.value
        except StepFailure as exc:
            result.aborted = True
            result.error = str(exc)
            log.warning("workflow_aborted workflow=%s reason=%s", workflow, exc)
        finally:
            result.duration_ms = max(0, _now_ms() - started)
            _emit(WorkflowEvent(
                kind="workflow_completed", ts_ms=_now_ms(),
                payload={
                    "workflow": workflow,
                    "duration_ms": result.duration_ms,
                    "ok": not result.aborted,
                },
            ))

        return result

    # ── Per-step execution ────────────────────────────────

    async def _run_step(
        self,
        step: Step,
        ctx: Mapping[str, Any],
        emit: Callable[[WorkflowEvent], None],
    ) -> StepResult:
        try:
            policy = self._library.policy(step.prompt_id)
        except PromptLibraryError as exc:
            emit(WorkflowEvent(
                kind="step_failed", ts_ms=_now_ms(),
                payload={
                    "step_id": step.step_id, "prompt_id": step.prompt_id,
                    "attempt": 1, "reason": f"prompt-load: {exc}", "fatal": True,
                },
            ))
            raise StepFailure(
                step_id=step.step_id, prompt_id=step.prompt_id,
                reason=f"prompt load failed: {exc}", attempts=1,
            ) from exc

        max_attempts = max(1, int(policy.retries) + 1)
        last_reason: str = ""
        step_started = _now_ms()

        for attempt in range(1, max_attempts + 1):
            emit(WorkflowEvent(
                kind="step_started", ts_ms=_now_ms(),
                payload={
                    "step_id": step.step_id, "prompt_id": step.prompt_id,
                    "attempt": attempt,
                },
            ))

            t0 = _now_ms()
            try:
                rendered = self._library.render(
                    step.prompt_id, **dict(step.build_vars(ctx)),
                )
            except PromptLibraryError as exc:
                last_reason = f"render: {exc}"
                emit(_fail_event(step, attempt, last_reason, fatal=False))
                break  # can't retry a deterministic render failure

            try:
                response = await call_prompt(
                    rendered, policy,
                    temperature=float(step.temperature),
                    max_tokens=int(step.max_tokens),
                )
            except asyncio.TimeoutError:
                last_reason = f"timeout after {policy.timeout_s:.1f}s"
                emit(_fail_event(step, attempt, last_reason, fatal=False))
                continue
            except Exception as exc:  # noqa: BLE001
                last_reason = f"llm: {exc.__class__.__name__}: {str(exc)[:180]}"
                emit(_fail_event(step, attempt, last_reason, fatal=False))
                continue

            content = extract_content(response)
            if not content:
                last_reason = "empty response"
                emit(_fail_event(step, attempt, last_reason, fatal=False))
                continue

            try:
                parsed = step.parse(content)
            except Exception as exc:  # noqa: BLE001
                last_reason = f"parse: {str(exc)[:180]}"
                emit(_fail_event(step, attempt, last_reason, fatal=False))
                continue

            verdict = step.validate(parsed)
            if verdict is not None:
                last_reason = f"validate: {verdict}"
                emit(_fail_event(step, attempt, last_reason, fatal=False))
                continue

            # Success.
            duration = max(0, _now_ms() - t0)
            emit(WorkflowEvent(
                kind="step_completed", ts_ms=_now_ms(),
                payload={
                    "step_id": step.step_id, "prompt_id": step.prompt_id,
                    "attempt": attempt, "duration_ms": duration,
                    "preview": _preview(parsed),
                },
            ))
            return StepResult(
                step_id=step.step_id, prompt_id=step.prompt_id,
                value=parsed, attempts=attempt,
                used_fallback=False,
                duration_ms=max(0, _now_ms() - step_started),
            )

        # All attempts exhausted. Consult fallback policy.
        fallback = (policy.fallback or "").strip().lower()
        if fallback == "abort" or not fallback:
            emit(_fail_event(step, max_attempts, last_reason, fatal=True))
            raise StepFailure(
                step_id=step.step_id, prompt_id=step.prompt_id,
                reason=last_reason or "unknown failure",
                attempts=max_attempts,
            )

        if step.fallback is None:
            # Policy said non-abort but the Step didn't wire a
            # fallback callable — treat as fatal so we don't
            # silently ship garbage.
            reason = f"{last_reason} (no Step.fallback configured for '{fallback}')"
            emit(_fail_event(step, max_attempts, reason, fatal=True))
            raise StepFailure(
                step_id=step.step_id, prompt_id=step.prompt_id,
                reason=reason, attempts=max_attempts,
            )

        try:
            value = step.fallback(ctx, policy.fallback)
        except StepFailure:
            raise
        except Exception as exc:  # noqa: BLE001
            reason = f"fallback raised: {exc}"
            emit(_fail_event(step, max_attempts, reason, fatal=True))
            raise StepFailure(
                step_id=step.step_id, prompt_id=step.prompt_id,
                reason=reason, attempts=max_attempts,
            ) from exc

        emit(WorkflowEvent(
            kind="step_completed", ts_ms=_now_ms(),
            payload={
                "step_id": step.step_id, "prompt_id": step.prompt_id,
                "attempt": max_attempts, "duration_ms": 0,
                "preview": _preview(value), "used_fallback": True,
            },
        ))
        return StepResult(
            step_id=step.step_id, prompt_id=step.prompt_id,
            value=value, attempts=max_attempts,
            used_fallback=True,
            duration_ms=max(0, _now_ms() - step_started),
        )


# ── Private helpers ────────────────────────────────────────────

def _now_ms() -> int:
    return int(time.time() * 1000)


def _preview(value: Any) -> str:
    try:
        s = str(value)
    except Exception:  # noqa: BLE001
        return ""
    s = s.replace("\n", " ").strip()
    return s if len(s) <= 80 else s[:77] + "…"


def _fail_event(
    step: Step, attempt: int, reason: str, *, fatal: bool,
) -> WorkflowEvent:
    return WorkflowEvent(
        kind="step_failed", ts_ms=_now_ms(),
        payload={
            "step_id": step.step_id, "prompt_id": step.prompt_id,
            "attempt": attempt, "reason": reason, "fatal": fatal,
        },
    )

"""
Tests for ``app.interactive.workflows.runner``.

Coverage:

* Happy-path: every step completes, context carries outputs.
* Validation failure retries up to ``policy.retries+1`` attempts.
* Timeout on the first attempt; success on retry.
* Fallback=abort raises StepFailure through the result.
* Non-abort fallback calls ``Step.fallback`` and marks used_fallback.
* Missing Step.fallback + non-abort policy is treated as fatal.
* Events are emitted in order with the right kinds + payload keys.
* Event-hook exceptions don't break the workflow.
"""
from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from app.interactive.prompts import PromptLibrary
from app.interactive.workflows import (
    Step,
    StepFailure,
    WorkflowEvent,
    WorkflowRunner,
    extract_content,
)


# ── Test library: a few disposable prompts on disk ───────────

def _mk_library(tmp_path: Path) -> PromptLibrary:
    index = tmp_path / "library.yaml"
    index.write_text(textwrap.dedent("""
        prompts:
          t.echo:     echo.yaml
          t.enum:     enum.yaml
          t.abort:    abort.yaml
          t.fb_ok:    fb_ok.yaml
          t.fb_noimp: fb_noimp.yaml
    """), encoding="utf-8")

    (tmp_path / "echo.yaml").write_text(textwrap.dedent("""
        id: t.echo
        version: "1.0.0"
        variables: [idea]
        system: "echo"
        user_template: "Idea: {idea}"
        policy: {retries: 0, timeout_s: 1.0}
        validation: {max_chars: 200}
        fallback: abort
    """), encoding="utf-8")

    (tmp_path / "enum.yaml").write_text(textwrap.dedent("""
        id: t.enum
        version: "1.0.0"
        variables: [idea]
        system: "enum"
        user_template: "{idea}"
        policy: {retries: 2, timeout_s: 1.0}
        validation:
          schema: enum
          allowed_values: [red, green, blue]
          max_chars: 32
        fallback: abort
    """), encoding="utf-8")

    (tmp_path / "abort.yaml").write_text(textwrap.dedent("""
        id: t.abort
        version: "1.0.0"
        variables: []
        system: "s"
        user_template: "u"
        policy: {retries: 0, timeout_s: 1.0}
        validation: {max_chars: 200}
        fallback: abort
    """), encoding="utf-8")

    (tmp_path / "fb_ok.yaml").write_text(textwrap.dedent("""
        id: t.fb_ok
        version: "1.0.0"
        variables: []
        system: "s"
        user_template: "u"
        policy: {retries: 0, timeout_s: 1.0}
        validation: {max_chars: 200}
        fallback: default_value
    """), encoding="utf-8")

    (tmp_path / "fb_noimp.yaml").write_text(textwrap.dedent("""
        id: t.fb_noimp
        version: "1.0.0"
        variables: []
        system: "s"
        user_template: "u"
        policy: {retries: 0, timeout_s: 1.0}
        validation: {max_chars: 200}
        fallback: default_value
    """), encoding="utf-8")

    return PromptLibrary(root=tmp_path)


# ── LLM stub: scripted responses per prompt_id ───────────────

class _ScriptedLLM:
    """Queue a list of responses / exceptions per prompt id.

    The runner calls ``llm_router.call_prompt`` — we patch that
    symbol at the module level so the runner sees the fake.
    """

    def __init__(self) -> None:
        self.queues: Dict[str, List[Any]] = {}
        self.calls: List[str] = []

    def feed(self, prompt_id: str, *responses: Any) -> None:
        self.queues.setdefault(prompt_id, []).extend(responses)

    async def __call__(self, prompt, policy, **_kw):
        self.calls.append(prompt.prompt_id)
        q = self.queues.get(prompt.prompt_id)
        if not q:
            raise AssertionError(f"No scripted response for {prompt.prompt_id}")
        nxt = q.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return {"choices": [{"message": {"content": str(nxt)}}]}


@pytest.fixture
def patch_call_prompt(monkeypatch):
    llm = _ScriptedLLM()
    monkeypatch.setattr(
        "app.interactive.workflows.runner.call_prompt", llm,
    )
    return llm


# ── Happy-path ────────────────────────────────────────────────

def test_happy_path_stores_outputs_in_context(tmp_path, patch_call_prompt):
    lib = _mk_library(tmp_path)
    patch_call_prompt.feed("t.echo", "planet ocean")
    patch_call_prompt.feed("t.enum", "green")

    steps = [
        Step(
            step_id="echo", prompt_id="t.echo", output_key="topic",
            build_vars=lambda c: {"idea": c["idea"]},
        ),
        Step(
            step_id="mode", prompt_id="t.enum", output_key="colour",
            build_vars=lambda c: {"idea": c["idea"]},
            validate=lambda v: None if v in {"red", "green", "blue"} else "bad",
        ),
    ]
    runner = WorkflowRunner(library=lib)
    result = asyncio.run(
        runner.run(workflow="demo", steps=steps, context={"idea": "ocean"}),
    )
    assert not result.aborted
    assert result.context["topic"] == "planet ocean"
    assert result.context["colour"] == "green"
    assert [s.step_id for s in result.steps] == ["echo", "mode"]
    assert all(s.attempts == 1 for s in result.steps)
    assert all(not s.used_fallback for s in result.steps)


# ── Retry + eventual success ─────────────────────────────────

def test_validation_miss_then_success(tmp_path, patch_call_prompt):
    lib = _mk_library(tmp_path)
    patch_call_prompt.feed("t.enum", "magenta", "invalid", "blue")

    step = Step(
        step_id="mode", prompt_id="t.enum", output_key="colour",
        build_vars=lambda _c: {"idea": "hello"},
        validate=lambda v: None if v in {"red", "green", "blue"} else "bad",
    )
    runner = WorkflowRunner(library=lib)
    result = asyncio.run(runner.run(workflow="demo", steps=[step]))
    assert not result.aborted
    assert result.context["colour"] == "blue"
    assert result.steps[0].attempts == 3


def test_timeout_then_success(tmp_path, patch_call_prompt):
    lib = _mk_library(tmp_path)
    patch_call_prompt.feed(
        "t.enum", asyncio.TimeoutError(), "red",
    )
    step = Step(
        step_id="mode", prompt_id="t.enum", output_key="colour",
        build_vars=lambda _c: {"idea": "hi"},
        validate=lambda v: None if v in {"red", "green", "blue"} else "bad",
    )
    runner = WorkflowRunner(library=lib)
    result = asyncio.run(runner.run(workflow="demo", steps=[step]))
    assert not result.aborted
    assert result.context["colour"] == "red"


# ── Abort path ───────────────────────────────────────────────

def test_exhausted_retries_abort_marks_aborted(tmp_path, patch_call_prompt):
    lib = _mk_library(tmp_path)
    patch_call_prompt.feed("t.enum", "bad", "still_bad", "nope")

    step = Step(
        step_id="mode", prompt_id="t.enum", output_key="colour",
        build_vars=lambda _c: {"idea": "x"},
        validate=lambda v: None if v in {"red", "green", "blue"} else "bad",
    )
    runner = WorkflowRunner(library=lib)
    result = asyncio.run(runner.run(workflow="demo", steps=[step]))
    assert result.aborted
    assert result.error and "mode" in result.error
    # The failing step is NOT appended — workflow halted before
    # we stored its (absent) value.
    assert result.steps == []


# ── Fallback path ────────────────────────────────────────────

def test_non_abort_fallback_is_called(tmp_path, patch_call_prompt):
    lib = _mk_library(tmp_path)
    patch_call_prompt.feed("t.fb_ok", "")  # empty triggers retry-then-fallback

    called = {"count": 0}

    def fallback(ctx, token):
        called["count"] += 1
        assert token == "default_value"
        return "fallback-value"

    step = Step(
        step_id="fb", prompt_id="t.fb_ok", output_key="value",
        build_vars=lambda _c: {},
        fallback=fallback,
    )
    runner = WorkflowRunner(library=lib)
    result = asyncio.run(runner.run(workflow="demo", steps=[step]))
    assert not result.aborted
    assert result.context["value"] == "fallback-value"
    assert result.steps[0].used_fallback is True
    assert called["count"] == 1


def test_non_abort_fallback_without_step_callable_aborts(
    tmp_path, patch_call_prompt,
):
    lib = _mk_library(tmp_path)
    patch_call_prompt.feed("t.fb_noimp", "")  # triggers fallback flow

    step = Step(
        step_id="fb", prompt_id="t.fb_noimp", output_key="value",
        build_vars=lambda _c: {},
        fallback=None,   # <- intentionally missing
    )
    runner = WorkflowRunner(library=lib)
    result = asyncio.run(runner.run(workflow="demo", steps=[step]))
    assert result.aborted
    assert "no Step.fallback" in (result.error or "")


# ── Events ────────────────────────────────────────────────────

def test_events_are_emitted_in_order(tmp_path, patch_call_prompt):
    lib = _mk_library(tmp_path)
    patch_call_prompt.feed("t.echo", "hi")
    patch_call_prompt.feed("t.enum", "red")

    got: List[WorkflowEvent] = []
    step1 = Step(step_id="echo", prompt_id="t.echo", output_key="topic",
                 build_vars=lambda c: {"idea": c["idea"]})
    step2 = Step(step_id="mode", prompt_id="t.enum", output_key="colour",
                 build_vars=lambda c: {"idea": c["idea"]},
                 validate=lambda v: None if v == "red" else "bad")
    runner = WorkflowRunner(library=lib)
    asyncio.run(runner.run(
        workflow="demo", steps=[step1, step2],
        context={"idea": "x"},
        on_event=got.append,
    ))

    kinds = [ev.kind for ev in got]
    assert kinds[0] == "workflow_started"
    assert kinds[-1] == "workflow_completed"
    assert kinds.count("step_started") == 2
    assert kinds.count("step_completed") == 2
    # workflow_completed carries ok=True
    assert got[-1].payload["ok"] is True


def test_event_hook_exceptions_do_not_break_the_workflow(
    tmp_path, patch_call_prompt,
):
    lib = _mk_library(tmp_path)
    patch_call_prompt.feed("t.echo", "hi")

    def boom(_ev):
        raise RuntimeError("hook broke")

    step = Step(step_id="echo", prompt_id="t.echo", output_key="topic",
                build_vars=lambda c: {"idea": "x"})
    runner = WorkflowRunner(library=lib)
    result = asyncio.run(runner.run(
        workflow="demo", steps=[step],
        context={"idea": "x"}, on_event=boom,
    ))
    assert not result.aborted
    assert result.context["topic"] == "hi"


def test_failed_events_carry_reason_and_attempt(tmp_path, patch_call_prompt):
    lib = _mk_library(tmp_path)
    patch_call_prompt.feed("t.enum", "nope", "red")
    step = Step(
        step_id="mode", prompt_id="t.enum", output_key="colour",
        build_vars=lambda _c: {"idea": "x"},
        validate=lambda v: None if v == "red" else "bad",
    )
    runner = WorkflowRunner(library=lib)
    got: List[WorkflowEvent] = []
    asyncio.run(runner.run(
        workflow="demo", steps=[step], on_event=got.append,
    ))
    fails = [ev for ev in got if ev.kind == "step_failed"]
    assert len(fails) == 1
    assert fails[0].payload["attempt"] == 1
    assert "validate" in fails[0].payload["reason"]
    assert fails[0].payload["fatal"] is False


# ── extract_content helper ────────────────────────────────────

def test_extract_content_happy_path():
    env = {"choices": [{"message": {"content": "  hello  "}}]}
    assert extract_content(env) == "hello"


def test_extract_content_tolerates_garbage():
    assert extract_content({}) == ""
    assert extract_content({"choices": []}) == ""
    assert extract_content({"choices": [None]}) == ""
    assert extract_content({"choices": [{"message": None}]}) == ""
    assert extract_content("not a dict") == ""

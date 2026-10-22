"""Deep research — a bounded deep-agent run: plan, delegate, gather with tools, write.

The harness primitives behind ChatGPT's and Claude's "deep research" modes, kept small and
local-first, with no extra dependency:

* a **plan** the model writes first (a few sub-questions), shown to the user as it runs;
* one **sub-agent per plan item**, each with a clean context and the per-turn tool loop
  (web search, page fetch, workspace and notes, the project's documents), reporting findings
  with [n] citations;
* a shared **source book** that renumbers every sub-agent's citations into one list;
* a **writer** pass that turns findings and sources into a cited report, streamed;
* a **time budget** and per-item call budget that end the run gracefully;
* a **durable job**: every event is numbered and written to the state store with the job's
  snapshot, so a client can reconnect after a refresh (``?after=<seq>``) and a finished
  report survives a restart. A job interrupted by a restart is marked so, never left running.

Gate: ``capability.py`` — offered only when the connection has a high-end model.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .config import (
    EXPERT_DEEP_JOB_TTL_S,
    EXPERT_DEEP_MAX_ITEMS,
    EXPERT_DEEP_ROUNDS_PER_ITEM,
    EXPERT_DEEP_TEMPERATURE,
    EXPERT_DEEP_TIME_BUDGET_S,
    EXPERT_MAX_TOKENS,
    EXPERT_SYSTEM_PROMPT,
)
from .policies import is_trivial
from .providers import mark_background
from .router import dispatch, step_messages, stream_provider_events
from .tool_loop import SourceBook, ThinkFilter, capability_key, stream_with_tools, tools_known
from . import compaction
from . import grounding
from . import state_store
from . import target as target_mod

logger = logging.getLogger("expert.deep")

PLANNER_SYSTEM = (
    "You are the lead researcher. Break the user's request into the few sub-questions whose "
    "answers, together, settle it. Each must be self-contained and searchable. Return JSON only: "
    '{{"questions": ["...", "..."]}} with 2 to {max_items} items.'
)
RESEARCHER_SYSTEM = (
    "You are a research sub-agent. Answer the sub-question with facts found with your tools: "
    "search, read the best pages, and report findings with the [n] numbers of the results you "
    "relied on. Be concrete — names, numbers, dates. Say when sources disagree or when nothing "
    "reliable was found. Keep it under 300 words."
)
WRITER_SYSTEM = (
    "You are the writer. From the findings and the numbered sources, write the report the user "
    "asked for: a short answer first, then sections with headings, specific facts, and [n] "
    "citations right after the sentences they support. Note gaps and disagreements plainly. "
    "Never invent a source or a number."
)

FINAL_STATES = ("done", "failed", "cancelled")


def _with_operator(system: str, operator_prompt: Optional[str]) -> str:
    """A role prompt plus the operator's context (a project's instructions) when given."""
    if operator_prompt and operator_prompt.strip():
        return f"{system}\n\nContext from the operator:\n{operator_prompt.strip()}"
    return system


@dataclass
class PlanItem:
    id: str
    title: str
    status: str = "pending"          # pending | running | done | skipped
    finding: str = ""
    sources: List[int] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "title": self.title, "status": self.status, "sources": list(self.sources),
                "summary": self.finding[:300]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PlanItem":
        return cls(id=str(d.get("id") or ""), title=str(d.get("title") or ""), status=str(d.get("status") or "pending"),
                   finding=str(d.get("summary") or d.get("finding") or ""), sources=list(d.get("sources") or []))


@dataclass
class DeepJob:
    id: str
    query: str
    provider: str
    model: Optional[str]
    session_id: Optional[str] = None
    status: str = "queued"           # queued | planning | researching | writing | done | failed | cancelled
    plan: List[PlanItem] = field(default_factory=list)
    report: str = ""
    sources: List[Dict[str, Any]] = field(default_factory=list)
    notices: List[str] = field(default_factory=list)
    error: str = ""
    created: float = field(default_factory=time.time)
    finished: Optional[float] = None
    seq: int = 0
    events: List[Dict[str, Any]] = field(default_factory=list)
    subscribers: List["asyncio.Queue[Dict[str, Any]]"] = field(default_factory=list)
    task: Optional["asyncio.Task[None]"] = None

    # ── events: numbered, fanned out, written down ──────────────────────────
    def emit(self, event: Dict[str, Any]) -> None:
        self.seq += 1
        event = {**event, "seq": self.seq}
        self.events.append(event)
        state_store.event_append(self.id, self.seq, event)
        if event["type"] != "token":
            self.persist()
        for q in list(self.subscribers):
            q.put_nowait(event)

    def subscribe(self, after: int = 0) -> "asyncio.Queue[Dict[str, Any]]":
        q: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        for e in self.events:
            if int(e.get("seq", 0)) > after:
                q.put_nowait(e)
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: "asyncio.Queue[Dict[str, Any]]") -> None:
        if q in self.subscribers:
            self.subscribers.remove(q)

    @property
    def finished_state(self) -> bool:
        return self.status in FINAL_STATES

    def cancel(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()

    def snapshot(self) -> Dict[str, Any]:
        end = self.finished or time.time()
        return {
            "job_id": self.id, "status": self.status, "query": self.query, "model": self.model,
            "provider": self.provider, "session_id": self.session_id,
            "plan": [p.as_dict() for p in self.plan], "report": self.report, "sources": self.sources,
            "notices": list(self.notices), "error": self.error, "elapsed_s": round(end - self.created, 1),
            "seq": self.seq, "created": self.created, "finished": self.finished,
        }

    def persist(self) -> None:
        state_store.job_save(self.id, self.status, self.snapshot(), created=self.created)

    @classmethod
    def from_snapshot(cls, snap: Dict[str, Any], events: List[Dict[str, Any]]) -> "DeepJob":
        job = cls(
            id=str(snap.get("job_id") or ""), query=str(snap.get("query") or ""),
            provider=str(snap.get("provider") or "local"), model=snap.get("model"), session_id=snap.get("session_id"),
            status=str(snap.get("status") or "failed"),
            plan=[PlanItem.from_dict(p) for p in snap.get("plan") or []],
            report=str(snap.get("report") or ""), sources=list(snap.get("sources") or []),
            notices=list(snap.get("notices") or []), error=str(snap.get("error") or ""),
            created=float(snap.get("created") or time.time()), finished=snap.get("finished"),
        )
        job.events = list(events)
        job.seq = max([int(e.get("seq", 0)) for e in events] + [int(snap.get("seq") or 0)])
        return job


JOBS: Dict[str, DeepJob] = {}
_RECOVERED = False


def recover_interrupted() -> int:
    """Jobs the store says were running when the process last stopped: there is no task
    behind them any more, so they are closed as failed, with the reason on record."""
    global _RECOVERED
    if _RECOVERED:
        return 0
    _RECOVERED = True
    count = 0
    for job_id in state_store.jobs_unfinished():
        row = state_store.job_load(job_id)
        if not row:
            continue
        job = DeepJob.from_snapshot(row["snapshot"], state_store.events_after(job_id, 0))
        job.status = "failed"
        job.error = "Interrupted: HomePilot restarted while this research was running."
        job.finished = time.time()
        job.seq += 1
        event = {"type": "error", "error": job.error, "seq": job.seq}
        job.events.append(event)
        state_store.event_append(job.id, job.seq, event)
        job.persist()
        count += 1
    if count:
        logger.info("deep research: closed %d job(s) interrupted by a restart", count)
    return count


def get_job(job_id: str) -> Optional[DeepJob]:
    """A live job, or a finished one read back from the store."""
    recover_interrupted()
    job = JOBS.get(job_id)
    if job is not None:
        return job
    row = state_store.job_load(job_id)
    if not row:
        return None
    job = DeepJob.from_snapshot(row["snapshot"], state_store.events_after(job_id, 0))
    JOBS[job_id] = job
    return job


def _prune() -> None:
    now = time.time()
    for key, job in list(JOBS.items()):
        if job.finished and now - job.finished > EXPERT_DEEP_JOB_TTL_S:
            JOBS.pop(key, None)
    state_store.jobs_prune(EXPERT_DEEP_JOB_TTL_S * 24)


def parse_plan(text: str, query: str, max_items: int) -> List[str]:
    """The planner's sub-questions: JSON when it obeyed, a bullet or numbered list when it did
    not, the request itself when nothing usable came back."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    questions: List[str] = []
    m = re.search(r"\{.*\}", text, flags=re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            qs = data.get("questions") if isinstance(data, dict) else None
            if isinstance(qs, list):
                questions = [str(q).strip() for q in qs if str(q).strip()]
        except json.JSONDecodeError:
            pass
    if not questions:
        for line in text.splitlines():
            if re.match(r"^\s*(?:[-*•]|\d+[.)])\s+\S", line):
                questions.append(re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip().strip('"'))
    questions = [q for q in questions if len(q) > 3][:max_items]
    return questions or [query]


def _short(exc: Exception) -> str:
    """One line of an error for a notice."""
    return " ".join(str(exc).split())[:160] or type(exc).__name__


def _findings_report(plan: List["PlanItem"], sources: List[Dict[str, Any]]) -> str:
    """The report when the writer cannot run: each researched question with its finding, and
    the numbered sources the findings cite."""
    blocks = [f"### {p.title}\n\n{p.finding.strip()}" for p in plan if p.finding and p.finding.strip()]
    out = "\n\n".join(blocks)
    if sources:
        out += "\n\n**Sources**\n\n" + "\n".join(f"[{s['n']}] {s.get('title') or s['url']} — {s['url']}" for s in sources)
    return out


def renumber(text: str, mapping: Dict[int, int]) -> str:
    """A sub-agent's local [n] citations rewritten to the job-wide numbers."""
    return re.sub(r"\[(\d+)\]", lambda m: f"[{mapping.get(int(m.group(1)), int(m.group(1)))}]", text or "")


def start(
    query: str,
    *,
    provider: str,
    model: Optional[str],
    history: List[Dict[str, Any]],
    chosen: Optional[target_mod.ChatTarget],
    timezone: Optional[str],
    context: Optional[str],
    note: Optional[str],
    notices: Optional[List[str]] = None,
    registry: Any = None,
    operator_prompt: Optional[str] = None,
    session_id: Optional[str] = None,
) -> DeepJob:
    """Create the job and run it in the background; the caller returns its id at once."""
    recover_interrupted()
    _prune()
    job = DeepJob(id=uuid.uuid4().hex[:12], query=query, provider=provider, model=model, session_id=session_id)
    job.notices.extend(notices or [])
    JOBS[job.id] = job
    job.persist()

    async def runner() -> None:
        with target_mod.using(chosen), grounding.using(timezone, context), compaction.using(note):
            await _run(job, list(history or []), registry=registry, operator_prompt=operator_prompt)

    job.task = asyncio.create_task(runner())
    return job


async def _run(job: DeepJob, history: List[Dict[str, Any]], *, registry: Any = None,
               operator_prompt: Optional[str] = None) -> None:
    started = time.monotonic()
    budget = EXPERT_DEEP_TIME_BUDGET_S
    kw = dict(model=job.model, temperature=EXPERT_DEEP_TEMPERATURE, max_tokens=EXPERT_MAX_TOKENS)
    book = SourceBook()
    # A research job is background work: on a busy endpoint, a person's chat goes first.
    mark_background()
    try:
        if is_trivial(job.query):
            # A greeting needs no plan, no searches and no report: one reply, and the reason.
            # (It also spares a shared endpoint the five to eight calls a research job makes.)
            job.status = "writing"
            job.emit({"type": "status", "status": "writing"})
            job.notices.append("A short message needs no research; it was answered directly.")
            parts: List[str] = []
            thinking = ThinkFilter()
            async for ev in stream_provider_events(
                step_messages(job.query, system_prompt=_with_operator(EXPERT_SYSTEM_PROMPT, operator_prompt), history=history),
                job.provider, model=job.model, temperature=EXPERT_DEEP_TEMPERATURE, max_tokens=512,
            ):
                if "delta" in ev:
                    clean = thinking.feed(ev["delta"])
                    if clean:
                        parts.append(clean)
                        job.emit({"type": "token", "content": clean})
            tail = thinking.flush()
            if tail:
                parts.append(tail)
                job.emit({"type": "token", "content": tail})
            job.report = "".join(parts)
            job.status = "done"
            job.finished = time.time()
            job.emit({
                "type": "done", "report": job.report, "sources": [], "notices": list(job.notices),
                "plan": [], "elapsed_s": round(time.monotonic() - started, 1),
            })
            return

        # 1. Plan
        job.status = "planning"
        job.emit({"type": "status", "status": "planning"})
        try:
            raw = await dispatch(
                step_messages(
                    f"Request:\n{job.query}\n\nReturn the JSON plan.",
                    system_prompt=_with_operator(PLANNER_SYSTEM.format(max_items=EXPERT_DEEP_MAX_ITEMS), operator_prompt),
                    history=history,
                ),
                job.provider, model=job.model, temperature=0.2, max_tokens=600,
            )
            plan_text = raw["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            plan_text = ""
        except Exception as exc:  # noqa: BLE001 - no plan is not no research
            logger.warning("Deep research %s: planner failed, researching the request as one question: %s", job.id, exc)
            job.notices.append(f"The planner could not run ({_short(exc)}); the request was researched as one question.")
            plan_text = ""
        job.plan = [PlanItem(id=f"q{i + 1}", title=q) for i, q in enumerate(parse_plan(plan_text, job.query, EXPERT_DEEP_MAX_ITEMS))]
        job.emit({"type": "plan", "items": [p.as_dict() for p in job.plan]})

        # 2. Research, one sub-agent per item, within the time budget. Every item starts with a
        #    web search run by HomePilot (the question as the query), so the findings are
        #    grounded whether or not the model can call tools itself; a capable model may search
        #    further on its own.
        job.status = "researching"
        job.emit({"type": "status", "status": "researching"})
        if tools_known(capability_key(target_mod.current(), job.provider, job.model)) is False:
            job.notices.append("This model cannot call tools; HomePilot ran the web searches for it.")
        out_of_time = False
        for item in job.plan:
            if time.monotonic() - started > budget:
                if not out_of_time:
                    out_of_time = True
                    job.notices.append(f"Time budget of {budget:g}s reached; the remaining items were skipped.")
                item.status = "skipped"
                job.emit({"type": "item", "id": item.id, "status": "skipped", "title": item.title})
                continue
            item.status = "running"
            job.emit({"type": "item", "id": item.id, "status": "running", "title": item.title})
            messages = step_messages(
                f"Overall request: {job.query}\n\nSub-question: {item.title}",
                system_prompt=_with_operator(RESEARCHER_SYSTEM, operator_prompt), history=history,
            )
            finding, local_sources = "", []
            try:
                async for ev in stream_with_tools(messages, job.provider, max_rounds=EXPERT_DEEP_ROUNDS_PER_ITEM,
                                                  registry=registry, forced=[("hp_web_search", {"query": item.title})], **kw):
                    if ev["type"] in ("tool_start", "tool_end", "wait"):
                        job.emit({**ev, "item": item.id})
                    elif ev["type"] == "notice":
                        if ev["text"] not in job.notices:
                            job.notices.append(ev["text"])
                        job.emit({**ev, "item": item.id})
                    elif ev["type"] == "done":
                        finding, local_sources = ev.get("content") or "", ev.get("sources") or []
            except Exception as exc:  # noqa: BLE001 - one question down is not the report down
                logger.warning("Deep research %s: item %s failed: %s", job.id, item.id, exc)
                item.status = "failed"
                item.finding = ""
                note = f"“{item.title}” could not be researched ({_short(exc)})."
                if note not in job.notices:
                    job.notices.append(note)
                job.emit({"type": "item", "id": item.id, "status": "failed", "title": item.title,
                          "summary": f"Could not be researched: {_short(exc)}"})
                continue
            mapping: Dict[int, int] = {}
            for s in local_sources:
                book.add([s])
                numbered = book.numbered([s])
                if numbered:
                    mapping[int(s.get("n", 0))] = numbered[0]["n"]
            item.finding = renumber(finding, mapping)
            item.sources = sorted(set(mapping.values()))
            item.status = "done"
            job.sources = list(book.items)
            job.emit({"type": "item", "id": item.id, "status": "done", "title": item.title,
                      "summary": item.finding[:300], "sources": item.sources})
            if book.items:
                job.emit({"type": "sources", "sources": list(book.items)})

        # 3. Write
        job.status = "writing"
        job.emit({"type": "status", "status": "writing"})
        findings = "\n\n".join(
            f"## {p.title}\n{p.finding or ('(could not be researched)' if p.status == 'failed' else '(not researched: out of time)')}"
            for p in job.plan
        )
        source_lines = "\n".join(
            f"[{s['n']}] {s.get('title') or s['url']} — {s['url']}" for s in book.items
        ) or "(no sources were found; say so and answer from general knowledge, marked as such)"
        writer_messages = step_messages(
            f"Request:\n{job.query}\n\nFindings:\n{findings}\n\nSources:\n{source_lines}\n\nWrite the report.",
            system_prompt=_with_operator(WRITER_SYSTEM, operator_prompt), history=history,
        )
        parts: List[str] = []
        thinking = ThinkFilter()
        try:
            async for ev in stream_provider_events(
                writer_messages, job.provider, model=job.model, temperature=EXPERT_DEEP_TEMPERATURE,
                max_tokens=max(EXPERT_MAX_TOKENS, 3000),
            ):
                if "delta" in ev:
                    clean = thinking.feed(ev["delta"])
                    if clean:
                        parts.append(clean)
                        job.emit({"type": "token", "content": clean})
                elif ev.get("notice") and ev["notice"] not in job.notices:
                    job.notices.append(ev["notice"])
        except Exception as exc:  # noqa: BLE001 - the findings are the report's substance
            researched = [p for p in job.plan if p.finding]
            if not researched and not parts:
                raise
            logger.warning("Deep research %s: writer failed, returning the findings: %s", job.id, exc)
            job.notices.append(f"The writer could not finish ({_short(exc)}); the findings are shown as gathered.")
            fallback = _findings_report(job.plan, book.items)
            text = ("\n\n---\n\n" if parts else "") + fallback
            parts.append(text)
            job.emit({"type": "token", "content": text})
        tail = thinking.flush()
        if tail:
            parts.append(tail)
            job.emit({"type": "token", "content": tail})
        job.report = "".join(parts)
        job.status = "done"
        job.finished = time.time()
        job.emit({
            "type": "done", "report": job.report, "sources": job.sources, "notices": list(job.notices),
            "plan": [p.as_dict() for p in job.plan], "elapsed_s": round(time.monotonic() - started, 1),
        })
    except asyncio.CancelledError:
        job.status = "cancelled"
        job.finished = time.time()
        job.emit({"type": "cancelled"})
    except Exception as exc:  # noqa: BLE001
        logger.error("Deep research %s failed: %s", job.id, exc, exc_info=True)
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished = time.time()
        job.emit({"type": "error", "error": job.error})

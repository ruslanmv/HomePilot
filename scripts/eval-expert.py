#!/usr/bin/env python3
"""Evaluate the Expert chat path against a running HomePilot, with the real models.

Ten scenarios from the roadmap's test table, run on demand (never in CI: they need a model):

  hello_fast          a greeting in Fast is short, with no tools and no stages
  followup_context    "the second option" resolves against the previous turns
  coding_expert       Expert returns code for a coding task
  tools_capability    a forced web search either runs or is reported as unavailable
  web_sources_cited   the answer carries numbered sources and cites one
  heavy_validation    Heavy gets a checkable calculation right and reports a verdict
  deep_resume         a Deep research job can be left and resumed without duplicates
  cancellation        a stream can be stopped early and the first event arrives quickly
  offline_mode        skipped until Privacy Lock exists
  compaction          an early fact survives a long history through the summary note

Usage (the backend venv has httpx):
  backend/.venv/bin/python scripts/eval-expert.py --backend http://127.0.0.1:8002
  backend/.venv/bin/python scripts/eval-expert.py --provider openai_compat \
      --base-url http://localhost:11435/v1 --model openwebui/internal-gemma4-31b --api-key-env OLLABRIDGE_API_KEY
  --only hello_fast,compaction   --json report.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterator, List, Optional

import httpx

UNESCAPE = re.compile(r"\\n")


@dataclass
class Result:
    id: str
    name: str
    passed: Optional[bool]          # None = skipped
    detail: str = ""
    latency_s: float = 0.0
    first_event_s: Optional[float] = None
    tools: int = 0
    sources: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)


class Eval:
    def __init__(self, args: argparse.Namespace) -> None:
        self.backend = args.backend.rstrip("/")
        self.timeout = args.timeout
        self.target: Dict[str, Any] = {"provider": args.provider}
        if args.base_url:
            self.target["base_url"] = args.base_url
        if args.model:
            self.target["model"] = args.model
        key = os.getenv(args.api_key_env, "") if args.api_key_env else ""
        if key:
            self.target["api_key"] = key
        self.headers = {"Content-Type": "application/json"}
        api_key = os.getenv("HOMEPILOT_API_KEY", "")
        if api_key:
            self.headers["x-api-key"] = api_key

    # ── transport ────────────────────────────────────────────────────────────

    def body(self, query: str, mode: str, **extra: Any) -> Dict[str, Any]:
        b: Dict[str, Any] = {
            "query": query, "thinking_mode": mode, "provider": "auto", "target": self.target,
            "feature_hints": {"budgetTier": "normal"}, "session_id": f"eval-{int(time.time())}-{mode}",
        }
        b.update(extra)
        return b

    def sse(self, method: str, path: str, body: Optional[Dict[str, Any]] = None, stop_after: Optional[str] = None,
            abort_after_s: Optional[float] = None) -> Iterator[Dict[str, Any]]:
        """Yield parsed events; ``stop_after`` closes the connection after that event type.
        ``abort_after_s`` closes it after that many seconds whether or not a line has arrived
        (a reader that stops is not waiting for the model's next token)."""
        started = time.monotonic()
        read_timeout = abort_after_s if abort_after_s is not None else self.timeout
        with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=10, read=read_timeout)) as client:
            try:
                yield from self._sse_lines(client, method, path, body, stop_after, abort_after_s, started)
            except httpx.ReadTimeout:
                if abort_after_s is None:
                    raise

    def _sse_lines(self, client: httpx.Client, method: str, path: str, body: Optional[Dict[str, Any]], stop_after: Optional[str],
                   abort_after_s: Optional[float], started: float) -> Iterator[Dict[str, Any]]:
            with client.stream(method, f"{self.backend}{path}", json=body, headers={**self.headers, "Accept": "text/event-stream"}) as r:
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.read().decode('utf-8', 'replace')[:300]}")
                name, seq, data = "", None, []
                for line in r.iter_lines():
                    if abort_after_s is not None and time.monotonic() - started > abort_after_s:
                        return
                    if line == "":
                        if data:
                            ev = self._event(name, seq, "\n".join(data))
                            if ev is not None:
                                yield ev
                                if stop_after and ev["type"] == stop_after:
                                    return
                        name, seq, data = "", None, []
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        name = line[6:].strip()
                    elif line.startswith("id:"):
                        seq = int(line[3:].strip() or 0)
                    elif line.startswith("data:"):
                        data.append(line[5:].lstrip(" "))

    @staticmethod
    def _event(name: str, seq: Optional[int], payload: str) -> Optional[Dict[str, Any]]:
        if not name:
            if payload == "[DONE]":
                return {"type": "end"}
            return {"type": "token", "text": UNESCAPE.sub("\n", payload), "seq": seq}
        if name == "final_answer":
            return {"type": "final_answer"}
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            return None
        obj = obj if isinstance(obj, dict) else {"value": obj}
        obj["type"] = name
        if seq is not None:
            obj["seq"] = seq
        return obj

    def run_stream(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """One /v1/expert/stream call → {content, meta, done, steps, tools, sources, verdict, first_event_s, latency_s}."""
        out: Dict[str, Any] = {"content": "", "steps": [], "tools": [], "sources": [], "notices": [], "verdict": None,
                               "meta": {}, "done": {}, "first_event_s": None}
        started = time.monotonic()
        answer, answering = [], body.get("thinking_mode") == "fast"
        for ev in self.sse("POST", "/v1/expert/stream", body):
            if out["first_event_s"] is None:
                out["first_event_s"] = round(time.monotonic() - started, 2)
            t = ev["type"]
            if t == "meta":
                out["meta"] = ev
                answering = answering or (ev.get("effort") or {}).get("level") == "direct"
            elif t == "step":
                out["steps"].append(ev.get("step"))
                answering = False
            elif t == "tool" and ev.get("phase") == "end":
                out["tools"].append(ev)
            elif t == "sources":
                out["sources"] = ev.get("sources", [])
            elif t == "notice":
                out["notices"].append(ev.get("text"))
            elif t == "verdict":
                out["verdict"] = ev
            elif t == "reset":
                answer = []
            elif t == "final_answer":
                answer, answering = [], True
            elif t == "token" and answering:
                answer.append(ev["text"])
            elif t == "done":
                out["done"] = ev
                if ev.get("content"):
                    answer = [ev["content"]]
            elif t == "error":
                raise RuntimeError(ev.get("error", "stream error"))
        out["content"] = "".join(answer)
        out["latency_s"] = round(time.monotonic() - started, 2)
        return out

    # ── scenarios ────────────────────────────────────────────────────────────

    def hello_fast(self) -> Result:
        r = self.run_stream(self.body("hello", "fast"))
        short = 0 < len(r["content"]) < 400
        ok = short and not r["tools"] and not r["steps"]
        return Result("hello_fast", "Greeting in Fast is short, no tools, no stages", ok,
                      f"{len(r['content'])} chars, {len(r['tools'])} tools, {len(r['steps'])} stages", r["latency_s"], r["first_event_s"])

    def followup_context(self) -> Result:
        history = [
            {"role": "user", "content": "Give me two options for a database in a small laptop app."},
            {"role": "assistant", "content": "1. SQLite: zero setup, one file. 2. PostgreSQL: a server, real concurrency."},
        ]
        r = self.run_stream(self.body("What does the second option need to run?", "fast", history=history))
        ok = "postgres" in r["content"].lower()
        return Result("followup_context", "The second option resolves against earlier turns", ok,
                      r["content"][:120].replace("\n", " "), r["latency_s"], r["first_event_s"])

    def coding_expert(self) -> Result:
        r = self.run_stream(self.body(
            "Write a Python function that returns the n-th Fibonacci number iteratively, with a short docstring and one example call.", "think"))
        ok = "```" in r["content"] and "def " in r["content"]
        return Result("coding_expert", "Expert returns code for a coding task", ok,
                      f"stages={r['steps']} effort={(r['meta'].get('effort') or {}).get('level')}", r["latency_s"], r["first_event_s"])

    def tools_and_sources(self) -> List[Result]:
        r = self.run_stream(self.body("What is HomePilot by ruslanmv? One sentence.", "fast",
                                      feature_hints={"budgetTier": "normal", "webSearch": "force"}))
        ran = bool(r["tools"])
        unavailable = any("not available" in (n or "") for n in r["notices"])
        caps = self.capabilities(probe=True)
        verified = (caps.get("verified") or {}).get("tools", "unprobed")
        a = Result("tools_capability", "A forced web search runs or is reported unavailable", ran or unavailable,
                   f"tool ran={ran}, unavailable notice={unavailable}, probe tools={verified}", r["latency_s"], r["first_event_s"],
                   tools=len(r["tools"]), sources=len(r["sources"]), extra={"verified": caps.get("verified")})
        cited = bool(r["sources"]) and bool(re.search(r"\[\d+\]", r["content"]))
        b = Result("web_sources_cited", "The answer carries numbered sources and cites one",
                   cited if ran else None, f"{len(r['sources'])} sources, cited={cited}" if ran else "skipped: web search did not run",
                   r["latency_s"], r["first_event_s"], tools=len(r["tools"]), sources=len(r["sources"]))
        return [a, b]

    def heavy_validation(self) -> Result:
        r = self.run_stream(self.body("Compute 17 × 24. Give the final number and one sentence of explanation.", "heavy"))
        verdict = (r["verdict"] or {}).get("verdict") or (r["done"].get("verdict"))
        ok = "408" in r["content"] and verdict in ("validated", "corrected", "needs_review", "reviewed")
        return Result("heavy_validation", "Heavy gets a checkable calculation right and reports a verdict", ok,
                      f"verdict={verdict} stages={r['steps']} effort={(r['meta'].get('effort') or {}).get('level')}",
                      r["latency_s"], r["first_event_s"])

    def deep_resume(self) -> Result:
        started = time.monotonic()
        with httpx.Client(timeout=30) as client:
            resp = client.post(f"{self.backend}/v1/expert/deep", json=self.body("What is HomePilot by ruslanmv and what can it do?", "heavy"), headers=self.headers)
        if resp.status_code == 403:
            return Result("deep_resume", "Deep research job survives a disconnect", None, f"skipped: {resp.json().get('detail', '')[:120]}")
        if resp.status_code >= 400:
            return Result("deep_resume", "Deep research job survives a disconnect", False, f"HTTP {resp.status_code}")
        job_id = resp.json()["job_id"]
        seen: List[int] = []
        try:
            for ev in self.sse("GET", f"/v1/expert/deep/{job_id}/events", stop_after="plan"):
                if "seq" in ev:
                    seen.append(ev["seq"])
            last = max(seen) if seen else 0
            after: List[int] = []
            final = None
            for ev in self.sse("GET", f"/v1/expert/deep/{job_id}/events?after={last}"):
                if "seq" in ev:
                    after.append(ev["seq"])
                if ev["type"] in ("done", "error", "cancelled"):
                    final = ev["type"]
                    break
            ok = final == "done" and (not after or min(after) > last) and len(set(after)) == len(after)
            return Result("deep_resume", "Deep research job survives a disconnect", ok,
                          f"job={job_id} final={final} replayed_from={last} new_events={len(after)}", round(time.monotonic() - started, 1))
        finally:
            with httpx.Client(timeout=10) as client:
                client.delete(f"{self.backend}/v1/expert/deep/{job_id}", headers=self.headers)

    def cancellation(self) -> Result:
        started = time.monotonic()
        first = None
        try:
            for ev in self.sse("POST", "/v1/expert/stream", self.body("Explain in detail how TCP congestion control works.", "heavy"), abort_after_s=3.0):
                if first is None:
                    first = round(time.monotonic() - started, 2)
        except Exception as exc:  # noqa: BLE001
            return Result("cancellation", "A stream stops early and the first event is prompt", False, f"{type(exc).__name__}: {exc}")
        elapsed = time.monotonic() - started
        ok = first is not None and first < 15 and elapsed < 10
        return Result("cancellation", "A stream stops early and the first event is prompt", ok,
                      f"first event {first}s, closed after {elapsed:.1f}s", round(elapsed, 1), first)

    def offline_mode(self) -> Result:
        return Result("offline_mode", "No external requests in offline mode", None, "skipped: Privacy Lock is not implemented yet")

    def compaction(self) -> Result:
        history = [{"role": "user", "content": "Remember this: my cat is named Pixel."},
                   {"role": "assistant", "content": "Noted: your cat is named Pixel."}]
        for i in range(14):
            history.append({"role": "user", "content": f"Filler question number {i}: what is {i} plus {i}? Please answer in a full sentence with some padding text."})
            history.append({"role": "assistant", "content": f"{i} plus {i} is {2 * i}. " + ("Padding sentence. " * 8)})
        r = self.run_stream(self.body("What is my cat's name?", "fast", history=history))
        compacted = bool(r["meta"].get("compacted"))
        ok = compacted and "pixel" in r["content"].lower()
        return Result("compaction", "An early fact survives a long history through the summary", ok,
                      f"compacted={compacted} answer={r['content'][:80].replace(chr(10), ' ')}", r["latency_s"], r["first_event_s"])

    def capabilities(self, probe: bool = False) -> Dict[str, Any]:
        with httpx.Client(timeout=120) as client:
            r = client.post(f"{self.backend}/v1/expert/capabilities", json={"target": self.target, "model": self.target.get("model"), "probe": probe}, headers=self.headers)
        return r.json() if r.status_code == 200 else {"error": r.status_code}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--backend", default="http://127.0.0.1:8002")
    p.add_argument("--provider", default="ollama")
    p.add_argument("--base-url", default="")
    p.add_argument("--model", default="")
    p.add_argument("--api-key-env", default="")
    p.add_argument("--only", default="")
    p.add_argument("--json", default="")
    p.add_argument("--timeout", type=float, default=300.0)
    args = p.parse_args()
    ev = Eval(args)

    order = ["hello_fast", "followup_context", "coding_expert", "tools_and_sources", "heavy_validation",
             "deep_resume", "cancellation", "offline_mode", "compaction"]
    wanted = {s.strip() for s in args.only.split(",") if s.strip()}
    caps = ev.capabilities()
    print(f"backend {ev.backend} · target {ev.target.get('provider')} {ev.target.get('model') or '(default)'} · "
          f"tier {caps.get('tier')} · deep research {'on' if (caps.get('deep_research') or {}).get('enabled') else 'off'}")
    results: List[Result] = []
    for name in order:
        if wanted and name not in wanted and not (name == "tools_and_sources" and wanted & {"tools_capability", "web_sources_cited"}):
            continue
        try:
            out = getattr(ev, name)()
        except Exception as exc:  # noqa: BLE001
            out = Result(name, name, False, f"{type(exc).__name__}: {exc}"[:200])
        for r in (out if isinstance(out, list) else [out]):
            results.append(r)
            mark = "PASS" if r.passed else ("skip" if r.passed is None else "FAIL")
            print(f"{mark:5} {r.id:18} {r.latency_s:6.1f}s  first {str(r.first_event_s) + 's' if r.first_event_s is not None else '-':>7}  {r.detail}")
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if r.passed is False)
    skipped = sum(1 for r in results if r.passed is None)
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"target": {k: v for k, v in ev.target.items() if k != "api_key"}, "capabilities": caps,
                       "results": [asdict(r) for r in results]}, fh, indent=2)
        print(f"report: {args.json}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

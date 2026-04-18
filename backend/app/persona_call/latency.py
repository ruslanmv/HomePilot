"""
Pre-emptive filler scheduler — "hmm, one sec…" within the 700 ms
Stivers trouble threshold.

Because the MVP chat path is *non-streaming* (the compat endpoint
returns 501 on stream=true), the only way to cover long LLM latency
is to emit a server-originated filler BEFORE the real reply arrives.

Usage (from ws.py inside a turn)::

    async with FillerScheduler(ws=..., facets=facets, cfg=cfg,
                               session_id=sid) as sched:
        reply = await turn.run_turn(...)
    # If the turn took longer than cfg.filler_emit_after_ms, the
    # scheduler already emitted one 'assistant.filler' event to the
    # client. Either way, the real reply follows.

Per the design doc: filler tokens are persona-specific with a
sensible universal fallback (covered by ``VoiceFacets.thinking_tokens``,
whose default pool is ["hmm", "let me think", "one sec", "hold on"]).
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Callable, Dict, List, Optional

from .config import PersonaCallConfig
from .facets import VoiceFacets


def _now_ms() -> int:
    return int(time.time() * 1000)


class FillerScheduler:
    """Async context-manager that emits at most ONE filler event per
    turn, ``filler_emit_after_ms`` after entering the context. Cancel
    on exit — if the LLM returned faster, no event is sent.

    The event is emitted via the ``send`` callable injected at
    construction, not by calling ``ws.send_text`` directly, so this
    module stays free of fastapi imports and is trivially unit-testable.
    """

    def __init__(
        self,
        *,
        send: Callable[[Dict[str, Any]], "asyncio.Future"],
        facets: VoiceFacets,
        cfg: PersonaCallConfig,
        session_id: str,
        recent_thinking: Optional[List[str]] = None,
    ) -> None:
        self._send = send
        self._facets = facets
        self._cfg = cfg
        self._sid = session_id
        self._recent = list(recent_thinking or [])
        self._task: Optional[asyncio.Task] = None
        self.emitted: bool = False
        self.emitted_token: Optional[str] = None

    def _pick_token(self) -> Optional[str]:
        pool = [t for t in self._facets.thinking_tokens if t]
        if not pool:
            return None
        last = (self._recent[-1].lower() if self._recent else "")
        candidates = [t for t in pool if t.lower() != last] or pool
        return random.choice(candidates)

    async def _fire(self) -> None:
        delay_ms = max(0, int(self._cfg.filler_emit_after_ms))
        try:
            await asyncio.sleep(delay_ms / 1000.0)
        except asyncio.CancelledError:
            return
        token = self._pick_token()
        if not token:
            return
        try:
            await self._send({
                "type": "assistant.filler",
                "payload": {
                    "token": token,
                    "ts": _now_ms(),
                    "session_id": self._sid,
                },
            })
            self.emitted = True
            self.emitted_token = token
        except Exception:
            # Best-effort — never let a filler failure break the turn.
            pass

    async def __aenter__(self) -> "FillerScheduler":
        self._task = asyncio.create_task(self._fire())
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass

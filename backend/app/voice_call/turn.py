"""
Turn bridge — send a ``transcript.final`` from the client to the
existing ``/v1/chat/completions`` endpoint and get back an assistant
reply (also final, no deltas).

Implementation note
-------------------
The review confirmed the compat endpoint currently returns 501 on
``stream=true`` (openai_compat_endpoint.py:477), so MVP M1 is final-
only. We invoke the endpoint via an internal loopback HTTP call; that
buys:

  * zero import-time coupling to the chat module,
  * the same auth / memory / persona context the normal chat path uses,
  * a natural seam for the V2 realtime-provider adapter (swap this
    function, everything else stays).

When the feature flag is off this module is never imported.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx


def _local_backend_url() -> str:
    """Where to reach our own FastAPI server over loopback. Honors an
    override for containerized / split-process deployments."""
    return (
        os.getenv("VOICE_CALL_INTERNAL_BACKEND_URL")
        or os.getenv("HOMEPILOT_INTERNAL_BACKEND_URL")
        or "http://127.0.0.1:8000"
    ).rstrip("/")


DEFAULT_TIMEOUT_SEC = float(os.getenv("VOICE_CALL_TURN_TIMEOUT_SEC", "30"))


async def run_turn(
    *,
    user_text: str,
    model: str,
    auth_bearer: Optional[str] = None,
    system_prompt: Optional[str] = None,
    additional_system: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> str:
    """Run a single assistant turn via the existing chat endpoint.

    Parameters
    ----------
    user_text:
        The final STT transcript from the client.
    model:
        The model id. ``persona:<project_id>`` / ``personality:<id>`` /
        plain ollama model name — whatever the existing chat endpoint
        accepts.
    auth_bearer:
        The caller's bearer token, forwarded verbatim so the chat
        endpoint sees the same user identity as the WS session owner.
    system_prompt / history:
        Optional pre-built context. Left empty the endpoint will attach
        its own persona / memory context based on the model.
    additional_system:
        Optional extra system message appended AFTER ``system_prompt``
        (or on its own if no ``system_prompt`` is provided). Additive
        only — used by ``persona_call`` to inject a per-turn phone-call
        suffix WITHOUT touching the persona's own system prompt that
        the compat endpoint already injects for ``persona:*`` models.

    Returns
    -------
    The assistant's reply text (the ``choices[0].message.content`` from
    the chat completion response). Raises on non-2xx responses so the
    caller can surface an ``error`` event over the WS.
    """
    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if additional_system:
        messages.append({"role": "system", "content": additional_system})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if auth_bearer:
        headers["Authorization"] = f"Bearer {auth_bearer}"
    if extra_headers:
        headers.update(extra_headers)

    payload = {
        "model": model,
        "messages": messages,
        # Final-only — must stay False at MVP. The compat endpoint
        # returns 501 on streaming requests.
        "stream": False,
        # Keep response tight for voice. Long prose makes for bad audio.
        "max_tokens": int(os.getenv("VOICE_CALL_TURN_MAX_TOKENS", "300")),
        "temperature": float(os.getenv("VOICE_CALL_TURN_TEMPERATURE", "0.7")),
    }

    url = f"{_local_backend_url()}/v1/chat/completions"
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SEC) as client:
        r = await client.post(url, json=payload, headers=headers)
    # Let the caller see the HTTP body on error — useful for debugging.
    if r.status_code >= 400:
        raise RuntimeError(
            f"chat endpoint {url} returned {r.status_code}: {r.text[:400]}"
        )
    data = r.json()
    try:
        return (
            data["choices"][0]["message"]["content"]
            if data.get("choices")
            else ""
        )
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(
            "chat endpoint returned an unexpected body shape: "
            + str(data)[:400]
        )

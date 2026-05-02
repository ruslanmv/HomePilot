# Live-play playback subsystem

The live-play surface (`POST /v1/interactive/play/sessions/{sid}/chat`
+ `GET /pending`) runs the real-time scene-generation loop: chat
arrives, the planner composes a scene, a render job goes to the
video backend, and the clip streams back to the `InteractivePlayer`
in the frontend.

## Module map

| File | Responsibility |
|---|---|
| `scene_memory.py` | Rolling context snapshot (persona, mood, last N turns, synopsis). Pure, synchronous. |
| `scene_planner.py` | `plan_next_scene` (sync heuristic) + `plan_next_scene_async` (LLM first, heuristic fallback). |
| `llm_composer.py` | LLM-backed composer — `app.llm.chat_ollama` with strict JSON mode. |
| `video_job.py` | `ix_scene_queue` CRUD + `render_now` (sync stub) + `render_now_async` (real-first, stub fallback). |
| `render_adapter.py` | Thin async wrapper over `app.comfy.run_workflow` + `app.asset_registry.register_asset`. |
| `asset_urls.py` | `resolve_asset_url` — registry lookup for the frontend `<video src>`. |
| `schema.py` | Defensive `CREATE IF NOT EXISTS` for `ix_scene_queue`. |
| `playback_config.py` | Env-flag + tuning-knob loader. |

## Enabling Phase-2 in production

All flags default **off** so upgrading is a no-op until you opt in.

```bash
# LLM scene composer — uses the configured Ollama / OpenAI-compatible backend
export INTERACTIVE_PLAYBACK_LLM=1
export INTERACTIVE_PLAYBACK_LLM_TIMEOUT_S=12        # optional, default 12
export INTERACTIVE_PLAYBACK_LLM_MAX_TOKENS=350      # optional, default 350
export INTERACTIVE_PLAYBACK_LLM_TEMPERATURE=0.65    # optional, default 0.65

# Video renderer — submits scene prompts to ComfyUI via run_workflow
export INTERACTIVE_PLAYBACK_RENDER=1
export INTERACTIVE_PLAYBACK_RENDER_WORKFLOW=animate   # optional, default 'animate'
export INTERACTIVE_PLAYBACK_RENDER_TIMEOUT_S=180      # optional, default 180

# Ollama + Comfy endpoints use the app-level config (unchanged)
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_MODEL=llama3.1:8b-instruct
export COMFY_BASE_URL=http://localhost:8188
```

Flip one or both flags per deployment — for example staging can
run the LLM composer with a stub renderer while the real video
backend warms up.

## Failure modes (graceful by design)

| Failure | Behaviour |
|---|---|
| `INTERACTIVE_PLAYBACK_LLM=1` but the LLM is unreachable / slow / malformed JSON | Falls back to the heuristic composer. No user-visible error. Structured log lines: `playback_llm_timeout`, `playback_llm_error`, `playback_llm_malformed_json`. |
| `INTERACTIVE_PLAYBACK_RENDER=1` but ComfyUI is down / times out / no output | Falls back to the phase-1 stub asset id. Job still lands `ready`. Logs: `playback_render_timeout`, `playback_render_error`, `playback_render_no_output`. |
| `asset_registry.get_asset` throws | `resolve_asset_url` returns `None`; frontend shows the mood backdrop. |
| Policy gate (`check_free_input`) blocks the message | `/chat` returns `{"status": "blocked", …}` without invoking the planner or render pipeline. |

Each fallback keeps the player's polling loop in a terminal
state, so the UI never hangs on a half-resolved turn.

## Observability

All structured logs share an `extra={"session_id": …}` field for
correlation. Grep-friendly event names:

- `playback_llm_timeout` / `playback_llm_error` / `playback_llm_malformed_json` / `playback_llm_empty_content` / `playback_llm_missing_fields`
- `playback_render_timeout` / `playback_render_error` / `playback_render_no_output`
- `playback_asset_register_failed`
- `playback_asset_lookup_failed`

Job-id stamps in `ix_scene_queue.job_id` carry a prefix so you
can separate the two render paths at a glance:

- `stub-*` — phase-1 fallback path used this request
- `live-*` — phase-2 real render was attempted

## Test coverage

The subsystem ships with 60+ tests across 7 files:

```
tests/test_interactive_playback_memory.py        rolling context + synopsis
tests/test_interactive_playback_planner.py       heuristic composer
tests/test_interactive_playback_planner_async.py LLM-first dispatch
tests/test_interactive_playback_llm_composer.py  LLM parsing + guardrails
tests/test_interactive_playback_jobs.py          scene queue + state machine
tests/test_interactive_playback_jobs_async.py    render_now_async fallback
tests/test_interactive_playback_render_adapter.py ComfyUI adapter contract
tests/test_interactive_playback_chat.py          /chat route end-to-end
tests/test_interactive_playback_asset_urls.py    URL resolver
tests/test_interactive_playback_config.py        env flag loader
```

Every test monkey-patches the real external call (chat_ollama,
run_workflow, register_asset) so CI never reaches for a network.

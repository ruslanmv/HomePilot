# Image generation performance — feasibility study and plan

**Branch:** `claude/image-perf-plan`, cut from `claude/elegant-einstein-uhqda0` at `86320f7`.
**Status:** investigation complete. **Phases 1–4 implemented** on `claude/image-perf-phase1-4`;
phases 5–10 still to do.

> ### Implemented — measured result
>
> Preflight cost on the generation path, ComfyUI unreachable, batch of four:
>
> | | before | after |
> |---|---|---|
> | image 1 | ~30 s | 0.003 ms |
> | image 2 | ~30 s | 0.001 ms |
> | image 3 | ~30 s | 0.000 ms |
> | image 4 | ~30 s | 0.001 ms |
> | **batch total** | **~120 s** | **0.005 ms** |
>
> The one remaining network call is a 2 s startup warmup on a background thread, off the
> request path, negative-cached on failure.
>
> Still outstanding and unchanged by this work: **Finding B**. Prompt refinement is now
> *measured* (`[IMAGE PERF] prompt_refinement_ms`) but not yet bounded, so read that number
> before quoting any end-to-end target.

Every claim below was checked against this branch. Where the brief's diagnosis was right it says
so and cites the line; where the code is *worse* than described, or where something material was
missing from the brief, it is called out as a numbered finding.

---

## 1. Verdict

**Feasible, and the dominant cost is almost certainly a bug rather than an architecture problem.**

The single highest-value change is roughly forty lines in one file
(`backend/app/comfy_utils/object_info_cache.py`) plus one call-site change in `comfy.py`. Phases
5–9 of the brief are real improvements worth doing, but they are tens of milliseconds against a
defect that costs tens of *seconds*. The ordering below reflects that.

One caveat the brief does not account for, and which caps what any amount of Comfy-transport work
can achieve — see **Finding B**.

---

## 2. What was verified

### 2.1 Confirmed as described

| Brief | Where | Status |
|---|---|---|
| P1 `/object_info` 30 s timeout | `object_info_cache.py:64` — `httpx.Timeout(30.0, connect=10.0)` | ✅ confirmed |
| P2 preflight on the hot path | `comfy.py:1069` — `validate_workflow_nodes()` before `/prompt` | ✅ confirmed |
| P3 timing logs hide setup | `comfy.py:1097` — `started` is set *after* `_post_prompt` | ✅ confirmed |
| P4 client per workflow | `comfy.py:1093` — `with httpx.Client(...)` | ✅ confirmed |
| P5 polling | `comfy.py:1128`, `COMFY_POLL_INTERVAL_S` default `1.0` (`config.py:189`) | ✅ confirmed |
| P6 batch = N workflows + `sleep(0.5)` | `orchestrator.py:1700-1723` | ✅ confirmed |
| P7 client per image in persistence | `files.py:292`, inside `for url in image_urls` | ✅ confirmed |
| P10 Imagine sends no conversation id | `Imagine.tsx:806-841` — no `conversation_id` key | ✅ confirmed |
| Model/VRAM rules | searched `comfy.py`, `orchestrator.py` for free/unload/restart/interrupt | ✅ **nothing to fix** — no such calls on the generation path. Only doc strings saying "restart ComfyUI". ComfyUI already owns model lifecycle. |

### 2.2 Finding A — there is no negative caching at all, not merely incorrect caching

The brief says the failure "is also not negative-cached correctly". It is worse: on failure
`_refresh()` returns **before** touching `_expires_at`, which stays `0.0` forever
(`object_info_cache.py:68-70`). `_nodes` also stays `None`. Both cache-validity conditions
therefore fail on every subsequent call, so **every image pays the full timeout again**.

Measured on this branch against a non-routable host:

```
call 1:  10.23s  nodes=0  expires_at=0.0
call 2:  10.06s  nodes=0  expires_at=0.0
call 3:  10.06s  nodes=0  expires_at=0.0
```

(10 s here is the *connect* timeout. A ComfyUI that accepts the TCP connection but is slow to
answer — see Finding C — pays the 30 s **read** timeout instead.)

This is not a cold-start cost. It is a per-image cost, permanently, until ComfyUI answers
`/object_info` promptly once.

### 2.3 Finding B — LLM prompt refinement is on the same hot path, unbounded, and defaults on

Not in the brief, and it caps the achievable target.

`orchestrator.py:801` — `prompt_refinement: Optional[bool] = True`; `Imagine.tsx:833` sends
`promptRefinement: props.promptRefinement ?? true`. So **every** Imagine generation makes a
blocking `await _refine_prompt(...)` LLM call (`orchestrator.py:1424` onward) before ComfyUI is
touched at all. There is no timeout on it in the image path.

On a machine whose chat model is large, cold, or sharing the GPU with ComfyUI, this is seconds to
tens of seconds, and it is invisible in the current logs. The brief's Phase 1 does list
`prompt_refinement_ms`, which is the right instinct — but the brief's target of

> Warm POST /chat total: approximately 2.5–4 seconds

is **not reachable while an unbounded LLM round-trip is in front of ComfyUI**, no matter how good
the Comfy transport becomes. Phase 1 must measure this before anyone commits to that number. See
§5 for the proposed handling.

### 2.4 Finding C — `/object_info` is slowest exactly when we need it

ComfyUI serves `/object_info` from the same Python process that runs the workflow. While a
diffusion job is executing, that endpoint is contended and can take seconds. So the preflight is
slowest precisely during generation — which is the only time HomePilot calls it. With Finding A
this compounds: a batch of four pays it four times, each time against a busier server.

### 2.5 Finding D — the batch path multiplies the defect, not just the orchestration

`imgBatchSize=4` currently performs 4 × (`/object_info` + workflow load + graph build + client
construct + `/prompt` + poll loop) plus 3 × `sleep(0.5)`. With Finding A that is 4 × up to 30 s of
pure preflight stall. Fixing Finding A alone converts this from catastrophic to merely wasteful.

### 2.6 Finding E — the existing tests constrain phases 2 and 5

`tests/test_comfy_node_preflight.py` (77 tests) patches `app.comfy_utils.object_info_cache.httpx.Client`
directly (line 290). A shared/injected client in Phase 5 must not break that seam.

Separately, `test_returns_empty_when_comfyui_unreachable` (line 274) constructs a cache against
`http://unreachable:9999` with the current 30 s timeout. It passes today only because DNS fails
fast; on a resolver that blackholes instead, that single test can burn 30 s of CI. Phase 2 fixes
this incidentally.

### 2.7 Finding F — native batching changes seed semantics, and the honest answer is not `[S, S+1, S+2, S+3]`

ComfyUI derives per-batch-index noise from one seed via a single sequential generator
(`comfy.sample.prepare_noise`). Image *i* of a batch of four at seed `S` is therefore **not** the
same image as a single generation at seed `S+i`.

Today HomePilot reports a distinct seed per image (`orchestrator.py:1714`, `seeds_used`) and the
frontend renders per-image seeds (`Imagine.tsx:919`, `seed: seeds[index] ?? seeds[0]`). If we
native-batch and keep populating `seeds` with four values, those values become a fabrication:
re-running any of them reproduces nothing.

This must be decided deliberately, not incidentally — options in §4, Phase 7.

### 2.8 Finding G — the `/comfy/view/` persistence branch already loses metadata

`files.py:279-281` takes `os.path.basename(url.split("?")[0])` and hardcodes `type=output`,
discarding `subfolder`. Any output written to a subfolder is fetched from the wrong path. This is
a latent correctness bug today and directly blocks the Phase 8 direct-copy work, which needs
`(filename, subfolder, type)`.

### 2.9 Finding H — direct local copy is feasible; the metadata is already in the URL

`comfy.py:788` — `_view_url()` emits
`{base}/view?filename=…&subfolder=…&type=…`, and `_extract_media` (line 814) populates all three
from ComfyUI's history. So the information Phase 8 needs survives into `persist_chat_images()` and
can be recovered with `urllib.parse` — no signature change required for the common path. Only the
`/comfy/view/` branch (Finding G) needs repair.

`COMFY_OUTPUT_DIR` does **not** exist in `config.py` today. `COMFY_INPUT_DIR` does
(`comfy.py:264`), and its resolution helper `_get_comfyui_input_dir()` is the pattern to mirror.

### 2.10 Finding I — native batching is feasible across all five txt2img workflows

Inspected `comfyui/workflows/*.json` (26 files):

| Workflow | Latent node | Current value |
|---|---|---|
| `txt2img.json` | `EmptyLatentImage` (id 5) | `batch_size: 1` |
| `txt2img-sd15-uncensored.json` | `EmptyLatentImage` (id 5) | `batch_size: 1` |
| `txt2img-pony-xl.json` | `EmptyLatentImage` (id 5) | `batch_size: 1` |
| `txt2img-flux-dev.json` | `EmptyLatentImage` (id 5) | `batch_size: 1` |
| `txt2img-flux-schnell.json` | `EmptyLatentImage` (id 5) | `batch_size: 1` |

All five terminate in `SaveImage`, which emits one entry per batch item, so `_extract_media`
already returns N URLs without modification.

Two enabling facts:

- `_deep_replace` (`comfy.py:512-533`) returns the raw value when the *entire* string is one
  placeholder, so `"batch_size": "{{batch_size}}"` yields an `int`, not `"4"`. No coercion needed.
- `orchestrator.py:1654` already does `refined.setdefault("batch_size", 1)` on one path, so the
  variable name is established.

11 of 26 workflow files mention `batch_size`; the remaining 15 (video, edit, upscale, faceswap…)
must stay on the sequential path.

---

## 3. Where the ~44 s goes — reconciliation

Nothing here is speculative arithmetic; each row is a measured or code-confirmed cost.

| Phase | Cost | Evidence |
|---|---|---|
| LLM prompt refinement | unmeasured, unbounded | Finding B |
| `/object_info` preflight | up to 30 s, **every image** | Finding A (measured), Finding C |
| ComfyUI execution | ~2 s warm | user's report |
| History poll granularity | 0–1 s | `COMFY_POLL_INTERVAL_S=1.0` |
| Persistence | localhost HTTP round-trip per image | Finding G/H |

The 30 s preflight plus an unmeasured LLM call comfortably accounts for the 44–46 s gap. The brief
is right that this is **not** diffusion inference and **not** a VRAM/checkpoint problem.

---

## 4. Plan

Each phase lands green and independently revertable. Phase ordering is by measured value, which
differs slightly from the brief: **Phase 2 is the fix**, and it should land in the same day as
Phase 1.

### Phase 1 — instrumentation (prerequisite, no behaviour change) ✅ done

`time.perf_counter()` throughout; never `time.time()` for durations.

- `run_workflow()`: `image_preprocess_ms`, `workflow_load_ms`, `lora_prepare_ms`,
  `template_replace_ms`, `node_preflight_ms`, `graph_validation_ms`, `prompt_post_ms`,
  `queue_and_execution_ms`, `history_fetch_ms`, `media_extract_ms`, `total_workflow_ms`.
- image path in `orchestrator.py`: `prompt_refinement_ms`, `preset_selection_ms`,
  `comfy_generation_ms`, `media_persistence_ms`, `message_storage_ms`, `total_image_request_ms`.
- Emit as single-line `[COMFY PERF]` / `[IMAGE PERF]` records. Response schemas unchanged.

**Exit criterion:** one real generation produces a breakdown summing to the observed `/chat`
elapsed. Do not proceed on assumption — Finding B in particular must be quantified here.

Tests assert the keys exist and the return schema is unchanged; never a duration value.

### Phase 2 — the actual fix: bound the timeout and negative-cache failures ✅ done

`object_info_cache.py`, per the brief's signature:

```python
def __init__(self, base_url, ttl_seconds=300.0, *,
             request_timeout_seconds=5.0, failure_ttl_seconds=30.0)
```

- `timeout = max(0.1, request_timeout_seconds)`; `httpx.Timeout(timeout, connect=min(2.0, timeout))`.
- **On failure:** keep valid stale data if present; otherwise store an empty result **and set
  `_expires_at = now + failure_ttl_seconds`.** That assignment is the whole of Finding A.
- Switch expiry to `time.monotonic()`.
- Record `last_status`, `last_duration_ms`, `last_error_type`, `hit`/`negative_hit` counters.
  Log a failure once per failure-TTL window, not once per image.
- Fix the docstring, which says 60 s while the default is 300 s.

**Expected effect on its own:** worst case falls from *30 s every image* to *5 s once per 30 s*.

### Phase 3 — single-flight refresh ✅ done

`threading.Lock` + double-check. Regression test: N concurrent callers against an expired cache
produce exactly one HTTP refresh.

### Phase 4 — take `/object_info` off the warm path ✅ done

`validate_workflow_nodes(workflow_name, prompt_graph, *, allow_network=False)`; `run_workflow`
passes `allow_network=False`. Cache-miss must **not** block or reject — `/prompt` is the
authoritative validator and already returns actionable errors.

Lifecycle: refresh once at backend startup (fire-and-forget, never blocking readiness), serve
stale-while-revalidate thereafter. Endpoints that explicitly ask for current node/model
information keep `force=True`. No scheduler.

**After Phases 2–4 the warm path performs zero `/object_info` network I/O.**

### Phase 5 — persistent transport

One `httpx.Client` with an explicit connection pool and one stable `client_id` per backend
process; closed on shutdown; thread-safe. Preserve `COMFY_BASE_URL` semantics for local and
Docker. Do **not** randomise `client_id` to defeat Comfy caching — node caching is beneficial and
random seeds already make sampling distinct.

Constraint from Finding E: keep the `httpx.Client` patch seam the existing 77 tests rely on.

### Phase 6 — WebSocket completion, polling retained

Only after 1–5 are benchmarked. Correlate by `prompt_id`; one `GET /history/{id}` on completion;
handle reconnect, execution errors, shutdown; honour `COMFY_POLL_MAX_S`; fall back to polling on
any WS failure. Isolate behind a small service abstraction rather than making `run_workflow`
async — the async conversion would touch far more than this problem justifies.

Expected saving: ~0.5 s average. Genuinely the lowest-value phase; schedule it last despite its
position in the brief.

### Phase 7 — real batching

1. Delete `time.sleep(0.5)` (`orchestrator.py:1723`) unconditionally. Free.
2. Template `"batch_size": "{{batch_size}}"` in the five workflows of Finding I.
3. Capability map (explicit allow-list keyed by workflow name, plus a structural check that an
   `EmptyLatentImage`-like node carries `batch_size`). Anything not on the list keeps the
   sequential path — with the sleep gone, preflight once, and the shared client.
4. Eligible path: one `run_workflow` call, `workflow_vars["batch_size"] = batch_size`.

**Seeds (Finding F) — the decision to make explicitly.** Recommendation: native-batch only when
the seed is *unpinned* (the common Imagine case, `img_seed in (None, 0, -1)`), and report
`seed = S` with `seeds = [S] * n` plus a `batch_index` per image. When the user has pinned a seed
and asked for n > 1, keep the sequential path so each image keeps a genuinely distinct,
reproducible seed. This preserves the reproducibility contract the advanced panel implies instead
of quietly turning `seeds` into four numbers that reproduce nothing.

Tests: an eligible `imgBatchSize=4` invokes `run_workflow` exactly once; an ineligible workflow
still returns 4 images; single-image behaviour byte-identical; no sleep on any path.

### Phase 8 — persistence

- Reuse one client across the loop; bounded concurrency (small semaphore), never unbounded.
- **Fix Finding G first** — the `/comfy/view/` branch must carry `subfolder` and `type`.
- Add `COMFY_OUTPUT_DIR` to `config.py`, resolved like `_get_comfyui_input_dir()`.
- When it is configured, the file exists, and the resolved path stays **inside** the configured
  root (path traversal check, since `filename`/`subfolder` originate from ComfyUI's response),
  copy it directly instead of fetching `http://localhost:8188/view?…`.
- HTTP `/view` remains the fallback for Docker without a shared filesystem, remote ComfyUI, and
  missing/misconfigured `COMFY_OUTPUT_DIR`. **This optimisation must never make a remote
  deployment fail.**

Tests: direct copy; missing local source → HTTP fallback; remote URL; already-persisted `/files/`
URL; traversal attempt refused.

### Phase 9 — hot-path caches, only if Phase 1 justifies them

Workflow template `lru_cache` keyed on `(path, mtime_ns)` returning `copy.deepcopy`; LoRA metadata
cache keyed on `(path, mtime_ns, size)`. **Skip either if profiling shows it negligible** — a JSON
file of this size parses in well under a millisecond, and an unjustified cache is a hot-reload bug
waiting to happen.

### Phase 10 — conversation id

Separate change, correctly flagged in the brief as **not** the latency cause. Retain the returned
`conversation_id` in Imagine session state and send it on subsequent generations. Do not let it
delay Phases 2–4.

---

## 5. Recommendation on Finding B

Not in the brief, and it decides whether the stated target is honest.

Once Phase 1 quantifies `prompt_refinement_ms`, pick one:

1. **Bound it.** A timeout (2–3 s) with fallback to the user's own prompt. `_refine_prompt`
   already has a failure path that preserves user intent, so this is small and safe.
2. **Overlap it.** Nothing in the refinement depends on `/object_info` or the workflow load, so it
   can run concurrently with graph preparation.
3. **Surface it.** Imagine already has a `promptRefinement` prop; if refinement is genuinely
   costing seconds, the toggle deserves to be visible and its cost stated.

(1) is the minimum. Until one of them lands, quote the target as
**"ComfyUI ~2–3 s + HomePilot overhead < 1 s + refinement (measured separately)"** rather than an
unqualified 2.5–4 s.

---

## 6. Expected outcome

| | now | after 2–4 | after 5–9 |
|---|---|---|---|
| `/object_info` on warm path | up to 30 s, every image | 0 | 0 |
| Transport setup | new client per image | new client per image | pooled |
| Completion latency | 0–1 s poll | 0–1 s poll | event-driven |
| Batch of 4 | 4 × everything + 1.5 s sleep | 4 × workflow, no preflight, no sleep | 1 × `/prompt` |
| Persistence | localhost HTTP per image | unchanged | direct copy where local |
| HomePilot overhead | tens of seconds | sub-second + refinement | sub-second + refinement |

Phases 2–4 are expected to recover the overwhelming majority of the regression. Phases 5–9 take
the remainder from "small" to "negligible" and are worth doing on their own merits — but they
should be measured, not assumed.

---

## 7. Rules carried forward

- ComfyUI owns model and VRAM lifecycle. No PyTorch checkpoint cache in HomePilot, no manual
  unload/reload, no holding model objects. Verified absent today; keep it that way.
- Preserve existing APIs and response schemas. Instrumentation is logging.
- Every phase leaves the tree green.
- No claim of success from ComfyUI's own `Prompt executed` line — measure the full `/chat`.

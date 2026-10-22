# Deep research — how it works, and how Expert and Heavy differ

HomePilot's chat has four ways to answer: **Fast**, **Expert**, **Heavy** and **Deep research**.
The first three answer in the conversation. Deep research is a job: it plans, delegates, reads
the web, and writes a cited report you can leave and come back to. This page explains the
technology behind Deep research, then what sets Expert and Heavy apart and where each could go.

Everything here is in-house code under `expert/backend/app/expert/` (no agent framework):
the same tool loop, the same providers, the same state store. The modes differ in how many
times the model is asked, with what role, and what runs around it.

## 1. Deep research

### What happens when you press "Deep research"

1. **Plan.** The model writes 2–5 sub-questions for the request. The plan appears in the
   work card at once, each item with its state.
2. **Research, one sub-agent per item.** Each item gets a clean context and its own turn of the
   tool loop: web search first (always), then page fetches, the workspace, notes, and the
   project's documents when the chat has a project. The sub-agent reports findings with `[n]`
   citations. Items run in sequence within a time budget (`EXPERT_DEEP_TIME_BUDGET_S`, 300 s)
   and a call budget per item (`EXPERT_DEEP_ROUNDS_PER_ITEM`).
3. **One source book.** Every sub-agent's citations are renumbered into a single list, so `[3]`
   means the same thing in every part of the report and in the sources panel.
4. **Write.** A writer pass turns the findings and sources into the report, streamed token by
   token into the chat.
5. **Done, or stopped.** The budget ending, a cancel (`DELETE /v1/expert/deep/{id}`) or an error
   closes the job gracefully; what was found so far is kept.

### The technology underneath

- **A durable job, not a request.** The job is a record in the Expert state store (SQLite at
  `<DATA_DIR>/expert_state.sqlite`). Every event it emits — plan, item status, tokens, sources,
  done — carries a sequence number and is written down. The browser follows the job over
  Server-Sent Events (`GET /v1/expert/deep/{id}/events`); after a refresh or a lost connection
  it reconnects with `?after=<seq>` (or `Last-Event-ID`) and receives only what it missed.
  A finished report survives a backend restart; a job cut off by one is marked interrupted,
  never left "running". The chat remembers which job belongs to which conversation and resumes
  it when you open that conversation.
- **The per-turn tool loop** (`tool_loop.py`). Tools are HomePilot's own MCP servers — web
  search and page fetch, workspace and notes search, the project's documents — discovered over
  JSON-RPC and offered to the model in OpenAI function-calling shape. The loop runs up to a few
  rounds of "model asks → HomePilot runs the tool → results go back numbered", then asks for the
  answer. In Deep research the web search is **forced**: it runs before the sub-agent is asked
  anything, so every item is grounded even if the model would not have searched on its own.
- **Models that cannot call tools still work.** Some connections reject the `tools` field.
  HomePilot learns that (and re-checks it an hour later), runs the search itself, and hands the
  model the results as plain text. The report is still cited; only the model's own choice of
  what to search is gone.
- **A capability gate.** Deep research is offered only when the selected model is high-end:
  a frontier family by name (GPT, Claude, Gemini, gpt-oss, GLM, Kimi, DeepSeek-V…) or at least
  `EXPERT_DEEP_MIN_PARAMS_B` (20B) parameters. Smaller models plan badly and lose the thread
  across items. `POST /v1/expert/capabilities` reports the tier; with `probe: true` it measures
  the model (one tiny tool call, one JSON instruction). `EXPERT_DEEP_RESEARCH=always|off`
  overrides the gate.
- **One model.** The model chosen in the chat is the one Deep research uses — no silent swap to
  a bigger one.
- **Streaming hygiene.** Frames carry `id:` sequence numbers; a `: keep-alive` comment goes out
  during long silences so proxies and browsers never take a working stream for a dead one; the
  pipeline is cancelled the moment the reader disconnects, which also stops the model call.
- **The work card.** The card above the answer shows the plan and each item's state while the
  job runs, then collapses to a summary with the elapsed time; opening it shows the items, the
  tools that ran, and the sources.

### Knobs

| Setting | Default | What it does |
| --- | --- | --- |
| `EXPERT_DEEP_RESEARCH` | `auto` | `auto` gates on the selected model; `always` / `off` override |
| `EXPERT_DEEP_MIN_PARAMS_B` | `20` | Parameter count that counts as high-end |
| `EXPERT_DEEP_TIME_BUDGET_S` | `300` | Wall-clock budget for one job |
| `EXPERT_DEEP_ROUNDS_PER_ITEM` | see config | Tool rounds each sub-agent may use |
| `EXPERT_DEEP_TEMPERATURE` | `0.3` | Sampling temperature for the job |
| `EXPERT_SSE_HEARTBEAT_S` | `10` | Seconds of silence before a keep-alive comment |

## 2. Expert and Heavy: what is different

Both answer inside the conversation and both can use the tools. They differ in **what the
extra model calls are for**.

| | **Expert** | **Heavy** |
| --- | --- | --- |
| Question it answers | "Think this through properly" | "Be right, and show me it was checked" |
| Stages | Analyze → Answer (from complexity 4: Analyze → Plan → Solve) | Reason → Synthesize → Validate (from complexity 5, or with "Search the web": Research first) |
| Extra calls buy | A better path to the answer | An independent check of the answer |
| Tools | In the Solve stage (and Analyze when a search was asked for) | In Research (when the request is complex or a search was asked for), otherwise in Reason |
| Output | The answer | The answer plus a **verdict**: `validated`, `corrected`, `reviewed` or `needs_review`, with the issues found |
| Typical use | Code, explanations, design, step-by-step problems | Decisions, calculations, facts you will act on, anything with a cost of being wrong |
| Cost | ~2–3× Fast | ~3–4× Fast |

Three things are the same in both, by design:

- **The mode is a ceiling, the request decides** (`policies.effort_for`). A greeting is one
  generation in any mode. Expert always writes its analysis first (that is the reasoning you
  see) and adds a plan only from complexity 4; Heavy runs its research agent only from
  complexity 5 or when "Search the web" is on. The work card's footer says which effort level
  ran and why.
- **One endpoint is never flooded.** Requests to the same gateway are paced (at most two in
  flight, one second between starts) and a rate limit or a 503 is waited out with exponential
  backoff before the first token. If Heavy's research agent or validator still cannot run, the
  answer is produced without it and the card says so — a turn never dies on one busy stage.
- **The history travels with every stage**, within a window; older turns are summarized into a
  running note rather than dropped (`compaction.py`).
- **Reasoning is visible.** With "Show reasoning" on (chat settings, the default), each stage's
  reasoning streams into the work card as it is written, as ChatGPT and Claude show their
  thinking. Off, the stages are named and each output sits behind "Show output" — the trace is
  always there to verify the reasons behind an answer.

### What the verdict means

Heavy's validator answers in JSON: a verdict, a list of issues with severities, an optional
corrected answer, the method it used and what it could not verify. A correction replaces the
answer (in the stream too). A "validated" that still lists a high-severity issue, or a
correction with no text, becomes `needs_review` — the card says so instead of claiming
certainty it does not have.

## 3. Behind a shared gateway

Heavy and Deep research make several model calls per turn. Against a shared, rate-limited
endpoint (an Open WebUI or LiteLLM gateway in front of vLLM or SGLang), HomePilot behaves like
a well-mannered client:

- **A queue with priorities.** At most two requests in flight per endpoint; the rest wait in
  line, a person's chat ahead of a research job's background calls. While a turn waits, the chat
  says so ("The model provider is busy; retrying in 8 s…").
- **A usage meter that learns the limit.** After a rate limit, the endpoint's cap is the number
  of calls that went through in the last minute; a token bucket then spreads calls at that rate,
  and the cap rises again after quiet minutes. `GET /v1/expert/usage` shows it.
- **Adaptive pacing.** A gap between request starts that doubles on every rate limit (up to
  15 s, shared by every caller) and shrinks back 15 % per success — the client finds the
  endpoint's real limit instead of tripping it.
- **Backoff with jitter.** A 429, a "rate limit" body, or a 502/503/504 is retried with
  exponential backoff (about 2, 4, 8, 16 s, ±25 %); `Retry-After` is honoured as a floor.
  Retries happen only before the first token, so nothing is ever shown twice.
- **Graceful degradation.** A stage that still cannot run is skipped and named: Heavy answers
  unvalidated, Deep research marks the item and keeps going, a failed writer returns the findings.
- **Clear errors from OllaBridge.** A provider's rate limit reaches the client as HTTP 429 with
  `Retry-After`, an outage as 502, a refused `tools` field as 400 `tools_unsupported` — never as
  a local-runtime 404.

Gateway-side settings that pair well with this: streaming-safe timeouts (no finite write
timeout for SSE), a per-key rate limit that answers 429 rather than 400, backpressure as
503 + `Retry-After`, and prefix-cache-aware routing. HomePilot keeps the system prompt and history
first and each stage's instruction last, so consecutive stages share a prompt prefix that such a
router can serve from cache.

## 4. Ideas

Directions that fit the current design, roughly in order of value for the effort.

**Expert**

- *Approve the plan.* Pause after the Plan stage on long tasks and let the reader edit or
  confirm the steps before Solve runs. The plan is already a separate, streamed stage.
- *Code-aware Solve.* When the chat has a project with code, give Solve the project search tool
  first (it already exists for documents) and show the files it read as chips.
- *Critique on demand.* The optional critique pass exists (`with_critique`); surface it as a
  "Review this answer" action under an Expert reply instead of a hidden flag.

**Heavy**

- *An independent validator.* Run the Validate stage on a different model or connection when one
  is configured (`HEAVY_VALIDATOR_PROVIDER` is already read), so the checker does not share the
  reasoner's blind spots. Show "checked by <model>" in the verdict.
- *Verifiable claims.* Ask the validator to tag each issue with the source it checked against
  (`[n]`), so a `needs_review` tells the reader what to open.
- *A confidence line.* One short sentence from the validator on how sure it is and why,
  rendered under the verdict badge.

**Deep research**

- *Follow-ups inside a report.* "Dig into item 3" starts a child job that reuses the parent's
  source book and appends to the same card.
- *Research as a routine.* A saved query that runs on a schedule and posts the report, using
  the existing Routines runner; the job model already survives restarts.
- *Export.* One click from a finished report to a document in the workspace, sources included.
- *Budget control.* Let the reader choose a quick (2 items, 2 min) or thorough (5 items,
  5 min) run before it starts.

**All three**

- *Native reasoning.* Engines serving reasoning models with a reasoning parser stream the
  model's thinking as `reasoning_content` beside `content`. Reading that field would let
  "Show reasoning" show the model's own reasoning, at no extra call.
- *Parallel sub-agents where the endpoint allows it.* Deep research items are independent; with a
  dedicated endpoint (`EXPERT_PROVIDER_MAX_INFLIGHT` raised) they could run side by side.
- *Per-project source memory.* Remember which sources a project's answers relied on, so later
  turns can cite them again without a new search.
- *Evaluation in CI with a recorded model.* `scripts/eval-expert.py` runs the ten scenarios
  against a live stack; recording one model's replies would let the same scenarios guard
  regressions without a GPU.

## Related

- `expert/README.md` — the Expert module, modes, streaming events and every knob.
- `docs/OLLABRIDGE.md` — connecting a gateway (OllaBridge) and its models.
- `scripts/eval-expert.py` — the ten-scenario evaluation against a running backend.

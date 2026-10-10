# Default chat — quality review against industry practice

Reviewed: the default text chat (Chat page, `POST /chat` → `orchestrator` → `llm.py`), October
2026. Compared with what users now expect from ChatGPT, Claude, Gemini, Open WebUI and LM Studio.

## Verdict

HomePilot's chat **looks and behaves like a professional product** — persona identity and memory,
voice, mobile layout, motion, accessibility and appearance settings are at or above the bar. The
gaps are in **inference plumbing**: answers are not streamed, cannot be stopped, regenerated or
edited, and the model's context window is never set, so long conversations lose context silently.
Most fixes reuse code that already exists in the repository.

## Scorecard

✅ meets the bar · ◐ partly · ✗ missing

### Conversation design

| Area | Industry standard | HomePilot today | |
|---|---|---|---|
| Token streaming | First words in < 1 s, answer streams | `POST /chat` waits for the full answer; the typewriter animates it afterwards. An SSE endpoint (`/v1/compute/chat/stream`) and client (`lib/streamChat.ts`) exist but the chat does not use them | ✗ |
| Stop generating | Stop button while answering | None (no request cancellation) | ✗ |
| Regenerate | Regenerate, often with alternatives | Retry only on a failed message | ✗ |
| Edit and resend | Edit a sent message, branch from it | None | ✗ |
| Markdown | GFM tables, lists, code blocks with copy | `react-markdown` + GFM, code blocks with copy | ✅ |
| Code highlighting | Syntax colouring | None | ◐ |
| Copy answer | One click | Yes | ✅ |
| Attachments | Images, documents | Images in chat; documents through Projects (RAG) | ✅ |
| Voice | Dictation and live voice | Hands-free voice and calls | ✅ |
| History and search | Searchable history | History panel, Ctrl+K search | ✅ |
| Identity and memory | Custom assistants with memory | Personas: picture, long-term memory, sessions, Conversation Hub | ✅ (ahead) |
| Answer feedback | 👍/👎 per answer | None | ✗ |
| Appearance | Density, avatars | Chat Appearance (thumbnails, compact spacing), Motion | ✅ |
| Accessibility | Labels, focus, reduced motion | Named messages, focus rings, reduced-motion support | ✅ |
| Mobile | Full-screen, keyboard-safe composer | Done in the mobile pass | ✅ |
| Errors | Clear error, retry, partial answer kept | Error + Retry; a partial answer is lost | ◐ |

### Inference

| Area | Industry standard | HomePilot today | |
|---|---|---|---|
| Context window | Set per model, sized to memory | `num_ctx` is never sent, so Ollama uses its default (a few thousand tokens) and truncates silently | ✗ |
| History sent | Full conversation, older turns summarised | Last 8 messages (`CHAT_HISTORY_LIMIT`, max 24), no summary; personas add long-term memory | ◐ |
| Answer length | Long answers, "continue" when cut | 900-token cap, no continue | ◐ |
| Sampling | Sensible defaults, per-model presets | Temperature 0.7 (0.9 in fun mode); no per-model presets | ◐ |
| Model fit for the hardware | Guidance on what runs well | Model Advisor (FitLab) — new | ✅ |
| Latency visibility | Time-to-first-token, tokens/s | Not shown | ✗ |
| Cancellation | Server stops when the user stops | 300 s timeout; generation continues after the user leaves | ◐ |
| Quality evaluation | Regression set per model/prompt change | None | ✗ |
| Install safety | Authenticated model installs | `POST /models/install` is open (`require_api_key` is a pass-through shim) | ◐ |

## What to do, in order

**P0 — biggest felt improvement, smallest risk**

1. **Stream the default chat.** Route text turns through the existing `/v1/compute/chat/stream`
   with `lib/streamChat.ts`; keep `POST /chat` as the fallback. Time-to-first-token goes from the
   whole generation time to well under a second. `StreamReveal` already renders progressive text.
2. **Stop button.** Abort the stream (AbortController) and close the upstream request so the GPU
   stops too; keep the partial answer.
3. **Set the context window.** Send `num_ctx` per model — 8K by default, or the largest context that
   fits: the Model Advisor already computes KV-cache size from FitLab's architecture data. This
   removes silent truncation, the single largest hidden quality loss.

**P1 — parity**

4. **Regenerate** the last answer and **edit and resend** a message (branching later).
5. **Continue** when an answer stops at the length cap (`done_reason == "length"`), and raise the
   desktop default to ~2,048 tokens.
6. **Syntax highlighting** in code blocks (lazy-loaded).
7. **Show speed** under each answer on hover — time to first token and tokens/s, from Ollama's
   `eval_count` / `eval_duration`.
8. **👍/👎 feedback** stored locally, as the seed of an evaluation set.

**P2 — depth**

9. **Rolling summary** of turns older than the history window.
10. **Golden-set evaluation**: 30–50 fixed prompts per use case, run on a model or prompt change.
    FitLab's roadmap has a matching "quality-eval lane".
11. **Per-model presets** (context, temperature, stop tokens), sourced from FitLab or the Ollama
    Modelfile.
12. **Authenticate model installs** and other mutating endpoints.

## Where FitLab fits

- Done: the Model Advisor ranks chat, vision, image and video models for this computer, notifies
  about clearly better ones, and installs them on request ([model-advisor.md](model-advisor.md)).
- Next: reuse its per-model architecture data to choose `num_ctx` (P0.3), and its measured
  tokens/s to set expectations in the chat (P1.7).

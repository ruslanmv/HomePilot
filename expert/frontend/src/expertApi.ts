// frontend/src/expertApi.ts
// Expert module API client — mirrors the pattern in api.ts / communityApi.ts
// Updated: handles think/heavy pipeline step events from SSE stream.

import { api, getApiKey } from "./ui/api";
import { getDefaultBackendUrl } from "./ui/lib/backendUrl";

const BASE = getDefaultBackendUrl();

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type ExpertProvider =
  | "auto" | "local" | "groq" | "grok" | "gemini" | "claude" | "openai";

export type ThinkingMode = "auto" | "fast" | "think" | "heavy";

export interface ExpertMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ExpertChatRequest {
  query: string;
  provider?: ExpertProvider;
  thinking_mode?: ThinkingMode;
  history?: ExpertMessage[];
  model?: string;
  temperature?: number;
  max_tokens?: number;
  system_prompt?: string;
  with_critique?: boolean;
}

export interface ExpertChatResponse {
  content: string;
  provider_used: string;
  model_used: string | null;
  complexity_score: number;
  thinking_mode_used: string;
  steps?: Record<string, string>;
}

export interface ExpertInfo {
  available_providers: string[];
  default_provider: string;
  local_threshold: number;
  groq_threshold: number;
  local_model: string;
  local_fast_model: string;
  groq_model: string;
  grok_model: string;
  gemini_model: string;
}

export interface StreamMeta {
  provider: string;
  complexity: number;
  thinking_mode: ThinkingMode;
}

export interface StreamStep {
  step: string;       // "analyze" | "plan" | "solve" | "research" | "reasoning" | "synthesis" | "validation"
  label: string;      // human-readable label e.g. "🔍 Analyzing problem…"
  provider?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// REST calls
// ─────────────────────────────────────────────────────────────────────────────

export async function fetchExpertInfo(): Promise<ExpertInfo> {
  const { data } = await api.get<ExpertInfo>("/v1/expert/info");
  return data;
}

export async function expertChat(req: ExpertChatRequest): Promise<ExpertChatResponse> {
  const { data } = await api.post<ExpertChatResponse>("/v1/expert/chat", req);
  return data;
}

export async function expertRoute(
  query: string, preferred = "auto"
): Promise<Record<string, unknown>> {
  const { data } = await api.post("/v1/expert/route", null, {
    params: { query, preferred },
  });
  return data;
}

// ─────────────────────────────────────────────────────────────────────────────
// Streaming via fetch + ReadableStream
// ─────────────────────────────────────────────────────────────────────────────

export interface StreamCallbacks {
  onMeta?: (meta: StreamMeta) => void;
  /** Called when a pipeline step starts (think/heavy modes only) */
  onStep?: (step: StreamStep) => void;
  /** Called when a pipeline step finishes */
  onStepEnd?: (stepName: string) => void;
  /** Called for each streamed token — includes the active step name if in a pipeline */
  onToken?: (token: string, step?: string) => void;
  /** Called when think/heavy pipeline emits final answer tokens (no step context) */
  onFinalAnswer?: (token: string) => void;
  onDone?: () => void;
  onError?: (err: string) => void;
}

/**
 * Stream an Expert response token-by-token.
 * Returns an AbortController so the caller can cancel mid-stream.
 */
export function expertStream(
  req: ExpertChatRequest,
  callbacks: StreamCallbacks
): AbortController {
  const controller = new AbortController();
  const apiKey = getApiKey();

  (async () => {
    try {
      const response = await fetch(`${BASE}/v1/expert/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(apiKey ? { "X-API-Key": apiKey } : {}),
        },
        body: JSON.stringify(req),
        signal: controller.signal,
      });

      if (!response.ok) {
        callbacks.onError?.(`HTTP ${response.status}: ${response.statusText}`);
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) { callbacks.onError?.("No response body"); return; }

      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "";
      let currentStep = "";  // track active step for token attribution

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (line === "") {
            // blank line = end of SSE event block — reset event type
            currentEvent = "";
            continue;
          }

          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
            continue;
          }

          if (line.startsWith("data: ")) {
            const payload = line.slice(6);

            if (payload === "[DONE]") {
              callbacks.onDone?.();
              return;
            }

            switch (currentEvent) {
              case "meta":
                try { callbacks.onMeta?.(JSON.parse(payload) as StreamMeta); } catch {}
                break;

              case "step":
                try {
                  const s = JSON.parse(payload) as StreamStep;
                  currentStep = s.step;
                  callbacks.onStep?.(s);
                } catch {}
                break;

              case "step_end":
                try {
                  const { step } = JSON.parse(payload) as { step: string };
                  callbacks.onStepEnd?.(step);
                  currentStep = "";
                } catch {}
                break;

              case "final_answer":
                // Pipeline emitted final answer — switch to final answer mode
                if (payload === "start") {
                  currentStep = "";  // clear step context so tokens go to turn.content
                }
                break;

              case "error":
                try {
                  const err = JSON.parse(payload) as { error: string };
                  callbacks.onError?.(err.error);
                } catch { callbacks.onError?.(payload); }
                return;

              default:
                // Plain token — if no step active, goes to final answer
                const token = payload.replace(/\\n/g, "\n");
                if (currentStep) {
                  callbacks.onToken?.(token, currentStep);
                } else {
                  callbacks.onFinalAnswer?.(token);
                  callbacks.onToken?.(token, undefined);
                }
                break;
            }
          }
        }
      }

      callbacks.onDone?.();
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      callbacks.onError?.(String(err));
    }
  })();

  return controller;
}

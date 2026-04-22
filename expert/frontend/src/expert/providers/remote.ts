import type { ExpertModeId } from "../types";
import type { InferenceRequest, InferenceResponse } from "./local";

export interface RemoteProviderConfig {
  baseUrl?: string;
  apiKey?: string;
  defaultModel?: string;
  timeoutMs?: number;
  headers?: Record<string, string>;
  enabled?: boolean;
}

const DEFAULT_REMOTE_BASE_URL =
  (typeof import.meta !== "undefined" &&
    (import.meta as { env?: Record<string, string> }).env?.VITE_REMOTE_LLM_URL) ||
  "";

const DEFAULT_REMOTE_API_KEY =
  (typeof import.meta !== "undefined" &&
    (import.meta as { env?: Record<string, string> }).env?.VITE_REMOTE_LLM_API_KEY) ||
  "";

const DEFAULT_REMOTE_MODEL =
  (typeof import.meta !== "undefined" &&
    (import.meta as { env?: Record<string, string> }).env?.VITE_REMOTE_LLM_MODEL) ||
  "Qwen/QwQ-32B";

const DEFAULT_TIMEOUT_MS = 180_000;

function buildTimeoutSignal(timeoutMs: number, external?: AbortSignal): AbortSignal {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  const cleanup = () => clearTimeout(timeout);
  controller.signal.addEventListener("abort", cleanup, { once: true });

  if (external) {
    if (external.aborted) {
      controller.abort();
    } else {
      external.addEventListener("abort", () => controller.abort(), { once: true });
    }
  }

  return controller.signal;
}

function fallbackRemoteModelForMode(mode: ExpertModeId): string {
  switch (mode) {
    case "fast":
      return "meta-llama/Llama-3.1-8B-Instruct";
    case "expert":
      return "Qwen/QwQ-32B";
    case "heavy":
      return "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B";
    case "beta":
      return "Qwen/Qwen2.5-72B-Instruct";
    case "auto":
    default:
      return DEFAULT_REMOTE_MODEL;
  }
}

export class RemoteProvider {
  readonly baseUrl: string;
  readonly apiKey: string;
  readonly defaultModel: string;
  readonly timeoutMs: number;
  readonly headers: Record<string, string>;
  readonly enabled: boolean;

  constructor(config: RemoteProviderConfig = {}) {
    this.baseUrl = config.baseUrl ?? DEFAULT_REMOTE_BASE_URL;
    this.apiKey = config.apiKey ?? DEFAULT_REMOTE_API_KEY;
    this.defaultModel = config.defaultModel ?? DEFAULT_REMOTE_MODEL;
    this.timeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.headers = config.headers ?? {};
    this.enabled = config.enabled ?? Boolean(this.baseUrl);
  }

  isConfigured(): boolean {
    return this.enabled && Boolean(this.baseUrl);
  }

  async isHealthy(): Promise<boolean> {
    if (!this.isConfigured()) {
      return false;
    }

    try {
      const response = await fetch(`${this.baseUrl}/models`, {
        method: "GET",
        headers: this.buildHeaders(),
      });
      return response.ok;
    } catch {
      return false;
    }
  }

  async chat(request: InferenceRequest): Promise<InferenceResponse> {
    if (!this.isConfigured()) {
      throw new Error("RemoteProvider is not configured.");
    }

    const signal = buildTimeoutSignal(this.timeoutMs, request.signal);
    const model = request.model ?? fallbackRemoteModelForMode(request.mode) ?? this.defaultModel;

    const response = await fetch(`${this.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...this.buildHeaders(),
      },
      signal,
      body: JSON.stringify({
        model,
        messages: request.messages,
        temperature: request.temperature ?? 0.3,
        max_tokens: request.maxTokens ?? 2000,
        stream: false,
      }),
    });

    if (!response.ok) {
      const body = await safeReadText(response);
      throw new Error(
        `RemoteProvider chat failed (${response.status}): ${body || response.statusText}`
      );
    }

    const data = await response.json();

    return {
      text: data?.choices?.[0]?.message?.content ?? "",
      model: data?.model ?? model,
      backend: "remote",
      usage: data?.usage
        ? {
            promptTokens: data.usage.prompt_tokens,
            completionTokens: data.usage.completion_tokens,
            totalTokens: data.usage.total_tokens,
          }
        : undefined,
      meta: {
        id: data?.id,
        created: data?.created,
      },
    };
  }

  private buildHeaders(): Record<string, string> {
    return {
      ...(this.apiKey ? { Authorization: `Bearer ${this.apiKey}` } : {}),
      ...this.headers,
    };
  }
}

async function safeReadText(response: Response): Promise<string> {
  try {
    return await response.text();
  } catch {
    return "";
  }
}

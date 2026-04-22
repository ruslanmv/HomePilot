import type { ExpertModeId } from "../types";

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface InferenceRequest {
  messages: ChatMessage[];
  mode: ExpertModeId;
  model?: string;
  temperature?: number;
  maxTokens?: number;
  signal?: AbortSignal;
}

export interface InferenceUsage {
  promptTokens?: number;
  completionTokens?: number;
  totalTokens?: number;
}

export interface InferenceResponse {
  text: string;
  model: string;
  backend: "local" | "remote";
  usage?: InferenceUsage;
  meta?: Record<string, unknown>;
}

export interface LocalProviderConfig {
  baseUrl?: string;
  defaultModel?: string;
  timeoutMs?: number;
  headers?: Record<string, string>;
}

const DEFAULT_LOCAL_BASE_URL =
  (typeof import.meta !== "undefined" &&
    (import.meta as Record<string, unknown>)?.env &&
    ((import.meta as { env?: Record<string, string> }).env?.VITE_LOCAL_LLM_URL as string)) ||
  "http://localhost:11434/v1";

const DEFAULT_LOCAL_MODEL =
  (typeof import.meta !== "undefined" &&
    (import.meta as { env?: Record<string, string> }).env?.VITE_LOCAL_LLM_MODEL) ||
  "llama3.1:8b";

const DEFAULT_TIMEOUT_MS = 120_000;

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

function fallbackModelForMode(mode: ExpertModeId): string {
  switch (mode) {
    case "fast":
      return "llama3.1:8b";
    case "expert":
      return "deepseek-r1:14b";
    case "heavy":
      return "deepseek-r1:14b";
    case "beta":
      return "qwen2.5:14b";
    case "auto":
    default:
      return DEFAULT_LOCAL_MODEL;
  }
}

export class LocalProvider {
  readonly baseUrl: string;
  readonly defaultModel: string;
  readonly timeoutMs: number;
  readonly headers: Record<string, string>;

  constructor(config: LocalProviderConfig = {}) {
    this.baseUrl = config.baseUrl ?? DEFAULT_LOCAL_BASE_URL;
    this.defaultModel = config.defaultModel ?? DEFAULT_LOCAL_MODEL;
    this.timeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.headers = config.headers ?? {};
  }

  async isHealthy(): Promise<boolean> {
    try {
      const response = await fetch(`${this.baseUrl}/models`, {
        method: "GET",
        headers: this.headers,
      });
      return response.ok;
    } catch {
      return false;
    }
  }

  async chat(request: InferenceRequest): Promise<InferenceResponse> {
    const signal = buildTimeoutSignal(this.timeoutMs, request.signal);
    const model = request.model ?? fallbackModelForMode(request.mode) ?? this.defaultModel;

    const response = await fetch(`${this.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...this.headers,
      },
      signal,
      body: JSON.stringify({
        model,
        messages: request.messages,
        temperature: request.temperature ?? 0.4,
        max_tokens: request.maxTokens ?? 1200,
        stream: false,
      }),
    });

    if (!response.ok) {
      const body = await safeReadText(response);
      throw new Error(
        `LocalProvider chat failed (${response.status}): ${body || response.statusText}`
      );
    }

    const data = await response.json();

    return {
      text: data?.choices?.[0]?.message?.content ?? "",
      model: data?.model ?? model,
      backend: "local",
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
}

async function safeReadText(response: Response): Promise<string> {
  try {
    return await response.text();
  } catch {
    return "";
  }
}

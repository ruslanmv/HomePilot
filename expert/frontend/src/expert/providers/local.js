function readLocalEnv() {
    if (typeof import.meta === "undefined") {
        return {};
    }
    const maybeEnv = import.meta.env;
    return maybeEnv ?? {};
}
const localEnv = readLocalEnv();
const DEFAULT_LOCAL_BASE_URL = localEnv.VITE_LOCAL_LLM_URL ?? "http://localhost:11434/v1";
const DEFAULT_LOCAL_MODEL = localEnv.VITE_LOCAL_LLM_MODEL ?? "llama3.1:8b";
const DEFAULT_TIMEOUT_MS = 120_000;
function buildTimeoutSignal(timeoutMs, external) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    const cleanup = () => clearTimeout(timeout);
    controller.signal.addEventListener("abort", cleanup, { once: true });
    if (external) {
        if (external.aborted) {
            controller.abort();
        }
        else {
            external.addEventListener("abort", () => controller.abort(), { once: true });
        }
    }
    return controller.signal;
}
function fallbackModelForMode(mode) {
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
    constructor(config = {}) {
        this.baseUrl = config.baseUrl ?? DEFAULT_LOCAL_BASE_URL;
        this.defaultModel = config.defaultModel ?? DEFAULT_LOCAL_MODEL;
        this.timeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT_MS;
        this.headers = config.headers ?? {};
    }
    async isHealthy() {
        try {
            const response = await fetch(`${this.baseUrl}/models`, {
                method: "GET",
                headers: this.headers,
            });
            return response.ok;
        }
        catch {
            return false;
        }
    }
    async chat(request) {
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
            throw new Error(`LocalProvider chat failed (${response.status}): ${body || response.statusText}`);
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
async function safeReadText(response) {
    try {
        return await response.text();
    }
    catch {
        return "";
    }
}

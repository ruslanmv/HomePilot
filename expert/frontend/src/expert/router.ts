import { resolveRoutingPolicy, type RoutingDecision } from "./policies";
import {
  LocalProvider,
  type ChatMessage,
  type InferenceResponse,
  type InferenceRequest,
} from "./providers/local";
import { RemoteProvider } from "./providers/remote";
import type { ExpertModeId } from "./types";
import type { MemoryStore } from "./memory/store";
import { InMemoryStore } from "./memory/store";
import type { EvalRecorder } from "./evals/harness";
import { InMemoryEvalRecorder } from "./evals/harness";
import { ReliabilityTracker } from "./reliability/metrics";
import type { ToolInvocation } from "./tools/types";
import { ToolRegistry } from "./tools/registry";
import { createBuiltinToolRegistry } from "./tools/builtin";

export interface RouteExpertRequest {
  mode: ExpertModeId;
  messages: ChatMessage[];
  hasAttachments?: boolean;
  sessionId?: string;
  signal?: AbortSignal;
}

export interface RouteExpertResponse extends InferenceResponse {
  decision: RoutingDecision;
}

export interface ExpertRouterConfig {
  local?: LocalProvider;
  remote?: RemoteProvider;
  monthlyGpuBudgetReached?: () => boolean;
  memoryStore?: MemoryStore;
  evalRecorder?: EvalRecorder;
  reliabilityTracker?: ReliabilityTracker;
  toolRegistry?: ToolRegistry;
}

type InferenceProvider = Pick<LocalProvider, "chat"> | Pick<RemoteProvider, "chat">;

export class ExpertRouter {
  private readonly local: LocalProvider;
  private readonly remote: RemoteProvider;
  private readonly monthlyGpuBudgetReached: () => boolean;
  private readonly memoryStore: MemoryStore;
  private readonly evalRecorder: EvalRecorder;
  private readonly reliabilityTracker: ReliabilityTracker;
  private readonly toolRegistry: ToolRegistry;

  constructor(config: ExpertRouterConfig = {}) {
    this.local = config.local ?? new LocalProvider();
    this.remote = config.remote ?? new RemoteProvider();
    this.monthlyGpuBudgetReached = config.monthlyGpuBudgetReached ?? (() => false);
    this.memoryStore = config.memoryStore ?? new InMemoryStore();
    this.evalRecorder = config.evalRecorder ?? new InMemoryEvalRecorder();
    this.reliabilityTracker = config.reliabilityTracker ?? new ReliabilityTracker();
    this.toolRegistry = config.toolRegistry ?? createBuiltinToolRegistry();
  }

  async route(request: RouteExpertRequest): Promise<RouteExpertResponse> {
    const [localAvailable, remoteAvailable] = await Promise.all([
      this.local.isHealthy().catch(() => false),
      this.remote.isHealthy().catch(() => false),
    ]);

    const decision = resolveRoutingPolicy({
      mode: request.mode,
      messages: request.messages,
      hasAttachments: request.hasAttachments,
      localAvailable,
      remoteAvailable,
      monthlyGpuBudgetReached: this.monthlyGpuBudgetReached(),
      providerStats: this.reliabilityTracker.snapshot(),
    });

    const started = Date.now();
    const messages = await this.buildMessagesWithMemory(request);

    let response: InferenceResponse;
    try {
      if (decision.provider === "remote") {
        response = await this.executeRemote({ ...request, messages }, decision);
      } else {
        response = await this.executeLocal({ ...request, messages }, decision);
      }
    } catch (error) {
      this.reliabilityTracker.record(decision.provider, false, Date.now() - started);
      throw error;
    }
    const latencyMs = Date.now() - started;

    this.reliabilityTracker.record(response.backend, true, latencyMs);
    await this.persistConversation(request, response.text);
    await this.evalRecorder.record({
      id: `${Date.now()}`,
      query: messages[messages.length - 1]?.content ?? "",
      response: response.text,
      latencyMs,
      provider: response.backend,
      strategy: decision.strategy,
    });

    return {
      ...response,
      decision,
    };
  }

  private async buildMessagesWithMemory(request: RouteExpertRequest): Promise<ChatMessage[]> {
    if (!request.sessionId) {
      return request.messages;
    }
    const memory = await this.memoryStore.recall(request.sessionId, 6);
    const memoryMessages: ChatMessage[] = memory.map((item) => ({
      role: item.role,
      content: item.content,
    }));
    return [...memoryMessages, ...request.messages];
  }

  private async persistConversation(request: RouteExpertRequest, answer: string): Promise<void> {
    if (!request.sessionId) {
      return;
    }

    const lastUser = [...request.messages].reverse().find((m) => m.role === "user");
    await this.memoryStore.append(request.sessionId, [
      {
        role: "user",
        content: lastUser?.content ?? "",
        timestamp: Date.now(),
      },
      {
        role: "assistant",
        content: answer,
        timestamp: Date.now(),
      },
    ]);
  }

  private async executeLocal(
    request: RouteExpertRequest,
    decision: RoutingDecision
  ): Promise<InferenceResponse> {
    if (decision.strategy === "single-pass") {
      return this.local.chat({ messages: request.messages, mode: request.mode, signal: request.signal });
    }
    if (decision.strategy === "expert-thinking") {
      return this.runExpertThinking(this.local, request);
    }
    return this.runHeavyMultiPass(this.local, request);
  }

  private async executeRemote(
    request: RouteExpertRequest,
    decision: RoutingDecision
  ): Promise<InferenceResponse> {
    if (decision.strategy === "single-pass") {
      return this.remote.chat({ messages: request.messages, mode: request.mode, signal: request.signal });
    }
    if (decision.strategy === "expert-thinking") {
      return this.runExpertThinking(this.remote, request);
    }
    return this.runHeavyMultiPass(this.remote, request);
  }

  private async runExpertThinking(
    provider: InferenceProvider,
    request: RouteExpertRequest
  ): Promise<InferenceResponse> {
    const userPrompt = request.messages[request.messages.length - 1]?.content ?? "";
    const toolContext = await this.runToolLoop(userPrompt, request.sessionId, request.signal, 3);

    const analysis = await provider.chat({
      messages: [
        {
          role: "system",
          content:
            "You are an expert planner. Analyze the user's problem and extract key constraints, goals, and assumptions.",
        },
        { role: "user", content: `${userPrompt}\n\nTool context:\n${toolContext}` },
      ],
      mode: "expert",
      maxTokens: 700,
      temperature: 0.2,
      signal: request.signal,
    });

    return provider.chat({
      messages: [
        {
          role: "system",
          content:
            "You are a strong expert assistant. Use the prior analysis to provide a clear, practical, high-quality answer.",
        },
        {
          role: "user",
          content: [
            "Original request:",
            userPrompt,
            "",
            "Analysis:",
            analysis.text,
            "",
            "Now produce the final answer.",
          ].join("\n"),
        },
      ],
      mode: "expert",
      maxTokens: 1600,
      temperature: 0.35,
      signal: request.signal,
    });
  }

  private async runHeavyMultiPass(
    provider: InferenceProvider,
    request: RouteExpertRequest
  ): Promise<InferenceResponse> {
    const userPrompt = request.messages[request.messages.length - 1]?.content ?? "";
    const toolContext = await this.runToolLoop(userPrompt, request.sessionId, request.signal, 5);

    const pass1 = await provider.chat({
      messages: [
        {
          role: "system",
          content:
            "Break the problem into subproblems, identify tradeoffs, and propose a robust solution outline.",
        },
        { role: "user", content: `${userPrompt}\n\nTool context:\n${toolContext}` },
      ],
      mode: "heavy",
      maxTokens: 900,
      temperature: 0.2,
      signal: request.signal,
    });

    const pass2 = await provider.chat({
      messages: [
        {
          role: "system",
          content:
            "Critique the outline, find weaknesses, edge cases, and missing practical considerations.",
        },
        {
          role: "user",
          content: `Problem:\n${userPrompt}\n\nDraft solution:\n${pass1.text}`,
        },
      ],
      mode: "heavy",
      maxTokens: 900,
      temperature: 0.25,
      signal: request.signal,
    });

    return provider.chat({
      messages: [
        {
          role: "system",
          content:
            "Produce the best final answer by combining the draft solution and critique into one coherent, practical response.",
        },
        {
          role: "user",
          content: `Problem:\n${userPrompt}\n\nDraft:\n${pass1.text}\n\nCritique:\n${pass2.text}`,
        },
      ],
      mode: "heavy",
      maxTokens: 2200,
      temperature: 0.3,
      signal: request.signal,
    });
  }

  private buildToolPlan(query: string, maxSteps: number): ToolInvocation[] {
    const plan: ToolInvocation[] = [];
    const lower = query.toLowerCase();

    if (/(latest|news|today|current|web|citation)/.test(lower)) {
      plan.push({ tool: "web_search", input: query });
    }
    if (/(project|docs|spec|architecture|history|memory)/.test(lower)) {
      plan.push({ tool: "retrieval", input: query });
    }
    if (/(code|debug|bug|error|stack|test)/.test(lower)) {
      plan.push({ tool: "code_exec", input: query });
    }
    if (/(compare|versus|vs|best model|benchmark)/.test(lower)) {
      plan.push({ tool: "model_compare", input: query });
    }

    if (!plan.length) {
      plan.push({ tool: "retrieval", input: query });
    }

    return plan.slice(0, maxSteps);
  }

  private async runToolLoop(
    query: string,
    sessionId?: string,
    signal?: AbortSignal,
    budget = 3
  ): Promise<string> {
    const plan = this.buildToolPlan(query, 4);
    const summary = await this.toolRegistry.executeMany(plan, {
      budget,
      sessionId,
      signal,
    });

    return summary.results
      .map((item) => `- [${item.tool}] ${item.ok ? "OK" : "FAIL"}: ${item.content}`)
      .join("\n");
  }
}

export function createExpertRouter(config: ExpertRouterConfig = {}): ExpertRouter {
  return new ExpertRouter(config);
}

export function toInferenceRequest(
  mode: ExpertModeId,
  messages: ChatMessage[],
  signal?: AbortSignal
): InferenceRequest {
  return { mode, messages, signal };
}

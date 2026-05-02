import type { ExpertModeId } from "./types";
import type { ChatMessage } from "./providers/local";
import type { ProviderStats } from "./reliability/metrics";

export type ProviderTarget = "local" | "remote";

export interface RoutingInput {
  mode: ExpertModeId;
  messages: ChatMessage[];
  hasAttachments?: boolean;
  remoteAvailable?: boolean;
  localAvailable?: boolean;
  monthlyGpuBudgetReached?: boolean;
  providerStats?: ProviderStats;
}

export interface RoutingDecision {
  provider: ProviderTarget;
  strategy: "single-pass" | "expert-thinking" | "heavy-multi-pass";
  complexityScore: number;
  reason: string;
  modelHint?: string;
}

export function estimateComplexity(messages: ChatMessage[]): number {
  const lastUserMessage =
    [...messages].reverse().find((m) => m.role === "user")?.content ?? "";

  let score = 0;

  if (lastUserMessage.length > 250) score += 2;
  if (lastUserMessage.length > 800) score += 2;

  if (/\b(analyze|compare|design|architect|reason|debug|research)\b/i.test(lastUserMessage)) {
    score += 2;
  }

  if (/\b(step by step|deeply|carefully|robust|scalable|tradeoff)\b/i.test(lastUserMessage)) {
    score += 2;
  }

  if ((lastUserMessage.match(/\?/g) || []).length >= 2) score += 1;
  if (messages.length > 8) score += 1;

  return Math.min(score, 10);
}

export function resolveRoutingPolicy(input: RoutingInput): RoutingDecision {
  const {
    mode,
    messages,
    hasAttachments = false,
    remoteAvailable = false,
    localAvailable = true,
    monthlyGpuBudgetReached = false,
    providerStats,
  } = input;

  const complexityScore = estimateComplexity(messages) + (hasAttachments ? 2 : 0);

  if (!localAvailable && !remoteAvailable) {
    throw new Error("No inference provider is available.");
  }

  const preferLocalByReliability = Boolean(
    providerStats &&
      providerStats.remoteSuccessRate < 0.7 &&
      providerStats.localSuccessRate >= providerStats.remoteSuccessRate
  );

  const preferRemoteByReliability = Boolean(
    providerStats &&
      providerStats.remoteSuccessRate >= 0.9 &&
      providerStats.remoteP95Ms > 0 &&
      (providerStats.localP95Ms === 0 || providerStats.remoteP95Ms < providerStats.localP95Ms * 1.4)
  );

  if (mode === "fast") {
    return {
      provider: localAvailable ? "local" : "remote",
      strategy: "single-pass",
      complexityScore,
      reason: localAvailable
        ? "Fast mode prefers local low-latency inference."
        : "Fast mode fell back to remote because local is unavailable.",
      modelHint: "fast",
    };
  }

  if (mode === "expert") {
    const useRemote =
      remoteAvailable &&
      !monthlyGpuBudgetReached &&
      !preferLocalByReliability;
    return {
      provider: useRemote ? "remote" : localAvailable ? "local" : "remote",
      strategy: "expert-thinking",
      complexityScore,
      reason:
        useRemote
          ? "Expert mode prefers stronger remote reasoning."
          : "Expert mode is using local reasoning due to reliability, remote unavailability, or budget policy.",
      modelHint: "expert",
    };
  }

  if (mode === "heavy") {
    return {
      provider: remoteAvailable && !monthlyGpuBudgetReached ? "remote" : "local",
      strategy: "heavy-multi-pass",
      complexityScore,
      reason:
        remoteAvailable && !monthlyGpuBudgetReached
          ? "Heavy mode routes to remote for multi-pass execution."
          : "Heavy mode fell back to local because remote is unavailable or blocked by policy.",
      modelHint: "heavy",
    };
  }

  if (mode === "beta") {
    const useRemote =
      remoteAvailable &&
      !monthlyGpuBudgetReached &&
      !preferLocalByReliability;
    return {
      provider: useRemote ? "remote" : "local",
      strategy: "expert-thinking",
      complexityScore,
      reason:
        useRemote
          ? "Beta mode uses the experimental remote configuration."
          : "Beta mode is using a local experimental fallback due to reliability or policy.",
      modelHint: "beta",
    };
  }

  if (complexityScore <= 2) {
    return {
      provider: localAvailable ? "local" : "remote",
      strategy: "single-pass",
      complexityScore,
      reason: "Auto selected fast local inference for a simple request.",
      modelHint: "fast",
    };
  }

  if (complexityScore <= 6) {
    const useRemote =
      remoteAvailable &&
      !monthlyGpuBudgetReached &&
      (preferRemoteByReliability || !preferLocalByReliability);
    return {
      provider: useRemote ? "remote" : localAvailable ? "local" : "remote",
      strategy: "expert-thinking",
      complexityScore,
      reason:
        useRemote
          ? "Auto selected remote expert reasoning for a medium-complexity request with healthy remote stats."
          : "Auto selected local expert reasoning because remote is unavailable, unreliable, or blocked by budget.",
      modelHint: "expert",
    };
  }

  return {
    provider: remoteAvailable && !monthlyGpuBudgetReached ? "remote" : "local",
    strategy: remoteAvailable && !monthlyGpuBudgetReached ? "heavy-multi-pass" : "expert-thinking",
    complexityScore,
    reason:
      remoteAvailable && !monthlyGpuBudgetReached
        ? "Auto escalated to remote heavy reasoning for a complex request."
        : "Auto kept the request local with expert reasoning because remote is unavailable or blocked by policy.",
    modelHint: remoteAvailable && !monthlyGpuBudgetReached ? "heavy" : "expert",
  };
}

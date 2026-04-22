export interface ProviderStats {
  localSuccessRate: number;
  remoteSuccessRate: number;
  localP95Ms: number;
  remoteP95Ms: number;
}

interface EventRecord {
  provider: "local" | "remote";
  ok: boolean;
  latencyMs: number;
}

export class ReliabilityTracker {
  private readonly events: EventRecord[] = [];

  record(provider: "local" | "remote", ok: boolean, latencyMs: number): void {
    this.events.push({ provider, ok, latencyMs });
    if (this.events.length > 500) this.events.shift();
  }

  snapshot(): ProviderStats {
    const local = this.events.filter((e) => e.provider === "local");
    const remote = this.events.filter((e) => e.provider === "remote");

    return {
      localSuccessRate: successRate(local),
      remoteSuccessRate: successRate(remote),
      localP95Ms: p95(local.map((e) => e.latencyMs)),
      remoteP95Ms: p95(remote.map((e) => e.latencyMs)),
    };
  }
}

function successRate(list: EventRecord[]): number {
  if (!list.length) return 1;
  const ok = list.filter((e) => e.ok).length;
  return ok / list.length;
}

function p95(values: number[]): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95));
  return sorted[idx];
}

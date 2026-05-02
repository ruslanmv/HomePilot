export class ReliabilityTracker {
    constructor() {
        this.events = [];
    }
    record(provider, ok, latencyMs) {
        this.events.push({ provider, ok, latencyMs });
        if (this.events.length > 500)
            this.events.shift();
    }
    snapshot() {
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
function successRate(list) {
    if (!list.length)
        return 1;
    const ok = list.filter((e) => e.ok).length;
    return ok / list.length;
}
function p95(values) {
    if (!values.length)
        return 0;
    const sorted = [...values].sort((a, b) => a - b);
    const idx = Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95));
    return sorted[idx];
}

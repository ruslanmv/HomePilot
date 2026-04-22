export class InMemoryEvalRecorder {
    constructor() {
        this.rows = [];
    }
    async record(sample) {
        const score = {
            groundedness: sample.response.length > 50 ? 0.75 : 0.45,
            helpfulness: sample.response.length > 120 ? 0.8 : 0.55,
            latency: sample.latencyMs < 3500 ? 0.85 : 0.55,
            overall: 0,
        };
        score.overall = Number(((score.groundedness + score.helpfulness + score.latency) / 3).toFixed(3));
        this.rows.push({ sample, score });
        return score;
    }
    async history(limit = 50) {
        return this.rows.slice(Math.max(0, this.rows.length - limit));
    }
}

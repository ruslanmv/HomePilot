export interface EvalSample {
  id: string;
  query: string;
  response: string;
  expected?: string;
  latencyMs: number;
  provider: "local" | "remote";
  strategy: "single-pass" | "expert-thinking" | "heavy-multi-pass";
}

export interface EvalScore {
  groundedness: number;
  helpfulness: number;
  latency: number;
  overall: number;
}

export interface EvalRecorder {
  record(sample: EvalSample): Promise<EvalScore>;
  history(limit?: number): Promise<Array<{ sample: EvalSample; score: EvalScore }>>;
}

export class InMemoryEvalRecorder implements EvalRecorder {
  private readonly rows: Array<{ sample: EvalSample; score: EvalScore }> = [];

  async record(sample: EvalSample): Promise<EvalScore> {
    const score: EvalScore = {
      groundedness: sample.response.length > 50 ? 0.75 : 0.45,
      helpfulness: sample.response.length > 120 ? 0.8 : 0.55,
      latency: sample.latencyMs < 3500 ? 0.85 : 0.55,
      overall: 0,
    };
    score.overall = Number(((score.groundedness + score.helpfulness + score.latency) / 3).toFixed(3));
    this.rows.push({ sample, score });
    return score;
  }

  async history(limit = 50): Promise<Array<{ sample: EvalSample; score: EvalScore }>> {
    return this.rows.slice(Math.max(0, this.rows.length - limit));
  }
}

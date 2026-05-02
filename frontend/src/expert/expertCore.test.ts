import { describe, expect, it } from "vitest";

import { ToolRegistry } from "../../../expert/frontend/src/expert/tools/registry";
import { InMemoryStore } from "../../../expert/frontend/src/expert/memory/store";
import { InMemoryEvalRecorder } from "../../../expert/frontend/src/expert/evals/harness";
import { ReliabilityTracker } from "../../../expert/frontend/src/expert/reliability/metrics";
import { resolveRoutingPolicy } from "../../../expert/frontend/src/expert/policies";
import { ExpertRouter } from "../../../expert/frontend/src/expert/router";
import type {
  InferenceRequest,
  InferenceResponse,
} from "../../../expert/frontend/src/expert/providers/local";

class FakeProvider {
  constructor(private readonly backend: "local" | "remote") {}

  async isHealthy(): Promise<boolean> {
    return true;
  }

  async chat(request: InferenceRequest): Promise<InferenceResponse> {
    const prompt = request.messages[request.messages.length - 1]?.content ?? "";
    return {
      text: `${this.backend.toUpperCase()}:${request.mode}:${prompt.slice(0, 40)}`,
      model: `${this.backend}-model`,
      backend: this.backend,
    };
  }
}

describe("expert core gaps coverage", () => {
  it("executes tool registry with budget constraints", async () => {
    const registry = new ToolRegistry();
    registry.register({
      name: "retrieval",
      description: "lookup",
      cost: 1,
      run: async (input) => ({ tool: "retrieval", ok: true, content: `R:${input}` }),
    });
    registry.register({
      name: "code_exec",
      description: "run",
      cost: 3,
      run: async (input) => ({ tool: "code_exec", ok: true, content: `C:${input}` }),
    });

    const summary = await registry.executeMany(
      [
        { tool: "retrieval", input: "docs" },
        { tool: "code_exec", input: "test" },
      ],
      { budget: 2 }
    );

    expect(summary.results).toHaveLength(2);
    expect(summary.results[0].ok).toBe(true);
    expect(summary.results[1].ok).toBe(false);
  });

  it("stores and recalls memory records", async () => {
    const memory = new InMemoryStore();
    await memory.append("s1", [
      { role: "user", content: "hello", timestamp: 1 },
      { role: "assistant", content: "hi", timestamp: 2 },
    ]);

    const rows = await memory.recall("s1", 2);
    expect(rows.map((r) => r.content)).toEqual(["hello", "hi"]);
  });

  it("records eval score and reliability metrics", async () => {
    const evals = new InMemoryEvalRecorder();
    const rel = new ReliabilityTracker();

    const score = await evals.record({
      id: "1",
      query: "q",
      response: "This is a reasonably helpful response for scoring.",
      latencyMs: 1200,
      provider: "local",
      strategy: "single-pass",
    });
    rel.record("local", true, 1000);
    rel.record("remote", false, 3000);

    expect(score.overall).toBeGreaterThan(0);
    expect((await evals.history()).length).toBe(1);
    expect(rel.snapshot().remoteSuccessRate).toBeLessThan(1);
  });

  it("routes with reliability-aware policy and executes through router", async () => {
    const decision = resolveRoutingPolicy({
      mode: "expert",
      messages: [{ role: "user", content: "design robust architecture" }],
      localAvailable: true,
      remoteAvailable: true,
      monthlyGpuBudgetReached: false,
      providerStats: {
        localSuccessRate: 1,
        remoteSuccessRate: 0.3,
        localP95Ms: 900,
        remoteP95Ms: 5000,
      },
    });

    expect(decision.provider).toBe("local");

    const router = new ExpertRouter({
      local: new FakeProvider("local") as any,
      remote: new FakeProvider("remote") as any,
    });

    const response = await router.route({
      mode: "auto",
      sessionId: "s2",
      messages: [{ role: "user", content: "please analyze this architecture" }],
    });

    expect(response.text.length).toBeGreaterThan(0);
    expect(["local", "remote"]).toContain(response.backend);
    expect(response.decision.strategy).toBeDefined();
  });
});

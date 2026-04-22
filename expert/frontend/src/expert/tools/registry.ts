import type { ToolDefinition, ToolInvocation, ToolResult, ToolRunContext } from "./types";

export interface ToolExecutionSummary {
  results: ToolResult[];
  spentBudget: number;
}

export class ToolRegistry {
  private readonly tools = new Map<string, ToolDefinition>();

  register(tool: ToolDefinition): this {
    this.tools.set(tool.name, tool);
    return this;
  }

  get(name: string): ToolDefinition | undefined {
    return this.tools.get(name);
  }

  list(): ToolDefinition[] {
    return [...this.tools.values()];
  }

  async executeMany(
    plan: ToolInvocation[],
    context: Omit<ToolRunContext, "budgetRemaining"> & { budget: number }
  ): Promise<ToolExecutionSummary> {
    const results: ToolResult[] = [];
    let budgetRemaining = context.budget;

    for (const step of plan) {
      const tool = this.get(step.tool);
      if (!tool) {
        results.push({
          tool: step.tool,
          ok: false,
          content: "Tool not registered.",
        });
        continue;
      }

      if (tool.cost > budgetRemaining) {
        results.push({
          tool: step.tool,
          ok: false,
          content: "Skipped due to tool budget limit.",
          meta: { requiredCost: tool.cost, budgetRemaining },
        });
        continue;
      }

      budgetRemaining -= tool.cost;
      const result = await tool.run(step.input, {
        sessionId: context.sessionId,
        budgetRemaining,
        signal: context.signal,
      });
      results.push(result);
    }

    return {
      results,
      spentBudget: context.budget - budgetRemaining,
    };
  }
}

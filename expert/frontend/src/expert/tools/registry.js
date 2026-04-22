export class ToolRegistry {
    constructor() {
        this.tools = new Map();
    }
    register(tool) {
        this.tools.set(tool.name, tool);
        return this;
    }
    get(name) {
        return this.tools.get(name);
    }
    list() {
        return [...this.tools.values()];
    }
    async executeMany(plan, context) {
        const results = [];
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

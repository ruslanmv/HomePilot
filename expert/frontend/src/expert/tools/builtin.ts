import type { ToolDefinition, ToolResult } from "./types";
import { ToolRegistry } from "./registry";

function ok(tool: string, content: string, meta?: Record<string, unknown>): ToolResult {
  return { tool, ok: true, content, meta };
}

export function createBuiltinToolRegistry(): ToolRegistry {
  const registry = new ToolRegistry();

  registry.register({
    name: "web_search",
    description: "Runs web search via configured MCP/search service.",
    cost: 2,
    run: async (input) =>
      ok(
        "web_search",
        `Simulated search summary for: ${input}. Connect this tool to your MCP search server for live grounded citations.`
      ),
  });

  registry.register({
    name: "retrieval",
    description: "Retrieves internal docs/knowledge from vector or indexed stores.",
    cost: 1,
    run: async (input) =>
      ok(
        "retrieval",
        `Simulated retrieval for: ${input}. Wire to your local document index (e.g., sqlite + embeddings) for production grounding.`
      ),
  });

  registry.register({
    name: "code_exec",
    description: "Executes code snippets in a sandbox and returns result summary.",
    cost: 3,
    run: async (input) =>
      ok(
        "code_exec",
        `Simulated code execution result for: ${input}. Replace with a secure sandbox runner before enabling by default.`
      ),
  });

  registry.register({
    name: "model_compare",
    description: "Compares multiple model/provider outputs and returns synthesis hints.",
    cost: 2,
    run: async (input) =>
      ok(
        "model_compare",
        `Simulated model comparison for: ${input}. Connect to your local + remote providers for real cross-model adjudication.`
      ),
  });

  return registry;
}

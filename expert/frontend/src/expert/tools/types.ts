export interface ToolRunContext {
  sessionId?: string;
  budgetRemaining: number;
  signal?: AbortSignal;
}

export interface ToolResult {
  tool: string;
  ok: boolean;
  content: string;
  meta?: Record<string, unknown>;
}

export interface ToolInvocation {
  tool: string;
  input: string;
}

export interface ToolDefinition {
  name: string;
  description: string;
  cost: number;
  run: (input: string, ctx: ToolRunContext) => Promise<ToolResult>;
}

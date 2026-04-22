export interface MemoryRecord {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
}

export interface MemoryStore {
  recall(sessionId: string, limit?: number): Promise<MemoryRecord[]>;
  append(sessionId: string, entries: MemoryRecord[]): Promise<void>;
}

export class InMemoryStore implements MemoryStore {
  private readonly data = new Map<string, MemoryRecord[]>();

  async recall(sessionId: string, limit = 8): Promise<MemoryRecord[]> {
    const rows = this.data.get(sessionId) ?? [];
    return rows.slice(Math.max(0, rows.length - limit));
  }

  async append(sessionId: string, entries: MemoryRecord[]): Promise<void> {
    const rows = this.data.get(sessionId) ?? [];
    rows.push(...entries);
    this.data.set(sessionId, rows);
  }
}

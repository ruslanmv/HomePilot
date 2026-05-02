export class InMemoryStore {
    constructor() {
        this.data = new Map();
    }
    async recall(sessionId, limit = 8) {
        const rows = this.data.get(sessionId) ?? [];
        return rows.slice(Math.max(0, rows.length - limit));
    }
    async append(sessionId, entries) {
        const rows = this.data.get(sessionId) ?? [];
        rows.push(...entries);
        this.data.set(sessionId, rows);
    }
}

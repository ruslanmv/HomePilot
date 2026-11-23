import { describe, expect, it } from "vitest";
import { STATE_LABEL, summarize } from "./DayPilotCard";

describe("DayPilotCard", () => {
  it("names every state the backend can report", () => {
    for (const s of ["connected", "offline", "stale", "needs_attention", "not_authorized"] as const) {
      expect(STATE_LABEL[s]).toBeTruthy();
    }
    expect(STATE_LABEL.needs_attention).toBe("Needs attention");
    expect(STATE_LABEL.not_authorized).toBe("Not authorized");
  });

  it("summarises only sections that are shared and enabled", () => {
    const s = summarize({
      plan: { status: "ok", focus: { title: "Write brief" } },
      tasks: { status: "not_enabled" },
      calendar: { status: "ok", conflicts: [{ first: "Sync", second: "1:1" }] },
      approvals: { status: "not_authorized" },
    });
    expect(s).toEqual({ priority: "Write brief", task: null, conflict: "Sync overlaps 1:1", approvals: null });
  });

  it("reports zero approvals as a real value, not as missing", () => {
    expect(summarize({ approvals: { status: "ok", pending: 0 } }).approvals).toBe(0);
  });
});

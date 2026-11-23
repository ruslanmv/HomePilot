import { describe, expect, it } from "vitest";
import { STRATEGIES, parseBudget } from "./EcosystemPanel";

describe("EcosystemPanel helpers", () => {
  it("treats an empty budget as no limit, never as zero", () => {
    expect(parseBudget("")).toBeNull();
    expect(parseBudget("   ")).toBeNull();
    expect(parseBudget("0")).toBe(0);
    expect(parseBudget("2.5")).toBe(2.5);
  });

  it("rejects negative and non-numeric budgets", () => {
    expect(parseBudget("-1")).toBeNull();
    expect(parseBudget("abc")).toBeNull();
  });

  it("offers every strategy the backend accepts, private mode included", () => {
    const values = STRATEGIES.map((s) => s.value);
    expect(values).toEqual([
      "hf_first", "local_first", "private_local", "lowest_cost",
      "fastest", "quality_first", "pinned", "legacy",
    ]);
    expect(new Set(values).size).toBe(values.length);
  });
});

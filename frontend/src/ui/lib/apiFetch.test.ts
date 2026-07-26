/**
 * Step-1 hotfix regression tests for the Settings API fetch guard.
 *
 * The reported "Unexpected token '<', "<!doctype "... is not valid JSON" error
 * came from parsing the SPA's index.html as JSON when a Settings API route was
 * not forwarded to the backend. fetchApiJson must turn that into an actionable
 * message and never throw a raw JSON.parse error.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchApiJson } from "./apiFetch";

function mockFetch(res: { ok?: boolean; status?: number; contentType?: string; body?: unknown }) {
  const headers = new Headers();
  if (res.contentType) headers.set("content-type", res.contentType);
  const ok = res.ok ?? true;
  const status = res.status ?? (ok ? 200 : 500);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok,
      status,
      headers,
      json: async () => {
        if (res.body === undefined) throw new SyntaxError("Unexpected token '<'");
        return res.body;
      },
    })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("fetchApiJson", () => {
  it("returns parsed JSON on a normal application/json response", async () => {
    mockFetch({ ok: true, status: 200, contentType: "application/json", body: { ok: true, providers: {} } });
    await expect(fetchApiJson("https://homepilot.ruslanmv.com/providers")).resolves.toEqual({
      ok: true,
      providers: {},
    });
  });

  it("throws an actionable deployment message when HTML is returned (SPA fallback)", async () => {
    mockFetch({ ok: true, status: 200, contentType: "text/html; charset=utf-8" });
    await expect(fetchApiJson("https://homepilot.ruslanmv.com/providers")).rejects.toThrow(
      /providers API is unavailable on this deployment/i,
    );
  });

  it("never surfaces a raw JSON parse error for an HTML body", async () => {
    mockFetch({ ok: true, status: 200, contentType: "text/html" });
    await expect(fetchApiJson("https://homepilot.ruslanmv.com/models")).rejects.not.toThrow(
      /Unexpected token/i,
    );
  });

  it("surfaces the JSON error message on a non-OK JSON response", async () => {
    mockFetch({ ok: false, status: 502, contentType: "application/json", body: { message: "cloud down" } });
    await expect(fetchApiJson("https://homepilot.ruslanmv.com/providers")).rejects.toThrow("cloud down");
  });

  it("includes the HTTP status when a non-JSON error has no body message", async () => {
    mockFetch({ ok: false, status: 404, contentType: "text/plain" });
    await expect(fetchApiJson("https://homepilot.ruslanmv.com/providers")).rejects.toThrow(/HTTP 404/);
  });
});

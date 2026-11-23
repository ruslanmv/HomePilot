import { afterEach, describe, expect, it, vi } from "vitest";
import { authFetch } from "./authFetch";

describe("authFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("sends the session token and credentials", async () => {
    const spy = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", spy);
    localStorage.setItem("homepilot_auth_token", "tok-1");
    await authFetch("/projects/p1", { headers: { "x-api-key": "k" } });
    const [, init] = spy.mock.calls[0];
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer tok-1");
    expect(new Headers(init.headers).get("x-api-key")).toBe("k");
    expect(init.credentials).toBe("include");
  });

  it("keeps an explicit Authorization header and works signed out", async () => {
    const spy = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", spy);
    localStorage.setItem("homepilot_auth_token", "tok-1");
    await authFetch("/x", { headers: { Authorization: "Bearer other" } });
    expect(new Headers(spy.mock.calls[0][1].headers).get("Authorization")).toBe("Bearer other");
    localStorage.clear();
    await authFetch("/x");
    expect(new Headers(spy.mock.calls[1][1].headers).has("Authorization")).toBe(false);
  });
});

import { describe, expect, it } from "vitest";
import { createComputeClient } from "@homepilot/compute-client";
import type { ApiClient } from "@homepilot/api-client";

/**
 * PR 3 — the compute-client admin surface. Verifies the wire seam: requests are
 * snake_case (recursively, for nested modality defaults), responses are
 * unwrapped + camelized, and DELETE routes hit the right paths.
 */

type Call = { method: string; path: string; body?: unknown };

function fakeApi(responses: Record<string, unknown>): { api: ApiClient; calls: Call[] } {
  const calls: Call[] = [];
  const reply = (path: string) => responses[path] ?? {};
  const api: ApiClient = {
    baseUrl: "http://test",
    get: async (p) => { calls.push({ method: "GET", path: p }); return reply(p) as never; },
    post: async (p, b) => { calls.push({ method: "POST", path: p, body: b }); return reply(p) as never; },
    put: async (p, b) => { calls.push({ method: "PUT", path: p, body: b }); return reply(p) as never; },
    del: async (p) => { calls.push({ method: "DELETE", path: p }); return {} as never; },
  };
  return { api, calls };
}

describe("compute-client admin", () => {
  it("lists and camelizes sources", async () => {
    const { api } = fakeApi({
      "/compute/admin/sources": { sources: [{ id: "s", name: "S", kind: "openai_compatible", base_url: "http://x", credential_ref: "r", enabled: true, execution_type: "direct" }] },
    });
    const sources = await createComputeClient(api).listComputeSources();
    expect(sources[0].baseUrl).toBe("http://x");
    expect(sources[0].credentialRef).toBe("r");
    expect(sources[0].executionType).toBe("direct");
  });

  it("sends per-model routes as snake_case", async () => {
    const { api, calls } = fakeApi({ "/compute/admin/routes": { route: {} } });
    await createComputeClient(api).upsertRoute({
      modality: "chat", modelId: "m", primaryTarget: "device:colab",
      fallbackTargets: ["local"], strategy: "pinned", privacy: "private_nodes",
    });
    const body = calls.find((c) => c.method === "POST")!.body as Record<string, unknown>;
    expect(body.model_id).toBe("m");
    expect(body.primary_target).toBe("device:colab");
    expect(body.fallback_targets).toEqual(["local"]);
  });

  it("recursively snake-cases nested modality defaults in settings", async () => {
    const { api, calls } = fakeApi({ "/compute/admin/settings": { settings: {} } });
    await createComputeClient(api).putComputeSettings({
      computeMode: "auto",
      modalityDefaults: {
        image: { modality: "image", strategy: "prefer_remote", fallbackTargets: ["local"], privacy: "private_nodes" },
      },
    });
    const body = calls.find((c) => c.method === "PUT")!.body as Record<string, unknown>;
    expect(body.compute_mode).toBe("auto");
    const md = body.modality_defaults as Record<string, Record<string, unknown>>;
    expect(md.image.fallback_targets).toEqual(["local"]);
  });

  it("resolveRoute passes model_id and returns the plan", async () => {
    const { api, calls } = fakeApi({
      "/compute/admin/resolve?modality=chat&model_id=m": { modality: "chat", model_id: "m", matched: "route", compute_mode: "local", targets: ["device:colab", "local"] },
    });
    const plan = await createComputeClient(api).resolveRoute("chat", "m");
    expect(plan.matched).toBe("route");
    expect(plan.targets).toEqual(["device:colab", "local"]);
    expect(calls[0].path).toContain("model_id=m");
  });

  it("tests a source and reads local resources", async () => {
    const { api, calls } = fakeApi({
      "/compute/admin/sources/oa/test": { ok: true, reason: "Reachable." },
      "/v1/system/resources": { gpus: [{ available: true, name: "RTX 4090", vram_total_mb: 24576, used_percent: 30 }], cpu: { percent: 12 }, ram: { percent: 40 } },
    });
    const client = createComputeClient(api);
    const t = await client.testComputeSource("oa");
    expect(t.ok).toBe(true);
    expect(calls[0]).toMatchObject({ method: "POST", path: "/compute/admin/sources/oa/test" });
    const res = await client.getLocalResources();
    expect(res.gpus[0].vramTotalMb).toBe(24576);   // snake→camel
    expect(res.gpus[0].usedPercent).toBe(30);
  });

  it("syncs from cloud via POST /compute/admin/sync", async () => {
    const { api, calls } = fakeApi({
      "/compute/admin/sync": { ok: true, linked: true, devices: 2, models: 5, source_id: "ollabridge-cloud" },
    });
    const r = await createComputeClient(api).syncFromCloud();
    expect(r).toMatchObject({ linked: true, devices: 2, models: 5 });
    expect(calls[0]).toMatchObject({ method: "POST", path: "/compute/admin/sync" });
  });

  it("deletes sources and routes at the right paths", async () => {
    const { api, calls } = fakeApi({});
    const client = createComputeClient(api);
    await client.deleteComputeSource("s 1");
    await client.deleteRoute("chat", "m/x");
    expect(calls[0]).toMatchObject({ method: "DELETE", path: "/compute/admin/sources/s%201" });
    expect(calls[1]).toMatchObject({ method: "DELETE", path: "/compute/admin/routes/chat/m%2Fx" });
  });
});

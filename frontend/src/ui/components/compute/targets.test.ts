import { describe, expect, it } from "vitest";
import { buildTargetOptions, targetLabel } from "./targets";
import type { ComputeDevice, ComputeSource, ModelManifest } from "@homepilot/types";

const device = (over: Partial<ComputeDevice>): ComputeDevice => ({
  id: "d",
  sourceId: "ob",
  name: "Colab T4",
  online: true,
  ephemeral: true,
  capacity: 1,
  activeJobs: 0,
  ...over,
});

describe("targetLabel", () => {
  it("maps well-known and dynamic targets to labels", () => {
    const sources = [{ id: "oa", name: "My vLLM" } as ComputeSource];
    const devices = [device({ id: "colab", name: "Colab T4" })];
    expect(targetLabel("local")).toBe("This PC");
    expect(targetLabel("ollabridge_cloud")).toContain("OllaBridge Cloud");
    expect(targetLabel("device:colab", sources, devices)).toBe("Colab T4");
    expect(targetLabel("source:oa", sources, devices)).toBe("My vLLM");
  });
});

describe("buildTargetOptions", () => {
  it("always offers Auto and This PC first", () => {
    const opts = buildTargetOptions({ modality: "chat", sources: [], devices: [], manifests: [] });
    expect(opts[0].label).toBe("Auto");
    expect(opts[1].target).toBe("local");
  });

  it("disables an offline device with a reason", () => {
    const opts = buildTargetOptions({
      modality: "chat",
      modelId: "m",
      sources: [],
      devices: [device({ id: "colab", online: false, onlineEffective: false })],
      manifests: [],
    });
    const colab = opts.find((o) => o.target === "device:colab")!;
    expect(colab.disabled).toBe(true);
    expect(colab.reason).toBe("Offline");
  });

  it("disables a device without enough VRAM", () => {
    const manifests: ModelManifest[] = [
      { id: "big", runtime: "comfyui", capabilities: ["image"], deviceIds: ["colab"], minimumVramMb: 20000 },
    ];
    const opts = buildTargetOptions({
      modality: "image",
      modelId: "big",
      sources: [],
      devices: [device({ id: "colab", vramMb: 8000 })],
      manifests,
    });
    const colab = opts.find((o) => o.target === "device:colab")!;
    expect(colab.disabled).toBe(true);
    expect(colab.reason).toContain("GB VRAM");
  });

  it("marks an OpenAI-compatible source chat-only for image requests", () => {
    const sources: ComputeSource[] = [
      { id: "oa", name: "vLLM", kind: "openai_compatible", enabled: true, executionType: "direct" },
    ];
    const opts = buildTargetOptions({ modality: "image", sources, devices: [], manifests: [] });
    const oa = opts.find((o) => o.target === "source:oa")!;
    expect(oa.disabled).toBe(true);
    expect(oa.reason).toBe("Chat only");
  });
});

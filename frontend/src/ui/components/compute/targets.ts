// Shared helpers for the Compute Sources & Routing UI — turning routing target
// strings (see backend app/compute/policies.py) into human labels and building
// the per-model execution options. Kept framework-free so components stay thin.

import type { ComputeDevice, ComputeSource, Modality, ModelManifest } from "@homepilot/types";

export const MODALITIES: Modality[] = ["chat", "multimodal", "image", "video", "edit"];

/** A selectable execution target for a model, with disabled reasoning. */
export interface TargetOption {
  target: string;
  label: string;
  detail?: string;
  disabled?: boolean;
  reason?: string;
}

const MODALITY_CAPABILITY: Record<Modality, string> = {
  chat: "chat",
  multimodal: "multimodal",
  image: "image",
  video: "video",
  edit: "edit",
};

/** Human label for a target string. Falls back to the raw string. */
export function targetLabel(
  target: string,
  sources: ComputeSource[] = [],
  devices: ComputeDevice[] = [],
): string {
  if (target === "local") return "This PC";
  if (target === "ollabridge_cloud" || target === "ollabridge:any")
    return "OllaBridge Cloud (any node)";
  if (target.startsWith("device:")) {
    const id = target.slice("device:".length);
    return devices.find((d) => d.id === id)?.name || `Device ${id}`;
  }
  if (target.startsWith("source:")) {
    const id = target.slice("source:".length);
    return sources.find((s) => s.id === id)?.name || `Source ${id}`;
  }
  if (target.startsWith("provider:")) return `Provider ${target.slice("provider:".length)}`;
  return target;
}

/**
 * Build the execution options for a (model, modality). Always offers Auto and
 * This PC; adds each online device and enabled remote source, disabling any that
 * can't serve the request and explaining why (the design's "Unavailable: …").
 */
export function buildTargetOptions(args: {
  modality: Modality;
  modelId?: string;
  sources: ComputeSource[];
  devices: ComputeDevice[];
  manifests: ModelManifest[];
}): TargetOption[] {
  const { modality, modelId, sources, devices, manifests } = args;
  const manifest = modelId ? manifests.find((m) => m.id === modelId) : undefined;
  const need = MODALITY_CAPABILITY[modality];

  const options: TargetOption[] = [
    { target: "", label: "Auto", detail: "Use the routing policy" },
    { target: "local", label: "This PC", detail: "Private GPU" },
  ];

  for (const d of devices) {
    const online = d.onlineEffective ?? d.online;
    const opt: TargetOption = {
      target: `device:${d.id}`,
      label: d.name || d.id,
      detail: [d.gpuName, d.vramMb ? `${Math.round(d.vramMb / 1024)} GB` : null]
        .filter(Boolean)
        .join(" · "),
    };
    if (!online) {
      opt.disabled = true;
      opt.reason = "Offline";
    } else if (manifest && manifest.deviceIds.length && !manifest.deviceIds.includes(d.id)) {
      opt.disabled = true;
      opt.reason = "Model not installed";
    } else if (manifest && need && manifest.capabilities.length && !manifest.capabilities.includes(need as never)) {
      opt.disabled = true;
      opt.reason = `No ${modality} capability`;
    } else if (
      manifest?.minimumVramMb &&
      d.vramMb != null &&
      d.vramMb < manifest.minimumVramMb
    ) {
      opt.disabled = true;
      opt.reason = `Requires ${Math.round(manifest.minimumVramMb / 1024)} GB VRAM`;
    }
    options.push(opt);
  }

  for (const s of sources) {
    if (s.kind === "local") continue; // already represented by "This PC"
    const opt: TargetOption = {
      target: `source:${s.id}`,
      label: s.name || s.id,
      detail: s.kind,
    };
    if (!s.enabled) {
      opt.disabled = true;
      opt.reason = "Disabled";
    } else if (
      (s.kind === "openai_compatible" || s.kind === "huggingface") &&
      modality !== "chat" &&
      modality !== "multimodal"
    ) {
      opt.disabled = true;
      opt.reason = "Chat only";
    }
    options.push(opt);
  }

  return options;
}

// @homepilot/core — platform-pure domain logic shared by every app.
//
// Pure functions and the analytics taxonomy: identical behaviour on web,
// desktop, and mobile. No I/O, no platform APIs.

import type { ComputeMode } from "@homepilot/types";

export interface AnalyticsEvent {
  name: string;
  props?: Record<string, unknown>;
}

export const analytics = {
  imageRequested: (model: string, mode: ComputeMode): AnalyticsEvent => ({
    name: "image_requested",
    props: { model, mode },
  }),
  jobCompleted: (task: string, gpuSeconds?: number): AnalyticsEvent => ({
    name: "job_completed",
    props: { task, gpuSeconds },
  }),
  deviceShared: (scope: "family" | "org"): AnalyticsEvent => ({
    name: "device_shared",
    props: { scope },
  }),
};

/** Compose a generation prompt from structured parts (identical across apps). */
export function composePrompt(parts: {
  subject: string;
  style?: string;
  details?: string[];
}): string {
  return [parts.subject, parts.style, ...(parts.details ?? [])]
    .filter((p): p is string => Boolean(p))
    .join(", ");
}

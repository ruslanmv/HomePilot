// @homepilot/config — shared constants + client feature flags (platform-pure).
//
// The API base URL is intentionally NOT read here: that is platform-specific
// (e.g. import.meta.env / window.location on web, app config on mobile). Each
// app resolves its base URL and injects it into @homepilot/api-client's
// createClient(). This file holds only values identical on every platform.

export const ENDPOINTS = {
  chat: "/v1/chat/completions",
  jobs: "/v1/jobs",
  imageGenerations: "/v1/images/generations",
  imageEdits: "/v1/images/edits",
  videoGenerations: "/v1/videos/generations",
  computeStatus: "/compute/status",
  computeMode: "/compute/mode",
  devices: "/v1/devices",
  pairStart: "/device/start",
  pairPoll: "/device/poll",
} as const;

export type ComputeModeDefault = "local" | "ollabridge_cloud" | "auto";

export interface FeatureFlags {
  /** Wave B / Batch 8 — family/org GPU sharing tiers. Default off. */
  sharingTiers: boolean;
  /** Default compute mode the client requests. */
  computeModeDefault: ComputeModeDefault;
}

export const DEFAULT_FLAGS: FeatureFlags = {
  sharingTiers: false,
  computeModeDefault: "auto",
};

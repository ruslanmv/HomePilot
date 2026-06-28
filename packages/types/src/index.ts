// @homepilot/types — shared DTOs (the single source of truth for all apps).
//
// Pure declarations: no runtime, no platform dependency. Mirrors the contracts
// in ../../ollabridge-cloud/docs/contracts/jobs-protocol.md and HomePilot's
// /compute/status. Keep snake_case ⇄ camelCase mapping in api-client/core, not
// here — this file is the canonical camelCase shape every app codes against.

export type Task = "image" | "video" | "edit" | "chat";
export type JobStatus =
  | "queued"
  | "routing"
  | "running"
  | "succeeded"
  | "failed"
  | "canceled";

export interface Artifact {
  url: string;
  contentType: string;
  seed?: number;
  width?: number;
  height?: number;
}

export interface JobError {
  code: string;
  message: string;
}

export interface Job {
  id: string;
  status: JobStatus;
  task: Task;
  model?: string;
  progress: number;
  output?: { artifacts: Artifact[] };
  error?: JobError;
  selectedDeviceId?: string;
  gpuSeconds?: number;
}

export interface JobEvent {
  kind: string;
  progress?: number | null;
  message?: string | null;
}

// --- Compute status (HomePilot Batch 6 /compute/status) ---
export type ComputeMode = "local" | "ollabridge_cloud" | "auto";

export interface ComputeStatus {
  mode: ComputeMode;
  configuredMode: ComputeMode;
  localGpuAvailable: boolean;
  cloudConfigured: boolean;
  cloudReachable: boolean;
  label: string;
  message: string;
  // MB6 — cloud-GPU burst ("works when your PC is off")
  premium?: boolean;
  burst?: boolean;
  burstGated?: boolean;
}

// --- Devices & sharing (Wave B / Batch 8) ---
export interface Device {
  id: string;
  name: string;
  platform?: string;
  online?: boolean;
  gpuName?: string;
  vramMb?: number;
}

export interface SupplierPolicy {
  deviceId: string;
  allowMyAccount: boolean;
  allowFamily: boolean;
  allowOrg: boolean;
  allowPublicJobs: boolean;
  paused: boolean;
}

// --- Product domain ---
export interface Persona {
  id: string;
  name: string;
  description?: string;
  avatarUrl?: string;
}

export interface CreditsWallet {
  balance: number;
  currency: string;
}

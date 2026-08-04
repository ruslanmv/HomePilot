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

// --- Compute Sources & Routing (HomePilot PR 2/3 /compute/admin/*) ---
// camelCase mirror of app/compute/schemas.py. The wire is snake_case; the
// compute-client normalizes both directions so every app codes against these.

export type SourceKind =
  | "local"
  | "ollabridge"
  | "openai_compatible"
  | "comfyui"
  | "huggingface"
  | "runpod"
  | "custom";
export type ExecutionType = "local" | "direct" | "relay";
export type ComputeRuntime = "ollama" | "vllm" | "comfyui" | "openai_api";
export type Capability = "chat" | "vision" | "image" | "video" | "edit" | "multimodal";
export type Modality = "chat" | "multimodal" | "image" | "video" | "edit";
export type RouteStrategy = "pinned" | "prefer_local" | "prefer_remote" | "lowest_cost";
export type RoutePrivacy = "local_only" | "private_nodes" | "hosted_allowed";

export interface ComputeSource {
  id: string;
  name: string;
  kind: SourceKind;
  baseUrl?: string;
  /** Opaque handle into the server-side secret store — never the secret itself. */
  credentialRef?: string;
  enabled: boolean;
  executionType: ExecutionType;
  meta?: Record<string, unknown>;
}

/** Richer than the Batch-8 `Device`: carries capacity/heartbeat for routing. */
export interface ComputeDevice {
  id: string;
  sourceId: string;
  name: string;
  online: boolean;
  ephemeral: boolean;
  gpuName?: string;
  vramMb?: number;
  utilization?: number;
  capacity: number;
  activeJobs: number;
  lastHeartbeat?: number;
  /** Server-computed: online AND heartbeat within TTL. */
  onlineEffective?: boolean;
  heartbeatAgeS?: number;
}

export interface ModelManifest {
  id: string;
  runtime: ComputeRuntime;
  capabilities: Capability[];
  deviceIds: string[];
  digest?: string;
  minimumVramMb?: number;
  workflowVersion?: string;
}

export interface ModelRoute {
  modality: Modality;
  modelId: string;
  primaryTarget: string;
  fallbackTargets: string[];
  strategy: RouteStrategy;
  maxQueueSeconds?: number;
  maxCostUsd?: number;
  privacy: RoutePrivacy;
}

export interface ModalityDefault {
  modality: Modality;
  strategy: RouteStrategy;
  target?: string;
  fallbackTargets: string[];
  privacy: RoutePrivacy;
}

export interface ComputeSettings {
  computeMode: ComputeMode;
  burstRequiresPremium: boolean;
  premiumEnabled: boolean;
  cloudUrl?: string;
  cloudImageModel: string;
  cloudVideoModel: string;
  deviceHeartbeatTtlS: number;
  modalityDefaults: Record<string, ModalityDefault>;
  /** PR 5 — per-request USD budget (null = no cap) + a timestamped price map. */
  maxCostUsdPerRequest?: number | null;
  costCatalog?: Record<string, unknown>;
}

/** A local GPU from /v1/system/resources (multi-GPU aware). */
export interface LocalGpu {
  index?: number;
  available: boolean;
  name?: string | null;
  vramTotalMb?: number | null;
  vramUsedMb?: number | null;
  usedPercent?: number | null;
  utilizationPercent?: number | null;
  temperatureC?: number | null;
  status?: string;
}

/** Local machine capacity (GPUs + CPU + RAM) for the Resources panel. */
export interface LocalResources {
  gpu: LocalGpu;
  gpus: LocalGpu[];
  cpu: { name?: string | null; physicalCores?: number; logicalCores?: number; percent?: number };
  ram: { totalMb?: number; usedMb?: number; percent?: number };
}

/** Result of probing a source's reachability. */
export interface SourceTestResult {
  ok: boolean;
  reason?: string;
}

/** Result of syncing paired devices + models from OllaBridge Cloud. */
export interface CloudSyncResult {
  ok: boolean;
  linked: boolean;
  devices: number;
  models: number;
  reason?: string;
  sourceId?: string;
}

/** Timestamped, per-target cost estimate (provider prices aren't hardcoded). */
export interface CostEstimate {
  target: string;
  currency: string;
  estimatedUsd?: number | null;
  perUnit?: string;
  asOf?: string;
  note?: string;
}

/** A cost estimate as it appears in a route explanation. */
export interface RouteCost extends CostEstimate {
  overBudget: boolean;
  selected: boolean;
}

/** What `/compute/admin/resolve` returns — how a request would be routed. */
export interface RouteResolution {
  modality: Modality;
  modelId?: string;
  matched: "route" | "modality_default" | "global_default";
  computeMode: ComputeMode;
  targets: string[];
  budgetUsd?: number | null;
  costs?: RouteCost[];
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

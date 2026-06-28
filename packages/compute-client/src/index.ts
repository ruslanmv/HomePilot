// @homepilot/compute-client — jobs, progress, devices, and sharing policy.
//
// THE single source of truth for Wave A/B compute behaviour. Web, desktop, and
// mobile all build the same client and call the same methods — so a fix here
// (e.g. job-polling) reaches every app on its next build, with no duplication.
//
// Transport for progress events is an injected port (SSE on web/desktop, a
// polyfill or polling on mobile), keeping this module platform-pure.

import type { ApiClient } from "@homepilot/api-client";
import type { Device, Job, JobEvent, ComputeStatus, SupplierPolicy } from "@homepilot/types";

export interface ImageJobInput {
  model?: string;
  prompt: string;
  negativePrompt?: string;
  width?: number;
  height?: number;
  steps?: number;
  seed?: number;
}

export interface VideoJobInput {
  model?: string;
  prompt?: string;
  image?: string;
}

/** Port: each app injects its event transport (SSE / polyfill / polling). */
export interface EventTransport {
  subscribe(url: string, onEvent: (event: JobEvent) => void): () => void;
}

export interface ComputeClient {
  // Wave A — generation jobs
  createImageJob(input: ImageJobInput): Promise<Job>;
  createVideoJob(input: VideoJobInput): Promise<Job>;
  getJobStatus(id: string): Promise<Job>;
  subscribeToJobEvents(
    id: string,
    onEvent: (event: JobEvent) => void,
    transport: EventTransport,
  ): () => void;
  getComputeStatus(): Promise<ComputeStatus>;
  // Wave B / Batch 8 — device sharing
  listUserDevices(): Promise<Device[]>;
  getDevicePolicy(deviceId: string): Promise<SupplierPolicy>;
  setDevicePolicy(deviceId: string, policy: Partial<SupplierPolicy>): Promise<SupplierPolicy>;
}

export function createComputeClient(api: ApiClient): ComputeClient {
  // The HTTP API speaks snake_case; @homepilot/types is camelCase. Normalize
  // responses in one place so every app gets correctly-shaped objects, while
  // requests are snake_case via toSnake(). This is the value of the SSOT: the
  // wire/representation seam lives here, not duplicated per app.
  const get = <T>(path: string) => api.get<unknown>(path).then((r) => camelize(r) as T);
  const post = <T>(path: string, body?: unknown) =>
    api.post<unknown>(path, body).then((r) => camelize(r) as T);
  const put = <T>(path: string, body?: unknown) =>
    api.put<unknown>(path, body).then((r) => camelize(r) as T);

  return {
    createImageJob: (input) => post<Job>("/v1/images/generations", toSnake(input)),
    createVideoJob: (input) => post<Job>("/v1/videos/generations", toSnake(input)),
    getJobStatus: (id) => get<Job>(`/v1/jobs/${id}`),
    subscribeToJobEvents: (id, onEvent, transport) =>
      transport.subscribe(`${api.baseUrl}/v1/jobs/${id}/events`, onEvent),
    getComputeStatus: () => get<ComputeStatus>("/compute/status"),
    listUserDevices: () => get<Device[]>("/v1/devices"),
    getDevicePolicy: (deviceId) => get<SupplierPolicy>(`/v1/devices/${deviceId}/policy`),
    setDevicePolicy: (deviceId, policy) =>
      put<SupplierPolicy>(`/v1/devices/${deviceId}/policy`, toSnake(policy)),
  };
}

const toCamel = (key: string): string =>
  key.replace(/_([a-z0-9])/g, (_m, c: string) => c.toUpperCase());

/** Recursively rewrite object keys snake_case → camelCase (values untouched). */
function camelize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(camelize);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[toCamel(k)] = camelize(v);
    }
    return out;
  }
  return value;
}

/** Shallow camelCase → snake_case for request bodies (the API speaks snake). */
function toSnake(obj: object): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj)) {
    if (value === undefined) continue;
    out[key.replace(/[A-Z]/g, (m) => `_${m.toLowerCase()}`)] = value;
  }
  return out;
}

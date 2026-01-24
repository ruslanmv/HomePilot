/**
 * Creator Studio API helpers.
 *
 * This module is used by Studio pages and expects CreatorStudioHost to provide
 * backendUrl + apiKey via the studio store.
 */

import { getStudioConfig } from "../stores/studioStore";

type FetchOpts = RequestInit & { signal?: AbortSignal };

export async function studioFetch<T>(path: string, opts: FetchOpts = {}): Promise<T> {
  const { backendUrl, apiKey } = getStudioConfig();
  const url = `${backendUrl}${path}`;

  const headers: Record<string, string> = {
    ...(opts.headers as any),
    "Content-Type": "application/json",
  };

  if (apiKey) headers["Authorization"] = `Bearer ${apiKey}`;

  const r = await fetch(url, { ...opts, headers });
  // Some backends may return empty bodies (e.g., 204). Handle safely.
  const text = await r.text();
  const j = text ? JSON.parse(text) : {};
  if (!r.ok) throw new Error((j as any)?.detail || (j as any)?.error || `HTTP ${r.status}`);
  return j as T;
}

export function studioGet<T>(path: string, opts: FetchOpts = {}) {
  return studioFetch<T>(path, { ...opts, method: "GET" });
}

export function studioPost<T>(path: string, body: any, opts: FetchOpts = {}) {
  return studioFetch<T>(path, { ...opts, method: "POST", body: JSON.stringify(body) });
}

export function studioPatch<T>(path: string, body?: any, opts: FetchOpts = {}) {
  return studioFetch<T>(path, { ...opts, method: "PATCH", body: body ? JSON.stringify(body) : undefined });
}

export function studioDelete<T>(path: string, opts: FetchOpts = {}) {
  return studioFetch<T>(path, { ...opts, method: "DELETE" });
}

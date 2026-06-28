import { createClient } from '@homepilot/api-client';
import { createComputeClient } from '@homepilot/compute-client';

import { secureTokenStorage } from './storage';

// Mobile has no window.location, so the backend base URL is user-configured
// (Account tab) and persisted in secure storage.
export const DEFAULT_BASE_URL = 'http://localhost:8000';

// The compute backend (image jobs, devices, sharing) is OllaBridge Cloud. The
// Connect screen defaults to this so a fresh install only needs an access token.
export const DEFAULT_CLOUD_URL = 'https://ruslanmv-ollabridge.hf.space';

let baseUrl = DEFAULT_BASE_URL;

export function setBaseUrl(url: string): void {
  baseUrl = url.replace(/\/+$/, '');
}

export function getBaseUrl(): string {
  return baseUrl;
}

// Built fresh per call (cheap) so a base-URL change in Account takes effect
// without an app restart. Sends BOTH headers so one credential works against
// either backend: OllaBridge Cloud resolves the caller via `Authorization:
// Bearer` (JWT / `ob_` API key); the HomePilot backend also accepts `X-API-Key`.
// (Previously this sent X-API-Key only, which the Cloud never reads → 401.)
export function getHttp() {
  return createClient({
    baseUrl,
    tokenProvider: { getToken: () => secureTokenStorage.get() },
    authHeader: (token) => ({ Authorization: `Bearer ${token}`, 'X-API-Key': token }),
  });
}

export function getComputeClient() {
  return createComputeClient(getHttp());
}

export function toAbsoluteUrl(url: string): string {
  return url.startsWith('http') ? url : `${baseUrl}${url}`;
}

import axios from "axios";

import { getDefaultBackendUrl } from "./lib/backendUrl";
import { createClient } from "@homepilot/api-client";
import { createComputeClient } from "@homepilot/compute-client";

// Resolve at module load. Priority:
//   1. VITE_API_URL build-time env (used in custom builds)
//   2. window.location.origin when served from a non-dev host (HF Space, Docker)
//   3. http://localhost:8000 for local dev only
const API_URL = getDefaultBackendUrl();

// Optional API key stored in localStorage (set in UI if you enable backend API_KEY)
export function getApiKey() {
  return localStorage.getItem("homepilot_api_key") || "";
}

export const api = axios.create({
  baseURL: API_URL,
  timeout: 180000,
});

api.interceptors.request.use((config) => {
  const k = getApiKey();
  if (k) config.headers["X-API-Key"] = k;
  return config;
});

// ── Shared, cross-platform clients (single source of truth) ────────────────
// First M2-extract runtime import: the fetch-based @homepilot/api-client +
// @homepilot/compute-client, wired with the SAME base URL and X-API-Key auth as
// the axios `api` above. The axios instance is intentionally left untouched —
// its 16 call sites rely on axios response semantics — and its call sites are
// strangled onto `http` / `computeClient` one PR at a time. New code should use
// these; they behave identically on web, desktop, and mobile.
export const http = createClient({
  baseUrl: API_URL,
  tokenProvider: { getToken: () => getApiKey() || null },
  authHeader: (key) => ({ "X-API-Key": key }),
});

export const computeClient = createComputeClient(http);

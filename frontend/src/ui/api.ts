import axios from "axios";

import { getDefaultBackendUrl } from "./lib/backendUrl";

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

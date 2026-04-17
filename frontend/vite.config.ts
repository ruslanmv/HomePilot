import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The Vite dev server runs on :3000 but the HomePilot backend lives on
// :8000. Anything the frontend calls with a relative path ("/v1/...",
// "/files/...", "/studio/...") must be proxied through to the backend
// — otherwise Vite's SPA fallback returns index.html and JSON.parse
// chokes with  "Unexpected token '<', \"<!doctype \"...".
//
// The resolveBackendUrl() helper in src/ui/lib/backendUrl.ts already
// points fetch() calls at http://localhost:8000 when the dev host +
// port are recognized. These proxy entries are the safety net for any
// code path that still uses a bare relative URL.
const BACKEND = process.env.HOMEPILOT_BACKEND_URL || 'http://localhost:8000'
const API_PREFIXES = [
  '/v1',
  '/files',
  '/studio',
  '/conversations',
  '/projects',
  '/personas',
  '/media',
  '/health',
  '/image-presets',
  '/comfy',
] as const

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: true,
    proxy: Object.fromEntries(
      API_PREFIXES.map((p) => [p, { target: BACKEND, changeOrigin: true }]),
    ),
  },
})

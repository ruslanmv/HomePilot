import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Wave B monorepo: the @homepilot/* shared packages live in ../packages and are
// consumed as build-time source aliases (not npm workspace deps), so the
// standalone frontend build/Docker image is unaffected except for copying
// packages/ into the build context. Matches the tsconfig "paths" entry.
const FRONTEND_DIR = path.dirname(fileURLToPath(import.meta.url))
const PACKAGES_DIR = path.resolve(FRONTEND_DIR, '../packages')
const SETTINGS_WITH_MEDIA = path.resolve(FRONTEND_DIR, 'src/ui/SettingsPanelWithMedia.tsx')

// Redirect only the real App.tsx Settings import through the additive media
// wrapper. The wrapper itself imports `./SettingsPanel` normally, so TypeScript
// resolves back to the canonical SettingsPanel.tsx with no recursion.
const settingsMediaResolver = {
  name: 'homepilot-settings-media',
  enforce: 'pre' as const,
  resolveId(source: string, importer?: string) {
    const normalizedImporter = importer?.replace(/\\/g, '/') || ''
    if (source === './SettingsPanel' && normalizedImporter.endsWith('/src/ui/App.tsx')) {
      return SETTINGS_WITH_MEDIA
    }
    return null
  },
}

// The Vite dev server runs on :3000 but the HomePilot backend lives on
// :8000. Anything the frontend calls with a relative path must be
// proxied through to the backend — otherwise Vite's SPA fallback
// returns index.html and JSON.parse chokes with
//   "Unexpected token '<', \"<!doctype \"...".
//
// resolveBackendUrl() in src/ui/lib/backendUrl.ts already points fetch()
// calls at http://localhost:8000 when the current host + port are a
// recognized dev pair. These proxy entries are the safety net for any
// code path that still uses a bare relative URL (Studio, Animate, Enhance
// and friends all have call sites like `fetch('/story/sessions/list')`
// or `${base}/video-presets` where `base` can resolve to the Vite origin
// if a stale localStorage override is set).
//
// The list is the union of every top-level path segment registered in
// backend/app/**/*.py with @app.get/post/patch/delete or @router.*.
// Keep in sync if you add a new top-level route.
const BACKEND = process.env.HOMEPILOT_BACKEND_URL || 'http://localhost:8000'
const API_PREFIXES = [
  // core chat + media + upload
  '/v1', '/api', '/chat', '/conversations', '/projects', '/files',
  '/upload', '/media', '/health', '/models', '/model-catalog',
  // creator + play story
  '/studio', '/story', '/game', '/episodes', '/genres',
  // image + video generation
  '/image', '/image-presets', '/video-presets', '/comfy',
  '/civitai', '/providers',
  // editing + enhance + avatar pipeline
  '/edit', '/enhance', '/face', '/fullbody', '/background', '/avatar', '/avatars',
  // personas + library + settings
  '/persona', '/personas', '/library', '/catalog', '/settings',
  // agentic + teams + MCP gateway
  '/a2a', '/agentic', '/teams', '/inventory', '/mcp',
  // misc helpers
  '/auto-detect', '/capabilities', '/compatibility', '/download',
  '/connect', '/disconnect', '/active', '/installed', '/invoke',
  '/card', '/context-block',
] as const

export default defineConfig({
  plugins: [settingsMediaResolver, react()],
  // Vite's default resolve.extensions puts .jsx BEFORE .tsx, so a bare
  // import like ``./ui/App`` (from main.tsx) silently picks the stale
  // App.jsx mirror over the canonical App.tsx. That's how the Expert
  // selector pill went missing on fresh builds — every edit landed in
  // .tsx but Vite was bundling the .jsx shadow. Flip the order until
  // the cleanup plan finishes removing the duplicate source tree. Once
  // the mirrors are gone this override becomes a no-op.
  resolve: {
    alias: [
      { find: /^@homepilot\/(.*)$/, replacement: `${PACKAGES_DIR}/$1/src` },
    ],
    extensions: ['.tsx', '.ts', '.mts', '.jsx', '.js', '.mjs', '.json'],
  },
  server: {
    port: 3000,
    host: true,
    proxy: Object.fromEntries(
      API_PREFIXES.map((p) => [
        p,
        { target: BACKEND, changeOrigin: true, ws: true },
      ]),
    ),
  },
})

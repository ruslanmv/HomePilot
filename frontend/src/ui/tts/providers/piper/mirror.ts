/**
 * Piper voice-model source resolution.
 *
 * Strategy (per product decision):
 *   1. PRIMARY  — upstream source used by @mintplex-labs/piper-tts-web,
 *      which fetches from HuggingFace `rhasspy/piper-voices`. This is
 *      the native path; we pass NO baseUrl on the first attempt so the
 *      library's own default kicks in.
 *   2. FALLBACK — ruslanmv/hp-piper-voices on HuggingFace, used only
 *      when the upstream fetch fails (network error, 4xx/5xx from the
 *      primary CDN). This keeps voice models reachable when rhasspy's
 *      bucket is down or rate-limited.
 *
 * The fallback URL can be overridden at build time via
 *   VITE_PIPER_FALLBACK_BASE_URL
 * so enterprise installs can point at an intranet mirror.
 */

/** HuggingFace "resolve/main" serves raw file bytes (no JSON wrapper)
 *  so the upstream WASM library can fetch ONNX + .onnx.json directly. */
export const DEFAULT_FALLBACK_BASE_URL =
  'https://huggingface.co/ruslanmv/hp-piper-voices/resolve/main'

export function getFallbackBaseUrl(): string {
  // Vite exposes import.meta.env at build time; guard with a defensive
  // read so this file works in Node test contexts too.
  try {
    const env = (import.meta as any)?.env
    const override = env?.VITE_PIPER_FALLBACK_BASE_URL
    if (typeof override === 'string' && override.trim()) return override.trim()
  } catch {
    // ignore
  }
  return DEFAULT_FALLBACK_BASE_URL
}

/** Heuristic: is this error likely a network / CDN problem (as opposed
 *  to, say, an ONNX runtime error for a malformed voice id)? We use it
 *  to decide whether the mirror fallback is worth trying. */
export function isNetworkyError(err: unknown): boolean {
  const msg = String((err as any)?.message || err || '').toLowerCase()
  if (!msg) return false
  // Fetch errors typically surface as TypeError with these substrings;
  // 4xx/5xx surface via the library's own error messages.
  return (
    msg.includes('failed to fetch') ||
    msg.includes('network') ||
    msg.includes('load failed') ||
    msg.includes('status 5') ||    // HTTP 5xx
    msg.includes('status: 5') ||
    msg.includes('http 5') ||
    msg.includes('status 404') ||
    msg.includes('404') ||
    msg.includes('typeerror')
  )
}

/**
 * piperTts — in-browser TTS via Piper WASM.
 *
 * Ported from ruslanmv/3D-Avatar-Chatbot/src/tts/PiperWasmTTSProvider.js
 * (SHA 727afe7c23286b3386894614603459dfe45cf257) to an ESM TypeScript
 * module so it can be used from React / Vite / TS without the IIFE
 * + window-global pattern the chatbot uses.
 *
 * Key additions over the chatbot's adapter:
 *   - `synthesizeToBlob(text, opts)` returns the WAV blob WITHOUT playing
 *     it. This is what the Creator Studio export wizard needs so it can
 *     upload the audio to the backend for mux-in during render.
 *   - `speak(text, opts)` keeps the classic play-through-speakers path
 *     for the wizard's Preview button.
 *
 * Behavior preserved from the original:
 *   - Module loaded on demand via dynamic `import()` of the jsDelivr CDN
 *     URL (avoids adding an npm dep + shipping WASM in the bundle).
 *   - ONNX models fetched on first use by `@mintplex-labs/piper-tts-web`
 *     and cached in the browser's OPFS store, keyed by voice id.
 *   - TtsSession singleton reset when the active voice changes so a new
 *     ONNX model actually loads.
 *   - Automatic OPFS quota-exceeded recovery via `flush()` + retry.
 *   - ONNX runtime `OrtRun` errors (out-of-vocab phonemes etc.) fall
 *     back to the default English voice and log the original voice id.
 */

import { DEFAULT_PIPER_VOICE_ID, PIPER_VOICES, type PiperVoice } from './piperVoices'

const CDN_URL =
  'https://cdn.jsdelivr.net/npm/@mintplex-labs/piper-tts-web@1.0.4/dist/piper-tts-web.js'

const STORAGE_VOICE_KEY = 'homepilot_piper_voice'

/** Shape of the upstream `@mintplex-labs/piper-tts-web` module we care about.
 *
 *  The library's ``predict`` accepts an optional ``baseUrl`` since v1.0.4;
 *  we forward it to support mirror fallback without patching the library.
 *  The field is typed optional so older bundles still satisfy the shape. */
type PiperModule = {
  predict: (args: {
    voiceId: string
    text: string
    baseUrl?: string
  }) => Promise<Blob>
  flush?: () => Promise<void>
  TtsSession?: { _instance: unknown }
}

/** In-module singletons. Kept in module scope (not exported) so multiple
 *  wizard opens reuse the same loaded module + same audio context. */
let _mod: PiperModule | null = null
let _loading: Promise<PiperModule> | null = null
let _audioCtx: AudioContext | null = null
let _currentSource: AudioBufferSourceNode | null = null
let _lastSynthesizedVoiceId: string | null = null

function _loadModule(): Promise<PiperModule> {
  if (_mod) return Promise.resolve(_mod)
  if (_loading) return _loading
  _loading = (async () => {
    // @vite-ignore — we intentionally import from a runtime CDN URL so the
    // Piper WASM runtime does not land in the main bundle.
    const mod = (await import(/* @vite-ignore */ CDN_URL)) as PiperModule
    if (typeof mod.predict !== 'function') {
      throw new Error('predict() not found in @mintplex-labs/piper-tts-web')
    }
    _mod = mod
    return mod
  })()
  try {
    return _loading
  } finally {
    // The finally runs after the promise settles (success OR error).
    _loading = null
  }
}

function _getAudioContext(): AudioContext {
  if (!_audioCtx || _audioCtx.state === 'closed') {
    const Ctor: typeof AudioContext =
      (window as any).AudioContext || (window as any).webkitAudioContext
    _audioCtx = new Ctor()
  }
  if (_audioCtx.state === 'suspended') void _audioCtx.resume()
  return _audioCtx
}

function _resetTtsSessionSingleton(mod: PiperModule): void {
  // The upstream library caches the active TtsSession across `predict()`
  // calls. When the voice changes we must null the singleton so a fresh
  // ONNX model is downloaded and loaded.
  if (mod.TtsSession) mod.TtsSession._instance = null
}

function _stopCurrent(): void {
  if (_currentSource) {
    try { _currentSource.stop() } catch { /* ignore */ }
    _currentSource = null
  }
}

// ── Public API ───────────────────────────────────────────────────────────────

/** List every voice in the bundled catalog. */
export function listVoices(): readonly PiperVoice[] {
  return PIPER_VOICES
}

/** Persisted currently-selected voice id, or the HFC Female default. */
export function getSelectedVoiceId(): string {
  try {
    const v = localStorage.getItem(STORAGE_VOICE_KEY)
    if (v) return v
  } catch { /* ignore */ }
  return DEFAULT_PIPER_VOICE_ID
}

export function setSelectedVoiceId(voiceId: string): void {
  try { localStorage.setItem(STORAGE_VOICE_KEY, voiceId || DEFAULT_PIPER_VOICE_ID) } catch {}
}

/**
 * True when the runtime supports Piper WASM (Web Audio + dynamic import +
 * OPFS). False on older browsers or in insecure contexts without OPFS.
 */
export function isSupported(): boolean {
  if (typeof window === 'undefined') return false
  if (typeof (window as any).AudioContext === 'undefined'
    && typeof (window as any).webkitAudioContext === 'undefined') {
    return false
  }
  // OPFS requires a secure context (https:// or localhost).
  if (!window.isSecureContext) return false
  return true
}

export interface SynthOptions {
  /** Voice id from listVoices(). Default: getSelectedVoiceId(). */
  voiceId?: string
  /** Optional override for the voice-model base URL. When unset, the
   *  upstream library's default (HuggingFace ``rhasspy/piper-voices``)
   *  is used. The Piper plugin passes a mirror URL here on retry after
   *  an upstream fetch failure so users behind flaky CDNs still get
   *  audio. */
  baseUrl?: string
}

export interface SpeakOptions extends SynthOptions {
  /** Playback rate 0.25–4.0. Applied as AudioBufferSourceNode.playbackRate;
   *  does not affect the underlying WAV data. Default 1.0. */
  rate?: number
  /** Called after the audio finishes playing. */
  onEnd?: () => void
  /** Called on any synthesis or playback error. */
  onError?: (err: Error) => void
}

/**
 * Synthesize `text` to a WAV Blob without playing it.
 *
 * This is the path used by the export wizard: the returned Blob is
 * uploaded to the backend per scene and mux-muxed into the final MP4.
 */
export async function synthesizeToBlob(text: string, opts: SynthOptions = {}): Promise<Blob> {
  const voiceId = (opts.voiceId || getSelectedVoiceId()).trim()
  const mod = await _loadModule()

  if (_lastSynthesizedVoiceId && _lastSynthesizedVoiceId !== voiceId) {
    _resetTtsSessionSingleton(mod)
  }

  const baseUrl = opts.baseUrl
  let audio: Blob
  try {
    audio = await mod.predict({ voiceId, text, ...(baseUrl ? { baseUrl } : {}) })
  } catch (err) {
    const msg = String(err || '')
    // OPFS quota hit → flush cache + retry once.
    const quota = msg.includes('QuotaExceeded') || msg.includes('NotReadable')
    if (quota && mod.flush) {
      await mod.flush()
      _resetTtsSessionSingleton(mod)
      audio = await mod.predict({ voiceId, text, ...(baseUrl ? { baseUrl } : {}) })
    } else {
      throw err
    }
  }

  _lastSynthesizedVoiceId = voiceId

  if (!audio || audio.size === 0) {
    throw new Error(`Piper returned empty audio for voice "${voiceId}"`)
  }
  return audio
}

/**
 * Classic play-through-speakers path. Used by the wizard's Preview button.
 *
 * `rate` is applied at playback time (via `AudioBufferSourceNode.playbackRate`)
 * rather than during synthesis — Piper itself does not accept a rate knob.
 */
export async function speak(text: string, opts: SpeakOptions = {}): Promise<void> {
  const { rate = 1.0, onEnd, onError } = opts
  try {
    const audioBlob = await synthesizeToBlob(text, opts)
    const ctx = _getAudioContext()
    const buffer = await ctx.decodeAudioData(await audioBlob.arrayBuffer())

    _stopCurrent()

    const source = ctx.createBufferSource()
    source.buffer = buffer
    source.playbackRate.value = Math.max(0.25, Math.min(4.0, rate))
    source.connect(ctx.destination)
    source.onended = () => {
      _currentSource = null
      if (onEnd) onEnd()
    }
    _currentSource = source
    source.start(0)
  } catch (err) {
    _currentSource = null
    if (onError) onError(err instanceof Error ? err : new Error(String(err)))
    else throw err
  }
}

/** Stop any currently-playing Preview speech. */
export function stop(): void {
  _stopCurrent()
}

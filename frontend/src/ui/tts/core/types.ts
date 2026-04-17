/**
 * TTS plugin registry — public types.
 *
 * A TtsProvider is a self-contained engine (Web Speech API, Piper WASM,
 * ElevenLabs, XTTS, …) that registers itself with the registry at import
 * time. The Settings panel reads ``getSettingsSchema()`` from the active
 * provider and renders its controls automatically, so adding a new engine
 * is one-file-and-done: no Settings edit, no call-site touch.
 *
 * This file intentionally declares only types — the registry itself and
 * its React glue live in ./registry and ./context respectively.
 */

export type TtsEngineId = string

export interface TtsVoice {
  /** Stable identifier unique within the provider's catalog. */
  id: string
  /** Human-readable label shown in the picker. */
  name: string
  /** BCP-47 tag like "en-US". Empty string when unknown. */
  lang: string
  /** Optional. Providers that do not know this should leave it unset. */
  gender?: 'female' | 'male' | 'other'
  /** Optional quality tier. "medium" is the production default. */
  quality?: 'low' | 'medium' | 'high'
}

export interface TtsCapabilities {
  /** Provider honors ``rate`` in speak/synthesize options. */
  rate: boolean
  /** Provider honors ``pitch`` in speak/synthesize options. */
  pitch: boolean
  /** Provider offers a catalog via ``listVoices()``. */
  voices: boolean
  /** Provider can return synthesized audio as a Blob (for export pipelines). */
  blobs: boolean
}

export interface TtsSpeakOptions {
  voiceId?: string
  /** 0.25–4.0, provider-clamped. */
  rate?: number
  /** 0.25–2.0, provider-clamped. May be ignored when
   *  capabilities.pitch === false. */
  pitch?: number
  onStart?: () => void
  onEnd?: () => void
  onError?: (err: Error) => void
}

export interface TtsSynthOptions {
  voiceId?: string
}

/** Declarative settings schema the provider exposes.
 *
 *  The Settings panel renders:
 *    - "select" → <select> populated from ``options``
 *    - "range"  → <input type="range"> with min/max/step
 *    - "toggle" → <input type="checkbox">
 *
 *  New provider = new schema; the panel itself never changes. */
export type SettingsField =
  | {
      kind: 'select'
      key: string
      label: string
      description?: string
      options: readonly { value: string; label: string }[]
      defaultValue: string
    }
  | {
      kind: 'range'
      key: string
      label: string
      description?: string
      min: number
      max: number
      step: number
      defaultValue: number
    }
  | {
      kind: 'toggle'
      key: string
      label: string
      description?: string
      defaultValue: boolean
    }

/** Every key in a provider's settings schema must appear here. Values
 *  are strings, numbers, or booleans — anything richer should be encoded
 *  in a string (and parsed in the provider) so the storage layer stays
 *  opaque. */
export type TtsSettings = Record<string, string | number | boolean>

export interface TtsProvider {
  readonly id: TtsEngineId
  readonly displayName: string
  readonly capabilities: TtsCapabilities

  /** Cheap synchronous probe: returns false when the provider's runtime
   *  is not usable (e.g. Piper in a non-secure context, Web Speech API
   *  in Node). The UI filters these out of the engine picker. */
  isAvailable(): boolean

  /** Warm up the provider. No-op for web-speech-api; lazy-loads the WASM
   *  runtime for piper-wasm. Idempotent. */
  init(): Promise<void>

  /** Return the catalog. May download a manifest the first time. */
  listVoices(): Promise<readonly TtsVoice[]>

  /** Render ``text`` to the speakers. Resolves when playback ends. */
  speak(text: string, opts?: TtsSpeakOptions): Promise<void>

  /** Return the synthesized audio as a Blob without playing it. Optional
   *  — providers may omit when ``capabilities.blobs === false``. The
   *  export pipeline uses this to upload per-scene narration. */
  synthesizeToBlob?(text: string, opts?: TtsSynthOptions): Promise<Blob>

  /** Halt any in-progress playback from this provider. */
  stop(): void

  /** Settings schema the Settings panel renders for this provider. */
  getSettingsSchema(): readonly SettingsField[]
}

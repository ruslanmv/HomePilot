/**
 * Resolve the voice the assistant will actually speak replies with.
 *
 * Three places store a voice choice and they are not the same key:
 *
 *   1. `readTtsProviderSettings(engineId).voiceId` — the schema-driven bucket
 *      written by the TTS Engine section. For the default `web-speech-api`
 *      engine that section renders no fields (the host panel shows its own
 *      "Assistant Voice" dropdown instead), so this key is normally *empty*.
 *   2. `homepilot_voice_config.voiceURI` — what `window.SpeechService` reads
 *      when it speaks an assistant reply. This is the authoritative choice.
 *   3. `homepilot_voice_uri` — the legacy key, still written by the Settings
 *      save path (`App.tsx`) from the Assistant Voice dropdown.
 *
 * Reading only (1) is what made "Test voice" preview the browser default
 * instead of the selected voice: the preview and the assistant were reading
 * different keys. Consumers should match the returned value against both
 * `SpeechSynthesisVoice.voiceURI` and `.name`, because the Settings dropdown
 * stores a voice *name* while `SpeechService` compares against `voiceURI`.
 */

import { readSettings } from './core/registry'

function _localStorage(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null
  } catch {
    return null
  }
}

function _fromVoiceConfig(): string {
  const storage = _localStorage()
  if (!storage) return ''
  try {
    const raw = storage.getItem('homepilot_voice_config')
    if (!raw) return ''
    const parsed = JSON.parse(raw) as { voiceURI?: unknown }
    return typeof parsed?.voiceURI === 'string' ? parsed.voiceURI : ''
  } catch {
    return ''
  }
}

function _fromLegacyKey(): string {
  const storage = _localStorage()
  if (!storage) return ''
  try {
    return storage.getItem('homepilot_voice_uri') || ''
  } catch {
    return ''
  }
}

/**
 * The voice id/name to preview, or `''` to mean "browser default".
 *
 * @param engineId       Active TTS engine.
 * @param engineSettings Already-read settings blob for that engine, if the
 *                       caller has one (avoids a second storage read).
 */
export function resolveAssistantVoiceId(
  engineId: string,
  engineSettings?: Record<string, unknown>,
): string {
  const settings = engineSettings ?? readSettings(engineId)
  const fromEngine = settings?.voiceId
  if (typeof fromEngine === 'string' && fromEngine) return fromEngine

  // Only the built-in Web Speech engine shares a voice list with the
  // Assistant Voice dropdown. A Piper voice id would be meaningless here.
  if (engineId !== 'web-speech-api') return ''

  return _fromVoiceConfig() || _fromLegacyKey()
}

/**
 * Human-readable label for a resolved voice id, for the Settings UI.
 */
export function describeAssistantVoice(
  voiceId: string,
  voices: readonly SpeechSynthesisVoice[],
): string {
  if (!voiceId) return 'System default'
  const match = voices.find((v) => v.voiceURI === voiceId || v.name === voiceId)
  if (!match) return `${voiceId} (not installed in this browser)`
  return `${match.name} (${match.lang})`
}

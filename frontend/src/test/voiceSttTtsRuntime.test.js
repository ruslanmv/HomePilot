import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const read = (path) => readFileSync(resolve(ROOT, path), 'utf8')

const index = read('frontend/index.html')
const runtime = read('frontend/public/js/homepilot-speech-runtime.js')
const settings = read('frontend/src/ui/components/TtsEngineSection.tsx')
const shim = read('frontend/src/ui/tts/shimSpeechService.ts')
const app = read('frontend/src/ui/App.tsx')
const backend = read('backend/app/voice/routes.py')

describe('shared Chat + Voice speech runtime', () => {
  it('installs selected-microphone recognition before legacy SpeechService is constructed', () => {
    const bridge = index.indexOf('/js/homepilot-speech-runtime.js')
    const legacy = index.indexOf('/js/speech-service.js')
    expect(bridge).toBeGreaterThan(-1)
    expect(legacy).toBeGreaterThan(bridge)
    expect(runtime).toContain('window.SpeechRecognition = HomePilotSpeechRecognition')
    expect(runtime).toContain('window.webkitSpeechRecognition = HomePilotSpeechRecognition')
  })

  it('records the microphone selected in Audio & Video and sends that exact audio to HomePilot STT', () => {
    expect(runtime).toContain("PREFS_KEY = 'homepilot_media_preferences_v1'")
    expect(runtime).toContain('deviceId = { exact: preferences.microphoneDeviceId }')
    expect(runtime).toContain("fetch('/v1/voice/stt/status'")
    expect(runtime).toContain("fetch('/v1/voice/transcribe'")
    expect(runtime).toContain('new MediaRecorder(this._stream')
    expect(runtime).toContain("'transcript_ready'")
    expect(backend).toContain('@router.post("/v1/voice/transcribe")')
    expect(backend).toContain('await stt.transcribe(audio, fmt=fmt)')
  })

  it('keeps native Web Speech only as an explicit fallback when HomePilot STT is unavailable', () => {
    expect(runtime).toContain('NativeSpeechRecognition')
    expect(runtime).toContain("'native_web_speech_fallback'")
    expect(runtime).toContain("microphone: 'browser-managed-default'")
  })

  it('automatically covers the existing Chat mic button without a second recorder implementation', () => {
    expect(app).toContain('(window as any).SpeechRecognition || (window as any).webkitSpeechRecognition')
    expect(runtime).toContain("return 'chat'")
    expect(runtime).toContain("'recognition_start_requested'")
    expect(runtime).toContain("'capture_opened'")
    expect(runtime).toContain("'transcription_failed'")
  })
})

describe('Settings voice diagnostics', () => {
  it('tests the actual SpeechService runtime instead of only the provider preview', () => {
    expect(settings).toContain('speechService()?.stopSpeaking?.()')
    expect(settings).toContain('svc.speak(text')
    expect(settings).toContain('Voice test passed')
    expect(runtime).toContain('[HomePilot:TTS]')
    expect(runtime).toContain("'speak_started'")
    expect(runtime).toContain("'speak_completed'")
  })

  it('traces both system voice and plugin providers regardless of shim load order', () => {
    expect(shim).toContain('[HomePilot:TTS]')
    expect(shim).toContain("trace('engine_selected'")
    expect(shim).toContain("trace('system_voice_delegate'")
    expect(shim).toContain("trace('provider_started'")
    expect(shim).toContain("trace('provider_completed'")
    expect(shim).toContain("trace('provider_error'")
  })

  it('runs a selected-mic → STT → TTS end-to-end diagnostic', () => {
    expect(settings).toContain('Speech → text → voice check')
    expect(settings).toContain('buildAudioConstraints(preferences)')
    expect(settings).toContain("runtime.transcribeBlob(blob, 'settings')")
    expect(settings).toContain('await speakThroughRuntime(`I heard: ${text}`)')
    expect(settings).toContain('Voice pipeline passed')
  })
})

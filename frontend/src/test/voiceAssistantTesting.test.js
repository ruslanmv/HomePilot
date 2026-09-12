/**
 * Wiring contracts for the voice input/output fixes.
 *
 * Source-level assertions in the same style as `microphoneDiagnostics.test.js`:
 * they lock the connections that, when missing, produced exactly the reported
 * symptoms — a chat microphone button that did nothing and logged nothing, a
 * recognizer cut off before it could transcribe, and a "Test voice" button that
 * previewed a different voice than the assistant speaks with.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const read = (path) => readFileSync(resolve(ROOT, path), 'utf8');

const speechService = read('frontend/public/js/speech-service.js');
const controller = read('frontend/src/ui/voice/useVoiceController.ts');
const app = read('frontend/src/ui/App.tsx');
const selfTest = read('frontend/src/ui/components/VoiceAssistantSelfTest.tsx');
const settingsPanel = read('frontend/src/ui/SettingsPanel.tsx');
const ttsSection = read('frontend/src/ui/components/TtsEngineSection.tsx');
const audioVideo = read('frontend/src/ui/components/AudioVideoSettings.tsx');
const sttService = read('frontend/src/ui/media/sttService.ts');
const vad = read('frontend/src/ui/voice/vad.ts');
const transcribeRoute = read('backend/app/voice/transcribe.py');
const mainApp = read('backend/app/main.py');

describe('SpeechService recognition instrumentation', () => {
  it('traces into the shared HomePilot:Mic buffer from a classic script', () => {
    expect(speechService).toContain('__HOMEPILOT_MIC_DEBUG__');
    expect(speechService).toContain('[HomePilot:Mic][speech-service]');
    expect(speechService).toContain("scope: 'speech-service'");
  });

  it('subscribes to the lifecycle events that expose a silent failure', () => {
    expect(speechService).toContain('this.recognition.onaudiostart');
    expect(speechService).toContain('this.recognition.onspeechstart');
    expect(speechService).toContain('this.recognition.onnomatch');
    expect(speechService).toContain('sawAudioStart');
    expect(speechService).toContain('sawSpeechStart');
  });

  it('guards the stop so VAD silence cannot end a warming-up session', () => {
    expect(speechService).toContain('STT_MIN_LISTEN_MS');
    expect(speechService).toContain('STT_MAX_LISTEN_MS');
    expect(speechService).toContain('stop_deferred_warming_up');
    expect(speechService).toContain('stop_applied_after_defer');
  });

  it('never records audio bytes or transcript text in the trace', () => {
    expect(speechService).toContain('never audio bytes and never recognized transcript');
    expect(speechService).toContain('characters: finalTranscript.trim().length');
    expect(speechService).not.toContain('transcript: finalTranscript');
  });
});

describe('voice controller stop reasons', () => {
  it('lets a VAD silence stop be deferred but forces a user-driven one', () => {
    expect(controller).toContain("svc.stopSTT?.({ reason: 'vad_silence' })");
    expect(controller).toContain("svc.stopSTT?.({ reason: 'manual_button', force: true })");
    expect(controller).toContain("svc?.stopSTT?.({ reason: 'turn_lock', force: true })");
  });

  it('logs why a turn produced no transcript, not just that it did not', () => {
    expect(controller).toContain('svc.getSttDiagnostics?.()');
    expect(controller).toContain('sawAudioStart: diagnostics.sawAudioStart');
    expect(controller).toContain('sawSpeechStart: diagnostics.sawSpeechStart');
    expect(controller).toContain('stoppedBy: diagnostics.stoppedBy');
  });
});

describe('one selected-microphone transcription path', () => {
  it('is served by an ungated backend endpoint', () => {
    // VOICE_BACKEND_ENABLED guards server-side LLM+TTS orchestration. Gating
    // transcription behind it would leave the web client with no alternative
    // to the device split this path exists to remove.
    expect(transcribeRoute).toContain('@router.post("/v1/voice/transcribe")');
    expect(transcribeRoute).toContain('@router.get("/v1/voice/stt/status")');
    // The docstring names the flag to explain why it is *not* consulted, so
    // assert the absence of a gate rather than of the word.
    expect(transcribeRoute).not.toMatch(/getattr\(\s*config\s*,\s*["']VOICE_BACKEND_ENABLED/);
    expect(transcribeRoute).not.toMatch(/config\.VOICE_BACKEND_ENABLED/);
    expect(mainApp).toContain('voice_transcribe_router');
  });

  it('records the microphone selected in Audio & Video', () => {
    expect(sttService).toContain('buildAudioConstraints(preferences)');
    expect(sttService).toContain('stt_selected_device_unavailable_fallback_default');
    expect(sttService).toContain('new MediaRecorder(stream)');
  });

  it('keeps Web Speech only as a fallback, and names which engine is in use', () => {
    expect(sttService).toContain("export type SttEngine = 'homepilot-backend' | 'web-speech'");
    expect(sttService).toContain('SttUnavailableError');
    expect(controller).toContain("engine: SttEngine = capability.available ? 'homepilot-backend' : 'web-speech'");
    expect(controller).toContain('stt_engine_resolved');
    expect(controller).toContain('usesOsDefaultInput');
  });

  it('transcribes the VAD’s own capture, so detection and text cannot disagree', () => {
    expect(vad).toContain('getStream: () => stream');
    expect(controller).toContain('vadRef.current?.getStream?.()');
    expect(controller).toContain('recorder_started');
  });

  it('does not gate voice on Web Speech when the backend transcribes', () => {
    // Otherwise a perfectly working setup (Firefox, or a Chromium build with no
    // recognizer) is refused for a capability it no longer needs.
    expect(controller).toContain('mediaRecorderSupported');
    expect(controller).toContain("(sttEngine === 'homepilot-backend' && mediaRecorderSupported) || webSpeechSupported");
  });

  it('discards a turn nobody is waiting for instead of paying to transcribe it', () => {
    expect(controller).toContain("discardRecording('turn_lock')");
    expect(controller).toContain("discardRecording('handsfree_cleanup')");
  });

  it('reports silence as silence, not as a failure', () => {
    expect(controller).toContain('stt_no_speech');
    expect(transcribeRoute).toContain('successful transcription of silence');
  });
});

describe('chat composer microphone button', () => {
  it('traces every outcome, so the first chat tab is no longer silent', () => {
    expect(app).toContain("microphoneDebug('chat', 'composer_mic_start_click'");
    expect(app).toContain("microphoneDebug('chat', 'composer_mic_stop_click'");
    expect(app).toContain("microphoneDebug('chat', 'composer_mic_onstart'");
    expect(app).toContain("microphoneDebug('chat', 'composer_mic_onend'");
    expect(app).toContain("microphoneDebug('chat', 'composer_mic_unsupported'");
    expect(app).toContain("microphoneDebugError('chat', 'composer_mic_error'");
    expect(app).toContain("microphoneDebugError('chat', 'composer_mic_start_failed'");
  });

  it('releases the shared recognition session instead of colliding with it', () => {
    // A page can hold only one SpeechRecognition. Starting a second one used to
    // abort silently, which is what made the button look dead.
    expect(app).toContain("shared.abortSTT?.('chat_composer_mic')");
  });

  it('prefers HomePilot transcription and falls back only when it is absent', () => {
    expect(app).toContain('getSttCapability().then');
    expect(app).toContain('startBackendListening');
    expect(app).toContain('composer_mic_fallback_web_speech');
    expect(app).toContain('recordAndTranscribe({');
  });

  it('shows a transcribing state rather than a still-pulsing record button', () => {
    expect(app).toContain('micTranscribing');
    expect(app).toContain('aria-label="Transcribing"');
  });

  it('tells the user why nothing was captured', () => {
    expect(app).toContain('composer-mic-notice');
    expect(app).toContain('setMicNotice');
    expect(app).toContain('explainSttOutcome(diagnostics');
    expect(app).toContain('explainSttError(name)');
  });

  it('no longer swallows an unsupported browser or a failed start', () => {
    expect(app).not.toContain('const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition');
    expect(app).not.toContain('try { recognition.start() } catch { /* already started */ }');
  });
});

describe('Settings voice self-test', () => {
  it('is mounted in the Voice Assistant card', () => {
    expect(settingsPanel).toContain('import VoiceAssistantSelfTest');
    expect(settingsPanel).toContain('<VoiceAssistantSelfTest />');
  });

  it('offers speech-to-text, text-to-speech and the full loop', () => {
    expect(selfTest).toContain('Test speech-to-text');
    expect(selfTest).toContain('Test text-to-speech');
    expect(selfTest).toContain('Test speech → text → voice');
    expect(selfTest).toContain('Recognized text');
  });

  it('exercises the same transcription path chat and Voice use', () => {
    // A test that calls a parallel implementation can pass while the real path
    // fails, which is the whole reason the old preview was misleading.
    expect(selfTest).toContain('recordAndTranscribe({');
    expect(selfTest).toContain('getSttCapability()');
    expect(selfTest).toContain('SttUnavailableError');
  });

  it('speaks through the runtime path, not a parallel provider call', () => {
    expect(selfTest).toContain('speakThroughRuntime(TTS_TEST_SENTENCE)');
    expect(selfTest).not.toContain('provider.speak(');
  });

  it('reads the recognized text back aloud for the end-to-end check', () => {
    expect(selfTest).toContain('speakThroughRuntime(`I heard: ${result.text}`)');
    expect(selfTest).toContain('The whole voice loop is working');
  });

  it('shows the recognized text so the user can confirm what was heard', () => {
    expect(selfTest).toContain('setHeard(result.text)');
    expect(selfTest).toContain('explainSttOutcome(diagnosticsRef.current, transcriptRef.current)');
  });

  it('says which engine is in use, including the fallback device caveat', () => {
    expect(selfTest).toContain('records your operating system default input');
    expect(selfTest).toContain('recordings leave this computer');
  });

  it('does not clobber the recognition callbacks hands-free voice installed', () => {
    expect(selfTest).toContain("shared?.abortSTT?.('settings_stt_test')");
    expect(selfTest).not.toContain('setRecognitionCallbacks');
  });

  it('treats Stop as "transcribe what I said", not "discard it"', () => {
    expect(selfTest).toContain('Stop and check');
    expect(selfTest).toContain('stopRecordingRef.current()');
  });

  it('traces every test into the shared microphone buffer', () => {
    expect(selfTest).toContain("microphoneDebug('settings', 'stt_test_started'");
    expect(selfTest).toContain("microphoneDebug('settings', 'stt_test_finished'");
    expect(selfTest).toContain("microphoneDebug('settings', 'voice_loop_test_started'");
    expect(selfTest).toContain("microphoneDebug('settings', 'voice_loop_test_completed'");
  });
});

describe('Test voice preview', () => {
  it('goes through the runtime path so it cannot pass while replies fail', () => {
    expect(ttsSection).toContain('isRuntimeTtsAvailable()');
    expect(ttsSection).toContain('speakThroughRuntime(');
  });

  it('resolves the Assistant Voice instead of an empty engine bucket', () => {
    expect(ttsSection).toContain('resolveAssistantVoiceId(activeId, settings)');
    expect(ttsSection).not.toContain("const voiceId = typeof settings.voiceId === 'string' ? settings.voiceId : undefined");
  });

  it('releases the button when the engine never starts speaking', () => {
    expect(ttsSection).toContain('startWatchdog');
    expect(ttsSection).toContain('never started speaking');
  });
});

describe('microphone routing warning', () => {
  it('warns in Audio & Video when recognition would use a different input', () => {
    expect(audioVideo).toContain('describeMicrophoneRouting');
    expect(audioVideo).toContain('Speech-to-text uses a different input.');
  });

  it('repeats the warning where the voice tests are run', () => {
    expect(selfTest).toContain('describeMicrophoneRouting');
    expect(selfTest).toContain('Microphone routing:');
  });

  it('suppresses the warning when the backend transcribes the selected device', () => {
    // On that path the bytes transcribed are the bytes captured, so there is no
    // split to warn about and the notice would be noise.
    expect(selfTest).toContain('if (backendStt) return { mismatch: false, message: null }');
  });
});

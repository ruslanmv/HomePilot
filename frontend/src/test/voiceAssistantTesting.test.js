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

  it('offers both a speech-to-text and a text-to-speech test', () => {
    expect(selfTest).toContain('Test speech-to-text');
    expect(selfTest).toContain('Test text-to-speech');
    expect(selfTest).toContain('Recognized text');
  });

  it('shows the recognized text so the user can confirm what was heard', () => {
    expect(selfTest).toContain('setHeard(transcriptRef.current)');
    expect(selfTest).toContain('explainSttOutcome(diagnosticsRef.current, transcriptRef.current)');
  });

  it('fails the TTS test when the engine never starts speaking', () => {
    // speechSynthesis reports no error for a missing voice, a muted output or a
    // blocked autoplay, so only the absence of onStart exposes it.
    expect(selfTest).toContain('TTS_START_TIMEOUT_MS');
    expect(selfTest).toContain('tts_test_never_started');
    expect(selfTest).toContain('The voice never started speaking');
  });

  it('does not clobber the recognition callbacks hands-free voice installed', () => {
    expect(selfTest).toContain("shared?.abortSTT?.('settings_stt_test')");
    expect(selfTest).not.toContain('setRecognitionCallbacks');
  });

  it('speaks the test sentence with the voice the assistant will actually use', () => {
    expect(selfTest).toContain('resolveAssistantVoiceId(activeEngineId, engineSettings)');
    expect(selfTest).toContain('voiceId: resolvedVoiceId || undefined');
  });

  it('traces both tests into the shared microphone buffer', () => {
    expect(selfTest).toContain("microphoneDebug('settings', 'stt_test_started'");
    expect(selfTest).toContain("microphoneDebug('settings', 'stt_test_finished'");
    expect(selfTest).toContain("microphoneDebug('settings', 'tts_test_started'");
    expect(selfTest).toContain("microphoneDebug('settings', 'tts_test_completed'");
  });
});

describe('Test voice preview', () => {
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
});

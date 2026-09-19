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
const sttRuntime = read('frontend/src/ui/media/sttRuntime.ts');
const webSpeechSession = read('frontend/src/ui/media/webSpeechSession.ts');
const settingsCard = read('frontend/src/ui/components/SpeechRecognitionSettings.tsx');
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
  it('lets a deferred stop stand but forces a user-driven one', () => {
    // The deferral itself lives in SpeechService. What the adapter must not do is force
    // every stop — that is what cut short utterances off mid-warm-up.
    expect(webSpeechSession).toContain('force: Boolean(options.force)');
    expect(controller).toContain("stopWebSpeech('voice', { reason: 'manual_button', force: true })");
    // A turn lock wants the microphone back now, transcript or not.
    expect(controller).toContain("abortWebSpeech('turn_lock')");
  });

  it('logs why a turn produced no transcript, not just that it did not', () => {
    expect(webSpeechSession).toContain('svc.getSttDiagnostics?.()');
    expect(controller).toContain('sawAudioStart: diagnostics.sawAudioStart');
    expect(controller).toContain('sawSpeechStart: diagnostics.sawSpeechStart');
    expect(controller).toContain('stoppedBy: diagnostics.stoppedBy');
  });
});

describe('the engine owns the microphone', () => {
  /*
   * The reported failure: hands-free Voice started HomePilot's VAD, which opens and holds
   * the microphone selected in Audio & Video, and then asked the browser recognizer — which
   * takes no deviceId and opens the OS default input — to transcribe the turn. Two captures,
   * two devices, no error from either, and a turn that produced nothing.
   *
   * These assertions are what make that unrepresentable, so they are worth more than the
   * timeout tuning they replace.
   */
  it('resolves the engine once, in one place, shared by chat and Voice', () => {
    expect(sttRuntime).toContain('export function ensureSttRuntimeResolved');
    expect(sttRuntime).toContain('stt_runtime_resolved');
    expect(sttRuntime).toContain('usesOsDefaultInput');
    // Both surfaces read that one object rather than resolving privately.
    expect(controller).toContain('const runtime = useSttRuntime()');
    expect(app).toContain('ensureSttRuntimeResolved().then');
    // …and the old private copies are gone.
    expect(app).not.toContain('micEngineOverrideRef');
    expect(controller).not.toContain('const [sttEngine, setSttEngine]');
  });

  it('never starts HomePilot’s VAD on the browser engine', () => {
    // `createVAD` must be unreachable unless the resolved engine is the local one.
    const captureEffect = controller.slice(
      controller.indexOf('Open exactly one capture, chosen by the engine'),
      controller.indexOf('Give the microphone back when Voice unmounts'),
    );
    expect(captureEffect.length).toBeGreaterThan(0);
    const browserBranch = captureEffect.indexOf("if (sttEngine === 'web-speech')");
    expect(browserBranch).toBeGreaterThan(-1);
    // The browser branch returns before `createVAD` is ever reached.
    expect(captureEffect.indexOf('createVAD(')).toBeGreaterThan(browserBranch);
    expect(captureEffect.slice(browserBranch, captureEffect.indexOf('createVAD(')))
      .toContain('return () => {');
  });

  it('never starts the browser recognizer on the local engine', () => {
    // The VAD callbacks record the VAD's own stream; nothing in them reaches Web Speech.
    const vadCallbacks = controller.slice(
      controller.indexOf('const vad = createVAD('),
      controller.indexOf('vadRef.current = vad;'),
    );
    expect(vadCallbacks.length).toBeGreaterThan(0);
    expect(vadCallbacks).toContain("startRecordingTurn('vad_speech_start')");
    expect(vadCallbacks).not.toContain('startWebSpeech');
    expect(vadCallbacks).not.toContain('startBrowserTurn');
  });

  it('hands the microphone over rather than opening a second capture', () => {
    expect(sttRuntime).toContain('export async function acquireMicrophone');
    expect(sttRuntime).toContain('await previous.release();');
    expect(sttRuntime).toContain('microphone_handoff');
    expect(controller).toContain("acquireMicrophone('voice', sttEngine");
    expect(app).toContain("acquireMicrophone('chat', 'homepilot-backend'");
    expect(app).toContain("acquireMicrophone('chat', 'web-speech'");
  });

  it('opens nothing at all until the engine is known', () => {
    // `pending`, not "assume the browser and correct later": that default sent the first
    // sentence of a session through an engine the user did not choose.
    expect(sttRuntime).toContain("status: 'pending'");
    expect(sttRuntime).toContain('effectiveEngine: null');
    expect(controller).toContain('handsfree_waiting_for_engine');
    expect(controller).toContain('stt_engine_pending');
  });

  it('keeps one browser recognizer with one owner', () => {
    expect(webSpeechSession).toContain('export async function startWebSpeech');
    expect(webSpeechSession).toContain("abortWebSpeech('handoff')");
    // Events reach the surface that owns the turn *now*, never the previous one.
    expect(webSpeechSession).toContain('current.generation !== gen');
    // The chat composer no longer builds a recognizer of its own.
    expect(app).not.toContain('new SR()');
    expect(app).not.toContain('recognitionRef.current');
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

  it('names which engine is in use, and how it was arrived at', () => {
    // The engine is no longer "the backend whenever it reports available" — see the
    // preference tests below — but the trace must still say which one runs and why.
    expect(sttService).toContain("export type SttEngine = 'homepilot-backend' | 'web-speech'");
    expect(sttService).toContain('SttUnavailableError');
    expect(sttRuntime).toContain('stt_runtime_resolved');
    expect(sttRuntime).toContain('reason: overrideReason ?? resolution.reason');
    expect(sttRuntime).toContain('usesOsDefaultInput');
    // …and the evidence behind a preflight switch, so "why am I not on the engine I picked"
    // is answerable from the trace alone.
    expect(sttRuntime).toContain('routingMismatch');
    expect(sttRuntime).toContain('routingKnown');
  });

  it('refuses to open a capture it can already tell will be deaf', () => {
    // `describeMicrophoneRouting` has been able to spot the OS-default split since the
    // Settings warning was written. Chat and Voice opened the capture anyway and learned it
    // from two failed turns — with the device list saying so before the first one.
    expect(sttRuntime).toContain('describeMicrophoneRouting');
    expect(sttRuntime).toContain("'routing-mismatch-preflight'");
    // Gated on evidence: no `default` alias to compare against is not proof they agree.
    expect(sttRuntime).toContain('routing.known');
    expect(sttRuntime).toContain('routing.mismatch');
    // And where the device list cannot tell — Chrome on Windows exposes no `default` alias —
    // a verdict a turn already established stands in, so the discovery is paid for once and
    // not on every page load.
    expect(sttRuntime).toContain('export function rememberRecognizerIsDeaf');
    expect(sttRuntime).toContain('export function recognizerKnownDeaf');
    expect(app).toContain('rememberRecognizerIsDeaf()');
    expect(controller).toContain('rememberRecognizerIsDeaf()');
    // Clearable, or a remembered verdict becomes the choice being refused.
    expect(sttRuntime).toContain('forgetRecognizerIsDeaf();');
    // And escapable: re-picking an engine in Settings disarms it, or "Browser" would be
    // unselectable for the session on any machine whose default input differs.
    expect(sttRuntime).toContain('routingPreflightArmed = false');
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
    expect(controller).toContain("sttEngine === 'homepilot-backend'\n      ? mediaRecorderSupported");
  });

  it('discards a turn nobody is waiting for instead of paying to transcribe it', () => {
    expect(controller).toContain("discardRecording('turn_lock')");
    // Teardown goes through one release, which discards the recorder before the stream it
    // is attached to goes away.
    expect(controller).toContain("releaseVoiceCapture('handsfree_vad_cleanup')");
    expect(controller).toContain('discardRecording(reason);');
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
    expect(app).toContain("microphoneDebug('chat', 'composer_mic_engine'");
    expect(app).toContain("microphoneDebug('chat', 'composer_mic_error'");
    // A session Chrome ended and dictation reopened is a distinct event from a turn ending.
    expect(app).toContain("microphoneDebug('chat', 'composer_mic_resumed'");
    // A start the adapter refused is traced there, where the one recognizer lives.
    expect(webSpeechSession).toContain('web_speech_start_failed');
    expect(webSpeechSession).toContain('web_speech_unsupported');
  });

  it('releases the shared recognition session instead of colliding with it', () => {
    // A page can hold only one SpeechRecognition. Starting a second one used to abort
    // silently, which is what made the button look dead — and the composer coordinating
    // that itself only covered one direction. One adapter does both now.
    expect(webSpeechSession).toContain("abortWebSpeech('handoff')");
    expect(app).toContain("abortWebSpeech('microphone_handoff')");
    expect(app).toContain("abortWebSpeech('chat_unmount')");
  });

  it('is always reachable, even when there is text to send', () => {
    // It used to be the *alternative* to Submit, so any text at all hid it: dictating a
    // correction onto a draft meant clearing the field first.
    expect(app).toContain('The microphone is always here.');
    expect(app).toContain("data-testid=\"composer-mic\"");
    expect(app).not.toContain(') : canSend ? (');
  });

  it('prefers the engine the session resolved, and falls back only when it breaks', () => {
    expect(app).toContain('ensureSttRuntimeResolved().then');
    expect(app).toContain('startBackendListening');
    expect(app).toContain('composer_mic_fallback_web_speech');
    expect(app).toContain('recordAndTranscribe({');
    // A mid-session fallback moves the whole session, not just this button.
    expect(app).toContain("applySttSessionOverride(\n          'web-speech',");
  });

  it('shows a transcribing state rather than a still-pulsing record button', () => {
    expect(app).toContain('micTranscribing');
    expect(app).toContain('aria-label="Transcribing"');
  });

  it('tells the user why nothing was captured', () => {
    expect(app).toContain('composer-mic-notice');
    expect(app).toContain('setMicNotice');
    expect(app).toContain('explainSttOutcome(diagnostics');
    expect(app).toContain('explainSttError(code)');
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
    // `describeSttRuntime`, not `describeSttResolution`: the resolution is what the
    // preference resolves to, and that stops being the truth the moment a session override
    // is in force. This card reported "Using the browser's speech recognition" about a
    // session that had already moved to on-device transcription.
    expect(selfTest).toContain('describeSttRuntime(runtime)');
    expect(settingsCard).toContain('describeSttRuntime(runtime)');
    expect(sttRuntime).toContain('export function describeSttRuntime');
    expect(sttRuntime).toContain('not the engine chosen in Settings');
    expect(read('frontend/src/ui/media/sttPreferences.ts'))
      .toContain('records your system default input');
    expect(selfTest).toContain('Recordings leave this computer');
  });

  it('takes the microphone rather than snatching it back and forth', () => {
    // The test used to abort whoever held the recognizer, which worked in one direction
    // only: the Voice tab's hands-free loop restarts every 400 ms, so it took the recognizer
    // straight back and the test died with a bare `aborted` before the user finished
    // speaking. Owning a lease is what makes the other surface wait instead.
    expect(selfTest).toContain("acquireMicrophone('settings', 'web-speech'");
    expect(selfTest).toContain("releaseMicrophone('settings')");
    expect(selfTest).toContain("startWebSpeech('settings'");
    expect(selfTest).not.toContain("shared?.abortSTT?.('settings_stt_test')");
    // Still no direct callback installation: the adapter owns that, for everybody.
    expect(selfTest).not.toContain('setRecognitionCallbacks');
    // And the loop yields to a lease it does not hold.
    expect(controller).toContain('handsfree_browser_yielded');
  });

  it('offers the end-to-end check whenever it can actually run', () => {
    // It was gated on the *resolved engine*, so on the default (Browser) it refused and told
    // the user to install a speech model — on a server that already had one. Which engine
    // chat uses is a different question from whether this check can run.
    expect(selfTest).toContain('const loopCanRun = Boolean(capability?.available) && recorderSupported');
    expect(selfTest).not.toContain('if (!backendStt || !recorderSupported) {');
    // Passing it must not be read as "the engine chat uses works".
    expect(selfTest).toContain('does not exercise that path');
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
    expect(selfTest).toContain('if (backendStt) return { mismatch: false, known: true, message: null }');
  });
});

describe('the speech-recognition engine is a choice, not a detection', () => {
  const preferences = read('frontend/src/ui/media/sttPreferences.ts');

  it('defaults chat and Voice to the browser, restoring the original behaviour', () => {
    // Preferring the local engine whenever it reported itself available broke chat
    // speech-to-text on a machine with an incomplete CUDA runtime: available, and failing
    // every turn. A default that works everywhere beats a better one that sometimes does.
    expect(preferences).toContain("chat: 'web-speech'");
  });

  it('lets the preference decide and the capability only constrain', () => {
    // Resolved once, in the shared runtime, rather than once per surface — two copies of
    // this decision is how chat and Voice came to disagree about which engine was running.
    expect(sttRuntime).toContain('resolveSttEngine(preference, {');
    expect(controller).not.toContain('resolveSttEngine(');
    expect(app).not.toContain('resolveSttEngine(');
    expect(sttRuntime).not.toContain("capability.available ? 'homepilot-backend' : 'web-speech'");
  });

  it('never overrides a choice silently', () => {
    // Somebody who chose on-device transcription for privacy must not be quietly served the
    // browser's, which sends audio to Google.
    expect(preferences).toContain('fellBack');
    expect(sttRuntime).toContain('fellBack: resolution.fellBack');
    expect(app).toContain('resolution?.fellBack');
    expect(settingsCard).toContain('Not the engine you chose');
  });

  it('says so too when it changes engines after the recognizer goes deaf', () => {
    // The recovery in `media/sttTurnHealth` moves a session onto a different engine without
    // being asked. That is the same act as a fallback and carries the same obligation, so
    // both surfaces must set a notice — not just switch.
    for (const [name, source] of [['controller', controller], ['app', app]]) {
      expect(source, `${name} should consult the detector`).toContain('isDeafTurn(');
      expect(source, `${name} should act on a plan`).toContain('planSttRecovery(');
      expect(source, `${name} should tell the user`).toMatch(
        /set(Stt|Mic)Notice\(recovery\.message\)/,
      );
    }
  });

  it('re-resolves when the setting changes, without a reload', () => {
    // One subscription, in the shared runtime, so both surfaces move together — and a
    // deliberate choice in Settings clears a recovery HomePilot made on its own.
    expect(sttRuntime).toContain('preferenceSubscription = subscribeSttPreferences');
    expect(sttRuntime).toContain('sessionOverride: null');
    expect(selfTest).toContain('subscribeSttPreferences((next) => setPreference(next.chat))');
  });

  it('aims the self-tests at the engine that will actually run', () => {
    // Testing the backend merely because it is available would pass while the path the user
    // chose stayed broken — and testing the *preference* would keep failing on a session
    // that had already recovered onto a working engine. The runtime is the only source that
    // is right in both cases.
    expect(selfTest).toContain("runtime.effectiveEngine === 'homepilot-backend'");
    expect(selfTest).not.toContain('resolveSttEngine(');
  });

  it('shows each engine’s cost, not only its benefit', () => {
    expect(settingsCard).toContain('goods');
    expect(settingsCard).toContain('bads');
    expect(settingsCard).toContain('system default input');
    expect(settingsCard).toContain('Google service');
  });

  it('reports the meeting engine rather than pretending to offer it', () => {
    // Two channels, hours of continuous audio and speaker labels: the browser recognizer can
    // do none of it, so there is one engine and nothing to choose.
    expect(settingsCard).toContain('This is not a setting');
    expect(settingsCard).toContain('/v1/meetingsense/status');
    expect(settingsCard).not.toContain('stt-engine-meetings');
  });
});

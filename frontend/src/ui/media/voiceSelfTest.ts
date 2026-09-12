/**
 * Pure logic behind Settings → Voice Assistant → "Test speech-to-text" and
 * "Test text-to-speech".
 *
 * Everything here is deliberately free of React and of live device access so
 * the interesting part — turning a browser's silence into an actionable
 * sentence — is unit-testable. The component in
 * `components/VoiceAssistantSelfTest.tsx` supplies the live inputs.
 */

/** What `SpeechService.getSttDiagnostics()` reports for one recognition turn. */
export interface SttDiagnostics {
  sawAudioStart?: boolean;
  sawSoundStart?: boolean;
  sawSpeechStart?: boolean;
  sawInterim?: boolean;
  sawResult?: boolean;
  sawNoMatch?: boolean;
  error?: string | null;
  elapsedMs?: number;
  lang?: string;
  stoppedBy?: string | null;
}

export interface SttOutcome {
  ok: boolean;
  /** One short line for the badge / heading. */
  headline: string;
  /** The concrete next step, written for someone who is not a developer. */
  detail: string;
}

/* eslint-disable @typescript-eslint/no-explicit-any */
type SpeechRecognitionCtor = new () => any;

export function getSpeechRecognitionCtor(
  scope: any = typeof window !== 'undefined' ? window : undefined,
): SpeechRecognitionCtor | null {
  if (!scope) return null;
  return scope.SpeechRecognition || scope.webkitSpeechRecognition || null;
}

export function isSpeechRecognitionSupported(
  scope: any = typeof window !== 'undefined' ? window : undefined,
): boolean {
  return Boolean(getSpeechRecognitionCtor(scope));
}

export function isSpeechSynthesisSupported(
  scope: any = typeof window !== 'undefined' ? window : undefined,
): boolean {
  return Boolean(scope && 'speechSynthesis' in scope && scope.speechSynthesis);
}
/* eslint-enable @typescript-eslint/no-explicit-any */

/**
 * Map the browser's own recognition error codes onto something a user can act
 * on. These are the values Chrome puts in `SpeechRecognitionErrorEvent.error`.
 */
export function explainSttError(error: string): SttOutcome {
  switch (error) {
    case 'not-allowed':
    case 'service-not-allowed':
      return {
        ok: false,
        headline: 'Microphone permission blocked',
        detail:
          'The browser refused speech recognition. Allow microphone access for this site, then run the test again.',
      };
    case 'no-speech':
      return {
        ok: false,
        headline: 'No speech detected',
        detail:
          'Recognition ran but heard nothing. Speak a full sentence close to the microphone, and check that the input HomePilot uses is the one you are speaking into.',
      };
    case 'audio-capture':
      return {
        ok: false,
        headline: 'Microphone could not be opened',
        detail:
          'Speech recognition could not capture audio. Another application may hold the microphone exclusively — close it and try again.',
      };
    case 'network':
      return {
        ok: false,
        headline: 'Recognition service unreachable',
        detail:
          'Chrome sends audio to a Google speech service for the Web Speech API, so it needs internet access. Offline? Use the local Whisper engine for meeting transcription instead.',
      };
    case 'aborted':
      return {
        ok: false,
        headline: 'Recognition was interrupted',
        detail:
          'Another part of HomePilot started listening at the same time. Turn hands-free voice off, then run this test again.',
      };
    case 'language-not-supported':
      return {
        ok: false,
        headline: 'Language not supported',
        detail:
          'The recognition language is not available in this browser. Pick a different language for speech-to-text.',
      };
    case 'InvalidStateError':
      return {
        ok: false,
        headline: 'Another recognition session is already open',
        detail:
          'A browser page can run only one speech recognition at a time. Stop hands-free voice or the chat microphone, then run this test again.',
      };
    default:
      return {
        ok: false,
        headline: 'Speech recognition failed',
        detail: `The browser reported "${error}". Run the microphone test above to confirm the input works, then try again.`,
      };
  }
}

/**
 * Turn one recognition turn into a verdict.
 *
 * The three silent failure modes are the whole point of this function. They are
 * indistinguishable from "no transcript" alone, and each has a different fix:
 *
 *   - no `audiostart`   → the recognizer never opened a capture at all.
 *   - `audiostart` but no `speechstart` → it captured a *silent* device. On
 *     Chrome this is almost always the OS default input, because the Web Speech
 *     API accepts no deviceId and therefore ignores the microphone selected in
 *     HomePilot.
 *   - `speechstart` but no result → it heard speech and produced nothing: cut
 *     off too early, wrong language, or an explicit `nomatch`.
 */
export function explainSttOutcome(
  diagnostics: SttDiagnostics,
  transcript: string,
): SttOutcome {
  const text = (transcript || '').trim();
  if (text) {
    return {
      ok: true,
      headline: 'Speech-to-text is working',
      detail: `Recognized ${text.length} character${text.length === 1 ? '' : 's'}. The text below is what HomePilot heard.`,
    };
  }

  if (diagnostics.error) return explainSttError(diagnostics.error);

  if (!diagnostics.sawAudioStart) {
    return {
      ok: false,
      headline: 'Recognition never received audio',
      detail:
        'The browser started recognition but never opened an audio capture. Check the site\'s microphone permission, and close any other app or tab that is holding the microphone.',
    };
  }

  if (!diagnostics.sawSpeechStart) {
    return {
      ok: false,
      headline: 'Recognition captured silence',
      detail:
        'Audio was captured but no speech was found in it. The Web Speech API always records your operating system\'s default input and ignores the microphone chosen in Audio & Video — make the microphone you speak into the OS default, then retest.',
    };
  }

  if (diagnostics.sawNoMatch) {
    return {
      ok: false,
      headline: 'Speech heard but not recognized',
      detail:
        'The recognizer detected speech and could not match it to words. Check that the speech-to-text language matches the language you are speaking.',
    };
  }

  return {
    ok: false,
    headline: 'Speech heard but no transcript returned',
    detail:
      'Speech was detected but recognition ended without a result — usually because it was stopped too early. Speak a longer sentence and let the test run to the end.',
  };
}

export interface MicrophoneRoutingNotice {
  /** Whether the selected microphone differs from the OS default input. */
  mismatch: boolean;
  message: string | null;
}

/**
 * Detect the split that makes the voice meter and the transcript disagree.
 *
 * HomePilot's VAD opens `getUserMedia` with the microphone selected in
 * Audio & Video. Chrome's `SpeechRecognition` takes no `deviceId` and always
 * records the OS default input. When those are two different microphones, the
 * level meter moves while recognition transcribes a device nobody is speaking
 * into. Nothing in the browser reports this, so it has to be inferred from the
 * device list.
 */
export function describeMicrophoneRouting(
  devices: readonly MediaDeviceInfo[],
  selectedDeviceId: string,
): MicrophoneRoutingNotice {
  if (!selectedDeviceId) {
    return { mismatch: false, message: null };
  }

  const inputs = devices.filter((device) => device.kind === 'audioinput');
  const selected = inputs.find((device) => device.deviceId === selectedDeviceId);

  if (!selected) {
    return {
      mismatch: false,
      message:
        'The microphone saved in Audio & Video is not currently connected. HomePilot will fall back to the system default input.',
    };
  }

  // `default` is Chrome's alias for "whatever the OS default is", so selecting
  // it can never disagree with recognition.
  if (selected.deviceId === 'default') return { mismatch: false, message: null };

  const osDefault = inputs.find((device) => device.deviceId === 'default');
  // Without the alias there is no way to know which input the OS prefers.
  // Staying quiet beats warning about a mismatch that may not exist.
  if (!osDefault) return { mismatch: false, message: null };

  const sameDevice = Boolean(selected.groupId) && selected.groupId === osDefault.groupId;
  if (sameDevice) return { mismatch: false, message: null };

  const name = selected.label || 'the selected microphone';
  return {
    mismatch: true,
    message:
      `Voice detection uses ${name}, but browser speech recognition always records your operating system's default input. ` +
      'Until they are the same device, the level meter can move while nothing is transcribed. ' +
      `Either make ${name} the default input in your OS sound settings, or set HomePilot's microphone to System default.`,
  };
}

/** Sentence spoken by the text-to-speech test. */
export const TTS_TEST_SENTENCE =
  'Text to speech is working. This is the voice HomePilot will use for replies.';

/**
 * How long to wait for `speechSynthesis` to fire `onstart` before declaring the
 * test failed.
 *
 * `speechSynthesis.speak()` resolves nothing and reports no error when it
 * cannot produce audio — a missing voice, a muted output, or a Chromium
 * autoplay block all look like success. Only the absence of `onstart` exposes
 * it, so the test needs its own deadline.
 */
export const TTS_START_TIMEOUT_MS = 4000;

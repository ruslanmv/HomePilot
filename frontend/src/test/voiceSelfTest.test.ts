/**
 * The logic that turns a silent browser into an actionable sentence.
 *
 * These are the cases behind the bug report "voice recording does not convert
 * audio to text": the trace showed `stt_onend { hadResult: false }` with no
 * interim, no result and no error, which on its own names none of the three
 * very different causes below.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import {
  TTS_START_TIMEOUT_MS,
  TTS_TEST_SENTENCE,
  describeMicrophoneRouting,
  explainSttError,
  explainSttOutcome,
  getSpeechRecognitionCtor,
  isSpeechRecognitionSupported,
  isSpeechSynthesisSupported,
} from '../ui/media/voiceSelfTest';

const device = (over: Partial<MediaDeviceInfo>): MediaDeviceInfo => ({
  deviceId: 'id',
  groupId: 'group',
  kind: 'audioinput',
  label: 'Microphone',
  toJSON: () => ({}),
  ...over,
} as MediaDeviceInfo);

describe('explainSttOutcome', () => {
  it('passes when a transcript came back', () => {
    const outcome = explainSttOutcome({ sawAudioStart: true, sawSpeechStart: true }, '  hello there ');
    expect(outcome.ok).toBe(true);
    expect(outcome.headline).toContain('working');
    // Length, not the words: the verdict must not leak transcript into logs.
    expect(outcome.detail).toContain('11 character');
  });

  it('blames the capture when recognition never received audio', () => {
    const outcome = explainSttOutcome({ sawAudioStart: false }, '');
    expect(outcome.ok).toBe(false);
    expect(outcome.headline).toBe('Recognition never received audio');
    expect(outcome.detail).toContain('permission');
  });

  it('names the OS-default routing split when audio was captured but silent', () => {
    const outcome = explainSttOutcome({ sawAudioStart: true, sawSpeechStart: false }, '');
    expect(outcome.ok).toBe(false);
    // Headlined as the user's symptom rather than the API's event. "Recognition captured
    // silence" describes what `SpeechRecognition` reported; "Microphone not hearing you" is
    // the thing the reader came to find out.
    expect(outcome.headline).toBe('Microphone not hearing you');
    expect(outcome.detail).toContain('no speech was found');
    expect(outcome.detail).toContain('allowed for this site');
  });

  it('points at the language when speech was heard but not matched', () => {
    const outcome = explainSttOutcome(
      { sawAudioStart: true, sawSpeechStart: true, sawNoMatch: true },
      '',
    );
    expect(outcome.ok).toBe(false);
    expect(outcome.detail).toContain('language');
  });

  it('points at an early stop when speech was heard and nothing was returned', () => {
    const outcome = explainSttOutcome({ sawAudioStart: true, sawSpeechStart: true }, '');
    expect(outcome.ok).toBe(false);
    expect(outcome.detail).toContain('stopped too early');
  });

  it('prefers a reported error over any inference', () => {
    const outcome = explainSttOutcome({ sawAudioStart: false, error: 'not-allowed' }, '');
    expect(outcome.headline).toBe('Microphone permission blocked');
  });
});

describe('explainSttError', () => {
  it('explains that Chrome speech recognition needs the network', () => {
    expect(explainSttError('network').detail).toContain('internet access');
  });

  it('explains the single-session limit behind InvalidStateError', () => {
    const outcome = explainSttError('InvalidStateError');
    expect(outcome.headline).toContain('already open');
    expect(outcome.detail).toContain('one speech recognition at a time');
  });

  it('still returns an actionable verdict for an unknown code', () => {
    const outcome = explainSttError('some-new-code');
    expect(outcome.ok).toBe(false);
    expect(outcome.detail).toContain('some-new-code');
  });
});

describe('describeMicrophoneRouting', () => {
  it('stays quiet when HomePilot uses the system default', () => {
    expect(describeMicrophoneRouting([], '')).toEqual({
      mismatch: false, known: true, defaultLabel: null, message: null,
    });
  });

  it('stays quiet when the selected input IS the OS default', () => {
    const devices = [
      device({ deviceId: 'default', groupId: 'g-array', label: 'Default - Array' }),
      device({ deviceId: 'array-id', groupId: 'g-array', label: 'Microphone Array' }),
    ];
    expect(describeMicrophoneRouting(devices, 'array-id').mismatch).toBe(false);
  });

  it('warns when voice detection and recognition would use different microphones', () => {
    const devices = [
      device({ deviceId: 'default', groupId: 'g-headset', label: 'Default - Headset' }),
      device({ deviceId: 'headset-id', groupId: 'g-headset', label: 'Headset' }),
      device({ deviceId: 'array-id', groupId: 'g-array', label: 'Microphone Array' }),
    ];
    const routing = describeMicrophoneRouting(devices, 'array-id');
    expect(routing.mismatch).toBe(true);
    expect(routing.message).toContain('Microphone Array');
    expect(routing.message).toContain("operating system's default input");
    // The device on the *other* side of the split, named. Without this the user is told to
    // make their microphone the default without being told what is holding that slot now.
    expect(routing.defaultLabel).toBe('Headset');
    expect(routing.message).toContain('which is Headset');
  });

  it('names the default input even when the split cannot be judged', () => {
    // `known: false` means "cannot tell which input the OS prefers", which is not the same as
    // "cannot tell what it is called". A deaf turn on this machine still has somewhere useful
    // to point, so the label survives the outcome that reports nothing else.
    const devices = [
      device({ deviceId: 'default', groupId: '', label: 'Default - Steam Streaming Microphone' }),
      device({ deviceId: 'array-id', groupId: '', label: 'Microphone Array' }),
    ];
    const routing = describeMicrophoneRouting(devices, 'array-id');
    expect(routing.defaultLabel).toBe('Steam Streaming Microphone');
  });

  it('strips Chrome’s alias prefix rather than repeating it', () => {
    // Chrome labels the alias "Default - X". Left in, every sentence reads "your system
    // default input, which is Default - X".
    const named = (label: string) => describeMicrophoneRouting(
      [device({ deviceId: 'default', label })],
      '',
    ).defaultLabel;
    expect(named('Default - Microphone (Realtek Audio)')).toBe('Microphone (Realtek Audio)');
    expect(named('Microphone (Realtek Audio)')).toBe('Microphone (Realtek Audio)');
    expect(named('')).toBeNull();
  });

  it('reports a saved microphone that is no longer connected', () => {
    const routing = describeMicrophoneRouting([device({ deviceId: 'default' })], 'unplugged-id');
    expect(routing.mismatch).toBe(false);
    expect(routing.message).toContain('not currently connected');
  });

  it('does not guess when the browser exposes no default alias', () => {
    // Still silent — a warning about a mismatch that may not exist is noise — but `known`
    // is false, so nothing downstream may report this as "the devices agree". Flattening
    // the two is what let a trace read `routingMismatch: false` on a machine where the
    // split was real and the browser recognizer was recording a silent device.
    const devices = [device({ deviceId: 'array-id', groupId: 'g-array' })];
    expect(describeMicrophoneRouting(devices, 'array-id')).toEqual({
      mismatch: false, known: false, defaultLabel: null, message: null,
    });
  });

  it('says it knows when the devices genuinely match', () => {
    const devices = [
      device({ deviceId: 'default', groupId: 'g-array' }),
      device({ deviceId: 'array-id', groupId: 'g-array' }),
    ];
    expect(describeMicrophoneRouting(devices, 'array-id').known).toBe(true);
  });
});

describe('capability probes', () => {
  it('accepts either the standard or the webkit-prefixed constructor', () => {
    expect(getSpeechRecognitionCtor({})).toBeNull();
    expect(isSpeechRecognitionSupported({})).toBe(false);

    const Ctor = class {};
    expect(getSpeechRecognitionCtor({ SpeechRecognition: Ctor })).toBe(Ctor);
    expect(getSpeechRecognitionCtor({ webkitSpeechRecognition: Ctor })).toBe(Ctor);
    expect(isSpeechRecognitionSupported({ webkitSpeechRecognition: Ctor })).toBe(true);
  });

  it('detects speech synthesis without throwing on a bare scope', () => {
    expect(isSpeechSynthesisSupported({})).toBe(false);
    expect(isSpeechSynthesisSupported({ speechSynthesis: {} })).toBe(true);
  });
});

describe('text-to-speech test constants', () => {
  it('keeps a deadline, because speechSynthesis reports no error for silence', () => {
    expect(TTS_START_TIMEOUT_MS).toBeGreaterThan(0);
    expect(TTS_TEST_SENTENCE.length).toBeGreaterThan(10);
  });
});

describe('resolveAssistantVoiceId', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('prefers the engine bucket when the TTS Engine section wrote a voice', async () => {
    const { resolveAssistantVoiceId } = await import('../ui/tts/resolveAssistantVoice');
    const resolved = resolveAssistantVoiceId('web-speech-api', { voiceId: 'Piper Amy' });
    expect(resolved).toBe('Piper Amy');
  });

  it('falls back to the voice the assistant actually speaks replies with', async () => {
    // The regression: on the default engine the TTS Engine section renders no
    // voice field, so its bucket stays empty and "Test voice" previewed the
    // browser default instead of the selected Assistant Voice.
    localStorage.setItem(
      'homepilot_voice_config',
      JSON.stringify({ voiceURI: 'Google US English' }),
    );
    const { resolveAssistantVoiceId } = await import('../ui/tts/resolveAssistantVoice');
    expect(resolveAssistantVoiceId('web-speech-api', {})).toBe('Google US English');
  });

  it('falls back to the legacy key when no voice config exists', async () => {
    localStorage.setItem('homepilot_voice_uri', 'Microsoft Zira - English (United States)');
    const { resolveAssistantVoiceId } = await import('../ui/tts/resolveAssistantVoice');
    expect(resolveAssistantVoiceId('web-speech-api', {})).toBe(
      'Microsoft Zira - English (United States)',
    );
  });

  it('never hands a browser voice name to a non-browser engine', async () => {
    localStorage.setItem('homepilot_voice_config', JSON.stringify({ voiceURI: 'Google US English' }));
    const { resolveAssistantVoiceId } = await import('../ui/tts/resolveAssistantVoice');
    expect(resolveAssistantVoiceId('piper-wasm', {})).toBe('');
  });
});

describe('describeAssistantVoice', () => {
  const voice = (name: string, lang: string): SpeechSynthesisVoice =>
    ({ name, lang, voiceURI: name, default: false, localService: true } as SpeechSynthesisVoice);

  it('labels the system default', async () => {
    const { describeAssistantVoice } = await import('../ui/tts/resolveAssistantVoice');
    expect(describeAssistantVoice('', [])).toBe('System default');
  });

  it('matches a stored voice name against the live voice list', async () => {
    const { describeAssistantVoice } = await import('../ui/tts/resolveAssistantVoice');
    expect(describeAssistantVoice('Google US English', [voice('Google US English', 'en-US')]))
      .toBe('Google US English (en-US)');
  });

  it('says so when the stored voice is gone from this browser', async () => {
    const { describeAssistantVoice } = await import('../ui/tts/resolveAssistantVoice');
    expect(describeAssistantVoice('Removed Voice', [])).toContain('not installed');
  });
});

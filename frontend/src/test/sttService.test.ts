/**
 * The selected-microphone transcription path.
 *
 * This replaces the split that caused the original bug: the VAD opened
 * `getUserMedia` on the microphone chosen in Audio & Video, while the browser's
 * `SpeechRecognition` takes no `deviceId` and always recorded the OS default
 * input. Posting a clip recorded from the selected device makes the two agree
 * by construction.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  SttUnavailableError,
  getSttCapability,
  resetSttCapabilityCache,
  transcribeBlob,
} from '../ui/media/sttService';

const okJson = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

describe('getSttCapability', () => {
  beforeEach(() => {
    resetSttCapabilityCache();
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    resetSttCapabilityCache();
  });

  it('reports what the server can transcribe with', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => okJson({
      available: true,
      provider: 'whisper-local',
      remote: false,
      hint: null,
    })));

    const capability = await getSttCapability();
    expect(capability).toEqual({
      available: true,
      provider: 'whisper-local',
      remote: false,
      hint: null,
    });
  });

  it('caches so a voice turn does not pay a round trip each time', async () => {
    const fetchMock = vi.fn(async () => okJson({ available: true, provider: 'whisper-local' }));
    vi.stubGlobal('fetch', fetchMock);

    await getSttCapability();
    await getSttCapability();

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('re-probes when forced', async () => {
    const fetchMock = vi.fn(async () => okJson({ available: true }));
    vi.stubGlobal('fetch', fetchMock);

    await getSttCapability();
    await getSttCapability({ force: true });

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('degrades to unavailable rather than throwing when the backend is down', async () => {
    // A client that cannot reach the server must fall back to the browser
    // recognizer, not break the microphone button.
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('ECONNREFUSED'); }));

    const capability = await getSttCapability();
    expect(capability.available).toBe(false);
    expect(capability.hint).toBeTruthy();
  });

  it('degrades to unavailable on a non-2xx status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => okJson({}, 500)));
    expect((await getSttCapability()).available).toBe(false);
  });

  it('flags a remote provider so the UI can warn before the user speaks', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => okJson({
      available: true,
      provider: 'openai-compat',
      remote: true,
    })));
    expect((await getSttCapability()).remote).toBe(true);
  });
});

describe('transcribeBlob', () => {
  afterEach(() => vi.restoreAllMocks());

  it('posts the recording and returns the transcript', async () => {
    const fetchMock = vi.fn(async () => okJson({
      text: '  turn the lights on  ',
      provider: 'whisper-local',
      remote: false,
      elapsed_ms: 412,
    }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await transcribeBlob(new Blob(['audio'], { type: 'audio/webm;codecs=opus' }));

    expect(result.text).toBe('turn the lights on');
    expect(result.provider).toBe('whisper-local');
    expect(result.elapsedMs).toBe(412);

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain('/v1/voice/transcribe');
    expect((init as RequestInit).method).toBe('POST');
    expect((init as RequestInit).body).toBeInstanceOf(FormData);
  });

  it('sends the container so the server can pick a decoder', async () => {
    const fetchMock = vi.fn(async () => okJson({ text: 'hi' }));
    vi.stubGlobal('fetch', fetchMock);

    await transcribeBlob(new Blob(['audio'], { type: 'audio/webm;codecs=opus' }));

    const body = (fetchMock.mock.calls[0][1] as RequestInit).body as FormData;
    expect(body.get('format')).toBe('webm');
    expect(body.get('audio')).toBeTruthy();
  });

  it('returns empty text for silence rather than raising', async () => {
    // A successful transcription of silence is a different fact from a failure,
    // and the caller has to be able to tell the user which happened.
    vi.stubGlobal('fetch', vi.fn(async () => okJson({ text: '   ' })));
    expect((await transcribeBlob(new Blob(['a']))).text).toBe('');
  });

  it('raises SttUnavailableError on 503 so the caller can fall back', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => okJson({
      detail: {
        error: 'speech-to-text not available on this server',
        hint: 'Install local speech',
        capability: { available: false },
      },
    }, 503)));

    await expect(transcribeBlob(new Blob(['a']))).rejects.toBeInstanceOf(SttUnavailableError);
  });

  it('carries the server hint into the error message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => okJson({
      detail: { error: 'transcription failed: ffmpeg missing' },
    }, 502)));

    await expect(transcribeBlob(new Blob(['a']))).rejects.toThrow(/ffmpeg missing/);
  });

  it('does not pretend to succeed on an unexpected status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => okJson(null, 404)));
    await expect(transcribeBlob(new Blob(['a']))).rejects.toThrow(/404/);
  });
});

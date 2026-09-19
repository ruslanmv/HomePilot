/**
 * One engine and one microphone owner, shared by every surface.
 *
 * Settings offers Browser / On this computer / Automatic as a single choice for the chat
 * composer and the Voice tab. The implementation used to keep three copies of that decision —
 * one in the controller, one in the composer, one per capability probe — so a recovery in one
 * surface was invisible to the other, and, far worse, hands-free Voice could hold HomePilot's
 * capture open on the selected microphone while the browser recognizer opened the operating
 * system's default input. Two devices, one turn, no error from either.
 *
 * These tests are about the object that makes that unrepresentable.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const capability = vi.fn();

vi.mock('../ui/media/sttService', () => ({
  getSttCapability: (...args: unknown[]) => capability(...(args as [])),
  resetSttCapabilityCache: vi.fn(),
  transcribeBlob: vi.fn(),
  openSelectedMicrophone: vi.fn(),
  recordAndTranscribe: vi.fn(),
  SttUnavailableError: class SttUnavailableError extends Error {},
}));

import {
  acquireMicrophone,
  applySttSessionOverride,
  clearSttSessionOverride,
  ensureSttRuntimeResolved,
  getMicrophoneLease,
  getSttRuntime,
  releaseMicrophone,
  rememberRecognizerIsDeaf,
  resetSttRuntimeForTests,
  subscribeSttRuntime,
} from '../ui/media/sttRuntime';
import { setSttPreferences, STT_PREFERENCES_STORAGE_KEY } from '../ui/media/sttPreferences';
import { MEDIA_PREFERENCES_STORAGE_KEY } from '../ui/media/mediaPreferences';

const LOCAL = { available: true, provider: 'whisper-local', remote: false, hint: null };
const NO_MODEL = { available: false, provider: null, remote: false, hint: null };

const enumerateDevices = vi.fn(async () => [] as MediaDeviceInfo[]);

/** An input list shaped like Chrome's: a `default` alias plus the real devices. */
function devices(defaultGroup: string, others: Array<[string, string]> = []) {
  return [
    { deviceId: 'default', kind: 'audioinput', label: 'Default', groupId: defaultGroup },
    ...others.map(([deviceId, groupId]) => ({
      deviceId, kind: 'audioinput', label: deviceId, groupId,
    })),
  ] as unknown as MediaDeviceInfo[];
}

function selectMicrophone(deviceId: string) {
  localStorage.setItem(
    MEDIA_PREFERENCES_STORAGE_KEY,
    JSON.stringify({ microphoneDeviceId: deviceId }),
  );
}

beforeEach(() => {
  localStorage.clear();
  resetSttRuntimeForTests();
  capability.mockClear();
  capability.mockResolvedValue(LOCAL);
  enumerateDevices.mockReset();
  enumerateDevices.mockResolvedValue([]);

  (window as unknown as { SpeechRecognition: unknown }).SpeechRecognition = class {};
  (globalThis as unknown as { MediaRecorder: unknown }).MediaRecorder = class {};
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn(), enumerateDevices },
  });
});

describe('resolving the engine', () => {
  it('opens nothing until the probe answers', () => {
    // `pending`, not "assume the browser and correct later". That default is what sent the
    // first sentence of a session — the one that matters most — through an engine the user
    // did not choose, purely because a status request was still in flight.
    expect(getSttRuntime().status).toBe('pending');
    expect(getSttRuntime().effectiveEngine).toBeNull();
  });

  it('lets the preference decide and the capability only constrain', async () => {
    localStorage.setItem(STT_PREFERENCES_STORAGE_KEY, JSON.stringify({ chat: 'homepilot' }));
    const runtime = await ensureSttRuntimeResolved();

    expect(runtime.status).toBe('ready');
    expect(runtime.effectiveEngine).toBe('homepilot-backend');
    expect(runtime.resolution?.fellBack).toBe(false);
  });

  it('reports a fallback rather than hiding it', async () => {
    // Somebody who picked on-device transcription for privacy must never be quietly served
    // the browser's, which sends audio to Google.
    capability.mockResolvedValue(NO_MODEL);
    localStorage.setItem(STT_PREFERENCES_STORAGE_KEY, JSON.stringify({ chat: 'homepilot' }));
    const runtime = await ensureSttRuntimeResolved();

    expect(runtime.effectiveEngine).toBe('web-speech');
    expect(runtime.resolution?.fellBack).toBe(true);
  });

  it('answers concurrent callers with one probe', async () => {
    // Chat and Voice mounting together must not race to two different engines.
    const [a, b] = await Promise.all([ensureSttRuntimeResolved(), ensureSttRuntimeResolved()]);
    expect(capability).toHaveBeenCalledTimes(1);
    expect(a.effectiveEngine).toBe(b.effectiveEngine);
  });
});

describe('the routing preflight', () => {
  /*
   * `SpeechRecognition` records the operating system's default input and accepts no
   * `deviceId`. When the microphone chosen in Audio & Video is a different device, a browser
   * turn records a microphone nobody is speaking into — and reports no error, because it
   * faithfully transcribed a silent room.
   *
   * The device list says so before the first turn. Learning it from two failed turns instead
   * is the difference between a product that works and one that has to be debugged.
   */
  it('does not open a capture it can already tell will be deaf', async () => {
    enumerateDevices.mockResolvedValue(devices('group-builtin', [['usb-mic', 'group-usb']]));
    selectMicrophone('usb-mic');

    const runtime = await ensureSttRuntimeResolved();

    expect(runtime.resolution?.engine).toBe('web-speech');
    expect(runtime.effectiveEngine).toBe('homepilot-backend');
    expect(runtime.sessionOverrideMessage).toContain('system default');
  });

  it('says so, because it changes which service sees the audio', async () => {
    enumerateDevices.mockResolvedValue(devices('group-builtin', [['usb-mic', 'group-usb']]));
    selectMicrophone('usb-mic');

    const runtime = await ensureSttRuntimeResolved();

    expect(runtime.sessionOverrideMessage).toContain('Speech Recognition');
  });

  it('leaves a matching device alone', async () => {
    // Same physical device as the OS default, so the recognizer hears exactly what the user
    // selected and there is nothing to fix.
    enumerateDevices.mockResolvedValue(devices('group-builtin', [['builtin', 'group-builtin']]));
    selectMicrophone('builtin');

    expect((await ensureSttRuntimeResolved()).effectiveEngine).toBe('web-speech');
  });

  it('leaves the system default alone', async () => {
    enumerateDevices.mockResolvedValue(devices('group-builtin', [['usb-mic', 'group-usb']]));
    // No explicit selection: the recognizer and HomePilot both follow the OS.
    expect((await ensureSttRuntimeResolved()).effectiveEngine).toBe('web-speech');
  });

  it('does nothing when the browser cannot say what the default is', async () => {
    // No `default` alias to compare against — Chrome on Windows often exposes none. That is
    // "cannot tell", not "they agree", and acting on it would move sessions on no evidence.
    enumerateDevices.mockResolvedValue([
      { deviceId: 'usb-mic', kind: 'audioinput', label: 'USB', groupId: 'group-usb' },
    ] as unknown as MediaDeviceInfo[]);
    selectMicrophone('usb-mic');

    const runtime = await ensureSttRuntimeResolved();
    expect(runtime.effectiveEngine).toBe('web-speech');
    expect(runtime.routing?.known).toBe(false);
  });

  it('does nothing when there is no engine to move to', async () => {
    capability.mockResolvedValue(NO_MODEL);
    enumerateDevices.mockResolvedValue(devices('group-builtin', [['usb-mic', 'group-usb']]));
    selectMicrophone('usb-mic');

    expect((await ensureSttRuntimeResolved()).effectiveEngine).toBe('web-speech');
  });

  it('survives a browser that refuses to enumerate devices', async () => {
    enumerateDevices.mockRejectedValue(new Error('NotAllowedError'));
    selectMicrophone('usb-mic');

    const runtime = await ensureSttRuntimeResolved();
    expect(runtime.status).toBe('ready');
    expect(runtime.effectiveEngine).toBe('web-speech');
  });

  it('remembers a verdict a turn established, where the device list cannot tell', async () => {
    /*
     * On Chrome for Windows there is often no `default` alias, so the split is real and
     * undetectable from the device list. The only thing that establishes it is a turn — the
     * user presses record, speaks, and the recognizer reports it opened a capture and heard
     * nothing.
     *
     * Paying for that once is reasonable. Paying for it on every page load is what was
     * happening: each reload offered the browser recognizer again and burned the user's first
     * sentence proving the same fact.
     */
    enumerateDevices.mockResolvedValue([
      { deviceId: 'usb-mic', kind: 'audioinput', label: 'USB', groupId: 'group-usb' },
    ] as unknown as MediaDeviceInfo[]);
    selectMicrophone('usb-mic');
    expect((await ensureSttRuntimeResolved()).effectiveEngine).toBe('web-speech');

    rememberRecognizerIsDeaf();
    resetSttRuntimeForTests(); // a new page load; the memory outlives it

    const runtime = await ensureSttRuntimeResolved();
    expect(runtime.effectiveEngine).toBe('homepilot-backend');
    // Not the paragraph explaining the mechanism — that was said when it was discovered, and
    // repeating it on every load is its own kind of noise.
    expect(runtime.sessionOverrideMessage).toContain('could not hear this microphone last time');
  });

  it('re-evaluates a different microphone', async () => {
    // The verdict is about a device, not about the browser. Selecting another one is a new
    // question, and answering it from the old memory would strand a user who fixed the fault.
    selectMicrophone('usb-mic');
    rememberRecognizerIsDeaf();

    selectMicrophone('headset');
    resetSttRuntimeForTests();

    expect((await ensureSttRuntimeResolved()).effectiveEngine).toBe('web-speech');
  });

  it('forgets the verdict when the user picks an engine again', async () => {
    // Otherwise a remembered verdict is not a memory — it is the choice being refused, for
    // good, on every future load.
    selectMicrophone('usb-mic');
    rememberRecognizerIsDeaf();
    await ensureSttRuntimeResolved();
    expect(getSttRuntime().effectiveEngine).toBe('homepilot-backend');

    setSttPreferences({ chat: 'web-speech' });
    await ensureSttRuntimeResolved({ force: true });
    resetSttRuntimeForTests();

    expect((await ensureSttRuntimeResolved()).effectiveEngine).toBe('web-speech');
  });

  it('stands down once the user insists on an engine', async () => {
    // Otherwise "Browser" would be unselectable for the session on any machine whose default
    // input differs — the preflight would re-apply on every resolve, and a default you cannot
    // override is the choice being taken away rather than a default.
    enumerateDevices.mockResolvedValue(devices('group-builtin', [['usb-mic', 'group-usb']]));
    selectMicrophone('usb-mic');
    expect((await ensureSttRuntimeResolved()).effectiveEngine).toBe('homepilot-backend');

    setSttPreferences({ chat: 'web-speech' });
    await ensureSttRuntimeResolved({ force: true });

    expect(getSttRuntime().effectiveEngine).toBe('web-speech');
    expect(getSttRuntime().sessionOverride).toBeNull();
  });

  it('keeps an explicit browser choice after a reload despite a routing mismatch', async () => {
    enumerateDevices.mockResolvedValue(devices('group-builtin', [['usb-mic', 'group-usb']]));
    selectMicrophone('usb-mic');

    setSttPreferences({ chat: 'web-speech' });
    await ensureSttRuntimeResolved({ force: true });
    resetSttRuntimeForTests(); // simulate a page reload while localStorage survives

    const runtime = await ensureSttRuntimeResolved();
    expect(runtime.preference).toBe('web-speech');
    expect(runtime.effectiveEngine).toBe('web-speech');
    expect(runtime.sessionOverrideMessage).toBeNull();
  });
});

describe('a session override', () => {
  it('is the engine in every surface at once', async () => {
    await ensureSttRuntimeResolved();
    const seen: (string | null)[] = [];
    subscribeSttRuntime((next) => seen.push(next.effectiveEngine));

    applySttSessionOverride('homepilot-backend', 'switched', 'chat');

    expect(getSttRuntime().effectiveEngine).toBe('homepilot-backend');
    // A subscriber is how the other surface finds out; polling its own copy is what let the
    // two disagree.
    expect(seen).toContain('homepilot-backend');
  });

  it('leaves the stored preference alone', async () => {
    await ensureSttRuntimeResolved();
    applySttSessionOverride('homepilot-backend', 'switched', 'voice');

    // A heuristic reacting to two bad turns has no business permanently overruling a choice.
    expect(getSttRuntime().preference).toBe('web-speech');
    expect(localStorage.getItem(STT_PREFERENCES_STORAGE_KEY)).toBeNull();
  });

  it('is refused when there is nothing to switch to', async () => {
    capability.mockResolvedValue(NO_MODEL);
    await ensureSttRuntimeResolved();
    applySttSessionOverride('homepilot-backend', 'switched', 'voice');

    expect(getSttRuntime().effectiveEngine).toBe('web-speech');
  });

  it('is cleared by a deliberate choice in Settings', async () => {
    await ensureSttRuntimeResolved();
    applySttSessionOverride('homepilot-backend', 'switched', 'voice');

    setSttPreferences({ chat: 'web-speech' });
    await ensureSttRuntimeResolved({ force: true });

    expect(getSttRuntime().sessionOverride).toBeNull();
    expect(getSttRuntime().effectiveEngine).toBe('web-speech');
  });

  it('can be dropped without re-probing', async () => {
    await ensureSttRuntimeResolved();
    applySttSessionOverride('homepilot-backend', 'switched', 'voice');
    clearSttSessionOverride();

    expect(getSttRuntime().effectiveEngine).toBe('web-speech');
  });
});

describe('microphone ownership', () => {
  it('releases the previous holder before granting the next', async () => {
    const order: string[] = [];
    await acquireMicrophone('voice', 'homepilot-backend', () => { order.push('voice-released'); });
    await acquireMicrophone('chat', 'web-speech', () => { order.push('chat-released'); });
    order.push('chat-acquired');

    // The release must land *before* the new owner is live: overlapping captures on one
    // device is the failure this registry exists to prevent.
    expect(order).toEqual(['voice-released', 'chat-acquired']);
    expect(getMicrophoneLease()).toEqual({ owner: 'chat', engine: 'web-speech' });
  });

  it('waits for a release that takes a moment', async () => {
    let released = false;
    await acquireMicrophone('voice', 'homepilot-backend', async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
      released = true;
    });
    await acquireMicrophone('chat', 'web-speech', () => {});

    expect(released).toBe(true);
  });

  it('treats an engine change by one owner as a hand-off', async () => {
    // Browser → on this computer is two different capture architectures. The old one has to
    // be gone before the new one opens, even within a single surface.
    const released: string[] = [];
    await acquireMicrophone('voice', 'web-speech', () => { released.push('web-speech'); });
    await acquireMicrophone('voice', 'homepilot-backend', () => { released.push('backend'); });

    expect(released).toEqual(['web-speech']);
    expect(getMicrophoneLease()?.engine).toBe('homepilot-backend');
  });

  it('ignores a release from a surface that no longer holds it', async () => {
    const released: string[] = [];
    await acquireMicrophone('voice', 'web-speech', () => { released.push('voice'); });
    await acquireMicrophone('chat', 'web-speech', () => { released.push('chat'); });
    released.length = 0;

    // A stale teardown from the surface that already handed over must not shut the current
    // owner's capture down.
    await releaseMicrophone('voice');

    expect(released).toEqual([]);
    expect(getMicrophoneLease()?.owner).toBe('chat');
  });

  it('survives a teardown that throws', async () => {
    await acquireMicrophone('voice', 'homepilot-backend', () => {
      throw new Error('track already stopped');
    });
    await acquireMicrophone('chat', 'web-speech', () => {});

    expect(getMicrophoneLease()?.owner).toBe('chat');
  });

  it('leaves nobody holding the microphone after a release', async () => {
    await acquireMicrophone('voice', 'homepilot-backend', () => {});
    await releaseMicrophone('voice');

    expect(getMicrophoneLease()).toBeNull();
  });
});

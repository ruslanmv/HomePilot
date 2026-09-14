/**
 * Choosing a speech-to-text engine per surface.
 *
 * Preferring the local engine whenever it reported itself *available* is what broke chat
 * speech-to-text on a machine whose CUDA runtime was present but incomplete: the provider
 * answered "available" and then failed every turn, while the browser path would have worked.
 * Availability is not suitability, so the preference decides and the capability only
 * constrains — and every combination of the two has to produce a defined answer.
 *
 * The rule that matters most: a fallback is always *reported*. Somebody who chose on-device
 * transcription for privacy and is quietly served the browser's — which ships audio to
 * Google — has been failed in a way no later message makes up for.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_STT_PREFERENCES,
  STT_PREFERENCES_STORAGE_KEY,
  describeSttResolution,
  getSttPreferences,
  resolveSttEngine,
  setSttPreferences,
  subscribeSttPreferences,
  type SttEngineSupport,
} from '../ui/media/sttPreferences';

const support = (over: Partial<SttEngineSupport> = {}): SttEngineSupport => ({
  backendAvailable: true,
  mediaRecorderSupported: true,
  webSpeechSupported: true,
  ...over,
});

describe('the stored preference', () => {
  beforeEach(() => localStorage.clear());

  it('defaults to the browser, which is what HomePilot behaved like before', () => {
    // A default that works everywhere beats a better default that works on some machines.
    expect(DEFAULT_STT_PREFERENCES.chat).toBe('web-speech');
    expect(getSttPreferences().chat).toBe('web-speech');
  });

  it('round-trips a choice', () => {
    setSttPreferences({ chat: 'homepilot' });
    expect(getSttPreferences().chat).toBe('homepilot');
  });

  it('falls back to the default for anything unrecognised', () => {
    localStorage.setItem(STT_PREFERENCES_STORAGE_KEY, JSON.stringify({ chat: 'wishful' }));
    expect(getSttPreferences().chat).toBe('web-speech');
  });

  it('survives corrupt storage', () => {
    localStorage.setItem(STT_PREFERENCES_STORAGE_KEY, '{not json');
    expect(getSttPreferences().chat).toBe('web-speech');
  });

  it('tells every surface, so Settings and Voice never disagree', () => {
    const seen = vi.fn();
    const stop = subscribeSttPreferences(seen);
    setSttPreferences({ chat: 'auto' });
    expect(seen).toHaveBeenCalledWith({ chat: 'auto' });
    stop();
    setSttPreferences({ chat: 'homepilot' });
    expect(seen).toHaveBeenCalledTimes(1);
  });
});

describe('resolveSttEngine', () => {
  describe('browser chosen', () => {
    it('runs the browser even when a local model is installed', () => {
      // The regression this whole split exists to stop: the local engine must not win just
      // because it is there.
      const r = resolveSttEngine('web-speech', support({ backendAvailable: true }));
      expect(r).toEqual({
        engine: 'web-speech', reason: 'preferred', fellBack: false, usable: true,
      });
    });

    it('stands in with the local engine where no recognizer exists', () => {
      // Firefox and Safari implement none, so this is the only way voice input works there.
      const r = resolveSttEngine('web-speech', support({ webSpeechSupported: false }));
      expect(r.engine).toBe('homepilot-backend');
      expect(r.reason).toBe('web-speech-unsupported');
      expect(r.fellBack).toBe(true);
    });

    it('reports nothing usable when neither path can run', () => {
      const r = resolveSttEngine('web-speech', support({
        webSpeechSupported: false, backendAvailable: false,
      }));
      expect(r.usable).toBe(false);
      expect(r.reason).toBe('none');
    });
  });

  describe('on this computer chosen', () => {
    it('runs the local engine', () => {
      const r = resolveSttEngine('homepilot', support());
      expect(r.engine).toBe('homepilot-backend');
      expect(r.fellBack).toBe(false);
    });

    it('falls back and says the server has no model', () => {
      const r = resolveSttEngine('homepilot', support({ backendAvailable: false }));
      expect(r.engine).toBe('web-speech');
      expect(r.reason).toBe('backend-unavailable');
      expect(r.fellBack).toBe(true);
    });

    it('distinguishes a browser that cannot record from a server with no model', () => {
      // "Install a model" and "this browser cannot record" need different actions.
      const r = resolveSttEngine('homepilot', support({ mediaRecorderSupported: false }));
      expect(r.reason).toBe('recorder-unsupported');
      expect(r.fellBack).toBe(true);
    });

    it('never claims to be usable when the fallback cannot run either', () => {
      const r = resolveSttEngine('homepilot', support({
        backendAvailable: false, webSpeechSupported: false,
      }));
      expect(r.usable).toBe(false);
    });
  });

  describe('automatic', () => {
    it('takes the local engine when it is genuinely usable', () => {
      const r = resolveSttEngine('auto', support());
      expect(r.engine).toBe('homepilot-backend');
      expect(r.reason).toBe('auto-backend');
    });

    it('takes the browser otherwise', () => {
      const r = resolveSttEngine('auto', support({ backendAvailable: false }));
      expect(r.engine).toBe('web-speech');
      expect(r.reason).toBe('auto-web-speech');
    });

    it('is not a fallback when it chooses — choosing is the job', () => {
      expect(resolveSttEngine('auto', support({ backendAvailable: false })).fellBack).toBe(false);
      expect(resolveSttEngine('auto', support()).fellBack).toBe(false);
    });

    it('needs a recorder before it picks the local engine', () => {
      const r = resolveSttEngine('auto', support({ mediaRecorderSupported: false }));
      expect(r.engine).toBe('web-speech');
    });
  });

  it('always answers, for every combination', () => {
    // Exhaustive rather than representative: an undefined corner here is a dead microphone.
    for (const preference of ['web-speech', 'homepilot', 'auto'] as const) {
      for (const backendAvailable of [true, false]) {
        for (const mediaRecorderSupported of [true, false]) {
          for (const webSpeechSupported of [true, false]) {
            const r = resolveSttEngine(preference, {
              backendAvailable, mediaRecorderSupported, webSpeechSupported,
            });
            expect(['web-speech', 'homepilot-backend']).toContain(r.engine);
            expect(typeof r.usable).toBe('boolean');
            // A resolution that is usable must name an engine that can actually run.
            if (r.usable && r.engine === 'homepilot-backend') {
              expect(backendAvailable && mediaRecorderSupported).toBe(true);
            }
            if (r.usable && r.engine === 'web-speech') {
              expect(webSpeechSupported).toBe(true);
            }
          }
        }
      }
    }
  });
});

describe('describeSttResolution', () => {
  it('names the provider and the microphone rule for the local engine', () => {
    const text = describeSttResolution(
      resolveSttEngine('homepilot', support()), 'whisper-local',
    );
    expect(text).toContain('whisper-local');
    expect(text).toContain('Audio & Video');
  });

  it('warns that the browser uses the system default input', () => {
    const text = describeSttResolution(resolveSttEngine('web-speech', support()), null);
    expect(text).toContain('system default input');
  });

  it('says plainly when the choice was overridden, and why', () => {
    const text = describeSttResolution(
      resolveSttEngine('homepilot', support({ backendAvailable: false })), null,
    );
    expect(text).toContain('You chose HomePilot transcription');
    expect(text).toContain('no speech model');
  });

  it('says when nothing at all can transcribe', () => {
    const text = describeSttResolution(
      resolveSttEngine('web-speech', support({
        webSpeechSupported: false, backendAvailable: false,
      })),
      null,
    );
    expect(text).toContain('No speech-to-text is available');
  });
});

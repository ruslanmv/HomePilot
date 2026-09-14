/**
 * Real-time meeting transcription: provisional reads of an utterance still being spoken.
 *
 * Everything about `partial` frames was already built except the one thing that triggers
 * them. The server's `on_partial` transcribes, emits `{type:'partial'}` and stores nothing;
 * the client re-emits it as `ms:partial`; `view.partial` holds it and both MeetingCard and
 * MeetingWorkspace render it as a provisional line. The recorder never sent one, so the
 * transcript only moved when an utterance *closed* — a 350 ms pause, or the 8 s hard cut for
 * somebody speaking without pausing.
 *
 * These tests pin the sending half, and the three rules that stop provisional text from
 * costing the transcript that gets kept.
 */

import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const SHIPPED = resolve(ROOT, 'frontend/public/js/homepilot-meetingsense.js');

let ms;

beforeAll(() => {
  // eslint-disable-next-line no-new-func
  new Function(readFileSync(SHIPPED, 'utf8')).call(window);
  ms = window.hpMeetingSense.internals;
});

/** One 20 ms frame at `level`, as a single channel. */
const frameAt = (level, samples = 320) => [new Float32Array(samples).fill(level)];

const LOUD = 0.25;
const QUIET = 0;

/** Feed `ms` worth of frames, collecting whatever the segmenter hands back. */
function feed(segmenter, level, durationMs, startMs = 0, onTick) {
  const frameMs = segmenter.frameMs;
  let t = startMs;
  const closed = [];
  for (let elapsed = 0; elapsed < durationMs; elapsed += frameMs) {
    const utterance = segmenter.push(frameAt(level), t);
    if (utterance) closed.push(utterance);
    if (onTick) onTick(t);
    t += frameMs;
  }
  return { closed, endMs: t };
}

describe('Segmenter.takePartial', () => {
  let segmenter;

  beforeEach(() => {
    segmenter = new ms.Segmenter({});
  });

  it('offers nothing while nobody is talking', () => {
    feed(segmenter, QUIET, 2000);
    expect(segmenter.takePartial(2000)).toBeNull();
  });

  it('offers nothing until there is enough audio to hold words', () => {
    // 400 ms of speech is below both MIN_PARTIAL_MS and the first-partial gate.
    const { endMs } = feed(segmenter, LOUD, 400);
    expect(segmenter.takePartial(endMs)).toBeNull();
  });

  it('offers a snapshot of the utterance still being spoken', () => {
    const { endMs } = feed(segmenter, LOUD, 1400);
    const partial = segmenter.takePartial(endMs);

    expect(partial).not.toBeNull();
    expect(partial.frames.length).toBeGreaterThan(0);
    expect(partial.t1).toBeGreaterThan(partial.t0);
    // Still open: nothing has been closed, so this is provisional by construction.
    expect(segmenter._inSpeech).toBe(true);
  });

  it('copies the frames, so the WAV encoder cannot race the speaker', () => {
    // The array the snapshot comes from keeps being appended to while the person talks. A
    // snapshot that mutated underneath the encoder is a transcript bug nobody would find.
    const { endMs } = feed(segmenter, LOUD, 1400);
    const partial = segmenter.takePartial(endMs);
    const captured = partial.frames.length;

    feed(segmenter, LOUD, 400, endMs);

    expect(partial.frames.length).toBe(captured);
    expect(segmenter._frames.length).toBeGreaterThan(captured);
  });

  it('rate-limits to one read per PARTIAL_EVERY_MS', () => {
    const { endMs } = feed(segmenter, LOUD, 1400);
    expect(segmenter.takePartial(endMs)).not.toBeNull();

    // Immediately after, and a little after, are both too soon.
    expect(segmenter.takePartial(endMs)).toBeNull();
    expect(segmenter.takePartial(endMs + ms.constants.PARTIAL_EVERY_MS - 20)).toBeNull();
    expect(segmenter.takePartial(endMs + ms.constants.PARTIAL_EVERY_MS)).not.toBeNull();
  });

  it('gives a long monologue live text instead of eight seconds of nothing', () => {
    // The case that reads as broken: someone talks straight through, so no silence close
    // fires and the first real segment waits for HARD_CUT_MS.
    const partials = [];
    const { closed } = feed(segmenter, LOUD, 7000, 0, (t) => {
      const partial = segmenter.takePartial(t);
      if (partial) partials.push(partial);
    });

    expect(closed).toHaveLength(0); // nothing closed inside the hard cut
    expect(partials.length).toBeGreaterThanOrEqual(4);
    // Each read covers more of the utterance than the last.
    for (let i = 1; i < partials.length; i += 1) {
      expect(partials[i].t1).toBeGreaterThan(partials[i - 1].t1);
    }
  });

  it('starts over once the utterance closes', () => {
    const { endMs } = feed(segmenter, LOUD, 1400);
    expect(segmenter.takePartial(endMs)).not.toBeNull();

    // Close it on silence, then talk again.
    const after = feed(segmenter, QUIET, 600, endMs);
    expect(after.closed).toHaveLength(1);

    const next = feed(segmenter, LOUD, 1400, after.endMs);
    // The new utterance gets its own first read rather than inheriting the old clock.
    expect(segmenter.takePartial(next.endMs)).not.toBeNull();
  });

  it('honours an explicit cadence, so the recorder can be tuned or tested', () => {
    const fast = new ms.Segmenter({ partialEveryMs: 200, minPartialMs: 100 });
    const { endMs } = feed(fast, LOUD, 400);
    expect(fast.takePartial(endMs)).not.toBeNull();
    expect(fast.takePartial(endMs + 200)).not.toBeNull();
  });
});

describe('micConstraints', () => {
  beforeEach(() => localStorage.clear());

  it('defaults to processed audio on the system default input', () => {
    // Matches DEFAULT_MEDIA_PREFERENCES; no deviceId means "whatever the OS uses".
    expect(ms.micConstraints()).toEqual({
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    });
  });

  it('records the microphone chosen in Settings, not the OS default', () => {
    // The bug this fixes: a meeting recorded an hour from the wrong input while the level
    // meter moved, because the meter reads this same stream.
    localStorage.setItem('homepilot_media_preferences_v1', JSON.stringify({
      microphoneDeviceId: 'intel-array-id',
    }));
    expect(ms.micConstraints().deviceId).toEqual({ exact: 'intel-array-id' });
  });

  it('respects the three processing toggles instead of hardcoding them', () => {
    localStorage.setItem('homepilot_media_preferences_v1', JSON.stringify({
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
    }));
    expect(ms.micConstraints()).toEqual({
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
    });
  });

  it('ignores an empty device id rather than sending an unsatisfiable constraint', () => {
    localStorage.setItem('homepilot_media_preferences_v1', JSON.stringify({
      microphoneDeviceId: '',
    }));
    expect(ms.micConstraints().deviceId).toBeUndefined();
  });

  it('survives corrupt or absent storage', () => {
    localStorage.setItem('homepilot_media_preferences_v1', '{not json');
    expect(ms.micConstraints().echoCancellation).toBe(true);
    localStorage.clear();
    expect(ms.micConstraints().echoCancellation).toBe(true);
  });

  it('ignores fields of the wrong type', () => {
    localStorage.setItem('homepilot_media_preferences_v1', JSON.stringify({
      echoCancellation: 'yes',
      microphoneDeviceId: 42,
    }));
    const constraints = ms.micConstraints();
    expect(constraints.echoCancellation).toBe(true);
    expect(constraints.deviceId).toBeUndefined();
  });
});

describe('the real-time contract, as source', () => {
  const source = readFileSync(SHIPPED, 'utf8');

  it('marks provisional frames with the flag the server reads', () => {
    expect(source).toContain('partial: true');
  });

  it('sends a partial straight down the socket, never through the queue', () => {
    // A partial arriving after its own utterance closed would overwrite real text with a
    // stale guess, so it must not be queued, retried, or counted in behind_ms.
    const sendPartial = source.slice(source.indexOf('_sendPartial(partial) {'));
    const body = sendPartial.slice(0, sendPartial.indexOf('\n        }'));
    expect(body).toContain('this._ws.send(');
    expect(body).not.toContain('this._queue.push(');
    expect(body).not.toContain('this._pump()');
  });

  it('keeps only one provisional read in flight, so a slow machine self-throttles', () => {
    expect(source).toContain('_partialInFlight');
    expect(source).toContain('PARTIAL_TIMEOUT_MS');
    // Released on the reply, on a real segment, and on reconnect — never left wedged.
    expect(source.match(/this\._partialInFlight = false/g).length).toBeGreaterThanOrEqual(4);
  });

  it('never spends a transcription while real audio is already waiting', () => {
    const wanted = source.slice(source.indexOf('_partialsWanted() {'));
    const body = wanted.slice(0, wanted.indexOf('\n        }'));
    expect(body).toContain('this._queue.length');
    expect(body).toContain('SOCKET_HIGH_WATER');
    expect(body).toContain('this.partialsDisabled');
  });

  it('tells the user when the selected microphone was not the one opened', () => {
    expect(source).toContain("emit('ms:mic_fallback'");
  });
});

describe('media capture: continuous audio from a shared tab or the machine', () => {
  /**
   * The workload the meeting recorder was never designed for. A shared YouTube tab never
   * goes quiet, so an utterance never closes on silence: every one is an 8 s hard cut, and
   * partials re-read a growing buffer ~6 times before the real chunk lands — roughly 4x
   * realtime of decoding per 1x of audio, which a CPU-only machine cannot sustain. Falling
   * behind is then what makes the queue shed, so the promise of a complete record fails
   * quietly.
   */

  it('switches to a short cadence once the audio is continuous', () => {
    const segmenter = new ms.Segmenter({});
    expect(segmenter.isMediaMode()).toBe(false);

    // Unbroken sound. Each 8 s hard cut is evidence; MEDIA_STREAK of them is the verdict.
    const { closed } = feed(segmenter, LOUD, 20_000);

    expect(closed.length).toBeGreaterThanOrEqual(ms.constants.MEDIA_STREAK);
    expect(segmenter.isMediaMode()).toBe(true);
    expect(segmenter.effectiveHardCutMs()).toBe(ms.constants.MEDIA_HARD_CUT_MS);
  });

  it('does not switch on one long sentence', () => {
    // A single hard cut is somebody talking at length. Chopping them into 2.5 s pieces would
    // be a regression, so two consecutive cuts are required.
    const segmenter = new ms.Segmenter({});
    feed(segmenter, LOUD, 8200);
    expect(segmenter.isMediaMode()).toBe(false);
  });

  it('goes back to conversation cadence when the audio starts pausing again', () => {
    const segmenter = new ms.Segmenter({});
    feed(segmenter, LOUD, 20_000);
    expect(segmenter.isMediaMode()).toBe(true);

    // The video stops and a person speaks: a close on silence is the counter-evidence.
    const talk = feed(segmenter, LOUD, 1200, 20_000);
    const pause = feed(segmenter, QUIET, 600, talk.endMs);

    expect(pause.closed.length).toBeGreaterThanOrEqual(1);
    expect(segmenter.isMediaMode()).toBe(false);
    expect(segmenter.effectiveHardCutMs()).toBe(ms.constants.HARD_CUT_MS);
  });

  it('registers quiet audio that the speech threshold would have ignored', () => {
    // The failure that loses content outright: a quiet passage of a shared video sits under
    // SILENCE_RMS, so nothing opens and that audio is never transcribed at all.
    const quietMedia = ms.constants.SILENCE_RMS / 2;
    expect(quietMedia).toBeGreaterThan(ms.constants.MEDIA_FLOOR_RMS);

    const conversation = new ms.Segmenter({});
    feed(conversation, quietMedia, 3000);
    expect(conversation._inSpeech).toBe(false); // below the speech threshold: ignored

    const media = new ms.Segmenter({});
    feed(media, LOUD, 20_000);
    expect(media.isMediaMode()).toBe(true);
    feed(media, quietMedia, 1000, 20_000);
    expect(media._inSpeech).toBe(true); // any sound at all is registered
  });

  it('cuts media segments at the short cadence, not the conversational one', () => {
    const segmenter = new ms.Segmenter({});
    feed(segmenter, LOUD, 20_000); // establish media mode
    const after = feed(segmenter, LOUD, 8000, 20_000);

    // 8 s of continuous audio now yields several segments instead of one.
    expect(after.closed.length).toBeGreaterThanOrEqual(2);
    for (const utterance of after.closed) {
      expect(utterance.t1 - utterance.t0).toBeLessThanOrEqual(ms.constants.MEDIA_HARD_CUT_MS + 400);
      expect(utterance.mediaMode).toBe(true);
    }
  });

  it('reports the loudest level per channel so a silent one need not be transcribed', () => {
    const segmenter = new ms.Segmenter({});
    // Two channels: the shared tab has sound, the microphone does not.
    for (let t = 0; t < 1400; t += segmenter.frameMs) {
      segmenter.push([new Float32Array(320).fill(LOUD), new Float32Array(320).fill(0)], t);
    }
    const closed = segmenter.flush();

    expect(closed.peak).toHaveLength(2);
    expect(closed.peak[0]).toBeGreaterThan(0.1);
    expect(closed.peak[1]).toBe(0);
  });
});

describe('the media-capture contract, as source', () => {
  const source = readFileSync(SHIPPED, 'utf8');

  it('holds far more media audio before dropping any of it', () => {
    // Two seconds is right for a conversation, where the newest words are what is awaited.
    // Media capture promises a complete record, so lagging must beat losing.
    expect(source).toContain('MEDIA_MAX_QUEUE_MS');
    expect(source).toContain('const budget = media ? MEDIA_MAX_QUEUE_MS : MAX_QUEUE_MS');
  });

  it('announces dropped audio instead of only counting it', () => {
    expect(source).toContain("emit('ms:audio_dropped'");
    expect(source).toContain('lostMs');
  });

  it('stops paying for partials once segments arrive every few seconds', () => {
    expect(source).toContain('this._segmenter.isMediaMode()) return false');
  });

  it('says when the cadence changed, so shorter segments do not look like a glitch', () => {
    expect(source).toContain("emit('ms:capture_mode'");
  });

  it('sends the per-channel energy hint on the wire', () => {
    expect(source).toContain('energy: utterance.peak');
  });
});

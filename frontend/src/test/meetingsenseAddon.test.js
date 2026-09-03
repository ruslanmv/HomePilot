/**
 * MeetingSense audio capture — the parts a test can actually reach (batch MS4).
 *
 * jsdom has no AudioContext, no AudioWorklet and no getDisplayMedia, so the capture graph
 * itself cannot be exercised here at all; that is what the manual matrix in
 * docs/MEETINGSENSE.md is for. What *can* be exercised is every decision made about the
 * samples once they arrive — the framing, the voice-activity cut, the WAV layout — which is
 * where the bugs that quietly corrupt a transcript live.
 *
 * The addon is a plain browser script rather than a module, so it is evaluated the way a page
 * would evaluate it and read back off `window`. That also means these tests exercise the file
 * that actually ships, not a re-export of it.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const SHIPPED = resolve(ROOT, 'frontend/public/js/homepilot-meetingsense.js');
const MIRROR = resolve(ROOT, 'community/addons/meetingsense/homepilot-meetingsense.js');

let ms;

beforeAll(() => {
    // eslint-disable-next-line no-new-func
    new Function(readFileSync(SHIPPED, 'utf8')).call(window);
    ms = window.hpMeetingSense.internals;
});

// ── the two copies ──────────────────────────────────────────────────────────

describe('the addon ships twice', () => {
    it('and the two copies are byte-identical', () => {
        // ScreenSense ships the same way — `index.html` loads the public copy while the
        // community folder is what people read and install from. Two copies that drift are
        // worse than one copy in the wrong place, because the bug reports come from a file
        // nobody is editing.
        const digest = (p) => createHash('sha256').update(readFileSync(p)).digest('hex');
        expect(digest(MIRROR)).toBe(digest(SHIPPED));
    });
});

// ── sample-level conversions ────────────────────────────────────────────────

describe('floatToPcm16', () => {
    it('maps the full scale', () => {
        const out = ms.floatToPcm16(Float32Array.from([0, 1, -1]));
        expect(Array.from(out)).toEqual([0, 32767, -32768]);
    });

    it('clamps rather than wrapping', () => {
        // A gain node can hand over a sample above 1.0. Without the clamp it wraps to a large
        // negative number, which is a click in the middle of a word rather than clipping.
        const out = ms.floatToPcm16(Float32Array.from([1.5, -1.5]));
        expect(Array.from(out)).toEqual([32767, -32768]);
    });

    it('is exact at zero', () => {
        expect(ms.floatToPcm16(Float32Array.from([0]))[0]).toBe(0);
    });
});

describe('resampleLinear', () => {
    it('returns the input untouched when the rate already matches', () => {
        const input = Float32Array.from([0.1, 0.2, 0.3]);
        expect(ms.resampleLinear(input, 16000, 16000)).toBe(input);
    });

    it('thirds the sample count going from 48 kHz to 16 kHz', () => {
        const input = new Float32Array(48);
        expect(ms.resampleLinear(input, 48000, 16000).length).toBe(16);
    });

    it('interpolates rather than dropping samples', () => {
        // A straight ramp must stay a straight ramp; picking every Nth sample would leave
        // steps, which is aliasing that Whisper hears as noise.
        const input = Float32Array.from({ length: 8 }, (_, i) => i / 8);
        const out = ms.resampleLinear(input, 8, 4);
        expect(Array.from(out)).toEqual([0, 0.25, 0.5, 0.75]);
    });

    it('survives an empty buffer', () => {
        expect(ms.resampleLinear(new Float32Array(0), 48000, 16000).length).toBe(0);
    });
});

// ── the WAV container ───────────────────────────────────────────────────────

function parseWav(buffer) {
    const view = new DataView(buffer);
    const text = (o, n) =>
        String.fromCharCode(...new Uint8Array(buffer, o, n));
    return {
        riff: text(0, 4),
        wave: text(8, 4),
        channels: view.getUint16(22, true),
        rate: view.getUint32(24, true),
        byteRate: view.getUint32(28, true),
        blockAlign: view.getUint16(32, true),
        bits: view.getUint16(34, true),
        dataBytes: view.getUint32(40, true),
        samples: new Int16Array(buffer.slice(44)),
    };
}

describe('encodeWav', () => {
    it('writes a header the server can read', () => {
        const wav = parseWav(ms.encodeWav([Int16Array.from([1, 2, 3])], 16000));
        expect(wav.riff).toBe('RIFF');
        expect(wav.wave).toBe('WAVE');
        expect(wav.channels).toBe(1);
        expect(wav.rate).toBe(16000);
        expect(wav.bits).toBe(16);
        expect(wav.dataBytes).toBe(6);
    });

    it('interleaves two channels, call first', () => {
        // The server splits on exactly this order: channel 0 is the call, channel 1 is this
        // microphone. Swap them and every transcript is attributed backwards, and nothing
        // anywhere in the stack would notice.
        const wav = parseWav(
            ms.encodeWav([Int16Array.from([1, 2, 3]), Int16Array.from([-1, -2, -3])], 16000),
        );
        expect(wav.channels).toBe(2);
        expect(Array.from(wav.samples)).toEqual([1, -1, 2, -2, 3, -3]);
    });

    it('gets the derived header fields right for stereo', () => {
        // A wrong byteRate or blockAlign makes players and decoders read the data at the
        // wrong speed — audio that is transcribed as gibberish rather than rejected.
        const wav = parseWav(ms.encodeWav([Int16Array.from([1]), Int16Array.from([2])], 16000));
        expect(wav.blockAlign).toBe(4);
        expect(wav.byteRate).toBe(16000 * 2 * 2);
    });

    it('produces a valid empty file rather than a truncated one', () => {
        const wav = parseWav(ms.encodeWav([new Int16Array(0)], 16000));
        expect(wav.dataBytes).toBe(0);
        expect(wav.riff).toBe('RIFF');
    });
});

// ── framing ─────────────────────────────────────────────────────────────────

describe('Framer', () => {
    it('cuts a long buffer into fixed frames', () => {
        const framer = new ms.Framer(4);
        expect(framer.push(new Float32Array(12)).length).toBe(3);
    });

    it('keeps the remainder for the next callback', () => {
        // The whole reason this is a class. An AudioWorklet delivers 128 samples at a time,
        // which after resampling is not a whole number of frames — dropping the leftover
        // loses a few milliseconds per callback, and that is a drift, not a fault, so it gets
        // found in week three.
        const framer = new ms.Framer(4);
        expect(framer.push(Float32Array.from([1, 2, 3])).length).toBe(0);
        const frames = framer.push(Float32Array.from([4, 5]));
        expect(frames.length).toBe(1);
        expect(Array.from(frames[0])).toEqual([1, 2, 3, 4]);
    });

    it('loses no samples across many ragged pushes', () => {
        const framer = new ms.Framer(4);
        let emitted = 0;
        for (const size of [3, 5, 1, 7, 2, 6]) {
            emitted += framer.push(new Float32Array(size)).length * 4;
        }
        emitted += framer.flush().length * 4;
        // 24 samples in; 6 frames of 4 out, the last one padded.
        expect(emitted).toBe(24);
    });

    it('pads the final partial frame rather than dropping it', () => {
        const framer = new ms.Framer(4);
        framer.push(Float32Array.from([9, 9]));
        const flushed = framer.flush();
        expect(flushed.length).toBe(1);
        expect(Array.from(flushed[0])).toEqual([9, 9, 0, 0]);
    });

    it('flushes nothing when it is empty', () => {
        expect(new ms.Framer(4).flush()).toEqual([]);
    });
});

// ── voice activity ──────────────────────────────────────────────────────────

const FRAME_MS = 20;
const FRAME_SAMPLES = 320;

function frame(level, channels = 1) {
    // A constant-magnitude frame: its RMS is exactly `level`, so a test can sit either side
    // of the threshold without arithmetic.
    return Array.from({ length: channels }, () => new Float32Array(FRAME_SAMPLES).fill(level));
}

function feed(segmenter, frames) {
    const out = [];
    let t = 0;
    for (const f of frames) {
        const utterance = segmenter.push(f, t);
        if (utterance) out.push(utterance);
        t += FRAME_MS;
    }
    return { utterances: out, tMs: t };
}

function repeat(f, count) {
    return Array.from({ length: count }, () => f);
}

const LOUD = 0.2;
const QUIET = 0.0;

describe('Segmenter', () => {
    it('emits nothing while the room is quiet', () => {
        const seg = new ms.Segmenter({});
        expect(feed(seg, repeat(frame(QUIET), 100)).utterances).toEqual([]);
    });

    it('closes an utterance after the trailing silence', () => {
        const seg = new ms.Segmenter({});
        // 1.2 s of speech, then 400 ms of quiet — past both the 1 s floor and the 350 ms
        // close.
        const { utterances } = feed(seg, [...repeat(frame(LOUD), 60), ...repeat(frame(QUIET), 20)]);
        expect(utterances.length).toBe(1);
    });

    it('does not close on a pause between two words', () => {
        // 200 ms of quiet is a breath in the middle of a sentence, not the end of one.
        const seg = new ms.Segmenter({});
        const { utterances } = feed(seg, [
            ...repeat(frame(LOUD), 60),
            ...repeat(frame(QUIET), 10),
            ...repeat(frame(LOUD), 30),
        ]);
        expect(utterances).toEqual([]);
    });

    it('ignores a cough — too short to be an utterance', () => {
        // 300 ms of noise then silence. Below the 1 s floor, so it stays open rather than
        // costing a transcription round trip to discover it says nothing.
        const seg = new ms.Segmenter({});
        const { utterances } = feed(seg, [
            ...repeat(frame(LOUD), 15),
            ...repeat(frame(QUIET), 30),
        ]);
        expect(utterances).toEqual([]);
    });

    it('hard-cuts a speaker who never pauses', () => {
        // Somebody presenting can talk for minutes without a gap the VAD accepts. Without
        // this the reader waits minutes for a line and the buffer grows without bound.
        const seg = new ms.Segmenter({});
        const { utterances } = feed(seg, repeat(frame(LOUD), 1000));
        expect(utterances.length).toBeGreaterThan(1);
        for (const u of utterances) {
            expect(u.t1 - u.t0).toBeLessThanOrEqual(ms.constants.HARD_CUT_MS + FRAME_MS);
        }
    });

    it('starts the utterance before the first loud frame', () => {
        // The attack of a word is quieter than its body, so the frame that trips the
        // threshold is already a syllable in. The ring buffer puts those frames back.
        const seg = new ms.Segmenter({});
        const { utterances } = feed(seg, [
            ...repeat(frame(QUIET), 30),
            ...repeat(frame(LOUD), 60),
            ...repeat(frame(QUIET), 20),
        ]);
        const [first] = utterances;
        expect(first.frames.length * FRAME_MS).toBeGreaterThan(60 * FRAME_MS);
    });

    it('carries a 200 ms overlap out of a hard cut', () => {
        // A hard cut fires at 8 s regardless of what the speaker is doing, so it lands inside
        // a word. Repeating the tail means the word is whole in one of the two chunks; the
        // server removes the duplicate. Losing the overlap loses the word instead.
        const seg = new ms.Segmenter({});
        const { utterances } = feed(seg, repeat(frame(LOUD), 1000));
        expect(utterances[0].hardCut).toBe(true);
        expect(utterances[0].t1 - utterances[1].t0).toBe(ms.constants.OVERLAP_MS);
    });

    it('carries no overlap out of a close on silence', () => {
        // Waiting for 350 ms of quiet is what buys the guarantee that nothing was cut, so
        // there is nothing to repeat. Re-sending audio from before a pause would hand the
        // server a duplicate to remove for no reason — and the frames carried would be the
        // silence itself, which is how a 200 ms overlap quietly becomes a 140 ms one.
        const seg = new ms.Segmenter({});
        const { utterances } = feed(seg, [
            ...repeat(frame(LOUD), 60),
            ...repeat(frame(QUIET), 20),
            ...repeat(frame(LOUD), 60),
            ...repeat(frame(QUIET), 20),
        ]);
        expect(utterances.length).toBe(2);
        expect(utterances[0].hardCut).toBe(false);
        expect(utterances[1].t0).toBeGreaterThanOrEqual(utterances[0].t1);
    });

    it('keeps time from the caller rather than counting frames itself', () => {
        // A dropped callback should show up as a gap in the timeline, not silently shift
        // every timestamp after it.
        const seg = new ms.Segmenter({});
        seg.push(frame(LOUD), 5000);
        expect(seg.flush().t0).toBe(5000);
    });

    it('takes the loudest channel, not the average', () => {
        // The level has to sit just above the threshold for this to mean anything: a shouted
        // 0.2 averaged with a silent channel is still 0.1 and clears it either way. The case
        // that matters is a soft voice or a distant microphone — near the floor, halved by a
        // silent second channel, and one side of the conversation stops being recorded.
        const seg = new ms.Segmenter({});
        const soft = ms.constants.SILENCE_RMS * 1.5; // above the floor; below it once halved
        expect(soft / 2).toBeLessThan(ms.constants.SILENCE_RMS);
        const oneSided = [
            new Float32Array(FRAME_SAMPLES).fill(QUIET),
            new Float32Array(FRAME_SAMPLES).fill(soft),
        ];
        const { utterances } = feed(seg, [...repeat(oneSided, 60), ...repeat(frame(QUIET, 2), 20)]);
        expect(utterances.length).toBe(1);
    });

    it('flushes an open utterance so the last sentence is not lost', () => {
        const seg = new ms.Segmenter({});
        feed(seg, repeat(frame(LOUD), 30));
        expect(seg.flush()).not.toBeNull();
    });

    it('flushes nothing when nothing is open', () => {
        expect(new ms.Segmenter({}).flush()).toBeNull();
    });
});

// ── assembling a chunk ──────────────────────────────────────────────────────

describe('utteranceToWav', () => {
    it('concatenates frames and keeps the channels apart', () => {
        const a = [Float32Array.from([1, 1]), Float32Array.from([-1, -1])];
        const b = [Float32Array.from([1, 1]), Float32Array.from([-1, -1])];
        const wav = parseWav(ms.utteranceToWav([a, b], 16000));
        expect(wav.channels).toBe(2);
        // Four sample frames, interleaved: call, mic, call, mic…
        expect(Array.from(wav.samples)).toEqual([32767, -32768, 32767, -32768, 32767, -32768, 32767, -32768]);
    });

    it('handles a mono utterance', () => {
        const wav = parseWav(ms.utteranceToWav([[Float32Array.from([0, 0, 0])]], 16000));
        expect(wav.channels).toBe(1);
        expect(wav.samples.length).toBe(3);
    });

    it('is a valid file for an empty utterance', () => {
        expect(parseWav(ms.utteranceToWav([], 16000)).riff).toBe('RIFF');
    });
});

// ── what we tell the user we are recording ──────────────────────────────────

describe('pickAudioMode', () => {
    it('names each combination', () => {
        expect(ms.pickAudioMode(true, true)).toBe('system+mic');
        expect(ms.pickAudioMode(true, false)).toBe('system');
        expect(ms.pickAudioMode(false, true)).toBe('mic');
        expect(ms.pickAudioMode(false, false)).toBe('none');
    });
});

describe('bytesToBase64', () => {
    it('round-trips', () => {
        const bytes = Uint8Array.from([0, 1, 2, 250, 255]);
        expect(Array.from(Buffer.from(ms.bytesToBase64(bytes.buffer), 'base64'))).toEqual([
            0, 1, 2, 250, 255,
        ]);
    });

    it('handles a buffer past the argument limit', () => {
        // `String.fromCharCode(...bytes)` on a whole 3-second chunk overflows the argument
        // limit and throws. A meeting would record silently until somebody spoke for long
        // enough, which is the worst possible time to find out.
        const big = new Uint8Array(200000).fill(7);
        expect(Buffer.from(ms.bytesToBase64(big.buffer), 'base64').length).toBe(200000);
    });
});

// ── the public surface ──────────────────────────────────────────────────────

describe('hpMeetingSense', () => {
    it('exposes the documented API', () => {
        for (const method of ['start', 'stop', 'muteMic']) {
            expect(typeof window.hpMeetingSense[method]).toBe('function');
        }
    });

    it('starts idle, recording nothing', () => {
        expect(window.hpMeetingSense.recording).toBe(false);
        expect(window.hpMeetingSense.audioMode).toBe('none');
    });

    it('refuses to start without a conversation to attach to', async () => {
        // A meeting with nowhere to land is a meeting nobody can find again — and this
        // refusal happens before any permission dialog, so a missing argument does not cost
        // the user a screen-share prompt.
        const result = await window.hpMeetingSense.start({});
        expect(result.ok).toBe(false);
        expect(result.error).toMatch(/conversationId/);
    });

    it('refuses to stop when it never started', async () => {
        expect((await window.hpMeetingSense.stop()).ok).toBe(false);
    });
});

// ── reconnect, backpressure and levels (MS4-a) ──────────────────────────────

describe('backoffDelay', () => {
    it('follows the 1-2-4-8 schedule', () => {
        expect([1, 2, 3, 4].map(ms.backoffDelay)).toEqual([1000, 2000, 4000, 8000]);
    });

    it('caps rather than doubling forever', () => {
        // An outage that lasts an hour must not drift to hourly retries and miss the moment
        // the network comes back.
        expect(ms.backoffDelay(5)).toBe(15000);
        expect(ms.backoffDelay(50)).toBe(15000);
    });

    it('is zero before the first attempt', () => {
        expect(ms.backoffDelay(0)).toBe(0);
    });
});

describe('shedQueue', () => {
    const item = (durationMs, silent = false) => ({ durationMs, silent, frame: {} });

    it('keeps everything inside the budget', () => {
        const queue = [item(800), item(900)];
        const result = ms.shedQueue(queue, ms.constants.MAX_QUEUE_MS);
        expect(result.dropped).toEqual([]);
        expect(result.behindMs).toBe(1700);
    });

    it('drops the near-silent chunk first', () => {
        // The sentence is *older* than the cough, and the cough still goes. That ordering is
        // the whole test: with the cough first, dropping by age alone gives the same answer
        // and the policy could be missing entirely without anything noticing.
        const speech = item(1500);
        const cough = item(1200, true);
        const result = ms.shedQueue([speech, cough], ms.constants.MAX_QUEUE_MS);
        expect(result.dropped).toEqual([cough]);
        expect(result.kept).toEqual([speech]);
    });

    it('drops the oldest silent chunk when there are several', () => {
        // Speech first again, so "oldest silent" is genuinely different from "oldest".
        const speech = item(900);
        const first = item(900, true);
        const second = item(900, true);
        const result = ms.shedQueue([speech, first, second], ms.constants.MAX_QUEUE_MS);
        expect(result.dropped[0]).toBe(first);
        expect(result.kept).toContain(speech);
    });

    it('falls back to the oldest when nothing is silent', () => {
        const oldest = item(1500);
        const newest = item(1500);
        const result = ms.shedQueue([oldest, newest], ms.constants.MAX_QUEUE_MS);
        expect(result.dropped).toEqual([oldest]);
    });

    it('never drops the last chunk, however far behind it is', () => {
        // Shedding down to nothing would mean a saturated connection records silence and says
        // it is fine. One chunk in hand is the floor.
        const only = item(30000);
        const result = ms.shedQueue([only], ms.constants.MAX_QUEUE_MS);
        expect(result.kept).toEqual([only]);
        expect(result.dropped).toEqual([]);
    });

    it('reports how far behind the survivors leave us', () => {
        const result = ms.shedQueue([item(900, true), item(900), item(900)], 2000);
        expect(result.behindMs).toBe(1800);
    });

    it('leaves an empty queue alone', () => {
        expect(ms.shedQueue([], 2000)).toEqual({ kept: [], dropped: [], behindMs: 0 });
    });
});

describe('the segmenter measures how much speech an utterance carries', () => {
    it('counts a full utterance as speech', () => {
        const seg = new ms.Segmenter({});
        const { utterances } = feed(seg, [...repeat(frame(LOUD), 60), ...repeat(frame(QUIET), 20)]);
        expect(utterances[0].speechMs).toBeGreaterThanOrEqual(60 * FRAME_MS);
    });

    it('marks a chunk that barely cleared the threshold', () => {
        // 200 ms of noise inside a long quiet stretch: the hard cut eventually closes it, and
        // what it carries is not a sentence.
        const seg = new ms.Segmenter({});
        const { utterances } = feed(seg, [
            ...repeat(frame(LOUD), 10),
            ...repeat(frame(QUIET), 500),
        ]);
        expect(utterances.length).toBe(1);
        expect(utterances[0].speechMs).toBeLessThan(ms.constants.MIN_SPEECH_MS);
    });
});

// ── the wiring (MS4-a) ──────────────────────────────────────────────────────
//
// Everything above is a pure function, and a pure function can be perfect and never called.
// These drive the recorder's own socket handling against a fake WebSocket, because the bug
// that matters here is not "the backoff schedule is wrong" — it is "nothing ever reconnects".

describe('reconnect and backpressure, wired', () => {
    let sockets;
    let recorder;
    let events;

    class FakeSocket {
        constructor(url) {
            this.url = url;
            this.readyState = 0;
            this.sent = [];
            this.bufferedAmount = 0;
            sockets.push(this);
        }
        send(data) {
            this.sent.push(JSON.parse(data));
        }
        close() {
            this.drop();
        }
        open() {
            this.readyState = 1;
            this.onopen?.();
        }
        deliver(frame) {
            this.onmessage?.({ data: JSON.stringify(frame) });
        }
        drop() {
            this.readyState = 3;
            this.onclose?.();
        }
    }

    let listeners;

    function listen(name) {
        const handler = (e) => events.push({ name, detail: e.detail });
        window.addEventListener(name, handler);
        // Tracked so it can be removed: a handler left attached closes over the `events`
        // variable, not the array it held, so every earlier test's listener starts pushing
        // into the current test's array and each event is counted once per test that ran
        // before it. That failed as "expected [1000, 1000, 1000] to equal [1000]".
        listeners.push([name, handler]);
    }

    beforeEach(() => {
        sockets = [];
        events = [];
        listeners = [];
        vi.useFakeTimers();
        vi.stubGlobal('WebSocket', FakeSocket);
        // A fresh recorder per test: the addon exports a singleton, and socket state left over
        // from one test would quietly decide the next.
        // eslint-disable-next-line no-new-func
        new Function(readFileSync(SHIPPED, 'utf8')).call(window);
        recorder = window.hpMeetingSense;
        for (const name of ['ms:reconnecting', 'ms:resumed', 'ms:status', 'ms:segment']) listen(name);
    });

    afterEach(() => {
        for (const [name, handler] of listeners) window.removeEventListener(name, handler);
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    const of = (name) => events.filter((e) => e.name === name);

    /** Open a socket and complete the handshake — the state every test below starts from. */
    async function openMeeting(opts = { conversationId: 'c1' }) {
        const promise = recorder._connect(opts);
        const ws = sockets[sockets.length - 1];
        ws.open();
        ws.deliver({ type: 'ready', meeting_id: 'm1' });
        await promise;
        return ws;
    }

    it('opens with a start frame when there is no meeting yet', async () => {
        const promise = recorder._connect({ conversationId: 'c1' });
        const ws = sockets[0];
        ws.open();
        expect(ws.sent[0].type).toBe('start');
        expect(ws.sent[0].conversation_id).toBe('c1');
        ws.deliver({ type: 'ready', meeting_id: 'm1' });
        expect((await promise).ok).toBe(true);
        expect(recorder.meetingId).toBe('m1');
    });

    it('opens with a resume frame once a meeting exists', async () => {
        await openMeeting();
        sockets[0].deliver({ type: 'segment', seq: 4, text: 'hello' });

        recorder.recording = true;
        sockets[0].drop();
        await vi.advanceTimersByTimeAsync(1000);

        const reconnected = sockets[1];
        expect(reconnected).toBeDefined();
        reconnected.open();
        // The last sequence it actually saw — the server replays anything above it, which is
        // the only way the frames that died in the old socket come back.
        expect(reconnected.sent[0]).toMatchObject({ type: 'resume', meeting_id: 'm1', last_seq: 4 });
    });

    it('reconnects on the documented schedule', async () => {
        await openMeeting();
        recorder.recording = true;

        sockets[0].drop();
        expect(of('ms:reconnecting').map((e) => e.detail.delay)).toEqual([1000]);

        // Each failed attempt lengthens the wait rather than hammering the server.
        await vi.advanceTimersByTimeAsync(1000);
        sockets[1].drop();
        await vi.advanceTimersByTimeAsync(2000);
        sockets[2].drop();
        expect(of('ms:reconnecting').map((e) => e.detail.delay)).toEqual([1000, 2000, 4000]);
    });

    it('announces a successful resume and resets the backoff', async () => {
        await openMeeting();
        recorder.recording = true;
        sockets[0].drop();
        await vi.advanceTimersByTimeAsync(1000);
        sockets[1].open();
        sockets[1].deliver({ type: 'resumed', meeting_id: 'm1', seq: 4 });

        expect(of('ms:resumed').length).toBe(1);
        expect(recorder.reconnecting).toBe(false);
        // A later blip starts from 1 s again, not from where the last outage left off.
        sockets[1].drop();
        expect(of('ms:reconnecting').at(-1).detail.delay).toBe(1000);
    });

    it('gives up when the meeting is past saving', async () => {
        // The grace window closed or the server restarted. Retrying forever would leave a
        // recording indicator on over a socket that will never accept audio again.
        await openMeeting();
        recorder.recording = true;
        sockets[0].drop();
        await vi.advanceTimersByTimeAsync(1000);
        sockets[1].open();
        sockets[1].deliver({ type: 'error', code: 'not_resumable', msg: 'gone' });

        expect(recorder.recording).toBe(false);
        expect(recorder.meetingId).toBeNull();
        // And the pill stops saying "reconnecting…": a permanent "reconnecting" over a
        // meeting that is gone is worse than saying nothing, because the user keeps waiting.
        expect(recorder.reconnecting).toBe(false);
        await vi.advanceTimersByTimeAsync(60000);
        expect(sockets.length).toBe(2);
    });

    it('does not reconnect after a deliberate stop', async () => {
        await openMeeting();
        recorder.recording = false; // what stop() sets before the socket closes
        sockets[0].drop();
        await vi.advanceTimersByTimeAsync(30000);
        expect(sockets.length).toBe(1);
        expect(of('ms:reconnecting')).toEqual([]);
    });

    it('holds audio while the socket is gone and sends it on resume', async () => {
        await openMeeting();
        recorder.recording = true;
        sockets[0].drop();

        // Said during the outage: the part someone most wants back.
        recorder._queue.push({ frame: { type: 'audio', t0: 0 }, durationMs: 900, silent: false });
        recorder._pump();
        expect(recorder.behindMs).toBe(900);

        await vi.advanceTimersByTimeAsync(1000);
        sockets[1].open();
        sockets[1].deliver({ type: 'resumed', meeting_id: 'm1' });
        expect(sockets[1].sent.filter((f) => f.type === 'audio').length).toBe(1);
        expect(recorder.behindMs).toBe(0);
    });

    it('sheds and reports when the queue outgrows the budget', async () => {
        await openMeeting();
        recorder.recording = true;
        sockets[0].drop();

        recorder._queue.push({ frame: { type: 'audio' }, durationMs: 1200, silent: true });
        recorder._queue.push({ frame: { type: 'audio' }, durationMs: 1500, silent: false });
        recorder._pump();

        const status = of('ms:status').at(-1).detail;
        expect(status.dropped).toBe(1);
        expect(status.behind_ms).toBe(1500);
        expect(recorder._queue.map((q) => q.silent)).toEqual([false]);
    });

    it('stops feeding a socket whose own buffer is full', async () => {
        // Without this the queue looks empty while the browser holds seconds of audio, and
        // behind_ms reports a number that is not true.
        await openMeeting();
        sockets[0].bufferedAmount = 10 * 1024 * 1024;
        recorder._queue.push({ frame: { type: 'audio' }, durationMs: 900, silent: false });
        recorder._pump();
        expect(sockets[0].sent.filter((f) => f.type === 'audio')).toEqual([]);
        expect(recorder.behindMs).toBe(900);
    });

    it('tracks the highest sequence it has seen, not the latest frame', async () => {
        // Frames can arrive out of order across a resume; taking the last one would move the
        // marker backwards and ask the server to replay what the client already has.
        await openMeeting();
        sockets[0].deliver({ type: 'segment', seq: 7 });
        sockets[0].deliver({ type: 'segment', seq: 3, replayed: true });
        expect(recorder._lastSeq).toBe(7);
    });
});

// ── keyframes (MS9) ─────────────────────────────────────────────────────────

/**
 * The thresholds in the scheduler are numbers, and a number in a heuristic is only as good as
 * the case that forced it. These tests *are* the argument for each one: every constant below
 * has a sequence here that fails if it moves, so changing a threshold means coming here and
 * saying which behaviour it is being changed for.
 *
 * The four sequences are the ones a real screen share produces: a slide flip, a document being
 * scrolled, a video playing, and a cursor moving over a slide nobody has touched in a minute.
 * Three of them change most of the frame. Only one of them is a slide.
 */

/** A blocky picture. Two different seeds differ in every cell, by more than PIXEL_DELTA. */
function slide(seed) {
    const { GRID_W, GRID_H } = ms.constants;
    const shades = [20, 90, 160, 230, 55];
    const gray = new Uint8Array(GRID_W * GRID_H);
    for (let y = 0; y < GRID_H; y++) {
        for (let x = 0; x < GRID_W; x++) {
            const cell = ((x >> 3) + (y >> 3) * 8 + seed * 7) % shades.length;
            gray[y * GRID_W + x] = shades[cell];
        }
    }
    return gray;
}

/** `base` with `ratio` of its pixels pushed well past the delta — a controlled difference. */
function disturb(base, ratio, salt) {
    const gray = Uint8Array.from(base);
    const count = Math.round(gray.length * ratio);
    for (let i = 0; i < count; i++) {
        // Strided rather than contiguous so the change is spread over the picture the way a
        // real one is; `salt` moves the stride so two disturbances differ from each other.
        const at = (i * 37 + (salt || 0) * 11) % gray.length;
        gray[at] = gray[at] > 127 ? gray[at] - 100 : gray[at] + 100;
    }
    return gray;
}

/** Push a sequence at the real sample rate and collect what came back. */
function run(frames, options) {
    const scheduler = new ms.KeyframeScheduler(options || {});
    const decisions = [];
    frames.forEach((gray, index) => {
        const decision = scheduler.push(gray, index * ms.constants.SAMPLE_MS);
        if (decision) decisions.push({ ...decision, index });
    });
    return decisions;
}

/** `count` copies of one picture. */
const hold = (gray, count) => Array.from({ length: count }, () => gray);

describe('grayscale', () => {
    it('weights the channels rather than averaging them', () => {
        // A plain average makes white text on saturated blue almost uniform, and every
        // structural difference the hash and the ratio depend on vanishes with it.
        const red = ms.grayscale(Uint8Array.from([255, 0, 0, 255]));
        const blue = ms.grayscale(Uint8Array.from([0, 0, 255, 255]));
        expect(red[0]).not.toBe(blue[0]);
        expect(red[0]).toBeGreaterThan(blue[0]);
    });

    it('gives one byte per pixel', () => {
        const out = ms.grayscale(new Uint8Array(4 * 10));
        expect(out.length).toBe(10);
    });
});

describe('changedRatio', () => {
    it('is zero for the same picture', () => {
        expect(ms.changedRatio(slide(1), slide(1), 12)).toBe(0);
    });

    it('is one when the picture changed size', () => {
        // The share switched resolution. Comparing position by position across two sizes
        // would report a fraction about a comparison that means nothing.
        expect(ms.changedRatio(slide(1), new Uint8Array(10), 12)).toBe(1);
    });

    it('counts a pixel only past the delta, not at it', () => {
        const a = new Uint8Array([100, 100]);
        const b = new Uint8Array([112, 113]);
        expect(ms.changedRatio(a, b, 12)).toBe(0.5);
    });

    it('counts a change in either direction', () => {
        expect(ms.changedRatio(new Uint8Array([200]), new Uint8Array([100]), 12)).toBe(1);
        expect(ms.changedRatio(new Uint8Array([100]), new Uint8Array([200]), 12)).toBe(1);
    });
});

describe('dhash', () => {
    it('is 64 bits', () => {
        expect(ms.dhash(slide(1), ms.constants.GRID_W, ms.constants.GRID_H)).toHaveLength(16);
    });

    it('survives a brightness shift, which is the whole reason it is relational', () => {
        // The same slide captured twice differs in exposure — a screen dimming, a JPEG round
        // trip. An average-based hash moves; a "is this cell brighter than the next" hash does
        // not, which is what lets the server reuse a caption for a slide shown again.
        const original = slide(3);
        const brighter = Uint8Array.from(original, (v) => Math.min(255, v + 25));
        const { GRID_W, GRID_H } = ms.constants;
        expect(ms.dhash(brighter, GRID_W, GRID_H)).toBe(ms.dhash(original, GRID_W, GRID_H));
    });

    it('separates two different slides', () => {
        const { GRID_W, GRID_H } = ms.constants;
        expect(ms.dhash(slide(1), GRID_W, GRID_H)).not.toBe(ms.dhash(slide(2), GRID_W, GRID_H));
    });
});

describe('the keyframe scheduler, on the four sequences a screen share actually produces', () => {
    it('a slide flip: one keyframe, of the settled slide', () => {
        // 6 samples of slide 1, then slide 2 for long enough to clear the 8 s floor.
        const frames = hold(slide(1), 6).concat(hold(slide(2), 26));
        const decisions = run(frames);
        expect(decisions.map((d) => d.reason)).toEqual(['first', 'change']);
    });

    it('scrolling a document: one keyframe when it stops, not one per sample', () => {
        // Twelve samples where most of the frame changes every time — which is exactly what a
        // video also looks like, and the reason the motion gate alone cannot tell them apart.
        const base = slide(1);
        const scrolling = Array.from({ length: 12 }, (_, i) => disturb(slide(2), 0.6, i));
        const frames = hold(base, 6).concat(scrolling, hold(slide(4), 26));
        const decisions = run(frames);
        expect(decisions.map((d) => d.reason)).toEqual(['first', 'change']);
        // And the one it took is from after the scroll stopped, not from the middle of it.
        expect(decisions[1].index).toBeGreaterThan(17);
    });

    it('a video playing: nothing, however long it plays', () => {
        // A still from the middle of a video describes nothing, and sixty of them describe
        // nothing sixty times. The heartbeat is deliberately not a way around this: it is
        // shortened to 5 s here and still must not fire, because it also requires stillness.
        const frames = Array.from({ length: 120 }, (_, i) => disturb(slide(1), 0.6, i));
        expect(run(frames, { heartbeatMs: 5000 })).toEqual([]);
    });

    it('a cursor wiggling on a static slide: one keyframe, then nothing for a minute', () => {
        const base = slide(1);
        const frames = Array.from({ length: 120 }, (_, i) => disturb(base, 0.003, i));
        const decisions = run(frames);
        expect(decisions.map((d) => d.reason)).toEqual(['first']);
    });
});

describe('what each threshold is for', () => {
    it('STILL_RATIO: churn above it is motion, and motion never settles into a keyframe', () => {
        // 5 % of the frame changing at every sample is under the motion gate and over the
        // stillness bar — a video thumbnail in the corner of a deck. Nothing is ever stable,
        // so nothing is ever captured, including the very first frame.
        const base = slide(1);
        const frames = Array.from({ length: 60 }, (_, i) => disturb(base, 0.05, i));
        expect(run(frames)).toEqual([]);
    });

    it('MOTION_RATIO: a settled screen 20 % different from the captured one is not new', () => {
        const base = slide(1);
        const frames = hold(base, 6).concat(hold(disturb(base, 0.2, 1), 40));
        expect(run(frames).map((d) => d.reason)).toEqual(['first']);
    });

    it('MOTION_RATIO: at 50 % it is', () => {
        const base = slide(1);
        const frames = hold(base, 6).concat(hold(disturb(base, 0.5, 1), 40));
        expect(run(frames).map((d) => d.reason)).toEqual(['first', 'change']);
    });

    it('STABLE_MS: a deck clicked through faster than the window yields nothing', () => {
        // Three samples per slide is 1.5 s on screen, and stability is counted from the second
        // of the three — so the window never closes. That is the intended answer: what was on
        // screen for a second and a half was not talked about.
        const frames = [];
        for (let i = 0; i < 12; i++) frames.push(...hold(slide(i + 1), 3));
        expect(run(frames)).toEqual([]);
    });

    it('STABLE_MS: the frame captured is the settled one, not the transition', () => {
        // The transition frame is a blend of the two slides. If stability were not required,
        // the capture would land on it and the caption would describe neither slide.
        const before = slide(1);
        const after = slide(2);
        const transition = disturb(after, 0.4, 9);
        const frames = hold(before, 6).concat([transition], hold(after, 30));
        const decisions = run(frames);
        const { GRID_W, GRID_H } = ms.constants;
        expect(decisions.at(-1).hash).toBe(ms.dhash(after, GRID_W, GRID_H));
        expect(decisions.at(-1).hash).not.toBe(ms.dhash(transition, GRID_W, GRID_H));
    });

    it('MIN_KEYFRAME_MS: a slide that flips inside the floor is captured late, not dropped', () => {
        // The first keyframe lands at 1.5 s and the second slide appears at 3 s. Dropping it
        // for being early would lose the slide entirely; it is taken at the first stable
        // sample from 9.5 s, which is the first one 8 s past the capture before it.
        const frames = hold(slide(1), 6).concat(hold(slide(2), 26));
        const decisions = run(frames);
        expect(decisions[0].t).toBe(1500);
        expect(decisions[1].t).toBe(9500);
        expect(decisions[1].t - decisions[0].t).toBeGreaterThanOrEqual(
            ms.constants.MIN_KEYFRAME_MS,
        );
    });

    it('HEARTBEAT_MS: a screen nothing changes on is still captured again', () => {
        // The case it exists for: a document written into over ten minutes, where no single
        // step crosses the motion gate and the screen is a different screen by the end.
        const frames = hold(slide(1), 60);
        const reasons = run(frames, { heartbeatMs: 10000 }).map((d) => d.reason);
        expect(reasons[0]).toBe('first');
        expect(reasons.slice(1)).toEqual(['heartbeat', 'heartbeat']);
    });

    it('the hourly cap holds, and is a rolling window rather than a bucket', () => {
        // A per-hour bucket lets 2n through either side of a boundary. The rolling window is
        // what actually bounds the captioning bill.
        const scheduler = new ms.KeyframeScheduler({ maxPerHour: 2 });
        const taken = [];
        // The deck is left alone for the first fifty minutes and then clicked through every
        // 20 s. That is what separates the two implementations: the captures land either side
        // of the hour boundary, where a bucket resets and lets a second pair straight through
        // while the first pair is still inside the last sixty minutes. A sequence that starts
        // changing at t = 0 cannot tell them apart — the bucket's edge is where its cost is.
        for (let i = 0; i < 15000; i++) {
            const t = i * 500;
            const seed = t < 3000000 ? 1 : Math.floor((t - 3000000) / 20000) + 2;
            const decision = scheduler.push(slide(seed), t);
            if (decision) taken.push(t);
        }
        expect(taken.length).toBeGreaterThan(2);
        // Never three inside any one hour.
        for (let i = 2; i < taken.length; i++) {
            expect(taken[i] - taken[i - 2]).toBeGreaterThanOrEqual(3600000);
        }
    });
});

describe('the sampler, wired', () => {
    it('does not start without a video track, and says so rather than throwing', () => {
        const recorder = new window.hpMeetingSense.constructor();
        expect(recorder._startWatching(null, {})).toBe(false);
        expect(recorder._startWatching({ getVideoTracks: () => [] }, {})).toBe(false);
        expect(recorder._watch).toBe(null);
    });

    it('stamps keyframes with the transcript clock, not the wall clock', () => {
        // MS10 joins a slide to the words spoken while it was up by comparing this number
        // against a segment's t0. Two clocks would put that join a sentence out.
        const recorder = new window.hpMeetingSense.constructor();
        recorder._elapsedSamples = ms.constants.TARGET_RATE * 3;
        expect(recorder._mediaClockMs()).toBe(3000);
    });
});

/**
 * HomePilot MeetingSense — audio capture for the meeting recorder (batches MS4, MS4-a).
 *
 * Opens its own screen + microphone capture, turns it into 16 kHz PCM16, cuts it into
 * utterances on silence, and streams them to `WS /v1/meetingsense/session`.
 *
 * ── Why this does not extend ScreenSense (decision D1) ────────────────────────────────────
 *
 * ScreenSense's promise is "one silent still, no backend, `audio: false`". MeetingSense breaks
 * both halves of that by design: it holds a stream open for an hour and it records sound. The
 * ~150 duplicated lines buy a ScreenSense that keeps working exactly as it does today, and let
 * the consent copy name precisely which capture is running.
 *
 * ── The audio graph ──────────────────────────────────────────────────────────────────────
 *
 *   getDisplayMedia({video, audio})  ──▶ gain ──▶ merger input 0   (the call: "them")
 *   getUserMedia({audio})            ──▶ gain ──▶ merger input 1   (this mic: "me")
 *                                                     │
 *                                                AudioWorklet ──▶ 20 ms frames ──▶ VAD
 *
 * Two gain nodes into a **channel merger**, never a sum. Summing would be one line shorter and
 * would destroy the only speaker signal there is — the server splits the two channels back
 * apart and labels them, and it can only do that because they arrived apart. Muting the
 * microphone sets *its* gain to zero, which is why mute has to be a node rather than a flag:
 * the call keeps recording while your side goes quiet.
 *
 * ── What is sent ─────────────────────────────────────────────────────────────────────────
 *
 * WAV-wrapped chunks with `format:"wav"`, `data_b64`, `t0`, `t1` — the same frame shape as
 * `/v1/voice/session` (decision D6), so there is one wire contract to debug rather than two.
 * The 44-byte header is worth it over raw PCM: a WAV states its own channel count, so a
 * microphone that drops out mid-meeting cannot leave the server splitting a mono stream in
 * half.
 *
 * Consecutive chunks **overlap by 200 ms**, because cutting on silence still cuts words: a
 * speaker who pauses mid-phrase puts the boundary inside "recog-"/"-nition". Overlapping means
 * the word is whole in at least one chunk, and the server removes the duplicate.
 *
 * ── When the network goes (MS4-a, decision D10) ───────────────────────────────────────────
 *
 * A dropped socket does not stop the recording. Capture keeps running, chunks queue, and the
 * client reconnects on a 1-2-4-8 s backoff capped at 15 s, sending `resume` with the last
 * sequence number it actually saw. The server holds the meeting for a grace window and replays
 * whatever died in the old socket, so a Wi-Fi blip costs nothing.
 *
 * If the queue outgrows two seconds the reconnect is not winning, and something has to give.
 * What goes is the chunk carrying the least speech — a cough, a chair, a keyboard — oldest
 * first, never the newest, which is what the reader is waiting for. `behind_ms` says how far
 * behind that leaves the transcript, which is what the card's "catching up" label reads.
 *
 * ── Public API ───────────────────────────────────────────────────────────────────────────
 *
 *   await hpMeetingSense.start({ conversationId, title, source, apiKey });
 *   hpMeetingSense.muteMic(true);          // your side only; the call keeps recording
 *   await hpMeetingSense.stop();
 *   hpMeetingSense.audioMode                // 'system+mic' | 'system' | 'mic' | 'none'
 *   hpMeetingSense.levels                   // RMS per channel, for the pill's meter
 *   hpMeetingSense.behindMs                 // unsent audio, for "catching up · N s behind"
 *
 * ── DOM events, on `window` ──────────────────────────────────────────────────────────────
 *
 *   ms:segment     a transcribed line          detail: {id, t0, t1, speaker, text, conf}
 *   ms:partial     provisional text            detail: {t0, speaker, text}
 *   ms:status      counters, mute, behind_ms   detail: {elapsed, segments, slides, ...}
 *   ms:audio_lost  a track ended mid-meeting   detail: {track, audioMode}
 *   ms:reconnecting  the socket dropped        detail: {attempt, delay, meetingId}
 *   ms:resumed       the meeting continued     detail: {meeting_id, segments, seq}
 *
 * Events rather than callbacks so more than one surface can listen — the chat card and the
 * recording pill are different components and neither owns the recorder.
 */
(function () {
    'use strict';

    // ── Constants ─────────────────────────────────────────────────────────────────────────

    /** Whisper works at 16 kHz internally; sending more is bytes it throws away. */
    const TARGET_RATE = 16000;

    /** One frame of analysis. 20 ms is the usual VAD grain — long enough to have an energy
     *  measurement, short enough that the end of speech is detected inside a syllable. */
    const FRAME_MS = 20;

    /** How much of the previous chunk each new one repeats. See the header. */
    const OVERLAP_MS = 200;

    /** Shorter than this is a cough, a chair, or a keyboard, and transcribing it costs a
     *  round trip to say so. */
    const MIN_UTTERANCE_MS = 1000;

    /** Trailing quiet that closes an utterance. Below ~250 ms this fires inside the pause
     *  between two words of one sentence and chops it in half. */
    const SILENCE_CLOSE_MS = 350;

    /** Somebody presenting can talk for minutes without a gap the VAD will accept. This
     *  bounds both the memory held and how long the reader waits for a line to appear. */
    const HARD_CUT_MS = 8000;

    /** RMS below this is treated as silence. Deliberately low: a false "speech" costs one
     *  wasted transcription, a false "silence" costs a lost sentence. */
    const SILENCE_RMS = 0.008;

    /** Reconnect backoff, per D10. Capped so a long outage retries steadily rather than
     *  drifting to hourly and missing the moment the network comes back. */
    const BACKOFF_MS = [1000, 2000, 4000, 8000];
    const BACKOFF_CAP_MS = 15000;

    /** How much unsent audio may pile up before the queue starts shedding. Two seconds is
     *  about one utterance: past that the transcript is visibly behind and dropping the least
     *  valuable chunk beats falling further behind on every one after it. */
    const MAX_QUEUE_MS = 2000;

    /** An utterance carrying less speech than this cleared the VAD by accident — a cough, a
     *  chair, a keyboard. These are what a saturated queue sheds first. */
    const MIN_SPEECH_MS = 300;

    /** Stop feeding the socket while this much is still in its own buffer. Without it the
     *  queue looks empty while the browser holds seconds of audio, and `behind_ms` lies. */
    const SOCKET_HIGH_WATER = 256 * 1024;

    // ── Keyframes (MS9) ───────────────────────────────────────────────────────────────────
    // The screen is watched twice a second and almost never captured. Every threshold below
    // exists to answer one question — "is this a new thing to look at, or the same thing still
    // moving?" — and every one of them is earned by a test over a synthetic sequence in
    // src/test/meetingsenseAddon.test.js. Changing a number here without changing that test is
    // how a meeting ends up with a keyframe per second of a video call.

    /** How often the screen is sampled. Twice a second: a slide flip is not missed, and the
     *  work is one 64x36 draw, which is cheaper than a repaint. */
    const SAMPLE_MS = 500;

    /** The thumbnail everything is decided on. 64x36 is 16:9 at the smallest size where a
     *  slide's block structure survives — small enough that comparing two of them is 2,304
     *  subtractions, which is why this can run every 500 ms without a worker. */
    const GRID_W = 64;
    const GRID_H = 36;

    /** How different two gray values must be to count as a changed pixel. Below about 10 the
     *  ratio tracks JPEG noise and the anti-aliasing of a blinking cursor. */
    const PIXEL_DELTA = 12;

    /** Changed-pixel ratio against the *last captured* frame above which the screen is showing
     *  something new. A slide flip moves most of the frame; scrolling a document moves most of
     *  it too, which is why this gate alone is not enough and stability below is the other
     *  half. A cursor, a caret, a clock in the corner move well under a percent. */
    const MOTION_RATIO = 0.35;

    /** Changed-pixel ratio between *consecutive samples* below which the picture counts as
     *  still. Not zero: a video thumbnail in the corner of a slide, an animated cursor and a
     *  ticking clock all keep a genuinely static slide slightly alive. */
    const STILL_RATIO = 0.02;

    /** How long the picture must hold still before it is captured. This is the whole
     *  difference between a slide flip and a video: both change most of the frame, and only
     *  one of them then stops. It also means the frame captured is the settled one rather than
     *  a half-drawn transition. */
    const STABLE_MS = 1500;

    /** Least time between two keyframes. A deck being clicked through fast is still a deck;
     *  eight seconds is roughly the point where a slide was on screen long enough to have been
     *  talked about. */
    const MIN_KEYFRAME_MS = 8000;

    /** Capture the screen anyway after this long with nothing captured, provided it is still.
     *  Catches the screen that changed by less than MOTION_RATIO at every step and is now a
     *  different screen — a document written into over ten minutes. */
    const HEARTBEAT_MS = 300000;

    /** Ceiling per rolling hour. Mirrors `vision.max_keyframes_per_hour`; the server reports
     *  its own value in `/status.limits` and that is the one that wins. */
    const MAX_KEYFRAMES_PER_HOUR = 60;

    /** JPEG quality and the widest frame uploaded. A slide is text on a flat background: 0.72
     *  keeps the text readable, and 1280 is enough for a vision model that will downscale it
     *  again anyway. */
    const JPEG_QUALITY = 0.72;
    const KEYFRAME_MAX_W = 1280;

    const API_BASE = window.HOMEPILOT_API_BASE || '';

    // ── Pure helpers ──────────────────────────────────────────────────────────────────────
    // Everything above the capture graph is a function over arrays, and is exported on
    // `hpMeetingSense.internals` for the unit tests. jsdom has no AudioContext and no
    // AudioWorklet, so this is the part a test can actually reach; the graph itself is
    // covered by the manual matrix in docs/MEETINGSENSE.md.

    /** Root-mean-square level of a frame — the energy the VAD thresholds on. */
    function rms(samples) {
        if (!samples || !samples.length) return 0;
        let sum = 0;
        for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
        return Math.sqrt(sum / samples.length);
    }

    /**
     * Float [-1, 1] to signed 16-bit.
     *
     * Clamps first. A sample above 1.0 — which a gain node can produce — wraps to a large
     * negative number without the clamp, and a wrap sounds like a gunshot in the middle of a
     * word rather than like clipping.
     */
    function floatToPcm16(samples) {
        const out = new Int16Array(samples.length);
        for (let i = 0; i < samples.length; i++) {
            const s = Math.max(-1, Math.min(1, samples[i]));
            out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        return out;
    }

    /**
     * Linear resample. Only runs when the browser refused the requested 16 kHz context.
     *
     * Linear interpolation is not the best resampler; it is the right one here. Speech at
     * 16 kHz downsampled from 48 kHz loses a little high end, which Whisper does not use, and
     * a proper polyphase filter would be a few hundred lines of DSP in an addon whose job is
     * to move bytes.
     */
    function resampleLinear(samples, fromRate, toRate) {
        if (!samples.length || fromRate === toRate) return samples;
        const ratio = fromRate / toRate;
        const length = Math.floor(samples.length / ratio);
        const out = new Float32Array(length);
        for (let i = 0; i < length; i++) {
            const pos = i * ratio;
            const left = Math.floor(pos);
            const right = Math.min(left + 1, samples.length - 1);
            const frac = pos - left;
            out[i] = samples[left] * (1 - frac) + samples[right] * frac;
        }
        return out;
    }

    /**
     * RIFF-wrap one or two channels of PCM16.
     *
     * Channel order is the contract the server reads: **channel 0 is the call, channel 1 is
     * this microphone.** Swap them and every transcript comes out attributed backwards, with
     * nothing anywhere in the stack to notice.
     */
    function encodeWav(channels, rate) {
        const count = channels.length;
        const frames = count ? channels[0].length : 0;
        const dataBytes = frames * count * 2;
        const buffer = new ArrayBuffer(44 + dataBytes);
        const view = new DataView(buffer);

        const ascii = (offset, text) => {
            for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
        };

        ascii(0, 'RIFF');
        view.setUint32(4, 36 + dataBytes, true);
        ascii(8, 'WAVE');
        ascii(12, 'fmt ');
        view.setUint32(16, 16, true); // PCM header length
        view.setUint16(20, 1, true); // PCM, uncompressed
        view.setUint16(22, count, true);
        view.setUint32(24, rate, true);
        view.setUint32(28, rate * count * 2, true); // byte rate
        view.setUint16(32, count * 2, true); // block align
        view.setUint16(34, 16, true); // bits per sample
        ascii(36, 'data');
        view.setUint32(40, dataBytes, true);

        let offset = 44;
        for (let i = 0; i < frames; i++) {
            for (let c = 0; c < count; c++) {
                view.setInt16(offset, channels[c][i], true);
                offset += 2;
            }
        }
        return buffer;
    }

    /** Base64 without a FileReader round trip. Chunked because `String.fromCharCode(...bytes)`
     *  on a whole 3-second chunk overflows the argument limit. */
    function bytesToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        const step = 0x8000;
        for (let i = 0; i < bytes.length; i += step) {
            binary += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
        }
        return btoa(binary);
    }

    /**
     * How long to wait before reconnect attempt ``n`` (1-based).
     *
     * A pure function because the schedule is a promise to the user — "it is coming back" —
     * and a schedule that quietly drifts is indistinguishable from one that gave up.
     */
    function backoffDelay(attempt) {
        if (attempt < 1) return 0;
        return attempt <= BACKOFF_MS.length ? BACKOFF_MS[attempt - 1] : BACKOFF_CAP_MS;
    }

    /**
     * Shed audio from a saturated queue, and say how far behind it leaves us.
     *
     * Returns ``{kept, dropped, behindMs}``. What is dropped is the least speech-bearing
     * chunk, oldest first — never the newest, because the newest is what the reader is
     * waiting to see, and never in time order alone, because that would throw away a sentence
     * to keep a cough.
     *
     * Pure, so the policy is testable without a socket. Getting this wrong is not visible in
     * a demo: it shows up an hour into a real meeting on a bad connection.
     */
    function shedQueue(queue, maxMs) {
        const total = (items) => items.reduce((n, item) => n + item.durationMs, 0);
        const kept = queue.slice();
        const dropped = [];
        while (total(kept) > maxMs && kept.length > 1) {
            // Oldest first among the near-silent; only if there are none does a real
            // utterance go, and then the oldest, which is the one already least useful live.
            let index = kept.findIndex((item) => item.silent);
            if (index === -1) index = 0;
            dropped.push(kept.splice(index, 1)[0]);
        }
        return { kept: kept, dropped: dropped, behindMs: total(kept) };
    }

    /** What the consent sheet and the popover say we are recording. */
    function pickAudioMode(hasSystem, hasMic) {
        if (hasSystem && hasMic) return 'system+mic';
        if (hasSystem) return 'system';
        if (hasMic) return 'mic';
        return 'none';
    }

    /**
     * Cuts an arbitrary stream of buffers into fixed-length frames.
     *
     * An AudioWorklet delivers 128 samples at a time at the context's rate; after resampling
     * that is a fractional number of samples per callback, so the leftover has to survive
     * until the next one. That leftover is the whole reason this is a class and not a
     * function — dropping it loses a few milliseconds per callback, which is a slow drift
     * rather than an audible fault, and drift is the kind of bug that gets found in week three.
     */
    class Framer {
        constructor(frameSamples) {
            this.frameSamples = frameSamples;
            this._pending = new Float32Array(0);
        }

        push(samples) {
            const merged = new Float32Array(this._pending.length + samples.length);
            merged.set(this._pending, 0);
            merged.set(samples, this._pending.length);

            const frames = [];
            let offset = 0;
            while (merged.length - offset >= this.frameSamples) {
                frames.push(merged.slice(offset, offset + this.frameSamples));
                offset += this.frameSamples;
            }
            this._pending = merged.slice(offset);
            return frames;
        }

        /** Whatever is left, padded to a whole frame. Called once, at stop. */
        flush() {
            if (!this._pending.length) return [];
            const frame = new Float32Array(this.frameSamples);
            frame.set(this._pending, 0);
            this._pending = new Float32Array(0);
            return [frame];
        }
    }

    /**
     * Energy VAD: turns a stream of frames into utterances, with the 200 ms lead-in.
     *
     * Multi-channel by construction — a frame is an array of channels, and the level is the
     * loudest of them, so somebody talking on either side keeps the utterance open. Taking the
     * *mean* instead would let a quiet microphone be averaged into silence by a quiet call.
     */
    class Segmenter {
        constructor(options) {
            const opts = options || {};
            this.frameMs = opts.frameMs || FRAME_MS;
            this.threshold = opts.threshold != null ? opts.threshold : SILENCE_RMS;
            this.minMs = opts.minMs != null ? opts.minMs : MIN_UTTERANCE_MS;
            this.silenceMs = opts.silenceMs != null ? opts.silenceMs : SILENCE_CLOSE_MS;
            this.hardCutMs = opts.hardCutMs != null ? opts.hardCutMs : HARD_CUT_MS;
            this.overlapFrames = Math.round((opts.overlapMs != null ? opts.overlapMs : OVERLAP_MS) / this.frameMs);

            this._ring = []; // ambient recent past, so a word's attack is not clipped off
            this._carry = []; // the overlap a hard cut owes the next utterance
            this._frames = []; // the utterance being built
            this._inSpeech = false;
            this._quietMs = 0;
            this._startMs = 0;
            this._speechMs = 0;
        }

        /**
         * Absorb one frame. Returns a closed utterance, or `null`.
         *
         * `tMs` is where this frame sits in the meeting. Passed in rather than counted here,
         * so a dropped callback shows up as a gap in the timeline instead of silently
         * shifting every timestamp after it.
         */
        push(frame, tMs) {
            const level = Math.max.apply(null, frame.map(rms));

            if (!this._inSpeech) {
                if (level < this.threshold) {
                    this._ring.push(frame);
                    if (this._ring.length > this.overlapFrames) this._ring.shift();
                    return null;
                }
                // Speech starts. The utterance opens *before* this frame: with the overlap a
                // hard cut owed it, then the ambient frames just before the threshold tripped
                // — the attack of a word is quieter than its body, so the frame that trips it
                // is already a syllable in.
                this._frames = this._carry.concat(this._ring, [frame]);
                this._startMs = tMs - (this._frames.length - 1) * this.frameMs;
                this._carry = [];
                this._ring = [];
                this._inSpeech = true;
                this._quietMs = 0;
                this._speechMs = this.frameMs;
                return null;
            }

            this._frames.push(frame);
            if (level < this.threshold) {
                this._quietMs += this.frameMs;
            } else {
                this._quietMs = 0;
                // Counted so a saturated queue can tell an utterance carrying a sentence from
                // one that cleared the threshold on a cough.
                this._speechMs += this.frameMs;
            }

            const durationMs = this._frames.length * this.frameMs;
            if (durationMs >= this.hardCutMs) return this._close(true);
            if (this._quietMs >= this.silenceMs && durationMs >= this.minMs) return this._close(false);
            return null;
        }

        /** Close whatever is open. Called at stop so the last sentence is not lost. */
        flush() {
            if (!this._inSpeech) return null;
            return this._close(false);
        }

        /**
         * ``hardCut`` decides whether the next utterance gets the 200 ms overlap, and it is
         * the one place where that question has an honest answer.
         *
         * The overlap exists because a cut can land inside a word. A **hard cut** does exactly
         * that — it fires at 8 s regardless of what the speaker is doing — so the next chunk
         * repeats the tail and the server removes the duplicate. A close on **silence** cut
         * nothing: that is what waiting for 350 ms of quiet buys. Carrying an overlap there
         * would re-send audio from before a pause, and — because the ring keeps filling with
         * ambient frames while nobody talks — the frames carried would be replaced by silence
         * anyway, which is how a 200 ms overlap quietly becomes a 140 ms one.
         */
        _close(hardCut) {
            const frames = this._frames;
            const utterance = {
                frames: frames,
                t0: this._startMs,
                t1: this._startMs + frames.length * this.frameMs,
                hardCut: !!hardCut,
                speechMs: this._speechMs,
            };
            this._carry = hardCut ? frames.slice(Math.max(0, frames.length - this.overlapFrames)) : [];
            this._ring = [];
            this._frames = [];
            this._inSpeech = false;
            this._quietMs = 0;
            this._speechMs = 0;
            return utterance;
        }
    }

    /** Frames (arrays of channel buffers) → one WAV, channels kept apart. */
    function utteranceToWav(frames, rate) {
        if (!frames.length) return encodeWav([new Int16Array(0)], rate);
        const channelCount = frames[0].length;
        const total = frames.reduce((n, f) => n + f[0].length, 0);
        const channels = [];
        for (let c = 0; c < channelCount; c++) {
            const merged = new Float32Array(total);
            let offset = 0;
            for (const frame of frames) {
                merged.set(frame[c], offset);
                offset += frame[c].length;
            }
            channels.push(floatToPcm16(merged));
        }
        return encodeWav(channels, rate);
    }

    // ── Keyframe decisions (MS9) ──────────────────────────────────────────────────────────

    /**
     * RGBA bytes → one gray byte per pixel.
     *
     * Luma weights rather than a plain average: a slide with white text on a saturated blue
     * background comes out as near-uniform gray under an average, and every structural
     * difference the hash and the ratio depend on disappears with it.
     */
    function grayscale(rgba) {
        const out = new Uint8Array(rgba.length >> 2);
        for (let i = 0, j = 0; j < out.length; i += 4, j++) {
            out[j] = (rgba[i] * 77 + rgba[i + 1] * 151 + rgba[i + 2] * 28) >> 8;
        }
        return out;
    }

    /**
     * The fraction of pixels that differ by more than `delta`.
     *
     * Two frames of different sizes are reported as completely different rather than compared
     * position by position: the screen share changed resolution, which is a new picture.
     */
    function changedRatio(a, b, delta) {
        if (!a || !b || a.length !== b.length || !a.length) return 1;
        const limit = typeof delta === 'number' ? delta : PIXEL_DELTA;
        let changed = 0;
        for (let i = 0; i < a.length; i++) {
            const d = a[i] - b[i];
            if (d > limit || d < -limit) changed++;
        }
        return changed / a.length;
    }

    /**
     * Difference hash: 64 bits saying, for each cell of a 9x8 grid, whether it is brighter
     * than the cell to its right.
     *
     * A *relational* hash, which is the point: it is unchanged by the brightness and contrast
     * differences between two captures of the same slide, so a slide re-shown later hashes
     * identically and the server reuses its caption instead of paying a vision model twice.
     * Box-averaged down from the sample grid rather than point-sampled — a point sample of a
     * slide can land on a glyph in one capture and the space beside it in the next.
     */
    function dhash(gray, width, height) {
        const w = width || GRID_W;
        const h = height || GRID_H;
        const W = 9;
        const H = 8;
        const sum = new Float64Array(W * H);
        const count = new Float64Array(W * H);
        for (let y = 0; y < h; y++) {
            const ty = Math.min(H - 1, Math.floor((y * H) / h));
            for (let x = 0; x < w; x++) {
                const tx = Math.min(W - 1, Math.floor((x * W) / w));
                sum[ty * W + tx] += gray[y * w + x];
                count[ty * W + tx] += 1;
            }
        }
        let hex = '';
        let nibble = 0;
        let bits = 0;
        for (let y = 0; y < H; y++) {
            for (let x = 0; x < W - 1; x++) {
                const left = sum[y * W + x] / (count[y * W + x] || 1);
                const right = sum[y * W + x + 1] / (count[y * W + x + 1] || 1);
                nibble = (nibble << 1) | (left > right ? 1 : 0);
                bits++;
                if (bits === 4) {
                    hex += nibble.toString(16);
                    nibble = 0;
                    bits = 0;
                }
            }
        }
        return hex;
    }

    /**
     * Decides which samples become keyframes.
     *
     * Pure: it is handed a gray thumbnail and a timestamp and answers with a decision or null,
     * which is what lets a test drive a whole meeting through it in a millisecond. The four
     * sequences that shaped it, and what each one demands:
     *
     * - **a slide flip** — most of the frame changes, then it stops. One keyframe, and of the
     *   settled slide rather than the transition.
     * - **scrolling a document** — most of the frame changes at every sample for several
     *   seconds, then it stops. One keyframe at the end, not one per sample.
     * - **a video playing** — most of the frame changes and never stops. No keyframe: a still
     *   from the middle of a video describes nothing, and sixty of them describe it sixty
     *   times. This is also why the heartbeat requires stillness.
     * - **a cursor wiggling on a static slide** — a fraction of a percent changes. Nothing,
     *   forever, however long it goes on.
     *
     * So the rule is *change plus stillness*, not change: the motion gate says the screen
     * became something else, and the stability window says it has finished becoming it.
     */
    class KeyframeScheduler {
        constructor(options) {
            const opts = options || {};
            this.pixelDelta = opts.pixelDelta || PIXEL_DELTA;
            this.motionRatio = opts.motionRatio || MOTION_RATIO;
            this.stillRatio = opts.stillRatio || STILL_RATIO;
            this.stableMs = opts.stableMs || STABLE_MS;
            this.minIntervalMs = opts.minIntervalMs || MIN_KEYFRAME_MS;
            this.heartbeatMs = opts.heartbeatMs || HEARTBEAT_MS;
            this.maxPerHour = opts.maxPerHour || MAX_KEYFRAMES_PER_HOUR;
            this.width = opts.width || GRID_W;
            this.height = opts.height || GRID_H;
            /** The previous sample, for the stillness test. */
            this._last = null;
            /** The last sample actually captured, for the motion gate. Compared against the
             *  capture rather than against the previous sample on purpose: a screen that drifts
             *  by 5 % every two seconds is never "moving" and is a different screen after a
             *  minute, and only the capture remembers what it looked like then. */
            this._captured = null;
            this._stableSince = null;
            this._lastCaptureMs = null;
            this._times = [];
        }

        /** Feed one sample. Returns a decision `{reason, t, hash}` or null. */
        push(gray, tMs) {
            const previous = this._last;
            this._last = gray;
            if (!previous) {
                this._stableSince = tMs;
                return null;
            }

            // Still? The comparison is against the previous *sample*, so the first sample after
            // motion stops still reads as moving — stability is therefore counted from the
            // moment two consecutive samples agree, which is what it should mean.
            if (changedRatio(previous, gray, this.pixelDelta) > this.stillRatio) {
                this._stableSince = null;
                return null;
            }
            if (this._stableSince === null) this._stableSince = tMs;
            if (tMs - this._stableSince < this.stableMs) return null;

            const since = this._lastCaptureMs === null ? Infinity : tMs - this._lastCaptureMs;
            let reason = null;
            if (this._captured === null) {
                reason = 'first';
            } else if (changedRatio(this._captured, gray, this.pixelDelta) > this.motionRatio) {
                reason = 'change';
            } else if (since >= this.heartbeatMs) {
                reason = 'heartbeat';
            }
            if (!reason) return null;

            // Deferred, not lost: a slide that flips four seconds after the last capture is
            // still different from the captured one at eight, so it is taken then.
            if (since < this.minIntervalMs) return null;
            if (!this._underCap(tMs)) return null;

            this._captured = gray;
            this._lastCaptureMs = tMs;
            this._times.push(tMs);
            return { reason: reason, t: tMs, hash: dhash(gray, this.width, this.height) };
        }

        /** Rolling hour rather than a per-hour bucket: a bucket lets 120 through across a
         *  boundary, and it is the cost of an hour of captioning that this bounds. */
        _underCap(tMs) {
            this._times = this._times.filter((t) => tMs - t < 3600000);
            return this._times.length < this.maxPerHour;
        }
    }

    /** The worklet, as source, so the addon stays one file the way ScreenSense is one file. */
    const PROCESSOR_SOURCE = `
        class MSCaptureProcessor extends AudioWorkletProcessor {
            process(inputs) {
                const input = inputs[0];
                if (input && input.length && input[0] && input[0].length) {
                    // Copy: the render quantum is reused by the graph the moment this returns.
                    this.port.postMessage(input.map((c) => new Float32Array(c)));
                }
                return true;
            }
        }
        registerProcessor('ms-capture', MSCaptureProcessor);
    `;

    function wsUrl(path) {
        const base = API_BASE || window.location.origin;
        const url = new URL(path, base);
        url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
        return url.toString();
    }

    function emit(name, detail) {
        window.dispatchEvent(new CustomEvent(name, { detail: detail }));
    }

    // ── The recorder ──────────────────────────────────────────────────────────────────────

    class HPMeetingSense {
        constructor() {
            this.audioMode = 'none';
            this.recording = false;
            this.meetingId = null;
            this.micMuted = false;
            /** RMS per channel, index 0 the call and index 1 this microphone. Read by the
             *  pill's level meter on its own frame loop — pushing 50 events a second for a
             *  meter that repaints 60 times a second would be noise, not data. */
            this.levels = [0];
            /** Unsent audio, in milliseconds. What the card's "catching up" label reads. */
            this.behindMs = 0;
            this.reconnecting = false;
            this._lastSeq = 0;
            this._queue = [];
            this._attempt = 0;
            this._reconnectTimer = null;
            this._ws = null;
            this._ctx = null;
            this._nodes = [];
            this._tracks = [];
            this._systemAudio = [];
            this._micAudio = [];
            this._micGain = null;
            this._frameSamples = Math.round((TARGET_RATE * FRAME_MS) / 1000);
            this._framers = null;
            this._segmenter = null;
            this._elapsedSamples = 0;
            this._rate = TARGET_RATE;
            /** MS9's sampler: `{ video, canvas, ctx, scheduler }` while slides are watched. */
            this._watch = null;
            this._watchTimer = null;
            /** Keyframes sent this meeting. Read by the card's slide count. */
            this.slideCount = 0;
        }

        /**
         * Ask for capture, open the socket, and begin.
         *
         * Screen audio is requested first and the microphone second, because the screen share
         * is the one that shows a browser dialog: a user who cancels it should not have
         * already granted a microphone they now have no use for.
         */
        async start(options) {
            const opts = options || {};
            if (this.recording) return { ok: false, error: 'already recording' };
            if (!opts.conversationId) return { ok: false, error: 'conversationId is required' };

            let system = null;
            let mic = null;
            let screen = null;
            try {
                system = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
                screen = system;
                if (!system.getAudioTracks().length) {
                    // Chrome on Linux, and every browser when the user picks a window rather
                    // than a tab, share video with no audio. That is a legitimate meeting —
                    // the mic still records this side — so it is reported, not refused.
                    //
                    // MS9: the *video* is worth keeping even so, when slides are being
                    // watched. A shared window with no audio is exactly the case where the
                    // slides carry what the microphone cannot.
                    if (!opts.watch) {
                        system.getVideoTracks().forEach((t) => t.stop());
                        screen = null;
                    }
                    system = null;
                }
            } catch (_) {
                system = null;
                screen = null;
            }
            try {
                mic = await navigator.mediaDevices.getUserMedia({
                    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
                });
            } catch (_) {
                mic = null;
            }

            this.audioMode = pickAudioMode(!!system, !!mic);
            if (this.audioMode === 'none') {
                return { ok: false, error: 'no audio source was granted', audioMode: 'none' };
            }

            try {
                await this._buildGraph(system, mic);
            } catch (err) {
                this._teardown();
                return { ok: false, error: String(err && err.message ? err.message : err) };
            }

            // Held for the reconnect: a resume needs the same options a start was given.
            this._opts = opts;
            const opened = await this._connect(opts);
            if (!opened.ok) {
                this._teardown();
                return opened;
            }
            this.recording = true;
            // After the socket, not before: a keyframe with nowhere to go is an upload the
            // user paid for and nothing received.
            const watching = opts.watch ? this._startWatching(screen, opts) : false;
            return {
                ok: true,
                meetingId: this.meetingId,
                audioMode: this.audioMode,
                watching: watching,
            };
        }

        /** Mute this side only. The call keeps recording — that is the point of two gains. */
        muteMic(muted) {
            this.micMuted = !!muted;
            if (this._micGain) this._micGain.gain.value = this.micMuted ? 0 : 1;
            this._send({ type: 'mute', mic: this.micMuted });
            return this.micMuted;
        }

        async stop() {
            if (!this.recording) return { ok: false, error: 'not recording' };
            // Cleared first: `recording` is what tells `onclose` a drop was a network event
            // rather than a deliberate stop, so a stop must not schedule a reconnect.
            this.recording = false;
            this._stopReconnecting();
            this._flush();
            this._pump();
            this._send({ type: 'stop' });
            // The socket is left to close on the server's `final`; closing it here would race
            // the frame that carries the counts the card is about to show.
            this._teardown();
            return { ok: true, meetingId: this.meetingId };
        }

        // ── internals ─────────────────────────────────────────────────────────────────────

        async _buildGraph(system, mic) {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (!AudioCtx) throw new Error('this browser has no AudioContext');

            // Asking for 16 kHz up front avoids resampling entirely where it is honoured.
            let ctx;
            try {
                ctx = new AudioCtx({ sampleRate: TARGET_RATE });
            } catch (_) {
                ctx = new AudioCtx();
            }
            this._ctx = ctx;
            this._rate = TARGET_RATE;

            if (!ctx.audioWorklet) throw new Error('this browser has no AudioWorklet');
            const url = URL.createObjectURL(new Blob([PROCESSOR_SOURCE], { type: 'text/javascript' }));
            try {
                await ctx.audioWorklet.addModule(url);
            } finally {
                URL.revokeObjectURL(url);
            }

            const channels = this.audioMode === 'system+mic' ? 2 : 1;
            const merger = ctx.createChannelMerger(channels);
            const worklet = new AudioWorkletNode(ctx, 'ms-capture', {
                numberOfInputs: 1,
                channelCount: channels,
                channelCountMode: 'explicit',
                channelInterpretation: 'discrete',
            });

            const attach = (stream, index, bucket) => {
                const source = ctx.createMediaStreamSource(stream);
                const gain = ctx.createGain();
                source.connect(gain);
                gain.connect(merger, 0, index);
                this._nodes.push(source, gain);
                stream.getTracks().forEach((track) => {
                    this._tracks.push(track);
                    if (track.kind === 'audio') bucket.push(track);
                    track.addEventListener('ended', () => this._onTrackEnded(track));
                });
                return gain;
            };

            // Channel 0 is the call and channel 1 is this microphone. The server splits on
            // exactly this order.
            if (system) attach(system, 0, this._systemAudio);
            if (mic) this._micGain = attach(mic, system ? 1 : 0, this._micAudio);

            this._frameSamples = Math.round((TARGET_RATE * FRAME_MS) / 1000);
            this._framers = null;
            this._segmenter = new Segmenter({});
            this._elapsedSamples = 0;
            this._channels = channels;

            worklet.port.onmessage = (event) => this._onAudio(event.data);
            merger.connect(worklet);
            // Not connected to the destination: routing the call's audio back to the speakers
            // is an echo, and routing the microphone there is feedback.
            this._nodes.push(merger, worklet);
        }

        _onAudio(chunk) {
            if (!this.recording || !chunk || !chunk.length) return;
            const rate = this._ctx ? this._ctx.sampleRate : TARGET_RATE;
            const resampled = chunk.map((c) => resampleLinear(c, rate, TARGET_RATE));

            // Frame each channel on the same boundaries, so a frame is one slice of time
            // across every channel rather than a per-channel offset that drifts.
            if (!this._framers) this._framers = resampled.map(() => new Framer(this._frameSamples));
            const perChannel = resampled.map((c, i) => this._framers[i].push(c));
            const frameCount = Math.min.apply(null, perChannel.map((f) => f.length));

            for (let i = 0; i < frameCount; i++) {
                const frame = perChannel.map((frames) => frames[i]);
                this.levels = frame.map(rms);
                const tMs = Math.round((this._elapsedSamples / TARGET_RATE) * 1000);
                this._elapsedSamples += frame[0].length;
                const utterance = this._segmenter.push(frame, tMs);
                if (utterance) this._sendUtterance(utterance);
            }
        }

        _flush() {
            if (!this._segmenter) return;
            const utterance = this._segmenter.flush();
            if (utterance) this._sendUtterance(utterance);
        }

        _sendUtterance(utterance) {
            const wav = utteranceToWav(utterance.frames, TARGET_RATE);
            this._queue.push({
                frame: {
                    type: 'audio',
                    format: 'wav',
                    data_b64: bytesToBase64(wav),
                    t0: utterance.t0,
                    t1: utterance.t1,
                },
                durationMs: utterance.t1 - utterance.t0,
                // An utterance carrying almost no speech cleared the VAD by accident. When the
                // queue has to shed, these go first: dropping a cough to keep a sentence.
                silent: (utterance.speechMs || 0) < MIN_SPEECH_MS,
            });
            this._pump();
        }

        /**
         * Move the queue into the socket, shedding first if it has grown past the budget.
         *
         * Nothing is dropped while the socket is merely closed for a moment — a reconnect is
         * expected to succeed, and the queue is what makes the gap invisible. It is the queue
         * outgrowing two seconds that forces a choice, and then the choice is made by how much
         * speech a chunk carries rather than by how old it is.
         */
        _pump() {
            const shed = shedQueue(this._queue, MAX_QUEUE_MS);
            const dropped = shed.dropped.length;
            this._queue = shed.kept;

            while (this._queue.length && this._ws && this._ws.readyState === 1) {
                if (this._ws.bufferedAmount > SOCKET_HIGH_WATER) break;
                this._ws.send(JSON.stringify(this._queue[0].frame));
                this._queue.shift();
            }

            const behind = this._queue.reduce((n, item) => n + item.durationMs, 0);
            if (behind !== this.behindMs || dropped) {
                this.behindMs = behind;
                emit('ms:status', { behind_ms: behind, dropped: dropped, reconnecting: this.reconnecting });
            }
        }

        _onTrackEnded(track) {
            // The user hit "Stop sharing", or a device was unplugged. The meeting continues on
            // whatever is left — losing the call's audio should not throw away the recording
            // of it so far.
            this._tracks = this._tracks.filter((t) => t !== track);
            this._systemAudio = this._systemAudio.filter((t) => t !== track);
            this._micAudio = this._micAudio.filter((t) => t !== track);
            this.audioMode = pickAudioMode(this._systemAudio.length > 0, this._micAudio.length > 0);
            emit('ms:audio_lost', { track: track.kind, audioMode: this.audioMode });
        }

        // ── slides (MS9) ──────────────────────────────────────────────────────────────────

        /**
         * Begin watching the shared screen for slides. Returns whether it started.
         *
         * Returns false rather than throwing on a browser or a test environment with no
         * canvas: a meeting that records audio and no slides is a meeting, and a recorder that
         * refuses to start because it could not open a 64x36 canvas is not.
         */
        _startWatching(stream, opts) {
            if (!stream || !stream.getVideoTracks || !stream.getVideoTracks().length) return false;
            let video;
            let canvas;
            let ctx;
            try {
                video = document.createElement('video');
                video.muted = true;
                video.playsInline = true;
                video.srcObject = stream;
                const played = video.play();
                if (played && played.catch) played.catch(() => {});
                canvas = document.createElement('canvas');
                canvas.width = GRID_W;
                canvas.height = GRID_H;
                ctx = canvas.getContext('2d', { willReadFrequently: true });
                if (!ctx) return false;
            } catch (_) {
                return false;
            }
            this._watch = {
                video: video,
                canvas: canvas,
                ctx: ctx,
                apiKey: (opts || {}).apiKey || null,
                scheduler: new KeyframeScheduler({
                    maxPerHour: (opts || {}).maxKeyframesPerHour || MAX_KEYFRAMES_PER_HOUR,
                }),
            };
            this._watchTimer = setInterval(() => this._sampleScreen(), SAMPLE_MS);
            return true;
        }

        /** One sample: draw the screen small, gray it, ask the scheduler. */
        _sampleScreen() {
            const watch = this._watch;
            if (!watch || !this.recording) return;
            let gray;
            try {
                if (!watch.video.videoWidth || !watch.video.videoHeight) return;
                watch.ctx.drawImage(watch.video, 0, 0, GRID_W, GRID_H);
                gray = grayscale(watch.ctx.getImageData(0, 0, GRID_W, GRID_H).data);
            } catch (_) {
                // A frame the browser will not hand over — a tab that went to the background,
                // a share being torn down. Skipping one sample costs nothing.
                return;
            }
            const decision = watch.scheduler.push(gray, this._mediaClockMs());
            if (decision) this._sendKeyframe(decision);
        }

        /**
         * The meeting clock, in milliseconds — the same one the transcript is stamped with.
         *
         * Deliberately the *audio* clock rather than `Date.now()`. MS10 joins a slide to the
         * words spoken while it was up by comparing this number with a segment's `t0`, and two
         * clocks that agree to within a second would put the join a sentence out at every
         * boundary. One clock cannot be out of step with itself.
         */
        _mediaClockMs() {
            return Math.round((this._elapsedSamples / TARGET_RATE) * 1000);
        }

        /** Grab the frame at full size, upload it, and tell the server where it landed. */
        async _sendKeyframe(decision) {
            const watch = this._watch;
            if (!watch) return;
            try {
                const vw = watch.video.videoWidth;
                const vh = watch.video.videoHeight;
                if (!vw || !vh) return;
                const scale = Math.min(1, KEYFRAME_MAX_W / vw);
                const full = document.createElement('canvas');
                full.width = Math.round(vw * scale);
                full.height = Math.round(vh * scale);
                full.getContext('2d').drawImage(watch.video, 0, 0, full.width, full.height);
                const blob = await new Promise((resolve) => {
                    full.toBlob(resolve, 'image/jpeg', JPEG_QUALITY);
                });
                if (!blob) throw new Error('the frame could not be encoded');

                const headers = {};
                if (watch.apiKey) headers['Authorization'] = 'Bearer ' + watch.apiKey;
                const form = new FormData();
                form.append('file', blob, 'meetingsense-' + decision.t + '.jpg');
                const up = await fetch(API_BASE + '/upload', {
                    method: 'POST',
                    headers: headers,
                    body: form,
                    credentials: 'include',
                });
                if (!up.ok) throw new Error('upload ' + up.status);
                const json = await up.json();
                const url = json.url || json.file_url || json.path;
                if (!url) throw new Error('upload returned no url');

                this.slideCount += 1;
                this._send({
                    type: 'keyframe',
                    t: decision.t,
                    url: url,
                    hash: decision.hash,
                    reason: decision.reason,
                });
                emit('ms:keyframe', { t: decision.t, url: url, hash: decision.hash, reason: decision.reason });
            } catch (err) {
                // A slide that could not be uploaded is a missing slide. The meeting keeps
                // recording, and the next keyframe is eight seconds away.
                emit('ms:keyframe_failed', {
                    t: decision.t,
                    error: String(err && err.message ? err.message : err),
                });
            }
        }

        _stopWatching() {
            if (this._watchTimer !== null) {
                clearInterval(this._watchTimer);
                this._watchTimer = null;
            }
            if (this._watch) {
                try {
                    this._watch.video.pause();
                    this._watch.video.srcObject = null;
                } catch (_) {
                    /* already gone */
                }
            }
            this._watch = null;
        }

        /**
         * Open the socket and either start a meeting or resume the one already running.
         *
         * One function for both because everything after the handshake is identical, and the
         * only difference that matters is which frame goes first — a `start` that creates a
         * meeting, or a `resume` that re-attaches to one (D10). Splitting them would mean two
         * copies of the message handler, which is two places for a new frame type to be
         * forgotten.
         */
        _connect(opts) {
            return new Promise((resolve) => {
                const resuming = !!this.meetingId;
                let ws;
                try {
                    ws = new WebSocket(wsUrl(API_BASE + '/v1/meetingsense/session'));
                } catch (err) {
                    resolve({ ok: false, error: String(err) });
                    return;
                }
                this._ws = ws;
                let settled = false;
                const settle = (result) => {
                    if (settled) return;
                    settled = true;
                    resolve(result);
                };

                ws.onopen = () => {
                    ws.send(
                        JSON.stringify(
                            resuming
                                ? { type: 'resume', meeting_id: this.meetingId, last_seq: this._lastSeq }
                                : {
                                      type: 'start',
                                      conversation_id: opts.conversationId,
                                      project_id: opts.projectId,
                                      title: opts.title,
                                      source: opts.source,
                                      notes: !!opts.notes,
                                      watch: !!opts.watch,
                                      audio: {
                                          rate: TARGET_RATE,
                                          channels: this._channels || 1,
                                          mode: this.audioMode,
                                      },
                                  },
                        ),
                    );
                };

                ws.onmessage = (event) => {
                    let frame;
                    try {
                        frame = JSON.parse(event.data);
                    } catch (_) {
                        return;
                    }
                    if (frame.type === 'ready') {
                        this.meetingId = frame.meeting_id;
                        settle({ ok: true });
                    } else if (frame.type === 'resumed') {
                        this.reconnecting = false;
                        this._attempt = 0;
                        emit('ms:resumed', frame);
                        settle({ ok: true });
                        // Whatever piled up while the socket was gone goes now, in order.
                        this._pump();
                    } else if (frame.type === 'segment') {
                        // Tracked so a resume can tell the server what actually arrived. The
                        // server replays anything above it — the frames that died in the old
                        // socket exist only in the store.
                        if (typeof frame.seq === 'number') this._lastSeq = Math.max(this._lastSeq, frame.seq);
                        emit('ms:segment', frame);
                    } else if (frame.type === 'partial') {
                        emit('ms:partial', frame);
                    } else if (frame.type === 'slide') {
                        // Two of these arrive for one slide: the frame when it is taken, and
                        // again when the caption lands. The card upserts on `id` (MS10).
                        emit('ms:slide', frame);
                    } else if (frame.type === 'status' || frame.type === 'final') {
                        emit('ms:status', frame);
                    } else if (frame.type === 'error') {
                        if (frame.code === 'not_resumable') {
                            // The grace window closed, or the server restarted. Nothing here
                            // can recover the meeting, and retrying forever would leave a
                            // recording indicator on over a socket that will never take audio.
                            this.meetingId = null;
                            this.recording = false;
                            this._stopReconnecting();
                        }
                        settle({ ok: false, error: frame.msg || frame.code });
                        emit('ms:status', frame);
                    }
                    // Anything else is a frame from a wave this client does not know about.
                    // Ignored on purpose, the same rule the server follows.
                };

                ws.onclose = () => {
                    settle({ ok: false, error: 'the session socket closed' });
                    if (this.recording) {
                        // A meeting in progress: the socket dying is a network event, not a
                        // decision. Keep capturing — the queue holds what is said meanwhile —
                        // and go back for it.
                        this._scheduleReconnect(opts);
                    } else {
                        this.recording = false;
                    }
                };
            });
        }

        /**
         * Go back for the meeting, with the backoff D10 specifies.
         *
         * Capture is deliberately *not* stopped: what someone says during a ten-second
         * reconnect is the part they will most want back, and the queue is what makes the gap
         * invisible when it works.
         */
        _scheduleReconnect(opts) {
            if (this._reconnectTimer !== null || !this.recording) return;
            this._attempt += 1;
            const delay = backoffDelay(this._attempt);
            this.reconnecting = true;
            emit('ms:reconnecting', { attempt: this._attempt, delay: delay, meetingId: this.meetingId });
            this._reconnectTimer = setTimeout(() => {
                this._reconnectTimer = null;
                if (!this.recording) return;
                this._connect(opts).then((result) => {
                    if (!result.ok && this.recording) this._scheduleReconnect(opts);
                });
            }, delay);
        }

        _stopReconnecting() {
            if (this._reconnectTimer !== null) {
                clearTimeout(this._reconnectTimer);
                this._reconnectTimer = null;
            }
            this.reconnecting = false;
        }

        _send(frame) {
            if (this._ws && this._ws.readyState === 1) this._ws.send(JSON.stringify(frame));
        }

        _teardown() {
            // Before the tracks: the sampler holds a <video> onto the stream it is about to
            // stop, and a stopped track behind a running interval is one exception per second.
            this._stopWatching();
            this._tracks.forEach((t) => {
                try {
                    t.stop();
                } catch (_) {
                    /* already gone */
                }
            });
            this._tracks = [];
            this._systemAudio = [];
            this._micAudio = [];
            this._nodes.forEach((n) => {
                try {
                    n.disconnect();
                } catch (_) {
                    /* already disconnected */
                }
            });
            this._nodes = [];
            if (this._ctx) {
                try {
                    this._ctx.close();
                } catch (_) {
                    /* already closed */
                }
            }
            this._ctx = null;
            this._micGain = null;
            this._framers = null;
        }
    }

    window.hpMeetingSense = new HPMeetingSense();

    /**
     * Exported for the unit tests, and stable.
     *
     * jsdom has no AudioContext, no AudioWorklet and no getDisplayMedia, so the capture graph
     * cannot be exercised in a test at all — what *can* be is every decision made about the
     * samples once they arrive, which is where the bugs that corrupt a transcript live. These
     * are named rather than reached for through a closure so a test failure points at a
     * function instead of at a line number.
     */
    window.hpMeetingSense.internals = {
        rms: rms,
        floatToPcm16: floatToPcm16,
        resampleLinear: resampleLinear,
        encodeWav: encodeWav,
        bytesToBase64: bytesToBase64,
        pickAudioMode: pickAudioMode,
        backoffDelay: backoffDelay,
        shedQueue: shedQueue,
        utteranceToWav: utteranceToWav,
        grayscale: grayscale,
        changedRatio: changedRatio,
        dhash: dhash,
        Framer: Framer,
        Segmenter: Segmenter,
        KeyframeScheduler: KeyframeScheduler,
        constants: {
            TARGET_RATE: TARGET_RATE,
            FRAME_MS: FRAME_MS,
            OVERLAP_MS: OVERLAP_MS,
            MIN_UTTERANCE_MS: MIN_UTTERANCE_MS,
            SILENCE_CLOSE_MS: SILENCE_CLOSE_MS,
            HARD_CUT_MS: HARD_CUT_MS,
            SILENCE_RMS: SILENCE_RMS,
            BACKOFF_MS: BACKOFF_MS,
            BACKOFF_CAP_MS: BACKOFF_CAP_MS,
            MAX_QUEUE_MS: MAX_QUEUE_MS,
            MIN_SPEECH_MS: MIN_SPEECH_MS,
            SAMPLE_MS: SAMPLE_MS,
            GRID_W: GRID_W,
            GRID_H: GRID_H,
            PIXEL_DELTA: PIXEL_DELTA,
            MOTION_RATIO: MOTION_RATIO,
            STILL_RATIO: STILL_RATIO,
            STABLE_MS: STABLE_MS,
            MIN_KEYFRAME_MS: MIN_KEYFRAME_MS,
            HEARTBEAT_MS: HEARTBEAT_MS,
            MAX_KEYFRAMES_PER_HOUR: MAX_KEYFRAMES_PER_HOUR,
            JPEG_QUALITY: JPEG_QUALITY,
            KEYFRAME_MAX_W: KEYFRAME_MAX_W,
        },
    };
})();

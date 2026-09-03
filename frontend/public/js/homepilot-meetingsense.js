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
            try {
                system = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
                if (!system.getAudioTracks().length) {
                    // Chrome on Linux, and every browser when the user picks a window rather
                    // than a tab, share video with no audio. That is a legitimate meeting —
                    // the mic still records this side — so it is reported, not refused.
                    system.getVideoTracks().forEach((t) => t.stop());
                    system = null;
                }
            } catch (_) {
                system = null;
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
            return { ok: true, meetingId: this.meetingId, audioMode: this.audioMode };
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
        Framer: Framer,
        Segmenter: Segmenter,
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
        },
    };
})();

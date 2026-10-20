/**
 * The meeting's own recording, as the browser uploads it (`RecordingUpload` in
 * `public/js/homepilot-meetingsense.js`; the server half is `library/recording.py`).
 *
 * jsdom has no MediaRecorder and no audio graph, so these drive the uploader with a fake
 * recorder and a fake `fetch`. What they pin is what makes a recording survive a real call:
 * nothing leaves the browser until the server says this meeting keeps audio; slices go in
 * order, one at a time, and a failed post is retried rather than skipped; a refusal stops the
 * recorder; and stopping uploads the last slice before saying "complete".
 */
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const SHIPPED = resolve(ROOT, 'frontend/public/js/homepilot-meetingsense.js');

let ms;

beforeAll(() => {
    // eslint-disable-next-line no-new-func
    new Function(readFileSync(SHIPPED, 'utf8')).call(window);
    ms = window.hpMeetingSense.internals;
});

class FakeRecorder {
    static isTypeSupported(type) {
        return type === 'audio/webm;codecs=opus';
    }

    constructor(stream, options) {
        this.stream = stream;
        this.options = options;
        this.mimeType = options.mimeType || '';
        this.state = 'inactive';
        FakeRecorder.last = this;
    }

    start(slice) {
        this.slice = slice;
        this.state = 'recording';
    }

    slice_(text) {
        this.ondataavailable({ data: new Blob([text]) });
    }

    stop() {
        this.state = 'inactive';
        this.ondataavailable({ data: new Blob(['tail']) });
        if (this.onstop) this.onstop();
    }
}

const ok = (body = {}) => ({ ok: true, status: 200, json: async () => body });
const refuse = (status, detail) => ({ ok: false, status, json: async () => ({ detail }) });

function harness(script = []) {
    const calls = [];
    const fetch = async (url, init) => {
        calls.push({ url, init, body: init && init.body ? await init.body.text() : null });
        const next = script.length ? script.shift() : ok();
        if (next instanceof Error) throw next;
        return next;
    };
    const upload = new ms.RecordingUpload({ id: 'stream' }, 1234, {
        Recorder: FakeRecorder, fetch, sleep: () => Promise.resolve(), apiKey: 'k-1',
    });
    return { upload, calls };
}

const settle = async () => {
    for (let i = 0; i < 10; i += 1) await new Promise((r) => setTimeout(r, 0));
};

beforeEach(() => {
    window.localStorage.clear();
    FakeRecorder.last = null;
});
afterEach(() => window.localStorage.clear());

describe('nothing leaves the browser until the server says this meeting keeps audio', () => {
    it('records from the start but holds every slice until it is bound', async () => {
        const { upload, calls } = harness();
        expect(upload.start()).toBe(true);
        expect(FakeRecorder.last.options).toEqual({ audioBitsPerSecond: 32000, mimeType: 'audio/webm;codecs=opus' });
        expect(FakeRecorder.last.slice).toBe(ms.constants.RECORDING_SLICE_MS);
        FakeRecorder.last.slice_('head');
        FakeRecorder.last.slice_('two');
        await settle();
        expect(calls).toEqual([]);

        upload.bind('m-1');
        await settle();
        expect(calls.map((c) => [c.url, c.body])).toEqual([
            ['/v1/meetingsense/library/item/m-1/recording?seq=0&offset_ms=1234', 'head'],
            ['/v1/meetingsense/library/item/m-1/recording?seq=1', 'two'],
        ]);
        expect(calls[0].init.headers['Content-Type']).toBe('audio/webm;codecs=opus');
    });

    it('a discarded recording sends nothing and stops the recorder', async () => {
        const { upload, calls } = harness();
        upload.start();
        FakeRecorder.last.slice_('head');
        upload.discard();
        upload.bind('m-1');
        await settle();
        expect(calls).toEqual([]);
        expect(FakeRecorder.last.state).toBe('inactive');
    });

    it('stopping a recording no meeting took is a discard', async () => {
        const { upload, calls } = harness();
        upload.start();
        FakeRecorder.last.slice_('head');
        expect(await upload.finish()).toBe('discarded');
        expect(calls).toEqual([]);
    });
});

describe('slices go in order and survive a bad connection', () => {
    it('retries a failed post instead of skipping it', async () => {
        const { upload, calls } = harness([new TypeError('offline'), ok(), ok()]);
        upload.start();
        upload.bind('m-1');
        FakeRecorder.last.slice_('head');
        FakeRecorder.last.slice_('two');
        await settle();
        expect(calls.map((c) => c.body)).toEqual(['head', 'head', 'two']);
        expect(upload.queue).toEqual([]);
    });

    it('drops what the server already has when a reply was lost', async () => {
        const { upload, calls } = harness([ok(), refuse(409, { code: 'out_of_order', expected: 3 }), ok()]);
        upload.start();
        upload.bind('m-1');
        FakeRecorder.last.slice_('a');
        await settle();
        upload.seq = 2; // as if two more had been sent and their answers lost
        FakeRecorder.last.slice_('c');
        FakeRecorder.last.slice_('d');
        await settle();
        expect(calls.map((c) => c.url.split('?')[1])).toEqual(['seq=0&offset_ms=1234', 'seq=2', 'seq=3']);
    });

    it('a refusal stops the recording for good', async () => {
        const events = [];
        const on = (e) => events.push(e.detail);
        window.addEventListener('ms:recording', on);
        const { upload, calls } = harness([refuse(404, 'not found')]);
        upload.start();
        upload.bind('m-1');
        FakeRecorder.last.slice_('head');
        await settle();
        FakeRecorder.last.slice_('more');
        await settle();
        window.removeEventListener('ms:recording', on);
        expect(calls).toHaveLength(1);
        expect(upload.state).toBe('failed');
        expect(FakeRecorder.last.state).toBe('inactive');
        expect(events.at(-1)).toMatchObject({ meetingId: 'm-1', state: 'failed', reason: 'refused' });
    });

    it('carries the same credentials as the library', async () => {
        window.localStorage.setItem('homepilot_api_key', 'key-9');
        window.localStorage.setItem('homepilot_auth_token', 'tok-7');
        const { upload, calls } = harness();
        upload.start();
        upload.bind('m-1');
        FakeRecorder.last.slice_('head');
        await settle();
        expect(calls[0].init.headers).toMatchObject({ 'x-api-key': 'key-9', Authorization: 'Bearer tok-7' });
        expect(calls[0].init.credentials).toBe('include');
    });
});

describe('stopping completes the recording', () => {
    it('uploads the last slice, then says complete', async () => {
        const events = [];
        const on = (e) => events.push(e.detail.state);
        window.addEventListener('ms:recording', on);
        const { upload, calls } = harness();
        upload.start();
        upload.bind('m-1');
        FakeRecorder.last.slice_('head');
        expect(await upload.finish()).toBe('done');
        window.removeEventListener('ms:recording', on);
        expect(calls.map((c) => c.url)).toEqual([
            '/v1/meetingsense/library/item/m-1/recording?seq=0&offset_ms=1234',
            '/v1/meetingsense/library/item/m-1/recording?seq=1',
            '/v1/meetingsense/library/item/m-1/recording/complete',
        ]);
        expect(calls[1].body).toBe('tail');
        expect(events).toEqual(['recording', 'saved']);
    });

    it('a server that misses "complete" is left to finish it itself', async () => {
        const { upload } = harness([ok(), ok(), refuse(503, 'down')]);
        upload.start();
        upload.bind('m-1');
        FakeRecorder.last.slice_('head');
        expect(await upload.finish()).toBe('incomplete');
    });
});

describe('the user\'s choice and the browser\'s formats', () => {
    it('keeps the audio unless Settings → Meetings switched it off', () => {
        expect(ms.keepAudioPreference()).toBe(true);
        window.localStorage.setItem('homepilot_meeting_prefs_v1', JSON.stringify({ language: 'en' }));
        expect(ms.keepAudioPreference()).toBe(true);
        window.localStorage.setItem('homepilot_meeting_prefs_v1', JSON.stringify({ keepAudio: false }));
        expect(ms.keepAudioPreference()).toBe(false);
    });

    it('picks the first container the browser can record', () => {
        expect(ms.recordingMimeType(FakeRecorder)).toBe('audio/webm;codecs=opus');
        expect(ms.recordingMimeType({ isTypeSupported: (t) => t === 'audio/mp4' })).toBe('audio/mp4');
        expect(ms.recordingMimeType({})).toBe('');
    });

    it('cannot start without a recorder', () => {
        const upload = new ms.RecordingUpload({ id: 's' }, 0, { Recorder: null, fetch: async () => ok() });
        upload._Recorder = null;
        expect(upload.start()).toBe(false);
    });
});

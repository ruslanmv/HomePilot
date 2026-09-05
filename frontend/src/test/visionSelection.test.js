/**
 * The vision model the user chose actually reaches the request (V1), and an empty answer is
 * a typed failure rather than a success with nothing in it (V3).
 *
 * The defect these close is subtle and looked exactly like a weak model. Settings has always
 * stored `homepilot_model_multimodal`, and `/v1/multimodal/analyze` has always accepted a
 * `model` — but the floating button auto-mounts with no options, so `opts.model` was
 * `undefined`, the field was omitted, and the backend auto-detected instead. Somebody who had
 * selected a good model still got whichever model detection happened to find, and the advice
 * that followed — "try a larger vision model" — was addressed to a choice they had already
 * made.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SHIPPED = resolve('public/js/homepilot-screensense.js');

function load() {
    // eslint-disable-next-line no-new-func
    new Function(readFileSync(SHIPPED, 'utf8')).call(window);
    return window.hpScreenSense;
}

let calls;

/** A fetch that records every request and answers upload then analyze. */
function stubFetch(analyze) {
    vi.stubGlobal(
        'fetch',
        vi.fn(async (url, init) => {
            const href = String(url);
            calls.push({ url: href, body: init && init.body });
            if (href.endsWith('/upload')) {
                return { ok: true, json: async () => ({ url: '/files/x.jpg' }) };
            }
            if (href.includes('/v1/multimodal/analyze')) {
                return analyze();
            }
            return { ok: true, json: async () => ({}) };
        })
    );
}

/** The body of the analyze request, parsed. */
function analyzeBody() {
    const call = calls.find((c) => c.url.includes('/v1/multimodal/analyze'));
    return call ? JSON.parse(call.body) : null;
}

/** A sense object in browser mode with a frame ready to capture. */
function ready() {
    const sense = load();
    sense.mode = 'browser';
    sense.captureFrame = async () => new Blob(['x'], { type: 'image/jpeg' });
    Object.defineProperty(sense, 'enabled', { get: () => true });
    return sense;
}

beforeEach(() => {
    calls = [];
    window.HOMEPILOT_SCREENSENSE_NO_AUTOBUTTON = true;
    stubFetch(() => ({ ok: true, json: async () => ({ ok: true, analysis_text: 'A code editor.' }) }));
});

afterEach(() => {
    vi.unstubAllGlobals();
    delete window.hpScreenSense;
});

// ── V1 ──────────────────────────────────────────────────────────────────────

describe('the chosen model reaches the request', () => {
    it('sends nothing when nothing was chosen, so the backend still auto-detects', async () => {
        const sense = ready();
        await sense.ask('what is this?');
        const body = analyzeBody();
        expect(body.model).toBeUndefined();
        expect(body.base_url).toBeUndefined();
        expect(body.provider).toBeUndefined();
    });

    it('sends what Settings chose', async () => {
        const sense = ready();
        sense.setVision({ provider: 'ollama', baseUrl: 'http://vision.local:11434', model: 'gemma3:4b' });
        await sense.ask('what is this?');
        expect(analyzeBody()).toMatchObject({
            model: 'gemma3:4b',
            base_url: 'http://vision.local:11434',
            provider: 'ollama',
        });
    });

    it('lets an explicit call override the setting', async () => {
        const sense = ready();
        sense.setVision({ model: 'gemma3:4b' });
        await sense.ask('what is this?', { model: 'qwen3-vl:8b' });
        expect(analyzeBody().model).toBe('qwen3-vl:8b');
    });

    it('treats an empty choice as no choice rather than a model named ""', async () => {
        const sense = ready();
        sense.setVision({ model: '   ', baseUrl: '' });
        await sense.ask('what is this?');
        expect(analyzeBody().model).toBeUndefined();
        expect(analyzeBody().base_url).toBeUndefined();
    });

    it('merges partial updates, so a host that only knows the model keeps the rest', async () => {
        const sense = ready();
        sense.setVision({ provider: 'ollama', baseUrl: 'http://vision.local:11434' });
        sense.setVision({ model: 'gemma3:4b' });
        expect(sense.getVision()).toEqual({
            provider: 'ollama',
            baseUrl: 'http://vision.local:11434',
            model: 'gemma3:4b',
        });
    });
});

// ── V3 ──────────────────────────────────────────────────────────────────────

describe('an empty answer', () => {
    it('is reported as empty, not as a transport failure', async () => {
        // Before V3 this was a 200 with an empty string. It is now a 422 with a typed code,
        // and reading `analyze 422` to the user would be worse than what the panel already
        // says — and would throw away the model's name, which is the actionable part.
        stubFetch(() => ({
            ok: false,
            status: 422,
            json: async () => ({
                ok: false,
                error_code: 'empty_model_response',
                error: 'moondream:latest returned no description of the image.',
                meta: { model: 'moondream:latest' },
            }),
        }));
        const sense = ready();
        const out = await sense.ask('what is this?');
        expect(out).toMatchObject({ ok: false, empty: true });
        expect(out.meta.model).toBe('moondream:latest');
    });

    it('reads the same to a person as an unusable one', async () => {
        stubFetch(() => ({
            ok: false,
            status: 422,
            json: async () => ({
                ok: false,
                error_code: 'empty_model_response',
                meta: { model: 'moondream:latest' },
            }),
        }));
        const sense = ready();
        const btn = sense.mountButton({ getConversationId: () => 'c1' });
        btn.click();
        // Waited for the sentence, not for the panel becoming visible: the panel shows
        // "Looking…" the moment the button is pressed, so a display check passes before the
        // request has resolved and asserts nothing about the outcome.
        await vi.waitFor(() =>
            expect(sense._panel.textContent).toMatch(/No usable answer from moondream:latest/)
        );
    });

    it('a real transport failure is still a failure', async () => {
        stubFetch(() => ({ ok: false, status: 500, json: async () => ({ error: 'Ollama is down' }) }));
        const sense = ready();
        const out = await sense.ask('what is this?');
        expect(out.ok).toBe(false);
        expect(out.empty).toBeUndefined();
        expect(out.error).toContain('Ollama is down');
    });
});

/**
 * What ScreenSense shows, and when it believes a share is live (batch MS31).
 *
 * Two bugs from one report, and they are opposites of the same mistake — saying something
 * about the screen that is not true.
 *
 * **The panel printed whatever the model said.** A small vision model asked an open question
 * about a screenshot sometimes answers "ersatz", or "erset up lngreck aggr;". Printed verbatim
 * beside the button, that reads as HomePilot being broken, when the truth is that the model is
 * too small for the job — and the useful response is to say so and name it.
 *
 * **Nothing noticed when a share ended.** The browser's own "Stop sharing" bar ends the stream
 * without calling anything here, and on a single screen that is the *normal* way it ends: you
 * share, switch away to look at the thing you shared, stop it from the bar, and come back. The
 * backend kept the share for its full timeout and the persona went on claiming it could see a
 * screen that was gone.
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

/** A MediaStream stand-in with the one behaviour that matters: it can end. */
function fakeStream() {
    const listeners = [];
    const track = {
        stop: vi.fn(),
        addEventListener: (name, fn) => { if (name === 'ended') listeners.push(fn); },
    };
    return {
        active: true,
        getTracks: () => [track],
        getVideoTracks: () => [track],
        getAudioTracks: () => [],
        end() { this.active = false; listeners.forEach((fn) => fn()); },
    };
}

let posts;

beforeEach(() => {
    posts = [];
    vi.stubGlobal('fetch', vi.fn(async (url, init) => {
        posts.push({ url: String(url), body: JSON.parse(init?.body || '{}') });
        return { ok: true, json: async () => ({}) };
    }));
    window.HOMEPILOT_SCREENSENSE_NO_AUTOBUTTON = true;
});

afterEach(() => {
    vi.unstubAllGlobals();
    delete window.hpScreenSense;
});

// ── what reaches the panel ──────────────────────────────────────────────────

describe('the answer filter', () => {
    // The filter is a closure, so it is exercised through the button that uses it.
    function mountWith(analysis, ok = true) {
        const sense = load();
        sense.mode = 'browser';
        sense.ask = async () => ({ ok, analysis_text: analysis, meta: { model: 'moondream' } });
        const btn = sense.mountButton({ getConversationId: () => 'c1' });
        return { sense, btn, panel: sense._panel };
    }

    it.each([
        ['ersatz'],
        ['erset up lngreck aggr;'],
        ['   '],
        [''],
        [null],
        ['too short'],
        // Five words, still nothing: the word floor alone lets this through, which is why
        // there is a character floor as well.
        ['ok no i see it'],
        ['a b c d e f'],
    ])('refuses to print %j as an answer', async (analysis) => {
        // The two real examples from the bug report, plus the neighbours of each.
        const { btn, panel } = mountWith(analysis);
        btn.click();
        await vi.waitFor(() => expect(panel.style.display).toBe('block'));
        expect(panel.textContent).toMatch(/No usable answer from moondream/);
        expect(panel.textContent).toMatch(/larger vision model/);
    });

    it.each([
        ["I'm sorry, I cannot see the image."],
        ['I am unable to view screenshots.'],
        ['As an AI, I do not have the ability to see your screen.'],
    ])('refuses a refusal: %j', async (analysis) => {
        // A refusal shown as an answer reads as the product being broken rather than the
        // model declining — MS9's rule, kept here.
        const { btn, panel } = mountWith(analysis);
        btn.click();
        await vi.waitFor(() => expect(panel.style.display).toBe('block'));
        expect(panel.textContent).toMatch(/No usable answer/);
    });

    it.each([
        ['The screen shows a Python traceback about a missing module.'],
        ['npm ERR! ENOENT: no such file or directory, open package.json'],
        ['Your test run failed on line 42 of the parser spec.'],
    ])('prints a real answer unchanged: %j', async (analysis) => {
        // The other direction, and the one a cleverer gibberish detector would eventually
        // get wrong: terse technical output is exactly what somebody most needs to see.
        const { btn, panel } = mountWith(analysis);
        btn.click();
        await vi.waitFor(() => expect(panel.textContent).toContain(analysis.slice(0, 20)));
        expect(panel.textContent).not.toMatch(/No usable answer/);
    });

    it('reports a capture failure in its own words', async () => {
        const { btn, panel } = mountWith('', false);
        btn.click();
        await vi.waitFor(() => expect(panel.style.display).toBe('block'));
        expect(panel.textContent).not.toMatch(/No usable answer/);
    });

    it('labels the panel and can be dismissed', async () => {
        // Floating prose beside a button reads as part of the page, which is how "ersatz"
        // came to look like a bug in HomePilot rather than a model saying nothing.
        const { btn, panel } = mountWith('The screen shows a Python traceback about a module.');
        btn.click();
        await vi.waitFor(() => expect(panel.style.display).toBe('block'));
        expect(panel.textContent).toContain('What I can see');
        panel.querySelector('button[aria-label="Dismiss"]').click();
        expect(panel.style.display).toBe('none');
    });
});

// ── when a share is really live ─────────────────────────────────────────────

describe('the share is believed only while it is real', () => {
    /**
     * Drives the addon's own `enable()` rather than assigning a stream by hand.
     *
     * The first version of this helper attached the `ended` listener itself, which meant every
     * test below was exercising the helper's wiring instead of the addon's — deleting the
     * production listener left them all green. Going through `enable()` is the difference
     * between testing the code and testing the test.
     */
    async function sharing() {
        const sense = load();
        sense.mode = 'browser';
        sense._conversationId = 'c1';
        const stream = fakeStream();
        vi.stubGlobal('navigator', {
            ...window.navigator,
            mediaDevices: { getDisplayMedia: async () => stream },
        });
        await sense.enable();
        posts.length = 0;   // the `start` from enable() is not what these tests are about
        return { sense, stream };
    }

    it('knows a live share is live', async () => {
        const { sense } = await sharing();
        expect(sense.enabled).toBe(true);
        expect(sense.verifyShare()).toBe(true);
    });

    it('tells the backend when the browser bar ends the share', async () => {
        // The bug: on one screen this is the normal way sharing ends, and nothing noticed.
        const { sense, stream } = await sharing();
        stream.end();
        expect(sense.enabled).toBe(false);
        const stops = posts.filter((p) => p.body.action === 'stop');
        expect(stops.length).toBe(1);
        expect(stops[0].url).toContain('/v1/meetingsense/screen/c1');
    });

    it('repairs a stale belief when the tab comes back', async () => {
        // Returning to the tab is when the answer is most likely to have changed and least
        // likely to have been noticed.
        const { sense, stream } = await sharing();
        stream.active = false;           // ended without firing, e.g. the window closed
        expect(sense.verifyShare()).toBe(false);
        expect(sense.enabled).toBe(false);
        expect(posts.filter((p) => p.body.action === 'stop').length).toBe(1);
    });

    it('does not re-announce a share that has ended', async () => {
        const { sense, stream } = await sharing();
        stream.end();
        posts.length = 0;
        sense.bindConversation('c2');
        expect(posts.filter((p) => p.body.action === 'start')).toEqual([]);
    });

    it('says nothing twice when the share ends twice', async () => {
        const { sense, stream } = await sharing();
        stream.end();
        sense.verifyShare();
        expect(posts.filter((p) => p.body.action === 'stop').length).toBe(1);
    });

    it('does not announce a share that ended while the model was thinking', async () => {
        // A real race, not a contrived one: the frame is captured, the analyze round trip
        // takes a second or two, and the user stops sharing in that window. Announcing the
        // share afterwards leaves the persona believing in a screen that is already gone.
        //
        // The stream is ended from inside the analyze response, which is the only way to sit
        // in that window — an earlier version of this test ended it before the capture, so
        // `ask` bailed out long before the line under test and the assertion proved nothing.
        const { sense, stream } = await sharing();
        // The real method name — an earlier version stubbed one that does not exist, so
        // `ask` bailed at the capture step and never reached the line under test.
        sense.captureFrame = async () => new Blob(['x'], { type: 'image/jpeg' });
        vi.stubGlobal('fetch', vi.fn(async (url, init) => {
            const target = String(url);
            if (init && init.body && typeof init.body === 'string' && target.includes('/screen/')) {
                posts.push({ url: target, body: JSON.parse(init.body) });
                return { ok: true, json: async () => ({}) };
            }
            if (target.includes('/upload')) {
                return { ok: true, json: async () => ({ url: '/files/x.jpg' }) };
            }
            // The analyze call: the share ends while this is in flight.
            stream.end();
            return {
                ok: true,
                json: async () => ({ ok: true, analysis_text: 'a real sentence about the screen here' }),
            };
        }));
        posts.length = 0;
        await sense.ask('what is this?', { conversationId: 'c1' });
        expect(posts.filter((p) => p.body.action === 'start')).toEqual([]);
    });

    it('leaves desktop and upload modes alone', () => {
        // Neither keeps a stream open, so there is nothing to verify and nothing to lose.
        const sense = load();
        for (const mode of ['desktop', 'upload']) {
            sense.mode = mode;
            expect(sense.verifyShare()).toBe(true);
            expect(sense.enabled).toBe(true);
        }
    });
});

/**
 * The MeetingSense entry point (batch MS5).
 *
 * Two things are load-bearing here and everything else is copy.
 *
 * **With the flag off, the button does not change.** ScreenSense's promise is a silent still
 * with no backend, and people who never enable MeetingSense keep it. The test for that is not
 * "the popover is absent" — it is that the button's `outerHTML` is byte-identical before and
 * after `attach()` has run, which also catches an `aria-` attribute or a stray listener class
 * added on the way past.
 *
 * **Every disabled control says why, and what to set.** A greyed-out toggle with no
 * explanation is the failure this batch exists to prevent, so each `/status` shape is rendered
 * and asserted, and one test walks the module for generic "unavailable" prose.
 */
import { describe as suite, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import axe from 'axe-core';

import {
    attach,
    buildPopover,
    describe as describeStatus,
    detectCapabilities,
    detectDesktopAudio,
    fetchStatus,
    type Capabilities,
    type MeetingSenseStatus,
} from '../ui/meetingsense/entryPoint';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const ENTRY_SOURCE = resolve(ROOT, 'frontend/src/ui/meetingsense/entryPoint.ts');

const DESKTOP: Capabilities = { canCaptureDisplay: true, platform: 'windows' };

function status(overrides: Partial<MeetingSenseStatus> = {}): MeetingSenseStatus {
    return {
        enabled: true,
        ready: true,
        stt: { available: true, provider: 'whisper-local', segments: true, remote: false },
        vision: { available: true, model: 'llava' },
        ...overrides,
    };
}

function noticeIds(s: MeetingSenseStatus | null, caps: Capabilities = DESKTOP) {
    return describeStatus(s, caps).notices.map((n) => n.id);
}

/**
 * ScreenSense's own button, built the way it builds it — including the bubble-phase click
 * listener that fires "Ask once". That listener is the thing MS5 has to work around without
 * editing the file it lives in, so a fake without it would test nothing.
 */
function screenSenseButton() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = '👁 Share screen';
    btn.title = 'Nexus asks your browser to share a window/screen';
    btn.style.cssText = 'position:fixed;right:18px;bottom:18px';
    document.body.appendChild(btn);
    const asks: number[] = [];
    btn.addEventListener('click', () => asks.push(Date.now()));
    (btn as unknown as { asks: number[] }).asks = asks;
    return btn as HTMLButtonElement & { asks: number[] };
}

beforeEach(() => {
    document.body.innerHTML = '';
});

afterEach(() => {
    vi.restoreAllMocks();
});

// ── the flag-off guarantee ──────────────────────────────────────────────────

suite('with MeetingSense disabled', () => {
    it('leaves the button byte-identical', () => {
        // Not "no popover appears" — that would still pass if attach() set an aria attribute
        // or a class on the way past, and the promise is that the button is untouched.
        const button = screenSenseButton();
        const before = button.outerHTML;
        const result = attach(button, { status: { enabled: false }, capabilities: DESKTOP });
        expect(result).toBeNull();
        expect(button.outerHTML).toBe(before);
    });

    it('adds nothing to the document', () => {
        const button = screenSenseButton();
        const before = document.body.innerHTML;
        attach(button, { status: { enabled: false }, capabilities: DESKTOP });
        expect(document.body.innerHTML).toBe(before);
    });

    it('treats an unreachable status the same as disabled', () => {
        // A frontend that cannot read `/status` must not offer a control the backend would
        // refuse. Silence reads as "off", never as "probably fine".
        const button = screenSenseButton();
        const before = button.outerHTML;
        expect(attach(button, { status: null, capabilities: DESKTOP })).toBeNull();
        expect(button.outerHTML).toBe(before);
    });

    it('still explains itself when asked', () => {
        expect(noticeIds({ enabled: false })).toEqual(['disabled']);
        expect(describeStatus({ enabled: false }, DESKTOP).notices[0].text).toContain(
            'MEETINGSENSE_ENABLED',
        );
    });
});

// ── honest degraded modes (§2a) ─────────────────────────────────────────────

suite('every unavailable capability says why and what to set', () => {
    it('a healthy local install has nothing to warn about', () => {
        expect(noticeIds(status())).toEqual([]);
        expect(describeStatus(status(), DESKTOP).canRecordAudio).toBe(true);
    });

    it('no speech provider repeats the server’s own hint rather than a second copy', () => {
        // The server already names the environment variable. Restating it in the client is a
        // second place to keep in step, and the two drift the first time one is edited.
        const hint = 'Set WHISPER_MODEL (e.g. small) for local transcription, or STT_BASE_URL for a remote one.';
        const described = describeStatus(
            status({ stt: { available: false, provider: null, hint } }),
            DESKTOP,
        );
        expect(described.canRecordAudio).toBe(false);
        expect(described.notices[0].text).toBe(hint);
    });

    it('falls back to a specific sentence when the server sends no hint', () => {
        const described = describeStatus(status({ stt: { available: false } }), DESKTOP);
        expect(described.notices[0].text).toMatch(/no speech provider is configured/i);
    });

    it('names a remote provider without ever echoing the endpoint', () => {
        const described = describeStatus(
            status({ stt: { available: true, provider: 'openai-compat', remote: true, segments: true } }),
            DESKTOP,
        );
        const text = described.notices.map((n) => n.text).join(' ');
        expect(text).toContain('openai-compat');
        // The endpoint can carry a key, so it is never in the status body and never here.
        expect(text).not.toMatch(/https?:\/\//);
    });

    it('says so when the provider cannot report timings', () => {
        expect(
            noticeIds(status({ stt: { available: true, provider: 'openai-compat', segments: false } })),
        ).toContain('stt-no-timestamps');
    });

    it('surfaces a silent CPU fallback', () => {
        // "auto" is a request, not an outcome. A model that quietly landed on CPU runs about
        // ten times slower, and nothing else in the UI would say why.
        const described = describeStatus(
            status({
                stt: {
                    available: true,
                    provider: 'whisper-local',
                    segments: true,
                    device: 'cpu',
                    device_note: 'requested cuda, running on cpu',
                },
            }),
            DESKTOP,
        );
        expect(described.notices.map((n) => n.text).join(' ')).toContain('running on cpu');
    });

    it('explains macOS rather than pretending it works', () => {
        const ids = noticeIds(status(), { canCaptureDisplay: true, platform: 'mac' });
        expect(ids).toContain('capture-mac');
        expect(
            describeStatus(status(), { canCaptureDisplay: true, platform: 'mac' })
                .notices.find((n) => n.id === 'capture-mac')!.text,
        ).toMatch(/virtual audio device/);
    });

    it('tells a Linux user to share a tab', () => {
        expect(noticeIds(status(), { canCaptureDisplay: true, platform: 'linux' })).toContain(
            'capture-linux',
        );
    });

    it('says slides will not be captioned when there is no vision model', () => {
        const described = describeStatus(status({ vision: { available: false, hint: 'Set MEETINGSENSE_VISION_MODEL.' } }), DESKTOP);
        const notice = described.notices.find((n) => n.id === 'vision-unavailable')!;
        expect(notice.text).toBe('Set MEETINGSENSE_VISION_MODEL.');
        // Slides are not required for a meeting, so this must not read as a blocker.
        expect(notice.tone).toBe('info');
    });

    it('contains no generic "unavailable" prose', () => {
        // §2a: every disabled state names its own cause. A bare "unavailable" is the string
        // that makes a user file a bug instead of setting a variable.
        const source = readFileSync(ENTRY_SOURCE, 'utf8');
        const code = source
            .split('\n')
            .filter((line) => !line.trimStart().startsWith('*') && !line.trimStart().startsWith('//'))
            .join('\n');
        for (const banned of ['not available', 'unavailable.', 'Unavailable', 'Not supported']) {
            expect(code).not.toContain(banned);
        }
    });
});

// ── mobile ──────────────────────────────────────────────────────────────────

suite('on a browser that cannot capture', () => {
    const MOBILE: Capabilities = { canCaptureDisplay: false, platform: 'mobile' };

    it('says a desktop browser is needed', () => {
        expect(noticeIds(status(), MOBILE)).toContain('capture-mobile');
    });

    it('hides the capture toggles rather than greying them', () => {
        // A disabled control on a phone invites tapping it and getting nothing; the sentence
        // below already carries the explanation.
        const popover = buildPopover(document, describeStatus(status(), MOBILE), MOBILE);
        expect(popover.querySelector('[data-ms="watch"]')).toBeNull();
        expect(popover.querySelector('[data-ms="record"]')).toBeNull();
        expect(popover.querySelector('[data-ms="notice:capture-mobile"]')).not.toBeNull();
    });

    it('distinguishes a desktop browser that simply cannot share audio', () => {
        expect(noticeIds(status(), { canCaptureDisplay: false, platform: 'linux' })).toContain(
            'capture-unsupported',
        );
    });
});

suite('detectCapabilities', () => {
    const win = (userAgent: string, hasDisplayMedia = true) => ({
        navigator: {
            userAgent,
            mediaDevices: hasDisplayMedia ? { getDisplayMedia: () => {} } : {},
        },
    });

    it('recognises a phone', () => {
        const caps = detectCapabilities(win('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile/15E148'));
        expect(caps.platform).toBe('mobile');
        expect(caps.canCaptureDisplay).toBe(false);
    });

    it('recognises macOS', () => {
        expect(detectCapabilities(win('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)')).platform).toBe('mac');
    });

    it('reports no capture when the API is missing', () => {
        expect(detectCapabilities(win('Mozilla/5.0 (X11; Linux x86_64)', false)).canCaptureDisplay).toBe(false);
    });
});

// ── the popover ─────────────────────────────────────────────────────────────

suite('the popover', () => {
    it('opens and closes from the button', () => {
        const button = screenSenseButton();
        const entry = attach(button, { status: status(), capabilities: DESKTOP })!;
        expect(entry.isOpen).toBe(false);
        button.click();
        expect(entry.isOpen).toBe(true);
        button.click();
        expect(entry.isOpen).toBe(false);
    });

    it('closes on Escape and gives focus back to the button', () => {
        // A popover that closes into nothing leaves a keyboard user at the top of the document
        // with no idea what happened.
        const button = screenSenseButton();
        const entry = attach(button, { status: status(), capabilities: DESKTOP })!;
        entry.open();
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(entry.isOpen).toBe(false);
        expect(document.activeElement).toBe(button);
    });

    it('leaves Escape alone when it is already closed', () => {
        const button = screenSenseButton();
        attach(button, { status: status(), capabilities: DESKTOP });
        const elsewhere = document.createElement('input');
        document.body.appendChild(elsewhere);
        elsewhere.focus();
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(document.activeElement).toBe(elsewhere);
    });

    it('reports which toggles were chosen', () => {
        const button = screenSenseButton();
        const chosen: unknown[] = [];
        const entry = attach(button, {
            status: status(),
            capabilities: DESKTOP,
            onStart: (choice) => chosen.push(choice),
        })!;
        entry.open();
        entry.popover.querySelector<HTMLInputElement>('[data-ms="record"]')!.checked = true;
        entry.popover.querySelector<HTMLButtonElement>('[data-ms="start"]')!.click();
        expect(chosen).toEqual([{ watchScreen: false, recordAudio: true, liveNotes: false }]);
        expect(entry.isOpen).toBe(false);
    });

    it('cannot switch on a capability the backend does not have', () => {
        const button = screenSenseButton();
        const entry = attach(button, {
            status: status({ stt: { available: false, hint: 'Set WHISPER_MODEL.' } }),
            capabilities: DESKTOP,
        })!;
        expect(entry.popover.querySelector<HTMLInputElement>('[data-ms="record"]')!.disabled).toBe(true);
        // Watching the screen still works without speech, so that one stays live.
        expect(entry.popover.querySelector<HTMLInputElement>('[data-ms="watch"]')!.disabled).toBe(false);
    });

    it('names the resolved provider', () => {
        const button = screenSenseButton();
        const entry = attach(button, { status: status(), capabilities: DESKTOP })!;
        expect(entry.popover.querySelector('[data-ms="provider"]')!.textContent).toContain('whisper-local');
    });

    it('reminds the user to tell participants', () => {
        const popover = buildPopover(document, describeStatus(status(), DESKTOP), DESKTOP);
        expect(popover.textContent).toMatch(/tell participants/i);
    });

    it('destroy puts the button back exactly as it was', () => {
        const button = screenSenseButton();
        const before = button.outerHTML;
        const entry = attach(button, { status: status(), capabilities: DESKTOP })!;
        expect(button.outerHTML).not.toBe(before);
        entry.destroy();
        expect(button.outerHTML).toBe(before);
        expect(document.getElementById('meetingsense-popover')).toBeNull();
    });
});

// ── "Ask once" keeps its exact current path ─────────────────────────────────

suite('the unchanged path', () => {
    it('runs on a plain click while MeetingSense is off', () => {
        const button = screenSenseButton();
        attach(button, { status: { enabled: false }, capabilities: DESKTOP });
        button.click();
        expect(button.asks.length).toBe(1);
    });

    it('does not also fire when the popover opens', () => {
        // Without the suppression, one click both asks a question and opens a menu — the user
        // gets an answer they did not request every time they reach for the toggles.
        const button = screenSenseButton();
        const entry = attach(button, { status: status(), capabilities: DESKTOP })!;
        button.click();
        expect(entry.isOpen).toBe(true);
        expect(button.asks.length).toBe(0);
    });

    it('fires exactly once from the popover, through ScreenSense’s own handler', () => {
        // Re-dispatched rather than reimplemented: "Ask once" is ScreenSense's behaviour, and
        // a second copy of it here would be the copy that goes stale.
        const button = screenSenseButton();
        const entry = attach(button, { status: status(), capabilities: DESKTOP })!;
        entry.open();
        entry.popover.querySelector<HTMLButtonElement>('[data-ms="ask"]')!.click();
        expect(button.asks.length).toBe(1);
        expect(entry.isOpen).toBe(false);
    });

    it('offers Ask once even when nothing can be recorded', () => {
        // The degraded popover is where somebody lands when speech is unconfigured, and the
        // one thing that still works must not disappear from it.
        const button = screenSenseButton();
        const entry = attach(button, {
            status: status({ stt: { available: false, hint: 'Set WHISPER_MODEL.' } }),
            capabilities: DESKTOP,
        })!;
        expect(entry.popover.querySelector<HTMLButtonElement>('[data-ms="ask"]')!.disabled).toBe(false);
        entry.popover.querySelector<HTMLButtonElement>('[data-ms="ask"]')!.click();
        expect(button.asks.length).toBe(1);
    });

    it('comes back after destroy', () => {
        const button = screenSenseButton();
        attach(button, { status: status(), capabilities: DESKTOP })!.destroy();
        button.click();
        expect(button.asks.length).toBe(1);
    });
});

// ── accessibility ───────────────────────────────────────────────────────────

suite('accessibility', () => {
    it('has zero axe violations when open', async () => {
        const button = screenSenseButton();
        const entry = attach(button, { status: status(), capabilities: DESKTOP })!;
        entry.open();
        const results = await axe.run(document.body, {
            rules: { 'color-contrast': { enabled: false } }, // jsdom does not lay out or paint
        });
        expect(results.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
    });

    it('has zero axe violations in the degraded shape too', async () => {
        // The degraded popover is a different tree — hidden toggles, more list items — and it
        // is the one a user in trouble actually reads.
        const button = screenSenseButton();
        const entry = attach(button, {
            status: status({ stt: { available: false, hint: 'Set WHISPER_MODEL.' }, vision: { available: false } }),
            capabilities: { canCaptureDisplay: false, platform: 'mobile' },
        })!;
        entry.open();
        const results = await axe.run(document.body, { rules: { 'color-contrast': { enabled: false } } });
        expect(results.violations.map((v) => v.id)).toEqual([]);
    });

    it('tells assistive tech what the button controls', () => {
        const button = screenSenseButton();
        const entry = attach(button, { status: status(), capabilities: DESKTOP })!;
        expect(button.getAttribute('aria-expanded')).toBe('false');
        expect(button.getAttribute('aria-controls')).toBe(entry.popover.id);
        entry.open();
        expect(button.getAttribute('aria-expanded')).toBe('true');
    });
});

// ── status fetch ────────────────────────────────────────────────────────────

suite('fetchStatus', () => {
    it('returns the body', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => status() })));
        expect((await fetchStatus())!.enabled).toBe(true);
    });

    it('returns null rather than throwing when the backend is down', async () => {
        // A frontend that throws here would break the page it is bolted onto, for a feature
        // that ships disabled.
        vi.stubGlobal('fetch', vi.fn(async () => {
            throw new Error('ECONNREFUSED');
        }));
        expect(await fetchStatus()).toBeNull();
    });

    it('returns null on a non-200', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({}) })));
        expect(await fetchStatus()).toBeNull();
    });
});

// ── desktop system audio (MS11) ─────────────────────────────────────────────

/**
 * The batch row for MS11 says "manual QA Windows + macOS", and it has to: nobody can run
 * Electron's loopback capture in CI. What *can* be tested is every decision made around it,
 * which is where the failure that matters lives — not "does loopback work on Windows" but
 * "does a mac user get told, before they record, that the call is not being captured".
 *
 * A user who believes the call is being recorded and finds out afterwards that it was not has
 * lost the meeting, and no amount of manual QA on a Windows machine catches that.
 */

// eslint-disable-next-line @typescript-eslint/no-var-requires
const desktopAudio = require(resolve(ROOT, 'desktop/meetingsense-audio.js'));

suite('the desktop audio module', () => {
    it('offers loopback on Windows and nowhere else on Electron 33', () => {
        expect(desktopAudio.loopbackSupported('win32')).toBe(true);
        expect(desktopAudio.loopbackSupported('darwin')).toBe(false);
        expect(desktopAudio.loopbackSupported('linux')).toBe(false);
    });

    it('never sends audio:loopback on a platform that would silently ignore it', () => {
        // The failure this prevents is quiet: the request resolves with a stream that has no
        // audio track, and the recorder reports "system+mic" for a meeting that recorded one
        // side of itself.
        const source = { id: 'screen:0' };
        expect(desktopAudio.displayMediaResponse(source, 'win32')).toEqual({
            video: source,
            audio: 'loopback',
        });
        expect(desktopAudio.displayMediaResponse(source, 'darwin')).toEqual({ video: source });
    });

    it('tells a mac user what would actually help, not just that it cannot', () => {
        const caps = desktopAudio.capabilities({ platform: 'darwin', enabled: true });
        expect(caps.loopback).toBe(false);
        expect(caps.mode).toBe('mic');
        expect(caps.hint).toMatch(/virtual audio device/i);
        expect(caps.hint).toMatch(/microphone/i);
    });

    it('separates "off" from "not possible here"', () => {
        // Two different facts, and the popover needs both: off on Windows means "turn it on",
        // and off on macOS means nothing the user can do about it.
        const windows = desktopAudio.capabilities({ platform: 'win32', enabled: false });
        const mac = desktopAudio.capabilities({ platform: 'darwin', enabled: false });
        expect([windows.supported, windows.loopback]).toEqual([true, false]);
        expect([mac.supported, mac.loopback]).toEqual([false, false]);
    });

    it('registers nothing at all when the flag is off', async () => {
        // The point of the batch's "desktop build unchanged with flag off": an installed
        // handler changes what every getDisplayMedia call in the app does, ScreenSense's
        // included.
        const calls: unknown[] = [];
        const session = { setDisplayMediaRequestHandler: (...args: unknown[]) => calls.push(args) };
        expect(desktopAudio.install({ session, desktopCapturer: {}, platform: 'win32', enabled: false })).toBe(
            false,
        );
        expect(calls).toEqual([]);
    });

    it('registers the handler with the system picker when the flag is on', async () => {
        let handler: any = null;
        let options: any = null;
        const session = {
            setDisplayMediaRequestHandler: (h: any, o: any) => {
                handler = h;
                options = o;
            },
        };
        const source = { id: 'screen:0' };
        const installed = desktopAudio.install({
            session,
            desktopCapturer: { getSources: async () => [source] },
            platform: 'win32',
            enabled: true,
        });
        expect(installed).toBe(true);
        expect(options).toEqual({ useSystemPicker: true });

        const answered: unknown[] = [];
        await handler({}, (r: unknown) => answered.push(r));
        expect(answered).toEqual([{ video: source, audio: 'loopback' }]);
    });

    it('refuses rather than throwing when there is nothing to capture', async () => {
        // An empty answer the renderer can handle: the recorder falls back to the microphone
        // rather than failing to start a meeting.
        for (const capturer of [
            { getSources: async () => [] },
            {
                getSources: async () => {
                    throw new Error('the compositor said no');
                },
            },
        ]) {
            let handler: any = null;
            const session = { setDisplayMediaRequestHandler: (h: any) => (handler = h) };
            desktopAudio.install({ session, desktopCapturer: capturer, platform: 'win32', enabled: true, log: () => {} });
            const answered: unknown[] = [];
            await handler({}, (r: unknown) => answered.push(r));
            expect(answered).toEqual([{}]);
        }
    });
});

suite('the popover, inside the desktop shell', () => {
    const mac = { enabled: true, supported: false, loopback: false, hint: 'macOS cannot share system audio…' };
    const windows = { enabled: true, supported: true, loopback: true, hint: 'The call’s audio and this microphone are both recorded.' };

    const ids = (caps: Capabilities) => describeStatus(status(), caps).notices.map((n) => n.id);

    it('says the call is being recorded on Windows', () => {
        const notices = describeStatus(status(), { ...DESKTOP, desktop: windows }).notices;
        const notice = notices.find((n) => n.id === 'desktop-loopback');
        expect(notice?.tone).toBe('info');
        expect(notice?.text).toBe(windows.hint);
    });

    it('warns, before recording starts, that a mac is not capturing the call', () => {
        const notices = describeStatus(status(), {
            canCaptureDisplay: true,
            platform: 'mac',
            desktop: mac,
        }).notices;
        const notice = notices.find((n) => n.id === 'desktop-no-loopback');
        expect(notice?.tone).toBe('warn');
        expect(notice?.text).toBe(mac.hint);
    });

    it('replaces the browser rules rather than showing both', () => {
        // The browser notices describe what Chrome's getDisplayMedia does. With the handler
        // installed, Electron answers that call itself — so leaving the Linux "share a tab"
        // notice in would be describing a dialog the user will never see.
        expect(ids({ canCaptureDisplay: true, platform: 'linux', desktop: { ...windows } })).toContain(
            'desktop-loopback',
        );
        expect(ids({ canCaptureDisplay: true, platform: 'linux', desktop: { ...windows } })).not.toContain(
            'capture-linux',
        );
        expect(ids({ canCaptureDisplay: true, platform: 'mac', desktop: mac })).not.toContain('capture-mac');
    });

    it('offers "turn it on" only where turning it on would help', () => {
        const off = { enabled: false, hint: 'Desktop system audio is off…' };
        expect(
            ids({ canCaptureDisplay: true, platform: 'windows', desktop: { ...off, supported: true, loopback: false } }),
        ).toContain('desktop-audio-off');
        // On a mac the answer is a virtual audio device, not a setting — so the browser's own
        // macOS notice stands and no "turn it on in Settings" is offered.
        const macOff = ids({
            canCaptureDisplay: true,
            platform: 'mac',
            desktop: { ...off, supported: false, loopback: false },
        });
        expect(macOff).not.toContain('desktop-audio-off');
        expect(macOff).toContain('capture-mac');
    });

    it('a browser is unaffected: no desktop notice, the browser rules stand', () => {
        const notices = ids({ canCaptureDisplay: true, platform: 'mac' });
        expect(notices.filter((id) => id.startsWith('desktop-'))).toEqual([]);
        expect(notices).toContain('capture-mac');
    });
});

suite('detectDesktopAudio', () => {
    it('is null in a browser, with no bridge to await', async () => {
        expect(await detectDesktopAudio({})).toBeNull();
        expect(await detectDesktopAudio({ homepilot: { isDesktop: true } })).toBeNull();
    });

    it('is null when an older shell has no handler for the channel', async () => {
        // The shell shipped before MS11 answers by rejecting. The browser rules then apply,
        // which is exactly what the renderer did before this batch.
        const win = { homepilot: { meetingSenseAudio: async () => { throw new Error('no handler'); } } };
        expect(await detectDesktopAudio(win)).toBeNull();
    });

    it('is null for an answer with no hint, rather than a popover with a blank line', async () => {
        const win = { homepilot: { meetingSenseAudio: async () => ({ enabled: true }) } };
        expect(await detectDesktopAudio(win)).toBeNull();
    });

    it('reads the shell’s answer', async () => {
        const win = {
            homepilot: {
                meetingSenseAudio: async () => desktopAudio.capabilities({ platform: 'win32', enabled: true }),
            },
        };
        const caps = await detectDesktopAudio(win);
        expect(caps?.loopback).toBe(true);
        expect(caps?.supported).toBe(true);
        expect(caps?.hint).toMatch(/both recorded/);
    });
});

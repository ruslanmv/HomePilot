/**
 * The mount (batch MS29, wave W11).
 *
 * W0–W10 built a recorder, a card, a pill, a consent sheet and a catalog, and mounted none of
 * it: every React component was a tested island that nothing rendered, and the recorder script
 * was never on the page. These are the tests for the layer that was missing.
 *
 * The promise under all of them is the one every batch was written to keep and this one is the
 * first to actually risk: **with the feature off, the application's DOM is what it was.** A
 * provider wrapped around the whole app is the single most dangerous thing this programme has
 * added, so it is asserted as `outerHTML` rather than by counting nodes.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import axe from 'axe-core';

import { MeetingSenseProvider, useMeetingControls } from '../ui/meetingsense/MeetingSenseProvider';
import { MeetingButton, blockedReason } from '../ui/meetingsense/MeetingButton';
import { CONSENT_STORAGE_KEY } from '../ui/meetingsense/ConsentSheet';

const ON = { enabled: true, ready: true, retention: 'text', stt: { available: true, provider: 'whisper' } };
const OFF = { enabled: false };

function memoryStorage(seed: Record<string, string> = {}): Storage {
    const map = new Map(Object.entries(seed));
    return {
        getItem: (k: string) => map.get(k) ?? null,
        setItem: (k: string, v: string) => void map.set(k, v),
        removeItem: (k: string) => void map.delete(k),
        clear: () => map.clear(),
        key: (i: number) => [...map.keys()][i] ?? null,
        get length() { return map.size; },
    } as Storage;
}

/** A stand-in for `window.hpMeetingSense`. */
function recorder(over: Record<string, unknown> = {}) {
    return {
        start: vi.fn(async () => ({ ok: true, meetingId: 'm1' })),
        stop: vi.fn(async () => ({ ok: true })),
        muteMic: vi.fn(),
        levels: [0],
        audioMode: 'system+mic',
        ...over,
    };
}

beforeEach(() => {
    (globalThis as Record<string, unknown>).hpMeetingSense = recorder();
});

afterEach(() => {
    delete (globalThis as Record<string, unknown>).hpMeetingSense;
    delete (globalThis as Record<string, unknown>).hpScreenSense;
});

// ── the promise ─────────────────────────────────────────────────────────────

describe('off is nothing', () => {
    it('renders its children and not one node more', () => {
        // The whole application is inside this provider. If it added a wrapper, every page in
        // the product would have gained one.
        const app = <main id="app"><p>the application</p></main>;
        const bare = render(app);
        const before = bare.container.innerHTML;
        bare.unmount();

        const wrapped = render(
            <MeetingSenseProvider conversationId="c1" status={OFF}>{app}</MeetingSenseProvider>,
        );
        expect(wrapped.container.innerHTML).toBe(before);
    });

    it('adds nothing even with the feature on, until something is recording', () => {
        // On is not the same as recording. A user who has never pressed the button sees the
        // application they have always seen.
        const app = <main id="app"><p>the application</p></main>;
        const bare = render(app);
        const before = bare.container.innerHTML;
        bare.unmount();

        const wrapped = render(
            <MeetingSenseProvider conversationId="c1" status={ON}>{app}</MeetingSenseProvider>,
        );
        expect(wrapped.container.innerHTML).toBe(before);
    });

    it('shows no button when the server has the feature off', () => {
        // Absent, not disabled. A permanently dead control teaches people the product is
        // broken; an absent one teaches them nothing, which is right when there is nothing
        // to learn.
        render(
            <MeetingSenseProvider conversationId="c1" status={OFF}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        expect(screen.queryByTestId('ms-record')).toBeNull();
    });

    it('shows no button outside the provider at all', () => {
        const { container } = render(<MeetingButton />);
        expect(container.innerHTML).toBe('');
    });

    it('refuses to start even when something reaches past the button', async () => {
        // `begin` is reachable through the context by anything in the tree. Hiding the control
        // is not the same as turning the capability off, so the provider checks the server's
        // switch itself.
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;
        function Probe() {
            const c = useMeetingControls();
            return <button type="button" onClick={() => c?.begin()} data-testid="force">go</button>;
        }
        render(
            <MeetingSenseProvider
                conversationId="c1" status={OFF}
                storage={memoryStorage({ [CONSENT_STORAGE_KEY]: 'true' })}
            >
                <Probe />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('force'));
        await act(async () => {});
        expect(rec.start).not.toHaveBeenCalled();
        expect(screen.queryByTestId('ms-pill')).toBeNull();
    });
});

// ── the button ──────────────────────────────────────────────────────────────

describe('the record button', () => {
    it('appears when the feature is on', () => {
        render(
            <MeetingSenseProvider conversationId="c1" status={ON}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        expect(screen.getByTestId('ms-record-button').textContent).toContain('Start meeting');
    });

    it('starts on one click, with notes and slides already on', async () => {
        // A record button that opens a form is a record button pressed after the first two
        // minutes of the meeting are gone.
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;
        render(
            <MeetingSenseProvider
                conversationId="c1" status={ON}
                storage={memoryStorage({ [CONSENT_STORAGE_KEY]: 'true' })}
            >
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => expect(rec.start).toHaveBeenCalled());
        expect(rec.start.mock.calls[0][0]).toMatchObject({
            conversationId: 'c1', notes: true, watch: true,
        });
    });

    it('becomes a stop button while recording, and the pill appears', async () => {
        render(
            <MeetingSenseProvider
                conversationId="c1" status={ON}
                storage={memoryStorage({ [CONSENT_STORAGE_KEY]: 'true' })}
            >
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('ms-record-button'));
        // §2a: recording state is unmissable. No prop can turn the pill off.
        await waitFor(() => expect(screen.getByTestId('ms-pill')).toBeTruthy());
        expect(screen.getByTestId('ms-record-button').textContent).toContain('Stop meeting');
        expect(screen.getByTestId('ms-card')).toBeTruthy();
    });

    it('pressing it again begins the stop, which is a countdown not a stop', async () => {
        // MS6's rule, and this test exists to keep the button honest about it: Stop does *not*
        // stop the recorder. It starts a ten-second window in which capture keeps running, so
        // undoing leaves no hole — the ten seconds somebody spends deciding are usually ten
        // seconds somebody was still talking. So the assertion is the countdown, not the stop.
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;
        render(
            <MeetingSenseProvider
                conversationId="c1" status={ON}
                storage={memoryStorage({ [CONSENT_STORAGE_KEY]: 'true' })}
            >
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => screen.getByTestId('ms-pill'));
        expect(rec.stop).not.toHaveBeenCalled();

        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => expect(screen.getByTestId('ms-undo')).toBeTruthy());
        expect(screen.getByTestId('ms-pill').getAttribute('data-phase')).toBe('stopping');
        // Still not stopped, on purpose.
        expect(rec.stop).not.toHaveBeenCalled();
    });

    it('hides the options chevron while recording', async () => {
        render(
            <MeetingSenseProvider
                conversationId="c1" status={ON}
                storage={memoryStorage({ [CONSENT_STORAGE_KEY]: 'true' })}
            >
                <MeetingButton onOptions={() => {}} />
            </MeetingSenseProvider>,
        );
        expect(screen.getByTestId('ms-record-options')).toBeTruthy();
        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => expect(screen.queryByTestId('ms-record-options')).toBeNull());
    });
});

describe('a blocked button says why', () => {
    it('names each cause in the user\'s terms', () => {
        // The one thing a disabled control must never do is stay silent about why.
        expect(blockedReason(OFF, 'c1')).toMatch(/turned off on this server/);
        expect(blockedReason(ON, null)).toMatch(/conversation/);
        expect(blockedReason(ON, 'c1')).toBeNull();
    });

    it('forwards the server\'s own hint about a missing speech provider', () => {
        // The server knows which provider is missing and what to set. Paraphrasing it here
        // would be a second, staler copy of that answer.
        const noStt = { enabled: true, stt: { available: false, hint: 'Set WHISPER_MODEL to enable transcription.' } };
        expect(blockedReason(noStt, 'c1')).toBe('Set WHISPER_MODEL to enable transcription.');
    });

    it('falls back to a real sentence when the server sends no hint', () => {
        const noStt = { enabled: true, stt: { available: false } };
        expect(blockedReason(noStt, 'c1')).toMatch(/No speech provider/);
    });

    it('disables the button and shows the reason on screen', () => {
        render(
            <MeetingSenseProvider conversationId={null} status={ON}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        expect((screen.getByTestId('ms-record-button') as HTMLButtonElement).disabled).toBe(true);
        expect(screen.getByTestId('ms-record-blocked').textContent).toMatch(/conversation/);
    });

    it('never starts a meeting with nowhere to land', async () => {
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;
        function Probe() {
            const c = useMeetingControls();
            return <button type="button" onClick={() => c?.begin()} data-testid="force">go</button>;
        }
        render(
            <MeetingSenseProvider
                conversationId={null} status={ON}
                storage={memoryStorage({ [CONSENT_STORAGE_KEY]: 'true' })}
            >
                <Probe />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('force'));
        await act(async () => {});
        expect(rec.start).not.toHaveBeenCalled();
    });
});

// ── consent ─────────────────────────────────────────────────────────────────

describe('consent comes before capture', () => {
    it('asks before the first recording on this machine', async () => {
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;
        render(
            <MeetingSenseProvider conversationId="c1" status={ON} storage={memoryStorage()}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => expect(screen.getByTestId('ms-consent')).toBeTruthy());
        // Nothing has been captured yet. The order is the point.
        expect(rec.start).not.toHaveBeenCalled();
    });

    it('starts once accepted', async () => {
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;
        render(
            <MeetingSenseProvider conversationId="c1" status={ON} storage={memoryStorage()}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => screen.getByTestId('ms-consent'));
        fireEvent.click(screen.getByTestId('ms-consent-accept'));
        await waitFor(() => expect(rec.start).toHaveBeenCalled());
    });

    it('does not remember unless the box is ticked', async () => {
        // The default. Somebody who accepts once has agreed to this recording, not to every
        // future one.
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;
        const store = memoryStorage();
        render(
            <MeetingSenseProvider conversationId="c1" status={ON} storage={store}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => screen.getByTestId('ms-consent'));
        fireEvent.click(screen.getByTestId('ms-consent-accept'));
        await waitFor(() => expect(rec.start).toHaveBeenCalled());
        expect(store.getItem(CONSENT_STORAGE_KEY)).toBeNull();
    });

    it('does not ask again once remembered', async () => {
        // A consent dialog that appears every time is one people learn to dismiss without
        // reading, which is the opposite of consent.
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;
        render(
            <MeetingSenseProvider
                conversationId="c1" status={ON}
                storage={memoryStorage({ [CONSENT_STORAGE_KEY]: 'true' })}
            >
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => expect(rec.start).toHaveBeenCalled());
        expect(screen.queryByTestId('ms-consent')).toBeNull();
    });

    it('accepting with "remember" means it is not asked again', async () => {
        // The write, not just the read. Without this, a provider that never persisted the
        // choice would still pass every other consent test here.
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;
        const store = memoryStorage();
        const first = render(
            <MeetingSenseProvider conversationId="c1" status={ON} storage={store}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => screen.getByTestId('ms-consent'));
        // Ticking the box is the user's choice, and it is unticked by default — consent that
        // remembers itself without being asked is not consent.
        fireEvent.click(screen.getByTestId('ms-consent-remember'));
        fireEvent.click(screen.getByTestId('ms-consent-accept'));
        await waitFor(() => expect(rec.start).toHaveBeenCalled());
        first.unmount();

        // A fresh mount, the same machine.
        render(
            <MeetingSenseProvider conversationId="c1" status={ON} storage={store}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => expect(rec.start).toHaveBeenCalledTimes(2));
        expect(screen.queryByTestId('ms-consent')).toBeNull();
    });

    it('cancelling records nothing and leaves no trace', async () => {
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;
        const { container } = render(
            <MeetingSenseProvider conversationId="c1" status={ON} storage={memoryStorage()}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => screen.getByTestId('ms-consent'));
        fireEvent.click(screen.getByTestId('ms-consent-cancel'));
        await waitFor(() => expect(screen.queryByTestId('ms-consent')).toBeNull());
        expect(rec.start).not.toHaveBeenCalled();
        expect(container.querySelector('[data-testid="ms-pill"]')).toBeNull();
    });
});

// ── failure is reported, never swallowed ────────────────────────────────────

describe('when it cannot start', () => {
    it('says so instead of looking like nothing happened', async () => {
        const rec = recorder({ start: vi.fn(async () => ({ ok: false, error: 'Microphone permission was denied.' })) });
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;
        render(
            <MeetingSenseProvider
                conversationId="c1" status={ON}
                storage={memoryStorage({ [CONSENT_STORAGE_KEY]: 'true' })}
            >
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() =>
            expect(screen.getByTestId('ms-record-error').textContent).toMatch(/Microphone permission/));
    });

    it('survives the recorder script not being on the page', async () => {
        // The state this batch exists to end, kept working: an older deployment without the
        // addon must degrade to a message, not a crash.
        delete (globalThis as Record<string, unknown>).hpMeetingSense;
        render(
            <MeetingSenseProvider
                conversationId="c1" status={ON}
                storage={memoryStorage({ [CONSENT_STORAGE_KEY]: 'true' })}
            >
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() =>
            expect(screen.getByTestId('ms-record-error').textContent).toMatch(/not loaded/));
    });
});

// ── the screen-share binding ────────────────────────────────────────────────

describe('screen-share awareness', () => {
    function sense() {
        const stub = { bindConversation: vi.fn(), setAwareness: vi.fn(), setVision: vi.fn() };
        (globalThis as Record<string, unknown>).hpScreenSense = stub;
        return stub;
    }

    it('hands ScreenSense the vision model the user chose (V1)', () => {
        // Settings stored these three and /v1/multimodal/analyze accepted them, but nothing
        // carried one to the other — so the floating button asked with no model and the
        // backend auto-detected. Somebody with a good model selected got moondream's answer.
        const stub = sense();
        localStorage.setItem('homepilot_provider_multimodal', 'ollama');
        localStorage.setItem('homepilot_base_url_multimodal', 'http://vision.local:11434');
        localStorage.setItem('homepilot_model_multimodal', 'gemma3:4b');
        render(<MeetingSenseProvider conversationId="c1" status={OFF}><div /></MeetingSenseProvider>);
        expect(stub.setVision).toHaveBeenCalledWith({
            provider: 'ollama',
            baseUrl: 'http://vision.local:11434',
            model: 'gemma3:4b',
        });
    });

    it('an unchosen model is an empty string, which means "let the backend decide"', () => {
        const stub = sense();
        localStorage.removeItem('homepilot_model_multimodal');
        render(<MeetingSenseProvider conversationId="c1" status={OFF}><div /></MeetingSenseProvider>);
        expect(stub.setVision).toHaveBeenCalledWith(
            expect.objectContaining({ model: '' }),
        );
    });

    it('an older copy of the addon without setVision is not a crash', () => {
        (globalThis as Record<string, unknown>).hpScreenSense = { bindConversation: vi.fn() };
        expect(() =>
            render(<MeetingSenseProvider conversationId="c1" status={OFF}><div /></MeetingSenseProvider>),
        ).not.toThrow();
    });

    it('tells ScreenSense which conversation a share belongs to', () => {
        const stub = sense();
        render(<MeetingSenseProvider conversationId="c1" status={OFF}><div /></MeetingSenseProvider>);
        expect(stub.bindConversation).toHaveBeenCalledWith('c1');
    });

    it('rebinds when the conversation changes', () => {
        // A share belongs to the conversation it started in. Leaving it bound would put one
        // person's screen into another thread's prompt.
        const stub = sense();
        const { rerender } = render(
            <MeetingSenseProvider conversationId="c1" status={OFF}><div /></MeetingSenseProvider>);
        rerender(<MeetingSenseProvider conversationId="c2" status={OFF}><div /></MeetingSenseProvider>);
        expect(stub.bindConversation).toHaveBeenLastCalledWith('c2');
    });

    it('applies the user\'s setting, and applies it before the binding', () => {
        // Order matters: the setting decides whether the binding may say anything at all.
        const stub = sense();
        const order: string[] = [];
        stub.setAwareness.mockImplementation(() => void order.push('setAwareness'));
        stub.bindConversation.mockImplementation(() => void order.push('bind'));
        render(
            <MeetingSenseProvider conversationId="c1" status={OFF} screenAwareness={false}>
                <div />
            </MeetingSenseProvider>);
        expect(stub.setAwareness).toHaveBeenCalledWith(false);
        expect(order).toEqual(['setAwareness', 'bind']);
    });

    it('defaults to on', () => {
        const stub = sense();
        render(<MeetingSenseProvider conversationId="c1" status={OFF}><div /></MeetingSenseProvider>);
        expect(stub.setAwareness).toHaveBeenCalledWith(true);
    });

    it('does not crash without ScreenSense, or on an older copy of it', () => {
        delete (globalThis as Record<string, unknown>).hpScreenSense;
        expect(() =>
            render(<MeetingSenseProvider conversationId="c1" status={OFF}><div /></MeetingSenseProvider>),
        ).not.toThrow();
        (globalThis as Record<string, unknown>).hpScreenSense = {};
        expect(() =>
            render(<MeetingSenseProvider conversationId="c2" status={OFF}><div /></MeetingSenseProvider>),
        ).not.toThrow();
    });
});

describe('accessibility', () => {
    it('has no axe violations, idle or recording', async () => {
        const idle = render(
            <MeetingSenseProvider conversationId="c1" status={ON}>
                <MeetingButton onOptions={() => {}} />
            </MeetingSenseProvider>,
        );
        expect((await axe.run(idle.container)).violations.map((v) => v.id)).toEqual([]);
        idle.unmount();

        const live = render(
            <MeetingSenseProvider
                conversationId="c1" status={ON}
                storage={memoryStorage({ [CONSENT_STORAGE_KEY]: 'true' })}
            >
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => screen.getByTestId('ms-pill'));
        expect((await axe.run(live.container)).violations.map((v) => v.id)).toEqual([]);
    });
});

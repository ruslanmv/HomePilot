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

/**
 * The node `MeetingWorkspace` portals into.
 *
 * It renders into `.hp-app-shell main` so the live meeting occupies the application's own
 * content area rather than floating over it. Without that node the portal has no host and the
 * workspace never appears — which looks exactly like "recording did not start", so the host is
 * set up here rather than left to be rediscovered per test.
 */
let appShell: HTMLElement | null = null;

function mountAppShell() {
    appShell = document.createElement('div');
    appShell.className = 'hp-app-shell';
    appShell.appendChild(document.createElement('main'));
    document.body.appendChild(appShell);
}

beforeEach(() => {
    (globalThis as Record<string, unknown>).hpMeetingSense = recorder();
    mountAppShell();
});

afterEach(() => {
    delete (globalThis as Record<string, unknown>).hpMeetingSense;
    delete (globalThis as Record<string, unknown>).hpScreenSense;
    appShell?.remove();
    appShell = null;
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
        expect(rec.start.mock.calls[0][0]).toMatchObject({ notes: true, watch: true });
        // A meeting records into a conversation of its own, not the one the button was
        // pressed from — an hour of transcript does not belong in the middle of a chat.
        // So the id is asserted as "a fresh one", not as the caller's.
        expect(rec.start.mock.calls[0][0].conversationId).toBeTruthy();
        expect(rec.start.mock.calls[0][0].conversationId).not.toBe('c1');
    });

    it('becomes a stop button while recording, and the workspace opens', async () => {
        render(
            <MeetingSenseProvider
                conversationId="c1" status={ON}
                storage={memoryStorage({ [CONSENT_STORAGE_KEY]: 'true' })}
            >
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('ms-record-button'));
        // §2a's rule survives the redesign: recording state is unmissable. The full-screen
        // workspace replaced the pill as the thing that cannot be missed.
        await waitFor(() => expect(screen.getByTestId('meeting-workspace')).toBeTruthy());
        expect(screen.getByTestId('ms-record-button').textContent).toContain('Stop meeting');
    });

    it('pressing it again ends the meeting and releases the microphone', async () => {
        // This replaces MS6's ten-second undo window. That window kept capture running after
        // Stop so an undo left no hole; the workspace removed it deliberately, because a
        // confirmed End must release the microphone there and then rather than keep recording
        // a room whose occupants believe it stopped.
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
        await waitFor(() => screen.getByTestId('meeting-workspace'));
        expect(rec.stop).not.toHaveBeenCalled();

        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => expect(rec.stop).toHaveBeenCalledTimes(1));
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

describe('the live meeting workspace', () => {
    /** Dispatch a transcribed line the way `homepilot-meetingsense.js` does. */
    const emitSegment = (text, seq) => act(() => {
        window.dispatchEvent(new CustomEvent('ms:segment', {
            detail: { id: `s${seq}`, seq, t0: seq * 1000, speaker: 'them', text },
        }));
    });

    async function startMeeting() {
        render(
            <MeetingSenseProvider
                conversationId="c1" status={ON}
                storage={memoryStorage({ [CONSENT_STORAGE_KEY]: 'true' })}
            >
                <MeetingButton />
            </MeetingSenseProvider>,
        );
        fireEvent.click(screen.getByTestId('ms-record-button'));
        return screen.findByTestId('meeting-workspace');
    }

    it('shows the transcript as it arrives, without changing tabs', async () => {
        /*
         * The workspace opened on Timeline, which renders decisions, slides and capture-source
         * changes and *no transcript*. So a live meeting showed "Meeting started" and nothing
         * else while the words were arriving one tab away, and the only way to learn it had
         * been working was to end the meeting and read the recap.
         *
         * During a meeting the question is "is it hearing me", and only the transcript
         * answers it.
         */
        const workspace = await startMeeting();
        emitSegment('the launch moves to October', 1);

        expect(workspace.textContent).toContain('the launch moves to October');
    });

    it('counts the lines where both tabs can see it', async () => {
        const workspace = await startMeeting();
        emitSegment('the launch moves', 1);
        emitSegment('pricing is agreed', 2);

        expect(screen.getByTestId('ms-transcript-count').textContent).toBe('2');

        // Still counted after switching away. The Timeline is a semantic view and shows no
        // transcript, so without the count it reads as "nothing is happening" — which is the
        // whole bug this replaced.
        fireEvent.click(screen.getByText(/Timeline/));
        expect(screen.getByTestId('ms-transcript-count').textContent).toBe('2');
        expect(workspace.textContent).not.toContain('the launch moves');
    });

    it('offers no way to close while it is still recording', async () => {
        // Closing a live meeting would be a Stop that does not say it is stopping, and
        // capture would outlive the window that said it was recording.
        await startMeeting();

        expect(screen.getByTestId('ms-workspace-end')).toBeTruthy();
        expect(screen.queryByTestId('ms-workspace-close')).toBeNull();
    });

    it('gives a way out once the meeting has ended', async () => {
        // The workspace is a full-screen portal, so "navigate somewhere else" was not an exit
        // — whatever you would navigate with is underneath it. A recap with no control on it
        // is a dead end, and that is the missing close button.
        await startMeeting();
        fireEvent.click(screen.getByTestId('ms-record-button'));

        const close = await screen.findByTestId('ms-workspace-close');
        fireEvent.click(close);

        await waitFor(() => expect(screen.queryByTestId('meeting-workspace')).toBeNull());
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

    it('brings its own conversation rather than needing one open', async () => {
        // This used to refuse: a meeting had nowhere to land without a conversation. It now
        // creates a dedicated one, so there is always somewhere — an hour of transcript does
        // not belong in the middle of a chat anyway.
        //
        // `MeetingButton` has not caught up: it still disables itself when the surrounding
        // conversation is null, and `blockedReason` still says a conversation is needed. The
        // capability and the control disagree, which is a real gap in the flow — but it is
        // the button that is stale, and this records which of the two is current.
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
        await waitFor(() => expect(rec.start).toHaveBeenCalledTimes(1));
        expect(rec.start.mock.calls[0][0].conversationId).toBeTruthy();
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
        // The workspace is a portal into the app shell, so it is audited where it actually
        // renders rather than inside the container that triggered it.
        const workspace = await screen.findByTestId('meeting-workspace');
        expect((await axe.run(live.container)).violations.map((v) => v.id)).toEqual([]);
        expect((await axe.run(workspace)).violations.map((v) => v.id)).toEqual([]);
    });
});

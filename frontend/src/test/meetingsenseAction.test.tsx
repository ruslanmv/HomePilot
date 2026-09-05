/**
 * Chat first (batch MS32, wave W12).
 *
 * MS29 mounted the record button under the composer and let it explain itself in place. The
 * result was that every chat screen — including for people who will never record a meeting —
 * carried an optional feature's control and the server's own setup string,
 * `Set WHISPER_MODEL (e.g. small) …`, directly beneath the message box, forever.
 *
 * These tests are the acceptance criteria for undoing that, written as behaviour rather than
 * as markup:
 *
 *   1. nothing about meetings is on screen until the control is pressed;
 *   2. an environment-variable name never reaches a chat user through this path;
 *   3. the control is a state as well as an action, and the live state is legible;
 *   4. Settings is where the precise, technical answer lives.
 */
import React from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

import { MeetingAction } from '../ui/meetingsense/MeetingAction';
import { meetingBlock } from '../ui/meetingsense/MeetingPanel';
import {
    MeetingSenseContext,
    MeetingSenseProvider,
    type MeetingControls,
} from '../ui/meetingsense/MeetingSenseProvider';
import { MeetingTranscriptionCard } from '../ui/meetingsense/MeetingTranscriptionCard';
import { CONSENT_STORAGE_KEY } from '../ui/meetingsense/ConsentSheet';

/** The real sentence the server sends, and the one thing chat must never show. */
const HINT = 'Set WHISPER_MODEL (e.g. small) for local transcription, or STT_BASE_URL for a remote one.';

const READY = { enabled: true, ready: true, stt: { available: true, provider: 'whisper', device: 'cpu' } };
const NO_STT = { enabled: true, ready: false, stt: { available: false, provider: null, hint: HINT } };
const OFF = { enabled: false };

function controls(over: Partial<MeetingControls> = {}): MeetingControls {
    return {
        live: false,
        starting: false,
        error: null,
        status: READY,
        conversationId: 'c1',
        begin: vi.fn(),
        end: vi.fn(),
        phase: 'idle',
        phaseText: 'not recording',
        elapsedMs: 0,
        micMuted: false,
        mute: vi.fn(),
        undo: vi.fn(),
        undoSecondsLeft: null,
        ...over,
    };
}

function mount(over: Partial<MeetingControls> = {}, props: Record<string, unknown> = {}) {
    const value = controls(over);
    const view = render(
        <MeetingSenseContext.Provider value={value}>
            <MeetingAction {...props} />
        </MeetingSenseContext.Provider>,
    );
    return { ...view, value };
}

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

afterEach(() => {
    delete (globalThis as Record<string, unknown>).hpMeetingSense;
});

// ── 1. the copy ─────────────────────────────────────────────────────────────

describe('meetingBlock', () => {
    it('is null when a meeting can start', () => {
        expect(meetingBlock(READY, 'c1')).toBeNull();
    });

    it('names the server switch, and does not offer Settings for it', () => {
        const block = meetingBlock(OFF, 'c1');
        // Settings cannot turn a server-side flag on, and a button that pretends otherwise
        // sends somebody hunting through a panel for a control that is not there.
        expect(block?.id).toBe('off');
        expect(block?.settings).toBe(false);
    });

    it('asks for a conversation before a provider', () => {
        // Order matters: with no conversation *and* no provider, "configure transcription" is
        // the wrong first instruction — the meeting has nowhere to land either way.
        const block = meetingBlock(NO_STT, null);
        expect(block?.id).toBe('no-conversation');
        expect(block?.settings).toBe(false);
    });

    it('uses the brief copy for an unconfigured provider', () => {
        const block = meetingBlock(NO_STT, 'c1');
        expect(block?.id).toBe('no-stt');
        expect(block?.title).toBe("Meeting transcription isn't configured");
        expect(block?.body).toBe('Configure a transcription provider to use meeting mode.');
        expect(block?.settings).toBe(true);
    });

    it('never repeats an environment-variable name', () => {
        // The regression this batch exists for. `status.stt.hint` is in scope here and it
        // would be the easy thing to pass through; every block is checked, not only the one
        // whose cause is the missing provider.
        for (const status of [OFF, NO_STT, READY]) {
            for (const conversation of ['c1', null]) {
                const block = meetingBlock(status, conversation);
                if (!block) continue;
                const text = `${block.title} ${block.body}`;
                expect(text).not.toMatch(/WHISPER_MODEL|STT_BASE_URL|_[A-Z]{2,}/);
            }
        }
    });
});

// ── 2. nothing until it is pressed ──────────────────────────────────────────

describe('the resting state', () => {
    it('renders nothing outside the provider', () => {
        const { container } = render(<MeetingAction />);
        expect(container.innerHTML).toBe('');
    });

    it('renders nothing when the server has the feature off', () => {
        const { container } = mount({ status: OFF });
        expect(container.innerHTML).toBe('');
    });

    it('shows no setup text before the control is pressed', () => {
        // The acceptance criterion, stated directly: an unconfigured install looks exactly
        // like a configured one until somebody asks.
        const { container } = mount({ status: NO_STT });
        expect(screen.getByTestId('ms-action-button')).toBeTruthy();
        expect(screen.queryByTestId('ms-setup-panel')).toBeNull();
        expect(container.textContent).not.toContain('WHISPER_MODEL');
        expect(container.textContent).not.toContain('configured');
    });

    it('is not disabled when a meeting cannot start', () => {
        // Live, so it can explain itself. A greyed control with nothing to press is the
        // failure mode this replaces.
        const { getByTestId } = mount({ status: NO_STT });
        expect((getByTestId('ms-action-button') as HTMLButtonElement).disabled).toBe(false);
    });
});

// ── 3. the state machine ────────────────────────────────────────────────────

describe('pressing it', () => {
    it('starts the meeting directly when everything is configured', () => {
        const { value } = mount();
        fireEvent.click(screen.getByTestId('ms-action-button'));
        expect(value.begin).toHaveBeenCalledTimes(1);
        // One press, one meeting. No popover, no confirmation step.
        expect(screen.queryByTestId('ms-action-popover')).toBeNull();
    });

    it('explains instead of starting when it cannot', () => {
        const { value } = mount({ status: NO_STT });
        fireEvent.click(screen.getByTestId('ms-action-button'));
        expect(value.begin).not.toHaveBeenCalled();
        expect(screen.getByTestId('ms-setup-panel').getAttribute('data-block')).toBe('no-stt');
        expect(screen.getByTestId('ms-action-popover').textContent).toContain(
            'Configure a transcription provider',
        );
    });

    it('offers no Settings button for a problem Settings cannot fix', () => {
        // "Open a conversation first" is not a configuration question. A Settings button
        // here sends somebody hunting through a panel for a control that is not in it.
        mount({ conversationId: null });
        fireEvent.click(screen.getByTestId('ms-action-button'));
        expect(screen.getByTestId('ms-setup-panel').getAttribute('data-block')).toBe(
            'no-conversation',
        );
        expect(screen.getByTestId('ms-action-popover').textContent).toContain(
            'Open a conversation first',
        );
        expect(screen.queryByTestId('ms-setup-settings')).toBeNull();
    });

    it('does not leak the server hint into the popover either', () => {
        mount({ status: NO_STT });
        fireEvent.click(screen.getByTestId('ms-action-button'));
        expect(screen.getByTestId('ms-action-popover').textContent).not.toContain('WHISPER_MODEL');
    });

    it('opens Settings through the event App already listens for', () => {
        const heard = vi.fn();
        window.addEventListener('homepilot:open-settings', heard);
        try {
            mount({ status: NO_STT });
            fireEvent.click(screen.getByTestId('ms-action-button'));
            fireEvent.click(screen.getByTestId('ms-setup-settings'));
            expect(heard).toHaveBeenCalledTimes(1);
            // And it closes on the way — a popover left open over the panel it just opened
            // is one the user has to dismiss before reading the answer.
            expect(screen.queryByTestId('ms-action-popover')).toBeNull();
        } finally {
            window.removeEventListener('homepilot:open-settings', heard);
        }
    });

    it('prefers an injected settings opener over the event', () => {
        const onOpenSettings = vi.fn();
        const heard = vi.fn();
        window.addEventListener('homepilot:open-settings', heard);
        try {
            mount({ status: NO_STT }, { onOpenSettings });
            fireEvent.click(screen.getByTestId('ms-action-button'));
            fireEvent.click(screen.getByTestId('ms-setup-settings'));
            expect(onOpenSettings).toHaveBeenCalledTimes(1);
            expect(heard).not.toHaveBeenCalled();
        } finally {
            window.removeEventListener('homepilot:open-settings', heard);
        }
    });

    it('closes on Escape', () => {
        mount({ status: NO_STT });
        fireEvent.click(screen.getByTestId('ms-action-button'));
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.queryByTestId('ms-action-popover')).toBeNull();
    });

    it('closes on a click elsewhere', () => {
        mount({ status: NO_STT });
        fireEvent.click(screen.getByTestId('ms-action-button'));
        fireEvent.mouseDown(document.body);
        expect(screen.queryByTestId('ms-action-popover')).toBeNull();
    });

    it('stays open when the click is inside it', () => {
        mount({ status: NO_STT });
        fireEvent.click(screen.getByTestId('ms-action-button'));
        fireEvent.mouseDown(screen.getByTestId('ms-action-popover'));
        expect(screen.queryByTestId('ms-action-popover')).toBeTruthy();
    });

    it('is inert and spinning while a meeting is starting', () => {
        const { value } = mount({ starting: true });
        const button = screen.getByTestId('ms-action-button') as HTMLButtonElement;
        expect(button.disabled).toBe(true);
        expect(button.getAttribute('data-state')).toBe('starting');
        expect(screen.getByTestId('ms-action-spinner')).toBeTruthy();
        fireEvent.click(button);
        expect(value.begin).not.toHaveBeenCalled();
    });
});

describe('while a meeting runs', () => {
    const LIVE = { live: true, phase: 'live' as const, phaseText: 'recording', elapsedMs: 522_000 };

    it('reads as a state, not just an action', () => {
        mount(LIVE);
        const button = screen.getByTestId('ms-action-button');
        expect(button.getAttribute('data-state')).toBe('live');
        expect(screen.getByTestId('ms-action-elapsed').textContent).toBe('08:42');
        // The label a screen reader gets carries the same two facts the pill does.
        expect(button.getAttribute('aria-label')).toBe('Meeting · 08:42');
    });

    it('opens a panel rather than stopping on the first click', () => {
        // Stop is destructive and the control is 36 pixels wide next to three others. A
        // press that ends a recording outright is one misclick from losing a meeting.
        const { value } = mount(LIVE);
        fireEvent.click(screen.getByTestId('ms-action-button'));
        expect(value.end).not.toHaveBeenCalled();
        expect(screen.getByTestId('ms-live-panel')).toBeTruthy();
        expect(screen.getByTestId('ms-panel-elapsed').textContent).toBe('08:42');
        expect(screen.getByTestId('ms-panel-phase').textContent).toBe('recording');
    });

    it('shows the running meeting even when a block would otherwise apply', () => {
        // A conversation switched away from mid-recording must not turn the control into a
        // setup prompt: the meeting is still running and Stop must stay reachable.
        mount({ ...LIVE, conversationId: null });
        fireEvent.click(screen.getByTestId('ms-action-button'));
        expect(screen.getByTestId('ms-live-panel')).toBeTruthy();
        expect(screen.queryByTestId('ms-setup-panel')).toBeNull();
    });

    it('ends the meeting from the panel', () => {
        const { value } = mount(LIVE);
        fireEvent.click(screen.getByTestId('ms-action-button'));
        fireEvent.click(screen.getByTestId('ms-panel-end'));
        expect(value.end).toHaveBeenCalledTimes(1);
    });

    it('mutes and unmutes, and says which it will do', () => {
        const { value } = mount(LIVE);
        fireEvent.click(screen.getByTestId('ms-action-button'));
        const mute = screen.getByTestId('ms-panel-mute');
        expect(mute.textContent).toBe('Mute mic');
        fireEvent.click(mute);
        expect(value.mute).toHaveBeenCalledWith(true);
    });

    it('offers Unmute when muted', () => {
        const { value } = mount({ ...LIVE, micMuted: true });
        fireEvent.click(screen.getByTestId('ms-action-button'));
        const mute = screen.getByTestId('ms-panel-mute');
        expect(mute.textContent).toBe('Unmute mic');
        expect(mute.getAttribute('aria-pressed')).toBe('true');
        fireEvent.click(mute);
        expect(value.mute).toHaveBeenCalledWith(false);
    });

    it('never offers a Pause it cannot honour', () => {
        // The recorder has mute and it has stop. A "Pause" that silently means "mute the
        // microphone" tells somebody their meeting is paused while the room is still being
        // captured.
        mount(LIVE);
        fireEvent.click(screen.getByTestId('ms-action-button'));
        expect(screen.getByTestId('ms-live-panel').textContent).not.toMatch(/Pause/i);
    });

    it('shows the undo countdown while stopping, and no way to stop twice', () => {
        const { value } = mount({
            ...LIVE, phase: 'stopping', phaseText: 'stopping…', undoSecondsLeft: 7,
        });
        fireEvent.click(screen.getByTestId('ms-action-button'));
        expect(screen.getByTestId('ms-panel-undo').textContent).toBe('Undo · 7s');
        expect(screen.queryByTestId('ms-panel-end')).toBeNull();
        fireEvent.click(screen.getByTestId('ms-panel-undo'));
        expect(value.undo).toHaveBeenCalledTimes(1);
    });

    it('surfaces a failed start under the control and not in the chat', () => {
        mount({ error: 'The meeting could not start.' });
        const error = screen.getByTestId('ms-action-error');
        expect(error.getAttribute('role')).toBe('status');
        expect(error.textContent).toContain('could not start');
    });
});

// ── 4. through the real provider ────────────────────────────────────────────

describe('wired to the provider', () => {
    it('one press starts a real recording', async () => {
        const start = vi.fn(async () => ({ ok: true, meetingId: 'm1' }));
        (globalThis as Record<string, unknown>).hpMeetingSense = {
            start, stop: vi.fn(async () => ({ ok: true })), muteMic: vi.fn(), levels: [0],
        };
        render(
            <MeetingSenseProvider
                conversationId="c1"
                status={READY}
                storage={memoryStorage({ [CONSENT_STORAGE_KEY]: 'true' })}
            >
                <MeetingAction />
            </MeetingSenseProvider>,
        );
        await act(async () => {
            fireEvent.click(screen.getByTestId('ms-action-button'));
        });
        await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
        expect(start.mock.calls[0][0]).toMatchObject({ conversationId: 'c1', notes: true, watch: true });
    });

    it('asks for consent before the first recording', async () => {
        const start = vi.fn(async () => ({ ok: true, meetingId: 'm1' }));
        (globalThis as Record<string, unknown>).hpMeetingSense = {
            start, stop: vi.fn(async () => ({ ok: true })), muteMic: vi.fn(), levels: [0],
        };
        render(
            <MeetingSenseProvider conversationId="c1" status={READY} storage={memoryStorage()}>
                <MeetingAction />
            </MeetingSenseProvider>,
        );
        await act(async () => {
            fireEvent.click(screen.getByTestId('ms-action-button'));
        });
        expect(start).not.toHaveBeenCalled();
    });
});

// ── 5. where the technical answer lives ─────────────────────────────────────

describe('Settings → Meeting transcription', () => {
    /**
     * `waitFor(() => expect(html).toBe(''))` passes on its first tick, before the probe has
     * resolved — it asserts that the component has not rendered *yet*, which every component
     * satisfies. So these settle the probe first and only then look.
     */
    async function settled(status: unknown) {
        let resolve: (v: unknown) => void = () => {};
        const gate = new Promise((r) => { resolve = r; });
        const view = render(
            <MeetingTranscriptionCard load={async () => { await gate; return status as never; }} />,
        );
        await act(async () => {
            resolve(null);
            await gate;
        });
        return view;
    }

    it('adds nothing to Settings when the feature is off', async () => {
        const { container } = await settled(OFF);
        expect(container.innerHTML).toBe('');
    });

    it('adds nothing when the probe fails', async () => {
        const { container } = await settled(null);
        expect(container.innerHTML).toBe('');
    });

    it('shows the server hint verbatim when transcription is unconfigured', async () => {
        render(<MeetingTranscriptionCard load={async () => NO_STT} />);
        await screen.findByTestId('ms-settings-transcription');
        expect(screen.getByTestId('ms-settings-state').textContent).toBe('Not configured');
        // Verbatim, because the server is the only thing that knows which provider is
        // missing — and this is the surface where that precision is what people came for.
        expect(screen.getByTestId('ms-settings-hint').textContent).toBe(HINT);
    });

    it('reports the provider when it is ready, and shows no hint', async () => {
        render(<MeetingTranscriptionCard load={async () => READY} />);
        await screen.findByTestId('ms-settings-transcription');
        expect(screen.getByTestId('ms-settings-state').textContent).toBe('Ready');
        expect(screen.getByTestId('ms-settings-transcription').textContent).toContain('whisper');
        expect(screen.queryByTestId('ms-settings-hint')).toBeNull();
    });

    it('shows no hint when transcription works, even if the server sends one', async () => {
        // `hint` is advice, not a fault. A device note next to a working provider is not a
        // setup problem and must not be presented as one.
        render(
            <MeetingTranscriptionCard
                load={async () => ({
                    enabled: true,
                    stt: { available: true, provider: 'whisper', hint: HINT },
                })}
            />,
        );
        await screen.findByTestId('ms-settings-transcription');
        expect(screen.getByTestId('ms-settings-state').textContent).toBe('Ready');
        expect(screen.queryByTestId('ms-settings-hint')).toBeNull();
    });

    it('does not render an empty hint box when the server sends no hint', async () => {
        render(
            <MeetingTranscriptionCard
                load={async () => ({ enabled: true, stt: { available: false } })}
            />,
        );
        await screen.findByTestId('ms-settings-transcription');
        expect(screen.queryByTestId('ms-settings-hint')).toBeNull();
    });
});

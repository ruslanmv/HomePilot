/**
 * Meeting, as a row in the composer's `+` menu.
 *
 * ── A second presentation, not a second implementation ───────────────────────────────────
 *
 * Moving an entry point is the kind of change that silently drops behaviour, and the behaviour
 * most at risk here is the part that is *not* "call begin()". The header button handled three
 * states that a naive menu row would get wrong:
 *
 *   - **blocked** — no MeetingSense, no speech-to-text, no conversation. Pressing must explain
 *     why, not start something that cannot work and not fail silently.
 *   - **starting** — a press already received; the wait is the feedback.
 *   - **live** — nothing to start. Offering "Start a meeting" while one runs would make the
 *     menu the only part of the interface disagreeing with the rest.
 *
 * So this reuses `meetingBlock`, `SetupPanel` and `LivePanel` unchanged and reads the same
 * `useMeetingControls()` the header button did. A meeting started from either is the same
 * meeting, because neither owns any state.
 */
import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const controls = vi.fn();

vi.mock('../ui/meetingsense/MeetingSenseProvider', () => ({
    useMeetingControls: () => controls(),
}));

import { MeetingMenuItem } from '../ui/meetingsense/MeetingMenuItem';

const READY = {
    live: false,
    starting: false,
    error: null,
    status: { enabled: true, stt: { available: true, provider: 'whisper' } },
    conversationId: 'conv-1',
    begin: vi.fn(),
    end: vi.fn(),
    phase: 'idle',
    phaseText: '',
    elapsedMs: 0,
    micMuted: false,
    mute: vi.fn(),
    undo: vi.fn(),
    undoSecondsLeft: null,
    capture: { audio: true, mic: true, slides: true, mode: null, myNames: '', assistantName: '' },
    setCapture: vi.fn(),
};

const give = (over: Record<string, unknown> = {}) => {
    const value = { ...READY, begin: vi.fn(), end: vi.fn(), ...over };
    controls.mockReturnValue(value);
    return value;
};

afterEach(() => {
    controls.mockReset();
    vi.clearAllMocks();
});

describe('starting a meeting from the menu', () => {
    it('uses the existing controls rather than a second implementation', () => {
        const value = give();
        const onDone = vi.fn();
        render(<MeetingMenuItem onDone={onDone} />);

        fireEvent.click(screen.getByTestId('ms-menu-start'));
        expect(value.begin).toHaveBeenCalledTimes(1);
        // And the menu closes: the workspace is about to take over the screen.
        expect(onDone).toHaveBeenCalledTimes(1);
    });

    it('renders nothing when the server has meetings off', () => {
        // Same rule the header button kept. A permanently dead row teaches people the product
        // is broken; an absent one teaches nothing, which is correct when there is nothing to
        // learn.
        give({ status: { enabled: false } });
        const { container } = render(<MeetingMenuItem onDone={vi.fn()} />);
        expect(container.textContent).toBe('');
    });

    it('renders nothing outside the provider', () => {
        controls.mockReturnValue(null);
        const { container } = render(<MeetingMenuItem onDone={vi.fn()} />);
        expect(container.textContent).toBe('');
    });
});

describe('the states a naive row would get wrong', () => {
    it('explains a block instead of starting something that cannot work', () => {
        const value = give({ status: { enabled: true, stt: { available: false } } });
        render(<MeetingMenuItem onDone={vi.fn()} />);

        fireEvent.click(screen.getByTestId('ms-menu-start'));
        expect(value.begin).not.toHaveBeenCalled();
        // The same copy `meetingBlock` gives the header button, so the two surfaces cannot
        // drift into giving different reasons for one refusal.
        expect(screen.getByTestId('ms-menu-blocked-panel').textContent)
            .toContain("Meeting transcription isn't configured");
    });

    it('lets the user back out of a block without leaving the menu', () => {
        // `SetupPanel` has no dismiss control of its own — in the header it sat in a popover an
        // outside click closed, and its only button is the optional "Open Settings". Inside a
        // menu that strands the reader with an explanation and no way back to the rest of it.
        give({ status: { enabled: true, stt: { available: false } } });
        render(<MeetingMenuItem onDone={vi.fn()} />);
        fireEvent.click(screen.getByTestId('ms-menu-start'));
        fireEvent.click(screen.getByTestId('ms-menu-back'));

        expect(screen.getByTestId('ms-menu-start')).toBeTruthy();
    });

    it('offers that way back even on a block with no Settings button', () => {
        // "Open a conversation first" renders `settings: false`, so without this the panel has
        // no controls whatsoever.
        give({ conversationId: null });
        render(<MeetingMenuItem onDone={vi.fn()} />);
        fireEvent.click(screen.getByTestId('ms-menu-start'));

        expect(screen.getByTestId('ms-menu-blocked-panel').textContent)
            .toContain('Open a conversation first');
        expect(screen.getByTestId('ms-menu-back')).toBeTruthy();
    });

    it('shows a meeting in progress rather than offering to start another', () => {
        // §2a keeps recording state unmissable through `RecordingPill`; this is the quieter
        // second place the same truth shows, in the menu somebody opens to think about
        // meetings. "Start a meeting" here would be the interface contradicting itself.
        give({ live: true, elapsedMs: 8 * 60_000 + 42_000, phase: 'live', phaseText: 'Recording' });
        render(<MeetingMenuItem onDone={vi.fn()} />);

        expect(screen.queryByTestId('ms-menu-start')).toBeNull();
        expect(screen.getByTestId('ms-menu-live').textContent).toContain('Meeting in progress');
        expect(screen.getByTestId('ms-menu-live').textContent).toContain('08:42');
    });

    it('opens the existing live controls from that row', () => {
        const value = give({ live: true, phase: 'live', phaseText: 'Recording', elapsedMs: 1000 });
        const onDone = vi.fn();
        render(<MeetingMenuItem onDone={onDone} />);

        fireEvent.click(screen.getByTestId('ms-menu-live'));
        expect(screen.getByTestId('ms-menu-live-panel')).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: /end/i }));
        expect(value.end).toHaveBeenCalledTimes(1);
        expect(onDone).toHaveBeenCalledTimes(1);
    });

    it('shows a press that has been received rather than hiding the row', () => {
        // Hiding it while starting reads as the click having done nothing.
        give({ starting: true, phase: 'starting' });
        render(<MeetingMenuItem onDone={vi.fn()} />);

        expect(screen.getByTestId('ms-menu-starting').textContent).toContain('Starting meeting…');
        expect(screen.queryByTestId('ms-menu-start')).toBeNull();
    });

    it('does not start a second meeting from the starting row', () => {
        const value = give({ starting: true, phase: 'starting' });
        render(<MeetingMenuItem onDone={vi.fn()} />);

        fireEvent.click(screen.getByTestId('ms-menu-starting'));
        expect(value.begin).not.toHaveBeenCalled();
    });
});

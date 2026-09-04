/**
 * Chips: rendering, dismissing, and the button that acts (batch MS25).
 *
 * The triggers live server-side and are tested there, with their negatives written down. What
 * is checked here is the half a browser owns: that a chip renders once, that dismissing is
 * local and does not delete, and — the load-bearing one — that **rendering a chip runs
 * nothing**. A chip carries a proposal, the proposal is a description, and only pressing the
 * button turns it into a request.
 */
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import axe from 'axe-core';

import { ChipRow } from '../ui/meetingsense/ChipRow';
import { MeetingCard } from '../ui/meetingsense/MeetingCard';
import { useMeetingSense } from '../ui/meetingsense/useMeetingSense';
import {
    EMPTY_VIEW,
    MAX_VISIBLE_CHIPS,
    chipLabel,
    dismissChip,
    mergeChip,
    resolveChip,
    visibleChips,
    type Chip,
} from '../ui/meetingsense/meetingState';

function chip(over: Partial<Chip> = {}): Chip {
    return {
        id: 'chip_a',
        kind: 'date',
        text: 'the draft is due by Friday',
        when: 'by Friday',
        proposal: { capability: 'calendar.create_event', label: 'Add to calendar' },
        ...over,
    };
}

// ── the pure functions ──────────────────────────────────────────────────────

describe('chip state', () => {
    it('merges on id, so a re-offer is one row', () => {
        // The server derives a chip's id from the offer rather than from a counter, precisely
        // so a reconnect or a second client on one meeting produces the same row.
        const once = mergeChip([], chip());
        expect(mergeChip(once, chip()).length).toBe(1);
    });

    it('keeps a dismissal when the same offer arrives again', () => {
        // The second copy is the same offer arriving again, not news about it. A re-offer that
        // un-dismissed a chip would put back exactly the thing the reader said no to.
        const after = dismissChip(mergeChip([], chip()), 'chip_a');
        expect(mergeChip(after, chip())[0].dismissed).toBe(true);
    });

    it('keeps a result when the same offer arrives again', () => {
        const done = resolveChip(mergeChip([], chip()), 'chip_a', { ok: true, tool: 'hp.cal' });
        expect(mergeChip(done, chip())[0].result).toEqual({ ok: true, tool: 'hp.cal' });
    });

    it('takes new server-side content on a re-offer', () => {
        const first = mergeChip([], chip({ text: 'first wording' }));
        expect(mergeChip(first, chip({ text: 'second wording' }))[0].text).toBe('second wording');
    });

    it('ignores a chip with no id', () => {
        expect(mergeChip([], { ...chip(), id: '' })).toEqual([]);
    });

    it('shows the newest first', () => {
        // A chip is about what was *just* said. Oldest-first would put the offer the reader
        // has already ignored at the top and the one they might want off the bottom.
        const list = [chip({ id: 'a' }), chip({ id: 'b' }), chip({ id: 'c' })];
        expect(visibleChips(list).map((c) => c.id)).toEqual(['c', 'b', 'a']);
    });

    it('caps what is on screen', () => {
        const many = Array.from({ length: 9 }, (_, i) => chip({ id: `c${i}` }));
        expect(visibleChips(many).length).toBe(MAX_VISIBLE_CHIPS);
    });

    it('hides a dismissed chip without deleting it', () => {
        const list = dismissChip([chip({ id: 'a' }), chip({ id: 'b' })], 'a');
        expect(list.length).toBe(2);
        expect(visibleChips(list).map((c) => c.id)).toEqual(['b']);
    });

    it('labels each kind', () => {
        expect(chipLabel(chip({ kind: 'question' }))).toBe('Asked you');
        expect(chipLabel(chip({ kind: 'decision' }))).toBe('Decision');
        expect(chipLabel(chip({ kind: 'action', owner: 'Ana' }))).toBe('Action · Ana');
        expect(chipLabel(chip({ kind: 'action', owner: 'me' }))).toBe('Action');
        expect(chipLabel(chip({ kind: 'date', when: 'by Friday' }))).toBe('Date · by Friday');
        expect(chipLabel(chip({ kind: 'link' }))).toBe('Link on slide');
    });
});

// ── rendering ───────────────────────────────────────────────────────────────

describe('ChipRow', () => {
    it('renders a chip with its text and its offer', () => {
        render(<ChipRow chips={[chip()]} onAccept={() => {}} onDismiss={() => {}} />);
        expect(screen.getByTestId('ms-chip')).toBeTruthy();
        expect(screen.getByText('the draft is due by Friday')).toBeTruthy();
        expect(screen.getByText('Add to calendar')).toBeTruthy();
    });

    it('renders nothing at all when there is nothing to offer', () => {
        const { container } = render(
            <ChipRow chips={[]} onAccept={() => {}} onDismiss={() => {}} />,
        );
        expect(container.innerHTML).toBe('');
    });

    it('rendering runs nothing', () => {
        // The batch's whole claim. A chip carries a proposal and the proposal is a
        // description; only the button turns it into a request.
        const onAccept = vi.fn();
        render(<ChipRow chips={[chip()]} onAccept={onAccept} onDismiss={() => {}} />);
        expect(onAccept).not.toHaveBeenCalled();
    });

    it('accepting sends the id, not the chip', () => {
        // Nothing on this page can rewrite what the user thought they were agreeing to.
        const onAccept = vi.fn();
        render(<ChipRow chips={[chip()]} onAccept={onAccept} onDismiss={() => {}} />);
        fireEvent.click(screen.getByTestId('ms-chip-accept-chip_a'));
        expect(onAccept).toHaveBeenCalledWith('chip_a');
        expect(onAccept.mock.calls[0].length).toBe(1);
    });

    it('dismissing calls back with the id', () => {
        const onDismiss = vi.fn();
        render(<ChipRow chips={[chip()]} onAccept={() => {}} onDismiss={onDismiss} />);
        fireEvent.click(screen.getByTestId('ms-chip-dismiss-chip_a'));
        expect(onDismiss).toHaveBeenCalledWith('chip_a');
    });

    it('offers no button when there is nothing to run', () => {
        // There is nothing to *do* about a question except answer it, and the card already
        // has a way to ask.
        render(
            <ChipRow
                chips={[chip({ kind: 'question', text: 'What do you think?', proposal: undefined })]}
                onAccept={() => {}}
                onDismiss={() => {}}
            />,
        );
        expect(screen.queryByTestId('ms-chip-accept-chip_a')).toBeNull();
        expect(screen.getByTestId('ms-chip-dismiss-chip_a')).toBeTruthy();
    });

    it('a pending chip cannot be pressed twice', () => {
        render(<ChipRow chips={[chip({ pending: true })]} onAccept={() => {}} onDismiss={() => {}} />);
        expect(screen.queryByTestId('ms-chip-accept-chip_a')).toBeNull();
        expect(screen.getByText('Working…')).toBeTruthy();
    });

    it('shows what an accepted chip did, and stays on screen', () => {
        // Somebody who pressed a button should see what it did rather than watch the row
        // vanish and have to trust it.
        render(
            <ChipRow
                chips={[chip({ result: { ok: true, tool: 'hp.calendar.create_event' } })]}
                onAccept={() => {}}
                onDismiss={() => {}}
            />,
        );
        expect(screen.getByText(/hp\.calendar\.create_event/)).toBeTruthy();
        expect(screen.queryByTestId('ms-chip-accept-chip_a')).toBeNull();
    });

    it("forwards the server's own reason when it did not run", () => {
        // It knows whether this install has no tools, no matching tool, or one this meeting
        // has not approved, and those need different fixes.
        render(
            <ChipRow
                chips={[chip({
                    result: { ok: false, reason: 'hp.calendar.create_event is not approved for this meeting' },
                })]}
                onAccept={() => {}}
                onDismiss={() => {}}
            />,
        );
        expect(screen.getByText(/is not approved for this meeting/)).toBeTruthy();
    });

    it('the dismiss button says what it dismisses', () => {
        // "×" is a name axe accepts and a screen-reader user cannot use: three chips in a row
        // read as three identical buttons called "times".
        render(<ChipRow chips={[chip()]} onAccept={() => {}} onDismiss={() => {}} />);
        const button = screen.getByTestId('ms-chip-dismiss-chip_a');
        expect(button.getAttribute('aria-label')).toBe('Dismiss: the draft is due by Friday');
    });

    it('announces politely, never assertively', () => {
        // An offer that interrupts a screen reader mid-sentence is the audible version of the
        // mistake this whole batch is arranged around avoiding.
        render(<ChipRow chips={[chip()]} onAccept={() => {}} onDismiss={() => {}} />);
        expect(screen.getByTestId('ms-chips').getAttribute('aria-live')).toBe('polite');
    });

    it('has no axe violations', async () => {
        const { container } = render(
            <ChipRow chips={[chip(), chip({ id: 'b', kind: 'question', proposal: undefined })]}
                onAccept={() => {}} onDismiss={() => {}} />,
        );
        const results = await axe.run(container);
        expect(results.violations.map((v) => v.id)).toEqual([]);
    });
});

// ── on the card ─────────────────────────────────────────────────────────────

describe('MeetingCard with chips', () => {
    it('shows no chips when the surface has not wired them', () => {
        // Which is also what an install with the flag off shows: the server sends none.
        render(<MeetingCard view={{ ...EMPTY_VIEW, chips: [chip()] }} />);
        expect(screen.queryByTestId('ms-chips')).toBeNull();
    });

    it('shows them when it has', () => {
        render(
            <MeetingCard
                view={{ ...EMPTY_VIEW, chips: [chip()] }}
                onAcceptChip={() => {}}
                onDismissChip={() => {}}
            />,
        );
        expect(screen.getByTestId('ms-chips')).toBeTruthy();
    });

    it('leaves the transcript exactly as it was', () => {
        // A chip must not push the words the reader is following down the card.
        const view = {
            ...EMPTY_VIEW,
            segments: [{ id: 's1', t0: 0, speaker: 'them', text: 'hello there' }],
        };
        const { container: without } = render(<MeetingCard view={view} />);
        const before = without.querySelector('[data-testid="ms-transcript"]')!.outerHTML;
        const { container: with_ } = render(
            <MeetingCard view={{ ...view, chips: [chip()] }}
                onAcceptChip={() => {}} onDismissChip={() => {}} />,
        );
        expect(with_.querySelector('[data-testid="ms-transcript"]')!.outerHTML).toBe(before);
    });
});

// ── the hook ────────────────────────────────────────────────────────────────

describe('useMeetingSense chips', () => {
    function harness(recorder: Record<string, unknown> | null = null) {
        const target = new EventTarget();
        let api: ReturnType<typeof useMeetingSense>;
        function Probe() {
            api = useMeetingSense({ target, recorder: recorder as never });
            return null;
        }
        render(<Probe />);
        return { target, get api() { return api!; } };
    }

    function fire(target: EventTarget, name: string, detail: unknown) {
        act(() => {
            target.dispatchEvent(new CustomEvent(name, { detail }));
        });
    }

    it('collects ms:chip', () => {
        const h = harness();
        fire(h.target, 'ms:chip', { id: 'chip_a', kind: 'decision', text: 'going with Postgres' });
        expect(h.api.view.chips.map((c) => c.id)).toEqual(['chip_a']);
    });

    it('ignores a chip frame with no id, and a frame with no detail at all', () => {
        const h = harness();
        fire(h.target, 'ms:chip', { kind: 'decision', text: 'x' });
        fire(h.target, 'ms:chip', null);
        fire(h.target, 'ms:chip_result', null);
        expect(h.api.view.chips).toEqual([]);
    });

    it('accepting sends the id to the recorder and marks it pending', () => {
        const acceptChip = vi.fn(() => true);
        const h = harness({ acceptChip, muteMic: () => {}, start: async () => ({ ok: true }), stop: async () => {} });
        fire(h.target, 'ms:chip', { id: 'chip_a', kind: 'date', text: 'by Friday' });
        act(() => h.api.acceptChip('chip_a'));
        expect(acceptChip).toHaveBeenCalledWith('chip_a');
        expect(h.api.view.chips[0].pending).toBe(true);
    });

    it('an older addon with no acceptChip does not throw', () => {
        // A newer card against an older addon is the ordinary case, not an error.
        const h = harness({ muteMic: () => {}, start: async () => ({ ok: true }), stop: async () => {} });
        fire(h.target, 'ms:chip', { id: 'chip_a', kind: 'date', text: 'by Friday' });
        act(() => h.api.acceptChip('chip_a'));
        expect(h.api.view.chips[0].pending).toBeFalsy();
    });

    it('a recorder that refuses does not mark it pending', () => {
        // `acceptChip` returns false when the meeting is no longer recording, and a chip left
        // saying "Working…" over a meeting that has ended never resolves.
        const h = harness({ acceptChip: () => false, muteMic: () => {}, start: async () => ({ ok: true }), stop: async () => {} });
        fire(h.target, 'ms:chip', { id: 'chip_a', kind: 'date', text: 'by Friday' });
        act(() => h.api.acceptChip('chip_a'));
        expect(h.api.view.chips[0].pending).toBeFalsy();
    });

    it('resolves on ms:chip_result', () => {
        const h = harness({ acceptChip: () => true, muteMic: () => {}, start: async () => ({ ok: true }), stop: async () => {} });
        fire(h.target, 'ms:chip', { id: 'chip_a', kind: 'date', text: 'by Friday' });
        act(() => h.api.acceptChip('chip_a'));
        fire(h.target, 'ms:chip_result', { id: 'chip_a', ok: true, tool: 'hp.cal' });
        expect(h.api.view.chips[0].pending).toBe(false);
        expect(h.api.view.chips[0].result).toMatchObject({ ok: true, tool: 'hp.cal' });
    });

    it('dismissing sends nothing to the recorder', () => {
        // One reader is not interested. That is not a fact about the meeting.
        const acceptChip = vi.fn(() => true);
        const h = harness({ acceptChip, muteMic: () => {}, start: async () => ({ ok: true }), stop: async () => {} });
        fire(h.target, 'ms:chip', { id: 'chip_a', kind: 'date', text: 'by Friday' });
        act(() => h.api.dismissChip('chip_a'));
        expect(acceptChip).not.toHaveBeenCalled();
        expect(h.api.view.chips[0].dismissed).toBe(true);
    });
});

/**
 * The ended meeting (batch MS33, wave W13).
 *
 * Ten waves built capture; this is the first that builds the payoff. The tests are grouped by
 * the claim they defend rather than by component:
 *
 *   1. the parsing, which can be wrong in ways nobody sees
 *   2. the payoff view — summary first, transcript demoted
 *   3. Ask, and citations that are only links when the server vouched for them
 *   4. the `•••` rule: safe now, deliberate later
 *   5. the pill's rest state
 *   6. the split action
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

import {
    answerParts, citations, dayLabel, durationLabel, hasPayoff, items,
    notesBody, segmentAt, stampToMs, summaryOf,
} from '../ui/meetingsense/meetingRecord';
import { MeetingSummary } from '../ui/meetingsense/MeetingSummary';
import { AskField } from '../ui/meetingsense/AskField';
import { MeetingMenu } from '../ui/meetingsense/MeetingMenu';
import { MeetingCard } from '../ui/meetingsense/MeetingCard';
import { RecordingPill } from '../ui/meetingsense/RecordingPill';
import { MeetingAction } from '../ui/meetingsense/MeetingAction';
import { CapturePopover, DEFAULT_CAPTURE } from '../ui/meetingsense/CapturePopover';
import { MeetingSenseContext, type MeetingControls } from '../ui/meetingsense/MeetingSenseProvider';
import { EMPTY_VIEW, type MeetingView } from '../ui/meetingsense/meetingState';

const NOTES = {
    recap: 'The team agreed to move the launch to October 8.',
    decisions: [{ text: 'Launch → October 8', t0: 61_000 }, { text: 'Pricing → Option B' }],
    actions: [{ text: 'send revised pricing', owner: 'Ana', t0: 124_000 }],
    questions: [{ text: 'Who signs off?' }, { text: 'Budget?', resolved: true }],
};

function view(over: Partial<MeetingView> = {}): MeetingView {
    return { ...EMPTY_VIEW, phase: 'live', meetingId: 'm1', ...over };
}

function ok(body: unknown) {
    return { ok: true, json: async () => body } as unknown as Response;
}

beforeEach(() => {
    // jsdom has neither, and the seek path uses both.
    (globalThis as Record<string, unknown>).requestAnimationFrame = (fn: FrameRequestCallback) => {
        fn(0);
        return 0;
    };
    if (!(globalThis as { CSS?: unknown }).CSS) {
        (globalThis as Record<string, unknown>).CSS = { escape: (s: string) => s };
    }
    Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => vi.restoreAllMocks());

// ── 1. the parsing ──────────────────────────────────────────────────────────

describe('reading a stored record', () => {
    it('unwraps all three notes shapes the server can send', () => {
        // The scar in `export.notes_body`: a test built `{"json": …}` by hand, a shape the
        // store never produces, so the Markdown export shipped without notes for a batch.
        // Reading only the shape you happened to test is the bug.
        expect(summaryOf(notesBody({ notes: NOTES }))).toContain('October 8');
        expect(summaryOf(notesBody({ json: JSON.stringify(NOTES) }))).toContain('October 8');
        expect(summaryOf(notesBody(NOTES))).toContain('October 8');
    });

    it('is null rather than empty for something that is not notes', () => {
        expect(notesBody(null)).toBeNull();
        expect(notesBody('a string')).toBeNull();
        expect(notesBody([1, 2])).toBeNull();
        expect(notesBody({ unrelated: 1 })).toBeNull();
    });

    it('prefers the rolling recap over an older summary field', () => {
        // Both can be present on a record written by an older engine; the recap is the one
        // kept current.
        expect(summaryOf({ recap: 'new', summary: 'old' })).toBe('new');
        expect(summaryOf({ summary: 'old' })).toBe('old');
        expect(summaryOf({ recap: '   ', summary: 'old' })).toBe('old');
    });

    it('drops items with no text instead of rendering a blank bullet', () => {
        const rows = items({ decisions: [{ text: 'keep' }, { text: '  ' }, {}, null, 'nope'] }, 'decisions');
        expect(rows.map((r) => r.text)).toEqual(['keep']);
    });

    it('keeps only the optional fields it can trust', () => {
        const [row] = items({ actions: [{ text: 'x', t0: -5, owner: '  ', resolved: 'yes' }] }, 'actions');
        expect(row.t0).toBeUndefined();      // a negative offset is not a moment
        expect(row.owner).toBeUndefined();   // whitespace is not a name
        expect(row.resolved).toBeUndefined(); // only a literal true resolves a question
    });

    it('knows whether there is a payoff worth showing', () => {
        expect(hasPayoff(notesBody({ notes: NOTES }))).toBe(true);
        expect(hasPayoff({ decisions: [], actions: [], recap: '' })).toBe(false);
        // Questions alone are not a payoff: a meeting that only raised questions still needs
        // its transcript, and promoting that over the recording would overstate the notes.
        expect(hasPayoff({ questions: [{ text: 'q' }] })).toBe(false);
    });

    it('labels the duration and the day', () => {
        const start = 1_700_000_000;
        expect(durationLabel({ started_at: start, ended_at: start + 2_520 })).toBe('42 min');
        expect(durationLabel({ started_at: start, ended_at: start + 3_840 })).toBe('1 h 04 min');
        expect(durationLabel({ started_at: start })).toBe('');
        expect(durationLabel({ started_at: start, ended_at: start - 10 })).toBe('');
        // `now` is a parameter because a function that reads the clock cannot be tested
        // across midnight, which is where every date bug in this programme has lived.
        const noon = new Date(2026, 0, 15, 12, 0, 0).getTime();
        expect(dayLabel({ started_at: noon / 1000 }, noon)).toBe('Today');
        expect(dayLabel({ started_at: noon / 1000 - 86_400 }, noon)).toBe('Yesterday');
        expect(dayLabel({ started_at: noon / 1000 - 86_400 * 5 }, noon)).not.toMatch(/Today|Yesterday/);
    });
});

describe('citations', () => {
    it('reads both stamp shapes', () => {
        expect(stampToMs('01:05')).toBe(65_000);
        expect(stampToMs('1:31:42')).toBe(5_502_000);
        expect(Number.isNaN(stampToMs('later'))).toBe(true);
    });

    it('links only what the server vouched for', () => {
        // A model writing "we shipped 12:30 units" has not cited anything, and turning that
        // into a jump link would be the UI inventing a source.
        expect(citations('we shipped 12:30 units', [])).toEqual([]);
        expect(citations('we shipped 12:30 units', ['31:42'])).toEqual([]);
        expect(citations('agreed at 12:30', ['12:30'])).toHaveLength(1);
    });

    it('does not find a stamp inside a longer run of digits', () => {
        // Without the boundaries, `12:34` matches inside `112:34` and the citation jumps to
        // a moment nobody named.
        expect(citations('build 112:34 failed', ['12:34'])).toEqual([]);
        expect(citations('build 12:345 failed', ['12:34'])).toEqual([]);
        expect(citations('build 12:34 failed', ['12:34'])).toHaveLength(1);
    });

    it('does not find a short stamp inside a long one', () => {
        // `31:42` sits inside `1:31:42`. Matching the tail would jump to the wrong hour.
        const found = citations('said at 1:31:42 exactly', ['1:31:42', '31:42']);
        expect(found.map((c) => c.stamp)).toEqual(['1:31:42']);
    });

    it('splits an answer into text and links, losing no characters', () => {
        const text = 'The date was 12:30 and the price 45:10 after that.';
        const parts = answerParts(text, ['12:30', '45:10']);
        expect(parts.filter((p) => p.kind === 'cite')).toHaveLength(2);
        expect(parts.map((p) => p.text).join('')).toBe(text);
    });

    it('lands a citation on the line already in progress', () => {
        // Not the nearest line. A stamp names when something was said, and the next line
        // starts after the sentence the citation is evidence for.
        const segments = [{ id: 'a', t0: 0 }, { id: 'b', t0: 60_000 }, { id: 'c', t0: 120_000 }];
        expect(segmentAt(segments, 90_000)).toBe('b');
        expect(segmentAt(segments, 60_000)).toBe('b');
        expect(segmentAt(segments, 0)).toBe('a');
        expect(segmentAt(segments, -1)).toBeNull();
    });
});

// ── 2. the payoff view ──────────────────────────────────────────────────────

describe('the summary', () => {
    it('leads with the summary, decisions and actions', () => {
        render(<MeetingSummary body={NOTES} />);
        expect(screen.getByTestId('ms-sum-summary').textContent).toContain('October 8');
        expect(screen.getByTestId('ms-sum-decisions-count').textContent).toBe('· 2');
        expect(screen.getByTestId('ms-sum-actions-count').textContent).toBe('· 1');
    });

    it('shows no heading for a section with nothing in it', () => {
        // "Decisions · 0" teaches people the section is unreliable, and they stop reading
        // the ones that do have content.
        render(<MeetingSummary body={{ recap: 'just talk' }} />);
        expect(screen.queryByTestId('ms-sum-decisions')).toBeNull();
        expect(screen.queryByTestId('ms-sum-actions')).toBeNull();
    });

    it('hides questions that were answered later in the meeting', () => {
        render(<MeetingSummary body={NOTES} />);
        const open = screen.getAllByTestId('ms-sum-questions-item');
        expect(open).toHaveLength(1);
        expect(open[0].textContent).toContain('Who signs off?');
    });

    it('says the summary is being written, and later that there is none', () => {
        const { rerender } = render(<MeetingSummary body={null} pending />);
        expect(screen.getByTestId('ms-sum-empty').textContent).toBe('Writing the summary…');
        rerender(<MeetingSummary body={null} />);
        // Not an error and not a spinner. Some meetings genuinely have no notes.
        expect(screen.getByTestId('ms-sum-empty').textContent).toContain('No summary');
    });

    it('makes a stamp a link only when it can be followed', () => {
        const onSeek = vi.fn();
        const { rerender } = render(<MeetingSummary body={NOTES} />);
        expect(screen.getAllByTestId('ms-sum-stamp')[0].tagName).toBe('SPAN');
        rerender(<MeetingSummary body={NOTES} onSeek={onSeek} />);
        const stamp = screen.getAllByTestId('ms-sum-stamp')[0];
        expect(stamp.tagName).toBe('BUTTON');
        fireEvent.click(stamp);
        expect(onSeek).toHaveBeenCalledWith(61_000);
    });
});

describe('the ended card', () => {
    const record = {
        meeting: { id: 'm1', title: 'Q3 Planning', started_at: 1_700_000_000, ended_at: 1_700_002_520 },
        notes: { notes: NOTES },
    };
    const segments = [
        { id: 's1', t0: 0, text: 'first', speaker: 'Ana' },
        { id: 's2', t0: 61_000, text: 'the launch moves', speaker: 'Marco' },
    ];

    it('keeps the live card exactly as it was', () => {
        render(<MeetingCard view={view({ segments })} record={record} />);
        expect(screen.getByTestId('ms-card-title').textContent).toBe('Meeting');
        expect(screen.queryByTestId('ms-summary')).toBeNull();
        expect(screen.queryByTestId('ms-ask')).toBeNull();
        // Live, so the transcript is the thing being read and is not behind a disclosure.
        expect(screen.queryByTestId('ms-transcript-toggle')).toBeNull();
        expect((screen.getByTestId('ms-transcript') as HTMLElement).hidden).toBe(false);
    });

    it('becomes the payoff when the meeting ends', () => {
        render(<MeetingCard view={view({ phase: 'ended', segments })} record={record} />);
        expect(screen.getByTestId('ms-card-title').textContent).toBe('Q3 Planning');
        expect(screen.getByTestId('ms-card-meta').textContent).toContain('42 min');
        expect(screen.getByTestId('ms-summary')).toBeTruthy();
        expect(screen.getByTestId('ms-ask')).toBeTruthy();
        expect(screen.getByTestId('ms-menu')).toBeTruthy();
    });

    it('demotes the transcript to evidence, and names what is behind it', () => {
        render(<MeetingCard view={view({ phase: 'ended', segments })} record={record} />);
        const toggle = screen.getByTestId('ms-transcript-toggle');
        expect(toggle.textContent).toContain('Transcript');
        expect(toggle.textContent).toContain('· 2');
        expect((screen.getByTestId('ms-transcript') as HTMLElement).hidden).toBe(true);
        fireEvent.click(toggle);
        expect((screen.getByTestId('ms-transcript') as HTMLElement).hidden).toBe(false);
    });

    it('opens the transcript at a cited moment', () => {
        render(<MeetingCard view={view({ phase: 'ended', segments })} record={record} />);
        expect((screen.getByTestId('ms-transcript') as HTMLElement).hidden).toBe(true);
        fireEvent.click(screen.getAllByTestId('ms-sum-stamp')[0]);
        // A citation that cannot be followed is decoration.
        expect((screen.getByTestId('ms-transcript') as HTMLElement).hidden).toBe(false);
        const cited = document.querySelector('[data-cited="true"]');
        expect(cited?.getAttribute('data-segment-id')).toBe('s2');
    });

    it('does not reclose a transcript the reader opened', () => {
        // The collapse fires on the transition to ended and never again. Notes arrive a
        // second or two after the meeting stops, so the render that brings the summary is
        // exactly the render that would shut the transcript under somebody reading it.
        const { rerender } = render(
            <MeetingCard view={view({ phase: 'ended', segments })} record={{ meeting: record.meeting }} />,
        );
        fireEvent.click(screen.getByTestId('ms-transcript-toggle'));
        expect((screen.getByTestId('ms-transcript') as HTMLElement).hidden).toBe(false);

        // The notes land: same phase, new record, several more renders.
        rerender(<MeetingCard view={view({ phase: 'ended', segments })} record={record} />);
        rerender(<MeetingCard view={view({ phase: 'ended', segments, elapsedMs: 1 })} record={record} />);
        expect((screen.getByTestId('ms-transcript') as HTMLElement).hidden).toBe(false);
    });

    it('collapses again if a second meeting ends in the same card', () => {
        // The transition is what collapses, so live → ended → live → ended collapses twice.
        // A latch that only ever fired once would leave the second meeting's transcript open
        // over its summary.
        const { rerender } = render(<MeetingCard view={view({ segments })} record={record} />);
        rerender(<MeetingCard view={view({ phase: 'ended', segments })} record={record} />);
        expect((screen.getByTestId('ms-transcript') as HTMLElement).hidden).toBe(true);
        fireEvent.click(screen.getByTestId('ms-transcript-toggle'));

        rerender(<MeetingCard view={view({ segments })} record={record} />);
        rerender(<MeetingCard view={view({ phase: 'ended', segments })} record={record} />);
        expect((screen.getByTestId('ms-transcript') as HTMLElement).hidden).toBe(true);
    });

    it('falls back to a title when nobody named the meeting', () => {
        render(<MeetingCard view={view({ phase: 'ended' })} record={{ meeting: { id: 'm1' } }} />);
        expect(screen.getByTestId('ms-card-title').textContent).toBe('Meeting');
    });
});

// ── 3. Ask ─────────────────────────────────────────────────────────────────

describe('asking the meeting', () => {
    it('answers, and links the stamps the server cited', async () => {
        const onSeek = vi.fn();
        const fetcher = vi.fn(async () => ok({ type: 'answer', text: 'Option B, agreed at 31:42.', cited: ['31:42'] }));
        render(<AskField meetingId="m1" fetcher={fetcher as never} onSeek={onSeek} />);
        fireEvent.change(screen.getByTestId('ms-ask-input'), { target: { value: 'pricing?' } });
        await act(async () => { fireEvent.click(screen.getByTestId('ms-ask-send')); });

        await waitFor(() => expect(screen.getByTestId('ms-ask-answer')).toBeTruthy());
        expect(screen.getByTestId('ms-ask-question').textContent).toBe('pricing?');
        const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
        expect(url).toBe('/v1/meetingsense/m1/ask');
        expect(JSON.parse(String(init.body))).toEqual({ text: 'pricing?' });
        fireEvent.click(screen.getByTestId('ms-ask-cite'));
        expect(onSeek).toHaveBeenCalledWith(1_902_000);
    });

    it('clears the box and shows the question while the answer is in flight', async () => {
        let release: (v: Response) => void = () => {};
        const fetcher = vi.fn(() => new Promise<Response>((r) => { release = r; }));
        render(<AskField meetingId="m1" fetcher={fetcher as never} />);
        fireEvent.change(screen.getByTestId('ms-ask-input'), { target: { value: 'who owns it?' } });
        await act(async () => { fireEvent.click(screen.getByTestId('ms-ask-send')); });
        expect((screen.getByTestId('ms-ask-input') as HTMLInputElement).value).toBe('');
        expect(screen.getByTestId('ms-ask-pending')).toBeTruthy();
        await act(async () => { release(ok({ text: 'Ana.', cited: [] })); });
        await waitFor(() => expect(screen.getByTestId('ms-ask-answer').textContent).toBe('Ana.'));
    });

    it('sends nothing for an empty question', async () => {
        const fetcher = vi.fn(async () => ok({ text: '' }));
        render(<AskField meetingId="m1" fetcher={fetcher as never} />);
        fireEvent.change(screen.getByTestId('ms-ask-input'), { target: { value: '   ' } });
        await act(async () => { fireEvent.submit(screen.getByTestId('ms-ask-input').closest('form')!); });
        expect(fetcher).not.toHaveBeenCalled();
        expect((screen.getByTestId('ms-ask-send') as HTMLButtonElement).disabled).toBe(true);
    });

    it('says so when a question cannot be answered', async () => {
        const fetcher = vi.fn(async () => ({ ok: false, json: async () => ({}) }) as unknown as Response);
        render(<AskField meetingId="m1" fetcher={fetcher as never} />);
        fireEvent.change(screen.getByTestId('ms-ask-input'), { target: { value: 'x' } });
        await act(async () => { fireEvent.click(screen.getByTestId('ms-ask-send')); });
        await waitFor(() => expect(screen.getByTestId('ms-ask-error')).toBeTruthy());
    });

    it('renders nothing without a meeting to ask about', () => {
        const { container } = render(<AskField meetingId={null} />);
        expect(container.innerHTML).toBe('');
    });
});

// ── 4. safe now, deliberate later ──────────────────────────────────────────

describe('the ••• menu', () => {
    const open = () => fireEvent.click(screen.getByTestId('ms-menu-trigger'));

    it('keeps every secondary action behind one control', () => {
        render(<MeetingMenu meetingId="m1" title="Q3" />);
        expect(screen.queryByTestId('ms-menu-sheet')).toBeNull();
        open();
        for (const id of ['rename', 'export', 'thread', 'project', 'delete']) {
            expect(screen.getByTestId(`ms-menu-${id}`)).toBeTruthy();
        }
    });

    it('names the new-thread action for the direction it goes', () => {
        // `POST /{id}/thread` creates a *new* conversation. "Continue conversation" would
        // describe the opposite of what the button does.
        render(<MeetingMenu meetingId="m1" title="Q3" />);
        open();
        expect(screen.getByTestId('ms-menu-thread').textContent).toBe('Discuss in new chat');
    });

    it('creates a thread and navigates to it', async () => {
        const onOpenConversation = vi.fn();
        const fetcher = vi.fn(async () => ok({ conversation_id: 'c9' }));
        render(<MeetingMenu meetingId="m1" title="Q3" fetcher={fetcher as never} onOpenConversation={onOpenConversation} />);
        open();
        await act(async () => { fireEvent.click(screen.getByTestId('ms-menu-thread')); });
        await waitFor(() => expect(onOpenConversation).toHaveBeenCalledWith('c9'));
        expect((fetcher.mock.calls[0] as unknown as [string])[0]).toBe('/v1/meetingsense/m1/thread');
    });

    it('will not attach to a project until one is chosen', async () => {
        // D4: being recorded must never put a meeting into a project. There is no sensible
        // default, so there is no enabled button until somebody picks.
        const fetcher = vi.fn(async () => ok([{ id: 'p1', name: 'Website redesign' }]));
        render(<MeetingMenu meetingId="m1" title="Q3" fetcher={fetcher as never} />);
        open();
        await act(async () => { fireEvent.click(screen.getByTestId('ms-menu-project')); });
        await waitFor(() => expect(screen.getByTestId('ms-dialog-project')).toBeTruthy());
        expect((screen.getByTestId('ms-confirm-attach') as HTMLButtonElement).disabled).toBe(true);

        fireEvent.change(screen.getByTestId('ms-dialog-project-select'), { target: { value: 'p1' } });
        expect((screen.getByTestId('ms-confirm-attach') as HTMLButtonElement).disabled).toBe(false);
        await act(async () => { fireEvent.click(screen.getByTestId('ms-confirm-attach')); });
        const attach = fetcher.mock.calls.find((c) => String(c[0]).endsWith('/attach'));
        expect(JSON.parse(String((attach as unknown as [string, RequestInit])[1].body))).toEqual({ project_id: 'p1' });
    });

    it('never deletes on the first press', async () => {
        const fetcher = vi.fn(async () => ok({ ok: true }));
        const onDeleted = vi.fn();
        render(<MeetingMenu meetingId="m1" title="Q3 Planning" fetcher={fetcher as never} onDeleted={onDeleted} />);
        open();
        fireEvent.click(screen.getByTestId('ms-menu-delete'));
        expect(fetcher).not.toHaveBeenCalled();

        const dialog = screen.getByTestId('ms-dialog-delete');
        expect(dialog.textContent).toContain('Q3 Planning');
        // The confirmation names what goes, because "are you sure?" tells nobody anything.
        expect(screen.getByTestId('ms-dialog-delete-note').textContent).toContain('transcript');
        fireEvent.click(screen.getByTestId('ms-dialog-cancel'));
        expect(fetcher).not.toHaveBeenCalled();
    });

    it('deletes once confirmed', async () => {
        const fetcher = vi.fn(async () => ok({ ok: true }));
        const onDeleted = vi.fn();
        render(<MeetingMenu meetingId="m1" title="Q3" fetcher={fetcher as never} onDeleted={onDeleted} />);
        open();
        fireEvent.click(screen.getByTestId('ms-menu-delete'));
        await act(async () => { fireEvent.click(screen.getByTestId('ms-confirm-delete')); });
        await waitFor(() => expect(onDeleted).toHaveBeenCalled());
        const call = fetcher.mock.calls[0] as unknown as [string, RequestInit];
        expect(call[0]).toBe('/v1/meetingsense/m1');
        expect(call[1].method).toBe('DELETE');
    });

    it('renames without a confirmation, because a rename is a rename away', async () => {
        const fetcher = vi.fn(async () => ok({ ok: true }));
        const onRenamed = vi.fn();
        render(<MeetingMenu meetingId="m1" title="Q3" fetcher={fetcher as never} onRenamed={onRenamed} />);
        open();
        fireEvent.click(screen.getByTestId('ms-menu-rename'));
        fireEvent.change(screen.getByTestId('ms-dialog-title-input'), { target: { value: 'Launch review' } });
        await act(async () => { fireEvent.click(screen.getByTestId('ms-confirm-rename')); });
        await waitFor(() => expect(onRenamed).toHaveBeenCalledWith('Launch review'));
        const call = fetcher.mock.calls[0] as unknown as [string, RequestInit];
        expect(call[1].method).toBe('PATCH');
        expect(JSON.parse(String(call[1].body))).toEqual({ title: 'Launch review' });
    });

    it('will not rename to nothing', () => {
        render(<MeetingMenu meetingId="m1" title="Q3" />);
        open();
        fireEvent.click(screen.getByTestId('ms-menu-rename'));
        fireEvent.change(screen.getByTestId('ms-dialog-title-input'), { target: { value: '   ' } });
        expect((screen.getByTestId('ms-confirm-rename') as HTMLButtonElement).disabled).toBe(true);
    });
});

// ── 5. the pill at rest ────────────────────────────────────────────────────

describe('the recording pill', () => {
    const live = { ...EMPTY_VIEW, phase: 'live' as const, elapsedMs: 763_000, provider: 'whisper', audioMode: 'system+mic' };

    it('rests as state, time and the meter — nothing else', () => {
        render(<RecordingPill view={live} />);
        expect(screen.getByTestId('ms-elapsed').textContent).toBe('12:43');
        expect(screen.getByTestId('ms-meter')).toBeTruthy();
        expect(screen.queryByTestId('ms-capture')).toBeNull();
        expect(screen.queryByTestId('ms-mute')).toBeNull();
        expect(screen.queryByTestId('ms-stop')).toBeNull();
    });

    it('opens the detail on a click, not a hover', () => {
        // Hover does not exist on a phone and is not reachable from a keyboard, so a
        // hover-only disclosure hides the audio setup from the people most likely to have
        // it wrong.
        render(<RecordingPill view={live} />);
        const toggle = screen.getByTestId('ms-pill-toggle');
        expect(toggle.tagName).toBe('BUTTON');
        fireEvent.click(toggle);
        expect(screen.getByTestId('ms-pill-details')).toBeTruthy();
        expect(screen.getByTestId('ms-mute').textContent).toBe('Mute my mic');
        expect(screen.getByTestId('ms-stop')).toBeTruthy();
    });

    it('says capture continues while it counts down', () => {
        // The exact ambiguity Undo exists to remove. A bare "stopping…" invites people to
        // stop talking, which is the one outcome the countdown was built to prevent.
        render(<RecordingPill view={{ ...live, phase: 'stopping' }} undoSecondsLeft={8} />);
        expect(screen.getByTestId('ms-pill').textContent).toContain('Stopping in 8s · still recording');
        expect(screen.getByTestId('ms-undo').textContent).toBe('Undo · 8s');
        // No disclosure to wander into for ten seconds.
        expect(screen.queryByTestId('ms-pill-toggle')).toBeNull();
    });
});

// ── 6. the split action ────────────────────────────────────────────────────

describe('the header control', () => {
    function controls(over: Partial<MeetingControls> = {}): MeetingControls {
        return {
            live: false, starting: false, error: null,
            status: { enabled: true, stt: { available: true, provider: 'whisper' } },
            conversationId: 'c1',
            begin: vi.fn(), end: vi.fn(), phase: 'idle', phaseText: 'not recording',
            elapsedMs: 0, micMuted: false, mute: vi.fn(), undo: vi.fn(), undoSecondsLeft: null,
            capture: DEFAULT_CAPTURE, setCapture: vi.fn(),
            ...over,
        };
    }
    const mount = (over: Partial<MeetingControls> = {}) => {
        const value = controls(over);
        render(
            <MeetingSenseContext.Provider value={value}>
                <MeetingAction />
            </MeetingSenseContext.Provider>,
        );
        return value;
    };

    it('still starts on one click', () => {
        // The chevron is a second control, not a step in front of the first.
        const value = mount();
        fireEvent.click(screen.getByTestId('ms-action-button'));
        expect(value.begin).toHaveBeenCalledTimes(1);
        expect(screen.queryByTestId('ms-action-capture')).toBeNull();
    });

    it('opens capture options from the chevron without starting', () => {
        const value = mount();
        fireEvent.click(screen.getByTestId('ms-action-options'));
        expect(value.begin).not.toHaveBeenCalled();
        expect(screen.getByTestId('ms-capture-popover')).toBeTruthy();
    });

    it('offers no chevron when there is nothing to configure', () => {
        // Live, starting, or blocked: a chevron into capture options for a meeting that is
        // already running configures nothing.
        mount({ live: true, phase: 'live' });
        expect(screen.queryByTestId('ms-action-options')).toBeNull();
    });

    it('closes the options on Escape', () => {
        mount();
        fireEvent.click(screen.getByTestId('ms-action-options'));
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.queryByTestId('ms-capture-popover')).toBeNull();
    });
});

describe('capture options', () => {
    it('starts with everything on and Note taker unlabelled as a mode', () => {
        expect(DEFAULT_CAPTURE).toEqual({ audio: true, mic: true, slides: true, mode: null });
        const onChange = vi.fn();
        render(<CapturePopover value={DEFAULT_CAPTURE} onChange={onChange} onClose={() => {}} />);
        for (const key of ['audio', 'mic', 'slides']) {
            expect((screen.getByTestId(`ms-cap-${key}`) as HTMLInputElement).checked).toBe(true);
        }
        // Note-taker is what MeetingSense *is*, not "mode 1 of 5".
        expect(screen.getByTestId('ms-cap-more-modes').textContent).toContain('Note taker');
        expect(screen.getByTestId('ms-cap-more-modes').textContent).toContain('Default');
    });

    it('keeps the four advanced modes behind a deliberate press', () => {
        const onChange = vi.fn();
        render(<CapturePopover value={DEFAULT_CAPTURE} onChange={onChange} onClose={() => {}} />);
        expect(screen.queryByTestId('ms-cap-mode-presenter')).toBeNull();
        fireEvent.click(screen.getByTestId('ms-cap-more-modes'));
        expect(screen.getByTestId('ms-cap-mode-presenter')).toBeTruthy();
        fireEvent.click(screen.getByTestId('ms-cap-mode-presenter'));
        expect(onChange).toHaveBeenCalledWith({ ...DEFAULT_CAPTURE, mode: 'presenter' });
    });

    it('turns a capture source off without touching the others', () => {
        const onChange = vi.fn();
        render(<CapturePopover value={DEFAULT_CAPTURE} onChange={onChange} onClose={() => {}} />);
        fireEvent.click(screen.getByTestId('ms-cap-slides'));
        expect(onChange).toHaveBeenCalledWith({ audio: true, mic: true, slides: false, mode: null });
    });
});

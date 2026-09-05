/**
 * The meetings catalog (batch MS28, wave W10).
 *
 * Two acceptance criteria, and the first one is a promise about *absence*: flag off, the
 * sidebar is identical. That is asserted as `outerHTML` byte-for-byte rather than by counting
 * nav items, for the reason MS7 gave about the degraded tree — a snapshot of the shape catches
 * a stray wrapper or a changed class that a count sails past, and "identical" is the word the
 * batch used.
 *
 * The second is filters and search, which live in `catalog.ts` as pure functions. The one that
 * matters most is the inverse of the feature: **with the chip off, History's list is History's
 * own**, same rows in the same order. A filter that quietly reorders the list when it is not
 * filtering is a regression wearing a feature's clothes.
 */
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import axe from 'axe-core';

import { MeetingFilter } from '../ui/meetingsense/MeetingFilter';
import { MeetingLibrary } from '../ui/meetingsense/MeetingLibrary';
import { MeetingDetail } from '../ui/meetingsense/MeetingDetail';
import { useMeetingCatalog } from '../ui/meetingsense/useMeetingCatalog';
import {
    dayLabel,
    durationLabel,
    filterConversations,
    catalogEnabled,
    filterMeetings,
    groupByDay,
    isLive,
    meetingConversations,
    meetingCount,
    meetingTitle,
    since,
    sourceLabel,
    sources,
    type Meeting,
} from '../ui/meetingsense/catalog';

const DAY = 86_400;
const NOW = 1_760_000_000;

function meeting(over: Partial<Meeting> = {}): Meeting {
    return {
        id: 'm1',
        conversation_id: 'c1',
        title: 'Q3 planning',
        source: 'zoom',
        started_at: NOW - DAY,
        ended_at: NOW - DAY + 1800,
        state: 'ended',
        segments: 120,
        keyframes: 8,
        ...over,
    };
}

function conv(id: string, last = 'hello there', updated = '2026-09-01T10:00:00Z') {
    return { conversation_id: id, last_content: last, updated_at: updated };
}

// ── the pure decisions ──────────────────────────────────────────────────────

describe('recognising a meeting', () => {
    it('comes from the server, not from a title', () => {
        // D5 notes the meeting message is the last message, which makes title-sniffing look
        // viable. It is not: the label is the *last* message, so it stops being the meeting's
        // the moment anybody replies in the thread — which is the normal case, since MS16
        // exists to make people carry on talking there.
        const ids = meetingConversations([meeting({ conversation_id: 'c1' }),
                                          meeting({ id: 'm2', conversation_id: 'c2' })]);
        expect([...ids].sort()).toEqual(['c1', 'c2']);
        // A conversation whose last message no longer mentions the meeting is still a meeting.
        expect(ids.has('c1')).toBe(true);
    });

    it('ignores meetings with no conversation behind them', () => {
        expect(meetingConversations([meeting({ conversation_id: null })]).size).toBe(0);
        expect(meetingConversations([meeting({ conversation_id: '  ' })]).size).toBe(0);
    });

    it('survives an empty or missing list', () => {
        expect(meetingConversations([]).size).toBe(0);
        expect(meetingConversations(null as never).size).toBe(0);
    });
});

describe('how a meeting is titled', () => {
    it('follows D5: mic, title, source, date', () => {
        expect(meetingTitle(meeting())).toBe('🎙 Q3 planning · Zoom · ' + dayLabel(NOW - DAY));
    });

    it('says untitled rather than dressing a timestamp up as a name', () => {
        expect(meetingTitle(meeting({ title: '' }))).toContain('Untitled meeting');
        expect(meetingTitle(meeting({ title: null }))).toContain('Untitled meeting');
    });

    it('drops the parts it does not have rather than printing blanks', () => {
        expect(meetingTitle({ id: 'm', title: 'Standup' })).toBe('🎙 Standup');
    });

    it('names the sources it knows and passes through the ones it does not', () => {
        expect(sourceLabel('meet')).toBe('Google Meet');
        expect(sourceLabel('teams')).toBe('Microsoft Teams');
        expect(sourceLabel('Bluejeans')).toBe('Bluejeans');
        expect(sourceLabel('')).toBe('Unknown source');
    });
});

describe('duration', () => {
    it('rounds to the minute', () => {
        expect(durationLabel(meeting({ started_at: 0, ended_at: 1800 }))).toBe('30 min');
    });

    it('never says zero minutes', () => {
        // "0 min" looks like a bug in the recorder rather than a short meeting.
        expect(durationLabel(meeting({ started_at: 0, ended_at: 40 }))).toBe('under a minute');
    });

    it('reads hours and minutes', () => {
        expect(durationLabel(meeting({ started_at: 0, ended_at: 3600 }))).toBe('1 h');
        expect(durationLabel(meeting({ started_at: 0, ended_at: 5400 }))).toBe('1 h 30 min');
    });

    it('says nothing for a meeting still running', () => {
        expect(durationLabel(meeting({ ended_at: null }))).toBe('');
        expect(durationLabel(meeting({ started_at: null }))).toBe('');
    });

    it('refuses a time that is not a number rather than subtracting it', () => {
        // A server that sent `"1800"` would subtract cleanly and report a duration for a
        // meeting that has not ended. The times here are chosen so the subtraction comes out
        // *positive* — with the fixture's own timestamps it lands negative and the "never
        // something negative" guard catches it, which would make this test pass for the
        // wrong reason.
        expect(durationLabel({ id: 'm', started_at: 0, ended_at: '1800' as never })).toBe('');
        expect(durationLabel({ id: 'm', started_at: '0' as never, ended_at: 1800 })).toBe('');
    });

    it('says nothing rather than something negative', () => {
        expect(durationLabel(meeting({ started_at: 100, ended_at: 50 }))).toBe('');
    });

    it('knows a live meeting', () => {
        expect(isLive(meeting({ state: 'live' }))).toBe(true);
        expect(isLive(meeting({ state: 'LIVE' }))).toBe(true);
        expect(isLive(meeting())).toBe(false);
    });
});

// ── History's filter ────────────────────────────────────────────────────────

describe('History, filtered', () => {
    const rows = [conv('c1', 'a meeting thread'), conv('c2', 'just a chat'), conv('c3', 'more')];
    const ids = new Set(['c1', 'c3']);

    it('with the chip off, the list is History\'s own', () => {
        // The inverse of the feature, and the one worth guarding: same rows, same order.
        expect(filterConversations(rows)).toEqual(rows);
        expect(filterConversations(rows, { meetingsOnly: false, meetingIds: ids })).toEqual(rows);
    });

    it('with the chip on, only the conversations with a recording', () => {
        expect(filterConversations(rows, { meetingsOnly: true, meetingIds: ids })
            .map((c) => c.conversation_id)).toEqual(['c1', 'c3']);
    });

    it('search still works, and composes with the chip', () => {
        expect(filterConversations(rows, { query: 'chat' }).map((c) => c.conversation_id))
            .toEqual(['c2']);
        expect(filterConversations(rows, { query: 'meeting', meetingsOnly: true, meetingIds: ids })
            .map((c) => c.conversation_id)).toEqual(['c1']);
    });

    it('searches the id as well as the content, exactly as History did', () => {
        expect(filterConversations(rows, { query: 'c2' }).map((c) => c.conversation_id))
            .toEqual(['c2']);
    });

    it('is case- and whitespace-insensitive on the query', () => {
        expect(filterConversations(rows, { query: '  CHAT  ' }).length).toBe(1);
    });

    it('the chip with no ids filters everything out rather than nothing', () => {
        // Fail closed: "meetings only" with nothing known to be a meeting is an empty list,
        // not the whole of History relabelled.
        expect(filterConversations(rows, { meetingsOnly: true })).toEqual([]);
    });

    it('counts the meetings on screen', () => {
        expect(meetingCount(rows, ids)).toBe(2);
        expect(meetingCount(rows, new Set())).toBe(0);
        expect(meetingCount([], ids)).toBe(0);
    });
});

// ── the library's filters ───────────────────────────────────────────────────

describe('the library filters', () => {
    const many = [
        meeting({ id: 'a', title: 'Q3 planning', source: 'zoom', started_at: NOW - DAY }),
        meeting({ id: 'b', title: 'Vendor call', source: 'meet', started_at: NOW - 10 * DAY }),
        meeting({ id: 'c', title: 'Retro', source: 'zoom', started_at: NOW - 40 * DAY }),
    ];

    it('is newest first', () => {
        expect(filterMeetings(many).map((m) => m.id)).toEqual(['a', 'b', 'c']);
    });

    it('sorts even when the input is not sorted', () => {
        const shuffled = [many[2], many[0], many[1]];
        expect(filterMeetings(shuffled).map((m) => m.id)).toEqual(['a', 'b', 'c']);
    });

    it('searches the title', () => {
        expect(filterMeetings(many, { query: 'vendor' }).map((m) => m.id)).toEqual(['b']);
    });

    it('searches the source, by its label as well as its key', () => {
        // Somebody looking for a meeting types "Google Meet", not "meet".
        expect(filterMeetings(many, { query: 'google meet' }).map((m) => m.id)).toEqual(['b']);
        expect(filterMeetings(many, { query: 'zoom' }).map((m) => m.id)).toEqual(['a', 'c']);
    });

    it('searches the attendees', () => {
        const withPeople = [meeting({ id: 'x', title: 'Sync', attendees: 'ana@example.com' })];
        expect(filterMeetings(withPeople, { query: 'ana' }).map((m) => m.id)).toEqual(['x']);
    });

    it('filters by source', () => {
        expect(filterMeetings(many, { source: 'zoom' }).map((m) => m.id)).toEqual(['a', 'c']);
        expect(filterMeetings(many, { source: '' }).length).toBe(3);
    });

    it('includes a meeting sitting exactly on the boundary', () => {
        // "The last 7 days" contains the moment 7 days ago.
        const boundary = since(7, NOW)!;
        expect(filterMeetings([meeting({ id: 'edge', started_at: boundary })],
                              { since: boundary }).map((m) => m.id)).toEqual(['edge']);
        expect(filterMeetings([meeting({ id: 'edge', started_at: boundary - 1 })],
                              { since: boundary })).toEqual([]);
    });

    it('filters by date range', () => {
        expect(filterMeetings(many, { since: since(7, NOW) }).map((m) => m.id)).toEqual(['a']);
        expect(filterMeetings(many, { since: since(30, NOW) }).map((m) => m.id)).toEqual(['a', 'b']);
        expect(filterMeetings(many, { since: since(null, NOW) }).length).toBe(3);
    });

    it('a meeting with no start time is out of every range but in all-time', () => {
        const undated = [...many, meeting({ id: 'z', started_at: null })];
        expect(filterMeetings(undated, { since: since(30, NOW) }).map((m) => m.id))
            .toEqual(['a', 'b']);
        expect(filterMeetings(undated).map((m) => m.id)).toContain('z');
    });

    it('composes source, range and query', () => {
        expect(filterMeetings(many, { source: 'zoom', since: since(7, NOW), query: 'q3' })
            .map((m) => m.id)).toEqual(['a']);
    });

    it('does not mutate what it was given', () => {
        // Sorting happens in place on the array `filter` returned, so what protects the
        // caller is that copy — which is worth pinning, because the sort is right there.
        const input = [many[2], many[0]];
        const before = input.map((m) => m.id);
        filterMeetings(input);
        expect(input.map((m) => m.id)).toEqual(before);
    });

    it('lists the sources present, alphabetically', () => {
        // Alphabetical so the chips do not move about between renders.
        expect(sources(many)).toEqual(['meet', 'zoom']);
        expect(sources([meeting({ source: '' })])).toEqual([]);
    });

    it('groups by day, newest first', () => {
        const grouped = groupByDay(many);
        expect(grouped.length).toBe(3);
        expect(grouped[0].meetings[0].id).toBe('a');
    });
});

// ── the chip ────────────────────────────────────────────────────────────────

describe('MeetingFilter', () => {
    it('shows the count', () => {
        render(<MeetingFilter count={4} active={false} onToggle={() => {}} />);
        expect(screen.getByTestId('ms-history-count').textContent).toBe('4');
    });

    it('renders nothing at all when there are no meetings', () => {
        // An account that has never recorded one sees the History it has always seen, down to
        // the DOM — and a chip reading "Meetings · 0" teaches the user the feature is broken.
        const { container } = render(<MeetingFilter count={0} active={false} onToggle={() => {}} />);
        expect(container.innerHTML).toBe('');
    });

    it('toggles, and says what it is', () => {
        const onToggle = vi.fn();
        render(<MeetingFilter count={2} active={false} onToggle={onToggle} />);
        const chip = screen.getByTestId('ms-history-chip');
        expect(chip.getAttribute('aria-pressed')).toBe('false');
        fireEvent.click(chip);
        expect(onToggle).toHaveBeenCalledWith(true);
    });

    it('offers a way back out when it is on', () => {
        const onToggle = vi.fn();
        render(<MeetingFilter count={2} active onToggle={onToggle} />);
        expect(screen.getByTestId('ms-history-chip').getAttribute('aria-pressed')).toBe('true');
        fireEvent.click(screen.getByTestId('ms-history-clear'));
        expect(onToggle).toHaveBeenCalledWith(false);
    });

    it('the chip itself toggles both ways', () => {
        // A chip that only ever turns on is a filter the user cannot leave except by finding
        // the secondary link — which is the one control here that is easy to miss.
        const onToggle = vi.fn();
        render(<MeetingFilter count={2} active onToggle={onToggle} />);
        fireEvent.click(screen.getByTestId('ms-history-chip'));
        expect(onToggle).toHaveBeenCalledWith(false);
    });

    it('has no axe violations', async () => {
        const { container } = render(<MeetingFilter count={2} active onToggle={() => {}} />);
        expect((await axe.run(container)).violations.map((v) => v.id)).toEqual([]);
    });
});

// ── the library ─────────────────────────────────────────────────────────────

describe('MeetingLibrary', () => {
    const many = [
        meeting({ id: 'a', title: 'Q3 planning', source: 'zoom', started_at: NOW - DAY }),
        meeting({ id: 'b', title: 'Vendor call', source: 'meet', started_at: NOW - 10 * DAY }),
    ];

    it('renders a card per meeting', () => {
        render(<MeetingLibrary meetings={many} now={NOW} />);
        expect(screen.getByTestId('ms-library-grid').children.length).toBe(2);
    });

    it('searches', () => {
        render(<MeetingLibrary meetings={many} now={NOW} />);
        fireEvent.change(screen.getByTestId('ms-library-search'), { target: { value: 'vendor' } });
        expect(screen.getByTestId('ms-library-grid').children.length).toBe(1);
        expect(screen.getByText('Vendor call')).toBeTruthy();
    });

    it('filters by range', () => {
        render(<MeetingLibrary meetings={many} now={NOW} />);
        fireEvent.click(screen.getByTestId('ms-library-range-7'));
        expect(screen.getByTestId('ms-library-grid').children.length).toBe(1);
    });

    it('filters by source', () => {
        render(<MeetingLibrary meetings={many} now={NOW} />);
        fireEvent.click(screen.getByTestId('ms-library-source-meet'));
        expect(screen.getByTestId('ms-library-grid').children.length).toBe(1);
    });

    it('offers no source facet when there is only one source', () => {
        // A filter with a single option is a control that cannot change anything.
        render(<MeetingLibrary meetings={[many[0]]} now={NOW} />);
        expect(screen.queryByTestId('ms-library-sources')).toBeNull();
    });

    it('tells an empty library apart from an over-filtered one', () => {
        const { unmount } = render(<MeetingLibrary meetings={[]} now={NOW} />);
        expect(screen.getByTestId('ms-library-empty').textContent).toMatch(/No meetings recorded/);
        unmount();
        render(<MeetingLibrary meetings={many} now={NOW} />);
        fireEvent.change(screen.getByTestId('ms-library-search'), { target: { value: 'zzz' } });
        expect(screen.getByTestId('ms-library-empty').textContent).toMatch(/match those filters/);
    });

    it('marks a meeting that is still recording', () => {
        render(<MeetingLibrary meetings={[meeting({ id: 'a', state: 'live' })]} now={NOW} />);
        expect(screen.getByTestId('ms-library-live-a')).toBeTruthy();
    });

    it('opens a meeting', () => {
        const onOpen = vi.fn();
        render(<MeetingLibrary meetings={many} now={NOW} onOpen={onOpen} />);
        fireEvent.click(screen.getByTestId('ms-library-card-a'));
        expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: 'a' }));
    });

    it('has no axe violations', async () => {
        const { container } = render(<MeetingLibrary meetings={many} now={NOW} />);
        expect((await axe.run(container)).violations.map((v) => v.id)).toEqual([]);
    });
});

// ── the detail rail ─────────────────────────────────────────────────────────

describe('MeetingDetail', () => {
    it('renders nothing without a meeting', () => {
        const { container } = render(<MeetingDetail meeting={null} />);
        expect(container.innerHTML).toBe('');
    });

    it('opens on notes and switches tabs', () => {
        render(
            <MeetingDetail
                meeting={meeting()}
                notes={{ recap: 'we agreed on pricing', decisions: [{ text: 'ship in October' }] }}
                slides={[{ id: 's1', caption: 'Q3 revenue' }]}
                segments={[{ id: 'g1', speaker: 'me', text: 'hello' }]}
            />,
        );
        expect(screen.getByTestId('ms-detail-recap').textContent).toBe('we agreed on pricing');
        fireEvent.click(screen.getByTestId('ms-detail-tab-slides'));
        expect(screen.getByTestId('ms-detail-slides').textContent).toContain('Q3 revenue');
        fireEvent.click(screen.getByTestId('ms-detail-tab-transcript'));
        expect(screen.getByTestId('ms-detail-transcript').textContent).toContain('hello');
    });

    it('says so when a tab has nothing in it', () => {
        render(<MeetingDetail meeting={meeting()} />);
        expect(screen.getByText(/No notes were taken/)).toBeTruthy();
        fireEvent.click(screen.getByTestId('ms-detail-tab-slides'));
        expect(screen.getByText(/No slides were captured/)).toBeTruthy();
    });

    it('leads back to the conversation', () => {
        // D5: the catalog is a way in, not a second home.
        const onOpen = vi.fn();
        render(<MeetingDetail meeting={meeting()} onOpenConversation={onOpen} />);
        fireEvent.click(screen.getByTestId('ms-detail-open'));
        expect(onOpen).toHaveBeenCalledWith('c1');
    });

    it('offers no way back when there is no conversation', () => {
        render(<MeetingDetail meeting={meeting({ conversation_id: null })}
                              onOpenConversation={() => {}} />);
        expect(screen.queryByTestId('ms-detail-open')).toBeNull();
    });

    it('says a live meeting is recording rather than showing a duration', () => {
        render(<MeetingDetail meeting={meeting({ state: 'live', ended_at: null })} />);
        expect(screen.getByTestId('ms-detail-meta').textContent).toContain('Recording now');
    });

    it('has no axe violations', async () => {
        const { container } = render(
            <MeetingDetail meeting={meeting()} notes={{ recap: 'r' }} onOpenConversation={() => {}} />,
        );
        expect((await axe.run(container)).violations.map((v) => v.id)).toEqual([]);
    });
});

// ── flag off → sidebar identical ────────────────────────────────────────────

describe('the _CATALOG flag', () => {
    it('needs both flags, because `enabled` does not imply the sub-flag', () => {
        // MS0 made the sub-flags independent of the master on purpose. An install with
        // MEETINGSENSE_CATALOG set and MeetingSense itself off would otherwise grow a nav item
        // leading to a view of a feature that cannot run.
        expect(catalogEnabled({ enabled: true, flags: { catalog: true } })).toBe(true);
        expect(catalogEnabled({ enabled: true, flags: { catalog: false } })).toBe(false);
        expect(catalogEnabled({ enabled: false, flags: { catalog: true } })).toBe(false);
    });

    it('everything unknown is off', () => {
        // None of these is a reason to change somebody's sidebar.
        expect(catalogEnabled(null)).toBe(false);
        expect(catalogEnabled(undefined)).toBe(false);
        expect(catalogEnabled({})).toBe(false);
        expect(catalogEnabled({ enabled: true })).toBe(false);
        expect(catalogEnabled('yes' as never)).toBe(false);
    });

    it('the sidebar is identical with the flag off', () => {
        // The batch's word was "identical", so this compares the rendered shape rather than
        // counting nav items: a stray wrapper or a changed class sails past a count.
        function Nav({ showMeetingsNav }: { showMeetingsNav: boolean }) {
            // The same structure App.tsx renders: a flat list of nav buttons with the Meetings
            // item behind the flag, and nothing else conditional.
            return (
                <div className="flex flex-col gap-px">
                    <button type="button">Chat</button>
                    <button type="button">Voice</button>
                    <button type="button">Teams</button>
                    {showMeetingsNav ? <button type="button">Meetings</button> : null}
                </div>
            );
        }
        const off = render(<Nav showMeetingsNav={false} />);
        const shapeOff = off.container.firstElementChild!.outerHTML;
        off.unmount();

        const baseline = render(
            <div className="flex flex-col gap-px">
                <button type="button">Chat</button>
                <button type="button">Voice</button>
                <button type="button">Teams</button>
            </div>,
        );
        expect(shapeOff).toBe(baseline.container.firstElementChild!.outerHTML);
        baseline.unmount();

        const on = render(<Nav showMeetingsNav />);
        expect(on.container.textContent).toContain('Meetings');
    });

    it('App.tsx renders the nav item only inside that guard', async () => {
        // The check the fixture above cannot make: that the real file is wired the way the
        // fixture models it. A guard that was written and then not used would leave every one
        // of these tests green and every sidebar changed.
        const fs = await import('node:fs/promises');
        const path = await import('node:path');
        // `import.meta.url` is an http URL under the vitest transform, so the path is resolved
        // from the project root instead.
        const source = await fs.readFile(path.resolve('src/ui/App.tsx'), 'utf8');
        const at = source.indexOf('label="Meetings"');
        expect(at).toBeGreaterThan(-1);
        // The nearest preceding conditional is the flag.
        const before = source.slice(Math.max(0, at - 400), at);
        expect(before).toContain('showMeetingsNav ?');
        // And the flag comes from the one place that decides it.
        expect(source).toContain('msCatalogEnabled(body)');
    });
});

// ── the shared fetch ────────────────────────────────────────────────────────

describe('useMeetingCatalog', () => {
    function harness(fetcher: typeof fetch, enabled = true) {
        let api: ReturnType<typeof useMeetingCatalog>;
        function Probe() {
            api = useMeetingCatalog({ fetcher, enabled });
            return null;
        }
        render(<Probe />);
        return { get api() { return api!; } };
    }

    const ok = (body: unknown) => ({ ok: true, json: async () => body }) as unknown as Response;

    it('loads the meetings when the feature is on', async () => {
        const fetcher = vi.fn(async (url: string) =>
            String(url).includes('status')
                ? ok({ enabled: true, flags: { catalog: false } })
                : ok({ meetings: [meeting()] }));
        const h = harness(fetcher as never);
        await waitFor(() => expect(h.api.meetings.length).toBe(1));
        expect(h.api.meetingIds.has('c1')).toBe(true);
    });

    it('asks nothing more when the feature is off', async () => {
        // The status route is always mounted and always answers, so this is a fact rather than
        // a guess from a failed request.
        const fetcher = vi.fn(async () => ok({ enabled: false }));
        const h = harness(fetcher as never);
        await waitFor(() => expect(h.api.loaded).toBe(true));
        expect(h.api.meetings).toEqual([]);
        expect(fetcher).toHaveBeenCalledTimes(1);
    });

    it('a failure is silence, not a banner', async () => {
        // A History panel that shows an error because an optional feature's endpoint was slow
        // has made the user's problem worse.
        const fetcher = vi.fn(async () => { throw new Error('offline'); });
        const h = harness(fetcher as never);
        await waitFor(() => expect(h.api.loaded).toBe(true));
        expect(h.api.meetings).toEqual([]);
    });

    it('does not fetch while the panel is closed', async () => {
        const fetcher = vi.fn(async () => ok({ enabled: true }));
        harness(fetcher as never, false);
        await act(async () => {});
        expect(fetcher).not.toHaveBeenCalled();
    });

    it('survives a body that is not the shape it expects', async () => {
        const fetcher = vi.fn(async (url: string) =>
            String(url).includes('status') ? ok({ enabled: true }) : ok({ meetings: 'nope' }));
        const h = harness(fetcher as never);
        await waitFor(() => expect(h.api.loaded).toBe(true));
        expect(h.api.meetings).toEqual([]);
    });
});

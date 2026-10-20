/**
 * The recap never says "No summary" while the summary is being written.
 *
 * A local model can take minutes over a whole transcript. The recap used to look four times in
 * six seconds, give up, and print "No summary for this meeting" — the reader concluded there
 * would be none. The meeting read now carries `summary_writing`, and the recap keeps looking
 * (more slowly) for as long as the server says so.
 */
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, renderHook, screen, waitFor } from '@testing-library/react';
import { useMeetingRecord } from '../ui/meetingsense/useMeetingRecord';
import { MeetingMinutes } from '../ui/meetingsense/MeetingMinutes';

afterEach(() => cleanup());

function respond(body: unknown) {
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } }));
}

describe('the meeting record while its summary is written', () => {
    it('keeps looking until the document lands', async () => {
        const writing = { meeting: { id: 'm1' }, segments: [{ text: 'hello' }], notes: null, summaries: [], summary_writing: true };
        const done = { ...writing, summary_writing: false, summaries: [{ id: 1, style: 'minutes', text: '# Minutes' }] };
        const answers = [writing, writing, writing, writing, writing, writing, done];
        const fetcher = vi.fn(() => respond(answers.shift() ?? done));

        const { result } = renderHook(() => useMeetingRecord({ meetingId: 'm1', fetcher: fetcher as unknown as typeof fetch, delayMs: 1 }));

        await waitFor(() => expect(result.current.record?.summaries?.length).toBe(1), { timeout: 2000 });
        // Past the four quick retries a record without notes used to get: it kept going.
        expect(fetcher.mock.calls.length).toBeGreaterThanOrEqual(7);
        expect(result.current.record?.summary_writing).toBe(false);
    });
});

describe('the minutes panel', () => {
    it('says the summary is being written, not that there is none', () => {
        render(<MeetingMinutes meetingId="m1" documents={[]} hasTranscript writing />);
        expect(screen.getByTestId('ms-minutes-writing').textContent).toMatch(/Writing the summary/);
        expect(screen.queryByTestId('ms-minutes-empty')).toBeNull();
    });

    it('still offers to write one when nothing is on its way', async () => {
        await act(async () => {
            render(<MeetingMinutes meetingId="m1" documents={[]} hasTranscript />);
        });
        expect(screen.getByTestId('ms-minutes-empty')).toBeTruthy();
    });
});

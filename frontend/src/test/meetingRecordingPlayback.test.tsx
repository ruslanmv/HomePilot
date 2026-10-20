/**
 * Keeping and playing back a live meeting's recording — the UI half.
 *
 * "Record a call" used to keep the transcript only. Now the audio is kept by default
 * (Settings → Meetings → Keep the audio recording), and the consent copy, the quick-record
 * dialog and the switch all say what will actually happen — including when the operator's
 * MEETINGSENSE_RETENTION decides for everyone. After the call the Meeting details page says the
 * recording is saving, then plays it, with every transcript time lined up with the recording
 * through the offset the server stored. Everything is mocked — no network, no audio.
 */
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MeetingsSettings } from '../ui/meetingsense/MeetingsSettings';
import { MeetingDetailPage } from '../ui/meetingsense/library/MeetingDetailPage';
import { effectiveRetention, readMeetingPrefs, MEETING_PREFS_KEY } from '../ui/meetingsense/meetingPrefs';
import { consentSentences } from '../ui/meetingsense/meetingState';
import { withUserRetention } from '../ui/meetingsense/ConsentSheet';

const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });

function stubFetch(routes: Array<[RegExp, () => unknown]>) {
    vi.stubGlobal('fetch', vi.fn(async (input: unknown) => {
        const url = String(input);
        for (const [pattern, reply] of routes) if (pattern.test(url)) return json(reply());
        return json({ detail: 'not found' }, 404);
    }));
}

beforeEach(() => {
    localStorage.clear();
});
afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

describe('who decides what is kept', () => {
    it('keeps the audio by default, and the user can turn it off', () => {
        expect(readMeetingPrefs().keepAudio).toBe(true);
        expect(effectiveRetention({ retention: 'all', retention_policy: null }, true)).toBe('all');
        expect(effectiveRetention({ retention: 'all', retention_policy: null }, false)).toBe('text');
    });

    it('the operator policy wins, and an older server is taken at its word', () => {
        expect(effectiveRetention({ retention: 'text', retention_policy: 'text' }, true)).toBe('text');
        expect(effectiveRetention({ retention: 'all', retention_policy: 'all' }, false)).toBe('all');
        // No `retention_policy` at all: a server from before recordings, which never kept audio.
        expect(effectiveRetention({ retention: 'text' }, true)).toBe('text');
    });

    it('the consent copy follows the user\'s choice', () => {
        const status = { stt: { provider: 'whisper-local' }, retention: 'all', retention_policy: null };
        expect(consentSentences(withUserRetention(status))[1]).toMatch(/audio .*kept until you delete the meeting/);
        localStorage.setItem(MEETING_PREFS_KEY, JSON.stringify({ keepAudio: false }));
        expect(consentSentences(withUserRetention(status))[1]).toMatch(/Only the transcript is kept/);
        expect(consentSentences(withUserRetention(status))[1]).toMatch(/audio is not stored/);
    });
});

describe('Settings → Meetings → Keep the audio recording', () => {
    it('is on by default and switching it off is saved', async () => {
        stubFetch([[/\/v1\/meetingsense\/status$/, () => ({ retention: 'all', retention_policy: null })]]);
        render(<MeetingsSettings />);
        const toggle = screen.getByRole('switch', { name: 'Keep the audio recording' });
        expect(toggle.getAttribute('aria-checked')).toBe('true');
        expect(screen.getByText(/play a meeting back and download it from Meetings/)).toBeTruthy();
        fireEvent.click(toggle);
        expect(toggle.getAttribute('aria-checked')).toBe('false');
        expect(JSON.parse(localStorage.getItem(MEETING_PREFS_KEY) || '{}').keepAudio).toBe(false);
    });

    it('shows the operator\'s policy, locked, when there is one', async () => {
        stubFetch([[/\/v1\/meetingsense\/status$/, () => ({ retention: 'text', retention_policy: 'text' })]]);
        render(<MeetingsSettings />);
        await screen.findByText(/MEETINGSENSE_RETENTION=text/);
        const toggle = screen.getByRole('switch', { name: 'Keep the audio recording' }) as HTMLButtonElement;
        expect(toggle.disabled).toBe(true);
        expect(toggle.getAttribute('aria-checked')).toBe('false');
    });
});

describe('playing a recorded meeting back', () => {
    const ITEM = {
        library_id: 'm1', meeting_id: 'm1', origin_type: 'meetingsense', origin_id: 'm1', title: 'Launch review',
        description: '', category: 'Recorded', started_at: 1_792_510_980, ended_at: 1_792_511_100, scheduled_for: null,
        duration_ms: 120_000, projects: [], source: { kind: 'meetingsense', label: 'HomePilot' }, media_present: true,
        recording_state: 'present', transcript_state: 'ready', summary_state: 'none', segments: 1,
        conversation_id: 'c', status: 'ended', live: false, warnings: [],
    };
    const SEGMENTS = [{ id: 's1', t0_ms: 5_000, t1_ms: 8_000, speaker: 'me', text: 'We ship on Monday.' }];
    const ASSET = {
        id: 'a1', kind: 'audio', role: 'primary', original_name: 'Launch review.webm', relative_path: 'recording.webm',
        sha256: 'x', mime: 'audio/webm', size_bytes: 1000, media_duration_ms: 118_000, source_id: 'meetingsense-live',
        origin_type: 'meetingsense', created_at: 0, metadata: { recorded: 'live', offset_ms: 2_000 }, source_available: true,
    };

    it('says the recording is saving, then plays it', async () => {
        let saving = true;
        stubFetch([
            [/\/library\/item\/m1$/, () => saving
                ? { item: { ...ITEM, recording_state: 'saving', media_present: false }, segments: SEGMENTS, assets: [] }
                : { item: ITEM, segments: SEGMENTS, assets: [ASSET] }],
            [/\/peaks$/, () => ({ peaks: [] })],
        ]);
        vi.useFakeTimers({ shouldAdvanceTime: true });
        try {
            render(<MeetingDetailPage libraryId="m1" onBack={() => undefined} />);
            expect(await screen.findByTestId('recording-saving')).toBeTruthy();
            saving = false;
            await vi.advanceTimersByTimeAsync(4_100); // the page looks again while it saves
            await waitFor(() => expect(document.querySelector('audio')).not.toBeNull());
            expect(screen.queryByTestId('recording-saving')).toBeNull();
        } finally {
            vi.useRealTimers();
        }
    });

    it('lines each transcript time up with the recording', async () => {
        stubFetch([
            [/\/library\/item\/m1$/, () => ({ item: ITEM, segments: SEGMENTS, assets: [ASSET] })],
            [/\/peaks$/, () => ({ peaks: [] })],
        ]);
        vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(() => Promise.resolve());
        render(<MeetingDetailPage libraryId="m1" onBack={() => undefined} />);
        const [stamp] = await screen.findAllByRole('button', { name: 'Play from 0:05' });
        fireEvent.click(stamp);
        // Said at 0:05 on the meeting's clock; the recording started 2 s into it.
        expect((document.querySelector('audio') as HTMLAudioElement).currentTime).toBe(3);
    });

    it('is a compact row until opened, and plays without opening', async () => {
        stubFetch([
            [/\/library\/item\/m1$/, () => ({ item: ITEM, segments: SEGMENTS, assets: [ASSET] })],
            [/\/peaks$/, () => ({ peaks: [0.2, 0.9, 0.4] })],
        ]);
        const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(() => Promise.resolve());
        render(<MeetingDetailPage libraryId="m1" onBack={() => undefined} />);
        const toggle = await screen.findByTestId('recording-toggle');
        expect(toggle.getAttribute('aria-expanded')).toBe('false');
        expect(screen.queryByRole('slider', { name: 'Position in the recording' })).toBeNull();
        expect(screen.getByText('Meeting recording')).toBeTruthy();

        fireEvent.click(screen.getByRole('button', { name: 'Play' }));
        expect(play).toHaveBeenCalled();

        fireEvent.click(toggle);
        expect(toggle.getAttribute('aria-expanded')).toBe('true');
        expect(screen.getByRole('slider', { name: 'Position in the recording' })).toBeTruthy();
        expect(screen.getByRole('combobox', { name: 'Playback speed' })).toBeTruthy();
        expect(document.querySelector('[data-testid="recording-controls"] a[href*="/media/a1?"][href*="download=1"]')).not.toBeNull();
        expect(localStorage.getItem('hp_meeting_player_open')).toBe('1');   // remembered
    });

    it('the More menu no longer repeats the recording as an Audio tab', async () => {
        stubFetch([
            [/\/library\/item\/m1$/, () => ({ item: ITEM, segments: SEGMENTS, assets: [ASSET] })],
            [/\/peaks$/, () => ({ peaks: [] })],
        ]);
        render(<MeetingDetailPage libraryId="m1" onBack={() => undefined} />);
        await screen.findByTestId('recording-toggle');
        fireEvent.click(screen.getByRole('button', { name: /^More$/ }));
        const items = screen.getAllByRole('menuitem').map((el) => el.textContent);
        expect(items).toEqual(['Summary', 'AI Chat', 'Properties']);
    });
});

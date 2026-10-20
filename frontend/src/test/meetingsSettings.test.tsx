/**
 * Settings → Meetings: four groups of choices, applied immediately and saved on this computer.
 *
 * The microphone is deliberately the *shared* media preference (the one Audio & Video edits),
 * and the default sources are the Quick record switches — so this tab can never disagree with
 * the places that already hold those choices.
 */
import React from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MeetingsSettings } from '../ui/meetingsense/MeetingsSettings';
import {
    MEETING_PREFS_DEFAULTS,
    MEETING_PREFS_KEY,
    readMeetingPrefs,
    writeMeetingPrefs,
} from '../ui/meetingsense/meetingPrefs';
import { QUICK_RECORD_KEY, readQuickPrefs } from '../ui/meetingsense/library/quickRecord';
import { MEDIA_PREFERENCES_STORAGE_KEY, getMediaPreferences } from '../ui/media/mediaPreferences';
import { formatWhen, statusChip } from '../ui/meetingsense/library/format';

beforeEach(() => {
    window.localStorage.clear();
});

afterEach(() => {
    cleanup();
    window.localStorage.clear();
});

describe('meeting preferences', () => {
    it('defaults to automatic language, live notes on and minutes', () => {
        expect(readMeetingPrefs()).toEqual(MEETING_PREFS_DEFAULTS);
    });

    it('keeps only values the recorder and the server understand', () => {
        window.localStorage.setItem(MEETING_PREFS_KEY, JSON.stringify({
            language: 'english please', liveNotes: 'yes', summaryStyle: 'poem', summaryLength: 'detailed',
        }));
        const prefs = readMeetingPrefs();
        expect(prefs.language).toBe('auto');
        expect(prefs.liveNotes).toBe(true);
        expect(prefs.summaryStyle).toBe('minutes');
        expect(prefs.summaryLength).toBe('detailed');
    });

    it('announces a change so an open meeting provider picks it up', () => {
        const seen: unknown[] = [];
        const onChange = (e: Event) => seen.push((e as CustomEvent).detail);
        window.addEventListener('homepilot:meeting-prefs-changed', onChange);
        writeMeetingPrefs({ language: 'it' });
        window.removeEventListener('homepilot:meeting-prefs-changed', onChange);
        expect(seen).toEqual([expect.objectContaining({ language: 'it' })]);
        expect(JSON.parse(window.localStorage.getItem(MEETING_PREFS_KEY) || '{}').language).toBe('it');
    });
});

describe('Settings → Meetings', () => {
    it('edits the Quick record defaults', () => {
        render(<MeetingsSettings />);
        fireEvent.click(screen.getByRole('switch', { name: 'Screen' }));
        fireEvent.click(screen.getByRole('switch', { name: 'Call audio' }));
        expect(readQuickPrefs()).toEqual({ audio: false, mic: true, screen: true });
        expect(window.localStorage.getItem(QUICK_RECORD_KEY)).not.toBeNull();
    });

    it('edits the shared microphone clean-up, not a copy of it', () => {
        render(<MeetingsSettings />);
        fireEvent.click(screen.getByRole('switch', { name: 'Noise suppression' }));
        expect(getMediaPreferences().noiseSuppression).toBe(false);
        expect(window.localStorage.getItem(MEDIA_PREFERENCES_STORAGE_KEY)).toContain('"noiseSuppression":false');
    });

    it('sets the spoken language and explains what it does', () => {
        render(<MeetingsSettings />);
        fireEvent.change(screen.getByLabelText('Spoken language'), { target: { value: 'es' } });
        expect(readMeetingPrefs().language).toBe('es');
        expect(screen.getByText('Every sentence is transcribed in this language.')).toBeTruthy();
    });

    it('turns live notes off for a slow computer and sets the summary defaults', () => {
        render(<MeetingsSettings />);
        fireEvent.click(screen.getByRole('switch', { name: 'Live notes during the meeting' }));
        fireEvent.change(screen.getByLabelText('Summary style'), { target: { value: 'email' } });
        fireEvent.change(screen.getByLabelText('Summary language'), { target: { value: 'Italian' } });
        const prefs = readMeetingPrefs();
        expect(prefs.liveNotes).toBe(false);
        expect(prefs.summaryStyle).toBe('email');
        expect(prefs.summaryLanguage).toBe('Italian');
    });

    it('recommends headphones', () => {
        render(<MeetingsSettings />);
        expect(screen.getByText(/Headphones give the cleanest transcript/)).toBeTruthy();
    });
});

describe('the library card', () => {
    it('shows the hour a meeting started, not just the day', () => {
        // Noon UTC, and the suite runs in UTC (vitest.config.ts).
        expect(formatWhen(1_772_280_000, 'en-US')).toBe('02/28/2026 · 12:00 PM');
        expect(formatWhen(null)).toBe('—');
    });

    it('says Reconnecting, not Recording, for a meeting waiting for its browser', () => {
        const chip = statusChip({
            transcript_state: 'ready', recording_state: 'paused', media_present: false, live: false,
            origin_type: 'meetingsense', warnings: [],
        });
        expect(chip.label).toBe('Reconnecting');
        expect(statusChip({
            transcript_state: 'ready', recording_state: 'none', media_present: false, live: false,
            origin_type: 'meetingsense', warnings: [],
        }).label).toBe('Transcribed');
    });
});

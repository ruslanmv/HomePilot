import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { MeetingButton } from '../ui/meetingsense/MeetingButton';
import { MeetingSenseProvider } from '../ui/meetingsense/MeetingSenseProvider';
import { CONSENT_STORAGE_KEY } from '../ui/meetingsense/ConsentSheet';

const ON = {
    enabled: true,
    ready: true,
    retention: 'text',
    stt: { available: true, provider: 'whisper-local', remote: false },
};

function memoryStorage(seed: Record<string, string> = {}): Storage {
    const map = new Map(Object.entries(seed));
    return {
        getItem: (key: string) => map.get(key) ?? null,
        setItem: (key: string, value: string) => void map.set(key, value),
        removeItem: (key: string) => void map.delete(key),
        clear: () => map.clear(),
        key: (index: number) => [...map.keys()][index] ?? null,
        get length() { return map.size; },
    } as Storage;
}

function recorder() {
    return {
        start: vi.fn(async () => ({ ok: true, meetingId: 'm1' })),
        stop: vi.fn(async () => ({ ok: true })),
        muteMic: vi.fn(),
        levels: [0],
        audioMode: 'system+mic',
    };
}

beforeEach(() => {
    (globalThis as Record<string, unknown>).hpMeetingSense = recorder();
});

afterEach(() => {
    delete (globalThis as Record<string, unknown>).hpMeetingSense;
});

describe('premium meeting start preflight', () => {
    it('changes the existing capture options before recording starts', async () => {
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;

        render(
            <MeetingSenseProvider conversationId="c1" status={ON} storage={memoryStorage()}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );

        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => expect(screen.getByTestId('ms-consent')).toBeTruthy());
        expect(rec.start).not.toHaveBeenCalled();

        fireEvent.click(screen.getByTestId('ms-start-slides'));
        fireEvent.click(screen.getByTestId('ms-start-mode-participant'));
        fireEvent.click(screen.getByTestId('ms-consent-accept'));

        await waitFor(() => expect(rec.start).toHaveBeenCalledTimes(1));
        expect(rec.start.mock.calls[0][0]).toMatchObject({
            conversationId: 'c1',
            notes: true,
            watch: false,
            audio: true,
            mic: true,
            mode: 'participant',
        });
    });

    it('keeps the existing remembered-consent fast path non-destructively', async () => {
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;

        render(
            <MeetingSenseProvider
                conversationId="c1"
                status={ON}
                storage={memoryStorage({ [CONSENT_STORAGE_KEY]: 'true' })}
            >
                <MeetingButton />
            </MeetingSenseProvider>,
        );

        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => expect(rec.start).toHaveBeenCalledTimes(1));
        expect(screen.queryByTestId('ms-consent')).toBeNull();
    });

    it('shows truthful local-processing and retention information before capture', async () => {
        render(
            <MeetingSenseProvider conversationId="c1" status={ON} storage={memoryStorage()}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );

        fireEvent.click(screen.getByTestId('ms-record-button'));
        const dialog = await screen.findByTestId('ms-consent');
        expect(dialog.textContent).toContain('Processed locally');
        expect(dialog.textContent).toContain('whisper-local');
        expect(dialog.textContent).toContain('Only the transcript is kept');
    });
});

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
    window.localStorage.removeItem('homepilot_provider_chat');
    window.localStorage.removeItem('homepilot_model_chat');
    window.localStorage.removeItem('homepilot_base_url_chat');
    vi.unstubAllGlobals();
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
            notes: true,
            watch: false,
            audio: true,
            mic: true,
            mode: 'participant',
        });
        // A meeting records into a conversation of its own, not the one the button was
        // pressed from, so the id is asserted as "a fresh one" rather than as the caller's.
        expect(rec.start.mock.calls[0][0].conversationId).not.toBe('c1');
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

    /*
     * MS34. What the meeting leaves behind, asked before rather than after.
     *
     * The moment a meeting stops is the moment the user is least willing to answer a form —
     * they want the recap. And for most people the answer is the same every week, so it
     * belongs with the other things they set once, beside the capture sources.
     */
    it('carries the chosen summary shape into the start frame', async () => {
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;

        render(
            <MeetingSenseProvider conversationId="c1" status={ON} storage={memoryStorage()}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );

        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => expect(screen.getByTestId('ms-consent')).toBeTruthy());
        fireEvent.click(screen.getByTestId('ms-start-summary-email'));
        fireEvent.click(screen.getByTestId('ms-start-length-detailed'));
        fireEvent.click(screen.getByTestId('ms-consent-accept'));

        await waitFor(() => expect(rec.start).toHaveBeenCalledTimes(1));
        expect(rec.start.mock.calls[0][0].summary).toMatchObject({
            style: 'email',
            length: 'detailed',
            provider: 'ollama',
        });
    });

    it('defaults to minutes at standard length without being asked', async () => {
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;

        render(
            <MeetingSenseProvider conversationId="c1" status={ON} storage={memoryStorage()}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );

        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => expect(screen.getByTestId('ms-consent')).toBeTruthy());
        fireEvent.click(screen.getByTestId('ms-consent-accept'));

        await waitFor(() => expect(rec.start).toHaveBeenCalledTimes(1));
        expect(rec.start.mock.calls[0][0].summary).toMatchObject({
            style: 'minutes',
            length: 'standard',
            provider: 'ollama',
        });
    });

    it('lets summary and private meeting conversation use different installed models', async () => {
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;
        window.localStorage.setItem('homepilot_provider_chat', 'ollama');
        window.localStorage.setItem('homepilot_model_chat', 'llama3.2:3b');
        window.localStorage.setItem('homepilot_base_url_chat', 'http://localhost:11434');

        const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
            if (String(input).includes('/models?')) {
                return {
                    ok: true,
                    status: 200,
                    json: async () => ({ ok: true, models: ['llama3.2:3b', 'qwen2.5:7b'] }),
                } as Response;
            }
            return { ok: true, status: 200, json: async () => ({}) } as Response;
        });
        vi.stubGlobal('fetch', fetchMock);

        render(
            <MeetingSenseProvider conversationId="c1" status={ON} storage={memoryStorage()}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );

        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => {
            expect(screen.getByTestId('ms-start-summary-model')).toHaveTextContent('qwen2.5:7b');
        });

        fireEvent.change(screen.getByTestId('ms-start-summary-model'), {
            target: { value: 'qwen2.5:7b' },
        });
        fireEvent.change(screen.getByTestId('ms-start-conversation-model'), {
            target: { value: 'llama3.2:3b' },
        });
        fireEvent.click(screen.getByTestId('ms-consent-accept'));

        await waitFor(() => expect(rec.start).toHaveBeenCalledTimes(1));
        expect(rec.start.mock.calls[0][0].summary).toMatchObject({
            provider: 'ollama',
            model: 'qwen2.5:7b',
            base_url: 'http://localhost:11434',
        });
        expect(rec.start.mock.calls[0][0].conversation).toEqual({
            provider: 'ollama',
            model: 'llama3.2:3b',
            base_url: 'http://localhost:11434',
        });
    });

    /*
     * MS34. Context the room will not supply.
     *
     * Everything else in this dialog says what HomePilot may capture. This is the one thing
     * the user can give it that the meeting cannot, and the reason the ask path grounds on
     * more than the transcript.
     */
    it('attaches pasted context to the meeting it belongs to', async () => {
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;
        const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }));
        vi.stubGlobal('fetch', fetchMock);

        render(
            <MeetingSenseProvider conversationId="c1" status={ON} storage={memoryStorage()}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );

        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => expect(screen.getByTestId('ms-consent')).toBeTruthy());
        fireEvent.change(screen.getByTestId('ms-start-context'), {
            target: { value: 'Agenda: launch date, legal sign-off, pricing.' },
        });
        fireEvent.click(screen.getByTestId('ms-consent-accept'));

        await waitFor(() => {
            const call = fetchMock.mock.calls.find(([url]) => String(url).includes('/prep'));
            expect(call).toBeTruthy();
            // Attached to the meeting the socket just created, not to the conversation: prep
            // is scoped to one meeting and is deleted with it.
            expect(String(call![0])).toContain('/v1/meetingsense/m1/prep');
            expect(JSON.parse(String((call![1] as RequestInit).body)).text)
                .toContain('legal sign-off');
        });
        vi.unstubAllGlobals();
    });

    it('attaches nothing when nothing was pasted', async () => {
        const rec = recorder();
        (globalThis as Record<string, unknown>).hpMeetingSense = rec;
        const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }));
        vi.stubGlobal('fetch', fetchMock);

        render(
            <MeetingSenseProvider conversationId="c1" status={ON} storage={memoryStorage()}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );

        fireEvent.click(screen.getByTestId('ms-record-button'));
        await waitFor(() => expect(screen.getByTestId('ms-consent')).toBeTruthy());
        fireEvent.click(screen.getByTestId('ms-consent-accept'));

        await waitFor(() => expect(rec.start).toHaveBeenCalled());
        expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/prep'))).toBe(false);
        vi.unstubAllGlobals();
    });

    it('says the long-meeting case is handled, because that is the doubt', async () => {
        render(
            <MeetingSenseProvider conversationId="c1" status={ON} storage={memoryStorage()}>
                <MeetingButton />
            </MeetingSenseProvider>,
        );

        fireEvent.click(screen.getByTestId('ms-record-button'));
        const dialog = await screen.findByTestId('ms-consent');
        expect(dialog.textContent).toContain('part by part');
    });
});

/**
 * The document the meeting was for (batch MS34).
 *
 * The recap screen had one summary on it — the rolling notes, written a window at a time
 * while the meeting ran and held to a card's worth of words however long it went on. For a
 * three-hour workshop that is four sentences, and "No summary for this meeting" whenever the
 * windows happened to fall in a model outage. Neither is the thing a person records a
 * meeting in order to get.
 *
 * ── What these tests hold ────────────────────────────────────────────────────────────────
 *
 * 1. **It is a different document from the notes, and both are on screen.** A reader who
 *    only ever sees the shorter one has no way to know the longer one exists.
 * 2. **Every generation appends.** Asking for a recap email after taking minutes must not be
 *    a gamble on liking the email better — the minutes stay, and both are reachable.
 * 3. **The style is the product.** Minutes, email, notes, brief and actions are five
 *    different documents, and the picker sends the one that was chosen.
 * 4. **A degraded document says so.** An extractive fallback that looks written is the
 *    version a reader cannot correct for.
 */
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MeetingMinutes, DocumentBody, SUMMARY_STYLES } from '../ui/meetingsense/MeetingMinutes';
import { summaryDocs } from '../ui/meetingsense/meetingRecord';

const DOC = {
    id: 'doc-1',
    style: 'minutes',
    text: '## Summary\n\nThey agreed to ship in October.\n\n## Actions\n\n- Marina chases legal',
    chunks: 4,
    created_at: 1_700_000_000,
};

let fetchMock: ReturnType<typeof vi.fn>;

function renderPanel(props: Partial<React.ComponentProps<typeof MeetingMinutes>> = {}) {
    return render(
        <MeetingMinutes
            meetingId="m-1"
            documents={[]}
            hasTranscript
            fetcher={fetchMock as unknown as typeof fetch}
            {...props}
        />,
    );
}

beforeEach(() => {
    fetchMock = vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({ ...DOC, id: 'doc-2', style: 'email', text: 'Subject: Q3 recap\n\nWe shipped.' }),
    }));
});

afterEach(() => {
    vi.clearAllMocks();
});

describe('the full summary panel', () => {
    it('shows the document a finished meeting already wrote', () => {
        renderPanel({ documents: [DOC] });
        expect(screen.getByTestId('ms-minutes-body')).toHaveTextContent('They agreed to ship in October.');
        expect(screen.getByTestId('ms-minutes-body')).toHaveTextContent('Marina chases legal');
    });

    it('offers to write one when the meeting has none yet', () => {
        renderPanel();
        expect(screen.getByTestId('ms-minutes-empty')).toHaveTextContent('No full summary yet');
        expect(screen.getByTestId('ms-minutes-generate')).not.toBeDisabled();
    });

    it('does not offer to summarise a meeting with no transcript', () => {
        // There is nothing to summarise, and a button that produces an error when pressed is
        // worse than one that says why it is not available.
        renderPanel({ hasTranscript: false });
        expect(screen.getByTestId('ms-minutes-generate')).toBeDisabled();
        expect(screen.getByTestId('ms-minutes-empty')).toHaveTextContent('no transcript');
    });

    it('writes one in the style that was picked', async () => {
        renderPanel();
        fireEvent.click(screen.getByTestId('ms-minutes-tune'));
        fireEvent.click(screen.getByTestId('ms-minutes-style-email'));
        fireEvent.click(screen.getByTestId('ms-minutes-length-short'));
        fireEvent.click(screen.getByTestId('ms-minutes-generate'));

        await waitFor(() => expect(fetchMock).toHaveBeenCalled());
        const [url, init] = fetchMock.mock.calls[0];
        expect(String(url)).toContain('/v1/meetingsense/m-1/summary');
        const body = JSON.parse(String((init as RequestInit).body));
        expect(body.style).toBe('email');
        expect(body.length).toBe('short');
    });

    it('sends the selected summary model target with a rewrite', async () => {
        const modelFetcher = vi.fn(async () => ({
            ok: true,
            status: 200,
            json: async () => ({ ok: true, models: ['llama3.2:3b', 'qwen2.5:7b'] }),
        } as Response));
        renderPanel({
            modelTarget: {
                provider: 'ollama',
                model: 'llama3.2:3b',
                baseUrl: 'http://localhost:11434',
            },
            modelFetcher: modelFetcher as unknown as typeof fetch,
        });

        fireEvent.click(screen.getByTestId('ms-minutes-tune'));
        await waitFor(() => expect(screen.getByTestId('ms-minutes-model')).toHaveTextContent('qwen2.5:7b'));
        fireEvent.change(screen.getByTestId('ms-minutes-model'), {
            target: { value: 'qwen2.5:7b' },
        });
        fireEvent.click(screen.getByTestId('ms-minutes-generate'));

        await waitFor(() => expect(fetchMock).toHaveBeenCalled());
        const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body));
        expect(body).toMatchObject({
            provider: 'ollama',
            model: 'qwen2.5:7b',
            base_url: 'http://localhost:11434',
        });
    });

    it('sends a custom instruction with the request', async () => {
        renderPanel();
        fireEvent.click(screen.getByTestId('ms-minutes-tune'));
        fireEvent.change(screen.getByTestId('ms-minutes-instructions'), {
            target: { value: 'Write it in Spanish.' },
        });
        fireEvent.click(screen.getByTestId('ms-minutes-generate'));

        await waitFor(() => expect(fetchMock).toHaveBeenCalled());
        const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body));
        expect(body.instructions).toBe('Write it in Spanish.');
    });

    it('keeps the earlier document when a second one is written', async () => {
        // The whole of what "additive" buys the user: pressing the button is not a gamble.
        renderPanel({ documents: [DOC] });
        fireEvent.click(screen.getByTestId('ms-minutes-generate'));

        await waitFor(() => {
            expect(screen.getByTestId('ms-minutes-body')).toHaveTextContent('Subject: Q3 recap');
        });
        expect(screen.getByTestId('ms-minutes-count')).toHaveTextContent('2 versions kept');

        const versions = screen.getAllByTestId('ms-minutes-version');
        expect(versions).toHaveLength(2);
        fireEvent.click(versions[0]);
        expect(screen.getByTestId('ms-minutes-body')).toHaveTextContent('They agreed to ship in October.');
    });

    it('says so plainly beside the button', () => {
        renderPanel({ documents: [DOC] });
        expect(screen.getByTestId('ms-minutes-additive')).toHaveTextContent('Every version is kept');
    });

    it('labels a document that had no model to write it', () => {
        renderPanel({ documents: [{ ...DOC, degraded: 'extractive' }] });
        expect(screen.getByTestId('ms-minutes-degraded'))
            .toHaveTextContent('No language model was reachable');
    });

    it('says why a meeting with no transcript refused', async () => {
        fetchMock.mockImplementationOnce(async () => ({ ok: false, status: 409, json: async () => ({}) }));
        renderPanel();
        fireEvent.click(screen.getByTestId('ms-minutes-generate'));
        await waitFor(() => {
            expect(screen.getByTestId('ms-minutes-error')).toHaveTextContent('no transcript to summarise');
        });
    });

    it('reports a failure rather than leaving the button spinning', async () => {
        fetchMock.mockImplementationOnce(async () => { throw new Error('offline'); });
        renderPanel();
        fireEvent.click(screen.getByTestId('ms-minutes-generate'));
        await waitFor(() => expect(screen.getByTestId('ms-minutes-error')).toHaveTextContent('offline'));
        expect(screen.getByTestId('ms-minutes-generate')).not.toBeDisabled();
    });

    it('reports how much of the meeting the document came from', () => {
        renderPanel({ documents: [DOC] });
        expect(screen.getByTestId('ms-minutes-meta')).toHaveTextContent('4 parts');
    });
});

describe('the document reader', () => {
    it('renders headings, bullets and paragraphs', () => {
        render(<DocumentBody text={'## Decisions\n- ship in October\nPlain prose.'} />);
        const body = screen.getByTestId('ms-minutes-body');
        expect(body.querySelector('h4')).toHaveTextContent('Decisions');
        expect(body).toHaveTextContent('ship in October');
        expect(body).toHaveTextContent('Plain prose.');
    });

    it('renders the bold time range the outline opens each part with', () => {
        render(<DocumentBody text={'**00:00:00–00:10:00** — they discussed the launch'} />);
        expect(screen.getByTestId('ms-minutes-body').querySelector('strong'))
            .toHaveTextContent('00:00:00–00:10:00');
    });

    it('leaves unrecognised syntax as text rather than swallowing the line', () => {
        // The safe direction: a stray marker shows as itself instead of eating what follows.
        render(<DocumentBody text={'a | b | c'} />);
        expect(screen.getByTestId('ms-minutes-body')).toHaveTextContent('a | b | c');
    });

    it('drops blank lines instead of rendering empty paragraphs', () => {
        render(<DocumentBody text={'one\n\n\n\ntwo'} />);
        expect(screen.getByTestId('ms-minutes-body').children).toHaveLength(2);
    });
});

describe('the record', () => {
    it('reads the documents off a hydrated meeting', () => {
        expect(summaryDocs({ summaries: [DOC] })).toHaveLength(1);
    });

    it('ignores an empty one rather than rendering a blank version tab', () => {
        expect(summaryDocs({ summaries: [{ id: 'x', text: '  ' }, DOC] })).toHaveLength(1);
    });

    it('is empty for an older server that does not send them', () => {
        expect(summaryDocs({})).toEqual([]);
        expect(summaryDocs(null)).toEqual([]);
    });
});

describe('the styles', () => {
    it('are the five the server knows', () => {
        // Mirrored client-side so the picker needs no round trip; a style here the server
        // does not have would silently fall back to minutes, which looks like a broken tab.
        expect(SUMMARY_STYLES.map((style) => style.id))
            .toEqual(['minutes', 'email', 'notes', 'brief', 'actions']);
    });

    it('each explain what they are for', () => {
        for (const style of SUMMARY_STYLES) expect(style.note.length).toBeGreaterThan(10);
    });
});

/**
 * Asking about a meeting while it is running.
 *
 * ── The three faults this locks down ─────────────────────────────────────────────────────
 *
 * The workspace has always had a composer that says *"Ask about this meeting…"*. It did none
 * of the three things that sentence promises.
 *
 * 1. **It did not read the meeting.** The question went to `POST /chat` — the general chat
 *    endpoint — so "what did they say about the tax cuts" was answered by a model that had
 *    never seen a word of the transcript. The endpoint built for this, `/v1/meetingsense/
 *    {id}/ask`, assembles the last ninety seconds verbatim plus the matching passages and
 *    works on a live meeting; nothing in the browser called it.
 *
 * 2. **The question vanished.** The exchange was rendered only inside the Timeline tab, and
 *    the workspace opens on Transcript. Pressing Enter produced no visible change anywhere.
 *
 * 3. **It was written into the meeting's record.** Posting to `/chat` with the meeting's
 *    `conversation_id` persisted every private question into the thread the meeting was
 *    recorded in — and interleaved it into the Timeline by timestamp, where an exchange
 *    nobody else was party to read as a moment of the meeting.
 *
 * A transcript is a record of what was said in the room. The value of that record is that
 * everything in it was spoken; one assistant answer merged into it and a reader can no longer
 * tell. So the lane is separate, labelled, and reaches the record only on purpose.
 */
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MeetingWorkspace } from '../ui/meetingsense/MeetingWorkspace';
import { EMPTY_VIEW } from '../ui/meetingsense/meetingState';
import { DEFAULT_CAPTURE } from '../ui/meetingsense/CapturePopover';

const source = (over = {}) => ({
  requested: true, health: 'receiving', label: null, level: 0, error: null, lastSignalAt: null,
  ...over,
});

const CAPTURE_STATUS = {
  meetingAudio: source(),
  microphone: source({ requested: false, health: 'off' }),
  screen: source({ requested: false, health: 'off' }),
};

const VIEW = {
  ...EMPTY_VIEW,
  phase: 'live',
  meetingId: 'm-live',
  elapsedMs: 22_000,
  segments: [
    { id: 's1', t0: 14_000, t1: 19_000, speaker: 'them', text: 'the government announced new economic measures' },
    { id: 's2', t0: 19_000, t1: 22_000, speaker: 'them', text: 'including tax cuts and grants' },
  ],
};

let fetchMock: ReturnType<typeof vi.fn>;

function renderWorkspace(view = VIEW, record: unknown = null) {
  return render(
    <MeetingWorkspace
      view={view as never}
      capture={DEFAULT_CAPTURE}
      captureStatus={CAPTURE_STATUS as never}
      conversationId="conv-meeting"
      screenStream={null}
      record={record as never}
      pendingNotes={false}
      onEnd={vi.fn()}
      onMute={vi.fn()}
    />,
  );
}

async function ask(question: string) {
  const box = await screen.findByPlaceholderText('Ask about this meeting…');
  fireEvent.change(box, { target: { value: question } });
  fireEvent.keyDown(box, { key: 'Enter' });
}

beforeEach(() => {
  const shell = document.createElement('div');
  shell.className = 'hp-app-shell';
  shell.appendChild(document.createElement('main'));
  document.body.appendChild(shell);

  fetchMock = vi.fn(async () => ({
    ok: true,
    json: async () => ({ text: 'They announced tax cuts and grants [00:00:19].', cited: ['00:00:19'] }),
  }));
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('requestAnimationFrame', (fn: FrameRequestCallback) => {
    fn(0);
    return 0;
  });
  vi.stubGlobal('CSS', {
    ...((globalThis as { CSS?: Record<string, unknown> }).CSS || {}),
    escape: (value: string) => value,
  });
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  document.querySelectorAll('.hp-app-shell').forEach((node) => node.remove());
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('asking a live meeting', () => {
  it('answers from the transcript, not the general chat model', async () => {
    renderWorkspace();
    await ask('what did they say about tax cuts?');

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    // The endpoint that reads the transcript. `/chat` cannot see the meeting at all, which is
    // why the old wiring produced fluent answers about nothing.
    expect(String(url)).toContain('/v1/meetingsense/m-live/ask');
    expect(String(url)).not.toContain('/chat');
    expect(JSON.parse(String(init.body))).toEqual({ text: 'what did they say about tax cuts?' });
  });

  it('never posts the question into the meeting conversation', async () => {
    renderWorkspace();
    await ask('what did they say about tax cuts?');

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    for (const [url, init] of fetchMock.mock.calls) {
      expect(String(url)).not.toMatch(/\/chat$/);
      // The tell-tale of the old path: a conversation id on the request body.
      expect(String(init?.body ?? '')).not.toContain('conv-meeting');
    }
  });

  it('shows the question and the answer without being told which tab to open', async () => {
    // The workspace opens on Transcript; the exchange used to render only in Timeline, so
    // nothing at all happened on screen. Sending is a request to see the answer.
    renderWorkspace();
    await ask('what did they say about tax cuts?');

    expect(await screen.findByTestId('ms-ask-question')).toHaveTextContent('what did they say about tax cuts?');
    await waitFor(() => {
      expect(screen.getByTestId('ms-ask-answer')).toHaveTextContent('They announced tax cuts and grants');
    });
  });

  it('marks the exchange as yours and as private', async () => {
    renderWorkspace();
    await ask('anything');

    expect(await screen.findByTestId('ms-ask-question')).toHaveTextContent('You · private');
    const privacy = screen.getByTestId('ms-ask-privacy').textContent || '';
    expect(privacy).toContain('not part of the meeting');
    expect(privacy).toContain('not recorded in the transcript');
  });

  it('keeps the transcript free of the exchange', async () => {
    renderWorkspace();
    await ask('what did they say about tax cuts?');
    await waitFor(() => expect(screen.getByTestId('ms-ask-answer')).toBeTruthy());

    // Back to the record of what was said in the room. It has two lines, the two that were
    // spoken, and the count beside the tab still says so.
    fireEvent.click(screen.getByText(/Transcript/));
    const transcript = screen.getByLabelText('Live transcript');
    expect(transcript.textContent).toContain('the government announced new economic measures');
    expect(transcript.textContent).not.toContain('what did they say about tax cuts?');
    expect(screen.getByTestId('ms-transcript-count')).toHaveTextContent('2');
  });

  it('renders a citation the server vouched for, and jumps to it', async () => {
    renderWorkspace();
    await ask('what did they say about tax cuts?');

    const cite = await screen.findByTestId('ms-ask-cite');
    expect(cite).toHaveTextContent('00:00:19');
    fireEvent.click(cite);
    // Following a citation lands in the transcript, where the cited moment is.
    await waitFor(() => expect(screen.getByLabelText('Live transcript')).toBeTruthy());
  });

  it('adds an answer to the notes only when asked to', async () => {
    renderWorkspace();
    await ask('what did they say about tax cuts?');
    await waitFor(() => expect(screen.getByTestId('ms-ask-answer')).toBeTruthy());

    // Nothing has been written to the meeting's record by answering.
    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes('/notes'))).toBe(true);

    fireEvent.click(screen.getByTestId('ms-ask-keep'));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes('/notes'));
      expect(call).toBeTruthy();
      // A `suggestion` sits *beside* the notes. Merged in, an assistant's paragraph is
      // indistinguishable from something a person said.
      expect(JSON.parse(String(call![1].body)).op).toBe('suggestion');
    });
    expect(screen.getByTestId('ms-ask-keep')).toHaveTextContent('Kept in meeting notes');
  });

  it('does not answer from nothing before the meeting id exists', async () => {
    // Falling back to the general model here is how a confident answer about no transcript
    // gets produced during the two seconds a meeting takes to connect.
    renderWorkspace({ ...VIEW, meetingId: null } as never);
    await ask('what did they say?');

    await waitFor(() => {
      expect(screen.getByTestId('ms-ask-answer')).toHaveTextContent('still connecting');
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('asking after the meeting ends', () => {
  const endedView = {
    ...VIEW,
    phase: 'ended',
    elapsedMs: 40_000,
    segments: [
      { id: 's30', t0: 30_000, t1: 32_000, speaker: 'them', text: "I'm girlfriend, your romantic partner." },
      { id: 's32', t0: 32_000, t1: 37_000, speaker: 'them', text: 'I love to flirt, roleplay, and make you feel desired and appreciated.' },
      { id: 's37', t0: 37_000, t1: 40_000, speaker: 'them', text: "I'm playful, passionate, and deeply caring." },
    ],
  };

  const record = {
    meeting: { id: 'm-live', title: 'Meeting recap', started_at: 1_700_000_000, ended_at: 1_700_000_040 },
    notes: null,
  };

  it('keeps the private Q&A lane visible on the recap screen', async () => {
    fetchMock.mockImplementationOnce(async () => ({
      ok: true,
      json: async () => ({
        text: 'They are describing a romantic-partner persona [00:00:30].',
        cited: ['00:00:30'],
      }),
    }));

    renderWorkspace(endedView as never, record);
    expect(await screen.findByTestId('ms-ended-ask')).toBeTruthy();

    await ask('what are they talking about?');

    await waitFor(() => {
      expect(screen.getByTestId('ms-ask-answer')).toHaveTextContent('romantic-partner persona');
    });
    expect(screen.getByTestId('ms-ask-question')).toHaveTextContent('what are they talking about?');

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain('/v1/meetingsense/m-live/ask');
    expect(String(url)).not.toContain('/chat');
    expect(JSON.parse(String(init.body))).toEqual({ text: 'what are they talking about?' });
  });

  it('opens the ended transcript when an answer citation is followed', async () => {
    fetchMock.mockImplementationOnce(async () => ({
      ok: true,
      json: async () => ({
        text: 'They describe a romantic-partner persona [00:00:30].',
        cited: ['00:00:30'],
      }),
    }));

    renderWorkspace(endedView as never, record);
    const transcript = await screen.findByTestId('ms-ended-transcript');
    expect((transcript as HTMLDetailsElement).open).toBe(false);

    await ask('what are they talking about?');
    const cite = await screen.findByTestId('ms-ask-cite');
    fireEvent.click(cite);

    expect((transcript as HTMLDetailsElement).open).toBe(true);
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });
});

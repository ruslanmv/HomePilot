/**
 * The end-of-meeting recap is the Meeting details page, and its assistant is a sidebar.
 *
 * One presentation for a meeting, the moment it ends and a week later: the recap renders the
 * library's Meeting details page in its `recap` form — the same header, tabs, insights banner,
 * overview and details column — plus what a just-finished meeting needs on its Overview: the
 * full summary with its versions, asking the meeting, and the screens it captured. With the
 * library switched off it falls back to the workspace's own recap.
 *
 * The assistant no longer dims the page or closes when a press that touched it ends outside;
 * it is a column of the layout that closes on X, Escape, or a press entirely outside it.
 * Everything here is mocked — no network.
 */
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MeetingWorkspace } from '../ui/meetingsense/MeetingWorkspace';
import { MeetingDetailPage } from '../ui/meetingsense/library/MeetingDetailPage';
import { EMPTY_VIEW } from '../ui/meetingsense/meetingState';
import { DEFAULT_CAPTURE } from '../ui/meetingsense/CapturePopover';

const MEETING = 'm-recap';
const ITEM = {
  library_id: MEETING, meeting_id: MEETING, origin_type: 'meetingsense', origin_id: MEETING,
  title: 'Untitled meeting', description: '', category: 'Recorded',
  started_at: 1_792_510_980, ended_at: 1_792_511_002, scheduled_for: null, duration_ms: 22_000,
  projects: [], source: { kind: 'meetingsense', label: 'HomePilot' }, media_present: false,
  recording_state: 'none', transcript_state: 'ready', summary_state: 'ready', segments: 3,
  conversation_id: 'conv', status: 'ended', live: false, warnings: [],
};
const DETAIL = {
  item: ITEM,
  segments: [
    { id: 's1', t0_ms: 3_000, t1_ms: 4_000, speaker: 'me', text: 'Hallo.' },
    { id: 's2', t0_ms: 4_000, t1_ms: 6_000, speaker: 'me', text: 'How are you?' },
    { id: 's3', t0_ms: 10_000, t1_ms: 12_000, speaker: 'me', text: 'Mi nombre es Ruslan.' },
  ],
  keyframes: [{ id: 'k1', t_ms: 2_000, url: 'data:image/png;base64,iVBORw0KGgo=', caption: 'The launch plan' }],
  summaries: [{
    id: 'doc1', style: 'minutes', degraded: 'extractive',
    text: '00:00:03–00:00:12 — [00:00:03] Hallo. [00:00:04] How are you? [00:00:10] Mi nombre es Ruslan.',
  }],
  notes: null,
  assets: [],
  jobs: [],
  versions: [],
};

function json(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

let asks: string[];

function installFetch({ library = true }: { library?: boolean } = {}) {
  asks = [];
  vi.stubGlobal('fetch', vi.fn(async (input: unknown, init?: { body?: string }) => {
    const url = String(input);
    if (url.includes(`/v1/meetingsense/library/item/${MEETING}/ask`)) {
      asks.push(JSON.parse(String(init?.body || '{}')).text);
      return json({ text: 'Ruslan introduced himself [00:00:10].', cited: ['00:00:10'] });
    }
    if (url.includes(`/v1/meetingsense/library/item/${MEETING}`)) {
      return library ? json(DETAIL) : json({ detail: 'not found' }, 404);
    }
    return json({ detail: 'not found' }, 404);
  }));
}

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  installFetch();
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

function renderRecap(onBack = vi.fn()) {
  render(<MeetingDetailPage libraryId={MEETING} variant="recap" onBack={onBack} />);
  return onBack;
}

describe('the recap is the Meeting details page', () => {
  it('opens on Overview with the full summary, Ask, key screens and the transcript — real data, no placeholders', async () => {
    // The details column opens by default from 1280 px; jsdom's window is 1024.
    localStorage.setItem('hp_meeting_details_open', '1');
    renderRecap();
    await screen.findByText('Untitled meeting', { selector: 'h1' });
    expect(screen.getByText('Completed')).toBeTruthy();
    for (const tab of ['Overview', 'Transcript', 'Actions']) expect(screen.getByRole('tab', { name: new RegExp(tab) })).toBeTruthy();

    const summary = screen.getByTestId('ms-minutes');
    expect(within(summary).getByText('Full summary')).toBeTruthy();
    expect(within(summary).getByTestId('ms-minutes-degraded')).toBeTruthy();
    expect(within(summary).getByText(/Mi nombre es Ruslan/)).toBeTruthy();

    expect(screen.getByTestId('ask-meeting-card')).toBeTruthy();
    expect(screen.getByPlaceholderText(/Ask anything about what was said in this meeting/)).toBeTruthy();

    const screens = screen.getByTestId('key-screens');
    expect(within(screens).getByText('Meeting screen 1')).toBeTruthy();
    expect(within(screens).getByText('The launch plan')).toBeTruthy();
    expect(screen.getByText('Hallo.')).toBeTruthy();
    expect(screen.getByText('Quick summary')).toBeTruthy();
  });

  it('the transcript-assembled document is not passed off as a summary anywhere else', async () => {
    localStorage.setItem('hp_meeting_details_open', '1');
    renderRecap();
    await screen.findByText('Untitled meeting', { selector: 'h1' });
    // Only the Full summary card quotes it, under its amber notice.
    expect(screen.getAllByText(/Mi nombre es Ruslan\./).length).toBe(2); // the summary + the transcript line
    // Meeting overview and the Quick summary both say so instead.
    expect(screen.getAllByText(/No summary yet\./).length).toBe(2);
    expect(screen.getByRole('button', { name: 'Write one now' })).toBeTruthy();
  });

  it('keeps the summary actions on one row and opens every screen from the header', async () => {
    renderRecap();
    const row = await screen.findByTestId('ms-minutes-actions');
    expect(within(row).getByTestId('ms-minutes-copy')).toBeTruthy();
    expect(within(row).getByTestId('ms-minutes-generate')).toBeTruthy();

    const viewAll = screen.getByRole('button', { name: /View all \(1\)/ });
    viewAll.focus();
    fireEvent.click(viewAll);
    expect(screen.getByRole('dialog', { name: /Meeting screen 1 of 1/ })).toBeTruthy();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(viewAll));
  });

  it('opens a captured screen full size and closes it on Escape', async () => {
    renderRecap();
    fireEvent.click(await screen.findByRole('button', { name: /Open The launch plan full size/ }));
    expect(screen.getByRole('dialog', { name: /Meeting screen 1 of 1/ })).toBeTruthy();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: /Meeting screen 1 of 1/ })).toBeNull();
  });

  it('the library page itself is unchanged: no recap-only cards', async () => {
    render(<MeetingDetailPage libraryId={MEETING} onBack={vi.fn()} />);
    await screen.findByText('Untitled meeting', { selector: 'h1' });
    expect(screen.queryByTestId('ms-minutes')).toBeNull();
    expect(screen.queryByTestId('ask-meeting-card')).toBeNull();
    expect(screen.queryByTestId('key-screens')).toBeNull();
  });
});

describe('the workspace shows it the moment a meeting ends', () => {
  function renderEnded() {
    const shell = document.createElement('div');
    shell.className = 'hp-app-shell';
    shell.appendChild(document.createElement('main'));
    document.body.appendChild(shell);
    const onClose = vi.fn();
    render(
      <MeetingWorkspace
        view={{ ...EMPTY_VIEW, phase: 'ended', meetingId: MEETING } as never}
        capture={DEFAULT_CAPTURE}
        captureStatus={{ meetingAudio: {}, microphone: {}, screen: {} } as never}
        conversationId="conv"
        screenStream={null}
        record={null}
        pendingNotes={false}
        onEnd={vi.fn()}
        onMute={vi.fn()}
        onClose={onClose}
      />,
    );
    return onClose;
  }

  it('renders the Meeting details page, and Back closes the recap', async () => {
    const onClose = renderEnded();
    expect(await screen.findByTestId('meeting-detail')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /^Back$/ }));
    expect(onClose).toHaveBeenCalled();
  });

  it('falls back to its own recap when the library is switched off', async () => {
    installFetch({ library: false });
    renderEnded();
    expect(await screen.findByTestId('ms-workspace-close')).toBeTruthy();
    expect(screen.queryByTestId('meeting-detail')).toBeNull();
  });
});

describe('the assistant is a sidebar', () => {
  async function openChat() {
    renderRecap();
    const box = await screen.findByPlaceholderText(/Ask anything about what was said/);
    fireEvent.change(box, { target: { value: 'what is this about?' } });
    fireEvent.submit(box.closest('form')!);
    const panel = await screen.findByTestId('assistant-drawer');
    await waitFor(() => expect(within(panel).getByText(/Ruslan introduced himself/)).toBeTruthy());
    return panel;
  }
  const press = (down: Element, up: Element = down) => {
    fireEvent.pointerDown(down);
    fireEvent.pointerUp(up);
  };

  it('opens beside the meeting, with nothing dimming the page', async () => {
    const panel = await openChat();
    expect(panel.getAttribute('data-layout')).toBe('inline');
    expect(asks).toEqual(['what is this about?']);
    expect(document.querySelector('.bg-black\\/50')).toBeNull();
    expect(screen.getByRole('button', { name: /Hide chat/ })).toBeTruthy();
  });

  it('stays open for anything inside it — including a press that ends outside', async () => {
    const panel = await openChat();
    const input = within(panel).getByLabelText('Ask a question about this meeting');
    press(input);
    press(within(panel).getByText(/Ruslan introduced himself/));
    // Selecting a line of the answer and letting go over the page.
    press(within(panel).getByText(/Ruslan introduced himself/), screen.getByText('Untitled meeting', { selector: 'h1' }));
    await new Promise((r) => setTimeout(r, 200));
    expect(screen.getByTestId('assistant-drawer')).toBeTruthy();
  });

  it('closes on a press outside, on X and on Escape — and keeps the conversation', async () => {
    await openChat();
    press(screen.getByText('Untitled meeting', { selector: 'h1' }));
    await waitFor(() => expect(screen.queryByTestId('assistant-drawer')).toBeNull());

    fireEvent.click(screen.getByTestId('assistant-launcher'));
    const reopened = await screen.findByTestId('assistant-drawer');
    expect(within(reopened).getByText('what is this about?')).toBeTruthy(); // history kept

    fireEvent.click(within(reopened).getByRole('button', { name: 'Close assistant' }));
    await waitFor(() => expect(screen.queryByTestId('assistant-drawer')).toBeNull());

    fireEvent.click(screen.getByTestId('assistant-launcher'));
    await screen.findByTestId('assistant-drawer');
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('assistant-drawer')).toBeNull());
  });

  it('a control that opens the assistant never counts as outside it', async () => {
    await openChat();
    press(screen.getByTestId('ask-meeting-card'));
    await new Promise((r) => setTimeout(r, 200));
    expect(screen.getByTestId('assistant-drawer')).toBeTruthy();
  });

  it('Enter sends, Shift+Enter adds a line', async () => {
    const panel = await openChat();
    const input = within(panel).getByLabelText('Ask a question about this meeting') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: 'who spoke?' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(asks).toEqual(['what is this about?']);
    await act(async () => { fireEvent.keyDown(input, { key: 'Enter' }); });
    await waitFor(() => expect(asks).toEqual(['what is this about?', 'who spoke?']));
  });
});

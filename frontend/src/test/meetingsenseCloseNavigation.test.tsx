/**
 * Regression for the Meeting recap Close loop.
 *
 * Closing used to unmount only the portal. The application underneath was still on the
 * dedicated meeting conversation, so the provider's restore effect immediately recognised
 * that conversation as an origin meeting and mounted the recap again. To the user the Close
 * button looked dead.
 *
 * A meeting started from chat now remembers that chat as its return destination. Closing the
 * ended recap resets MeetingSense and navigates there; an explicit-dismiss guard prevents the
 * meeting conversation from re-hydrating during the state transition.
 */
import React, { useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MeetingSenseProvider } from '../ui/meetingsense/MeetingSenseProvider';
import { MeetingButton } from '../ui/meetingsense/MeetingButton';
import { CONSENT_STORAGE_KEY } from '../ui/meetingsense/ConsentSheet';

const ON = {
  enabled: true,
  ready: true,
  retention: 'text',
  stt: { available: true, provider: 'whisper' },
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
    start: vi.fn(async () => ({ ok: true, meetingId: 'm-close' })),
    stop: vi.fn(async () => ({ ok: true })),
    muteMic: vi.fn(),
    levels: [0],
    audioMode: 'system+mic',
  };
}

let appShell: HTMLElement | null = null;

beforeEach(() => {
  appShell = document.createElement('div');
  appShell.className = 'hp-app-shell';
  appShell.appendChild(document.createElement('main'));
  document.body.appendChild(appShell);
  (globalThis as Record<string, unknown>).hpMeetingSense = recorder();
});

afterEach(() => {
  delete (globalThis as Record<string, unknown>).hpMeetingSense;
  appShell?.remove();
  appShell = null;
  vi.restoreAllMocks();
});

function Harness() {
  const [conversationId, setConversationId] = useState('chat-before-meeting');
  return (
    <MeetingSenseProvider
      conversationId={conversationId}
      status={ON}
      storage={memoryStorage({ [CONSENT_STORAGE_KEY]: 'true' })}
      onOpenConversation={setConversationId}
    >
      <div data-testid="current-conversation">{conversationId}</div>
      <MeetingButton />
    </MeetingSenseProvider>
  );
}

describe('closing an ended MeetingSense workspace', () => {
  it('returns to the previous chat and stays closed', async () => {
    render(<Harness />);

    expect(screen.getByTestId('current-conversation').textContent).toBe('chat-before-meeting');
    fireEvent.click(screen.getByTestId('ms-record-button'));

    const workspace = await screen.findByTestId('meeting-workspace');
    expect(workspace).toBeTruthy();
    const meetingConversation = screen.getByTestId('current-conversation').textContent;
    expect(meetingConversation).toBeTruthy();
    expect(meetingConversation).not.toBe('chat-before-meeting');

    // End the meeting; once finalization completes the recap exposes Close.
    fireEvent.click(screen.getByTestId('ms-record-button'));
    const close = await screen.findByTestId('ms-workspace-close');
    fireEvent.click(close);

    await waitFor(() => {
      expect(screen.getByTestId('current-conversation').textContent).toBe('chat-before-meeting');
      expect(screen.queryByTestId('meeting-workspace')).toBeNull();
    });

    // Give restore effects another turn. This is the race the old implementation lost:
    // unmounting the portal alone caused the same meeting recap to come straight back.
    await act(async () => {
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(screen.getByTestId('current-conversation').textContent).toBe('chat-before-meeting');
    expect(screen.queryByTestId('meeting-workspace')).toBeNull();
  });
});

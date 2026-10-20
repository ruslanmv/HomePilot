/**
 * The Routines page on HomePilot's shared design system (src/ui/ds).
 *
 * What a person relies on, with the API mocked:
 *  - an empty list invites the first routine, and the button opens the editor as a real
 *    dialog (named, Escape closes it);
 *  - the scheduling notice tells the truth: on, off (with the setting that turned it off), or
 *    unknown — never "on" when it is not;
 *  - each routine's badge is honest: Active, Manual only when scheduling is off, Paused;
 *  - the switch pauses a routine through the API; Remove asks first; an error offers a retry.
 */
import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import RoutinesView, { routineStatus, runStatus } from '../ui/routines/RoutinesView';

const ROUTINE = {
  id: 'r1', name: 'Morning news', enabled: true, timezone: 'Europe/Rome',
  schedule: { type: 'daily', time: '07:30' }, target: { type: 'assistant' },
  action: { type: 'news_digest', parameters: {} },
  delivery: { in_app: true, notification: true, create_conversation: true, speak_if_active: true, catch_up: true },
  created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
};

const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });

function mockApi({ routines = [] as unknown[], scheduler = true as boolean | null, failList = false } = {}) {
  const calls: Array<{ url: string; method: string; body?: unknown }> = [];
  vi.stubGlobal('fetch', vi.fn(async (input: unknown, init?: { method?: string; body?: string }) => {
    const url = String(input);
    const method = init?.method || 'GET';
    calls.push({ url, method, body: init?.body ? JSON.parse(init.body) : undefined });
    if (url.includes('/v1/routines/capabilities')) {
      return scheduler === null ? json({}, 500) : json({ available: true, scheduler_enabled: scheduler });
    }
    if (url.includes('/v1/routines/runs')) return json({ runs: [] });
    if (method === 'PATCH') return json({ ...ROUTINE, ...(init?.body ? JSON.parse(init.body) : {}) });
    if (method === 'DELETE') return json({ ok: true });
    if (url.includes('/v1/routines')) return failList ? json({ detail: 'database is locked' }, 500) : json({ routines });
    if (url.includes('/projects')) return json({ projects: [] });
    return json({}, 404);
  }));
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

describe('status, said honestly', () => {
  it('names the routine state from the routine and the server', () => {
    expect(routineStatus(true, true).label).toBe('Active');
    expect(routineStatus(true, false)).toMatchObject({ label: 'Manual only', tone: 'amber' });
    expect(routineStatus(true, null).label).toBe('Enabled');
    expect(routineStatus(false, true)).toMatchObject({ label: 'Paused', tone: 'slate' });
    expect(runStatus('failed')).toMatchObject({ label: 'Failed', tone: 'red' });
    expect(runStatus('running')).toMatchObject({ label: 'Running', busy: true });
  });
});

describe('the Routines page', () => {
  it('invites the first routine and opens the editor as a dialog', async () => {
    mockApi();
    render(<RoutinesView backendUrl="" />);
    expect(await screen.findByText('No routines yet')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 1, name: 'Routines' })).toBeTruthy();
    expect(screen.getByText('Scheduled runs are on.')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Create your first routine' }));
    const dialog = await screen.findByRole('dialog', { name: 'New routine' });
    expect(within(dialog).getByLabelText('Name')).toBeTruthy();
    expect(within(dialog).getByRole('button', { name: 'Create routine' }).hasAttribute('disabled')).toBe(true);
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'New routine' })).toBeNull());
  });

  it('says which setting turned scheduling off, and marks routines Manual only', async () => {
    mockApi({ routines: [ROUTINE], scheduler: false });
    render(<RoutinesView backendUrl="" />);
    expect(await screen.findByText('Run now is available.')).toBeTruthy();
    expect(screen.getByText('ROUTINES_EXECUTION_ENABLED=false')).toBeTruthy();
    expect(screen.getByText('Manual only')).toBeTruthy();
    expect(screen.queryByText('Scheduled runs are on.')).toBeNull();
  });

  it('claims nothing when it could not check the server', async () => {
    mockApi({ routines: [ROUTINE], scheduler: null });
    render(<RoutinesView backendUrl="" />);
    expect(await screen.findByText(/Could not check whether scheduled runs are on/)).toBeTruthy();
    expect(screen.getByText('Enabled')).toBeTruthy();
  });

  it('pauses with the switch, and asks before removing', async () => {
    const calls = mockApi({ routines: [ROUTINE] });
    render(<RoutinesView backendUrl="" />);
    fireEvent.click(await screen.findByRole('switch', { name: 'Pause routine' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH' && (c.body as any)?.enabled === false)).toBe(true));
    expect(await screen.findByText('Paused')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false); // asked first
    expect(screen.getByText(/Remove “Morning news”\?/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true));
    expect(screen.queryByText('Morning news')).toBeNull();
  });

  it('offers a retry when the list cannot load', async () => {
    mockApi({ failList: true });
    render(<RoutinesView backendUrl="" />);
    expect(await screen.findByRole('button', { name: 'Try again' })).toBeTruthy();
  });
});

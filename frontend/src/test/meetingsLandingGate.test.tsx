/**
 * The Meetings landing page must not change while meeting intelligence lands in the detail
 * view. This gate snapshots the rendered markup of `MeetingsHome` with a fixed library, so
 * any change to its structure or classes fails here before anyone looks at a screenshot.
 *
 * Updating the snapshot is a deliberate act (`vitest -u`) that belongs in a pull request
 * which says the landing page is meant to change.
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { MeetingsHome } from '../ui/meetingsense/library/MeetingsHome'
import type { LibraryItem } from '../ui/meetingsense/library/api'

// Noon UTC, so the printed date is the same on every machine between UTC-11 and UTC+11.
const NOON = 1_772_280_000

function item(over: Partial<LibraryItem> = {}): LibraryItem {
  return {
    library_id: 'm1', meeting_id: 'm1', origin_type: 'import', origin_id: 'm1', title: 'Architecture Review',
    description: 'Discussed system architecture.', category: 'Project Meeting', started_at: NOON, ended_at: null,
    scheduled_for: null, duration_ms: 3_120_000, projects: [{ id: 'p1', name: 'HomePilot' }],
    source: { kind: 'upload', label: 'Upload' }, media_present: true, recording_state: 'present',
    transcript_state: 'ready', summary_state: 'ready', segments: 3, conversation_id: null, status: 'completed',
    live: false, warnings: [], ...over,
  }
}

const LIBRARY = {
  items: [
    item(),
    item({ library_id: 'm2', meeting_id: 'm2', title: 'Budget review', category: 'Client Call', origin_type: 'sync', source: { kind: 'sync', label: 'Synced folder' }, transcript_state: 'ready_warnings' }),
    item({ library_id: 'm3', meeting_id: 'm3', title: 'Kickoff', origin_type: 'scheduled', recording_state: 'awaiting', transcript_state: 'none', media_present: false, scheduled_for: NOON + 86_400, started_at: null }),
  ],
  next_cursor: null, total: 3, counts: { all: 3, imported: 2, scheduled: 1, processing: 0 },
  facets: { sources: [{ kind: 'upload', label: 'Upload' }], projects: [{ id: 'p1', name: 'HomePilot' }] },
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://hp.test')
    const body = url.pathname.endsWith('/jobs') ? { jobs: [], stt: { available: true } } : LIBRARY
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
  }))
})
afterEach(() => { vi.unstubAllGlobals() })

it('keeps the Meetings landing page exactly as it is', async () => {
  const { container } = render(<MeetingsHome status={{ enabled: true, intelligence: true } as any} onOpen={() => undefined} canRecordLive />)
  await screen.findByTestId('meetings-grid')
  await screen.findByText('Architecture Review')
  expect(screen.getByTestId('meetings-home')).toBeInTheDocument()
  for (const name of ['New Meeting', 'Import Files', 'Folder Sync']) expect(screen.getByRole('button', { name })).toBeInTheDocument()
  expect(container.innerHTML).toMatchSnapshot()
})

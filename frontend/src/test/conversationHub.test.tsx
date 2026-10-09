/**
 * Conversation Hub: the project's own picture is its identity, the latest
 * conversation is one tap away, and the memory and history sections keep
 * their existing behaviour.
 */
import React from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SessionPanel from '../ui/sessions/SessionPanel'
import PersonaHubDrawer from '../ui/sessions/PersonaHubDrawer'
import { ProjectAvatar } from '../ui/components/ProjectAvatar'
import {
  parseServerTime,
  projectAvatarUrl,
  projectTypeLabel,
  relationshipAge,
  shortDate,
  timeAgo,
} from '../ui/projectIdentity'

const NOW = Date.parse('2026-10-09T12:00:00Z')

function utc(msAgo: number): string {
  // Server form: "YYYY-MM-DD HH:MM:SS", UTC, no zone marker.
  return new Date(NOW - msAgo).toISOString().replace('T', ' ').slice(0, 19)
}

const MIN = 60_000
const DAY = 86_400_000

function session(id: string, mode: 'voice' | 'text', count: number, ago: number, ended = true, summary: string | null = null) {
  return {
    id,
    project_id: 'p1',
    conversation_id: `c-${id}`,
    mode,
    title: null,
    started_at: utc(ago),
    ended_at: ended ? utc(ago - 10 * MIN) : null,
    message_count: count,
    summary,
  }
}

function mockApi(sessions: any[], memories: any[] = []) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    const body = url.includes('/persona/sessions?')
      ? { ok: true, sessions }
      : url.includes('/persona/memory')
        ? { ok: true, memories, count: memories.length }
        : { ok: true }
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } }))
  })
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(NOW)
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('project identity helpers', () => {
  it('uses the saved picture, with a cache-buster and the session token', () => {
    localStorage.setItem('homepilot_auth_token', 'tok')
    const project = {
      updated_at: 1700000000.5,
      persona_appearance: {
        selected_thumb_filename: 'projects/p1/persona/appearance/thumb_avatar_a.webp',
        selected_filename: 'projects/p1/persona/appearance/avatar_a.png',
      },
    }
    expect(projectAvatarUrl(project, 'http://hp')).toBe('http://hp/files/projects/p1/persona/appearance/thumb_avatar_a.webp?v=1700000000500&token=tok')
    expect(projectAvatarUrl(project, 'http://hp', 'full')).toContain('/avatar_a.png?')
    expect(projectAvatarUrl({ persona_appearance: {} }, 'http://hp')).toBeNull()
    expect(projectAvatarUrl(null, 'http://hp')).toBeNull()
  })

  it('reads server times as UTC and describes them in plain words', () => {
    expect(parseServerTime('2026-10-09 11:46:00')).toBe(Date.parse('2026-10-09T11:46:00Z'))
    expect(timeAgo(utc(14 * MIN))).toBe('14 min ago')
    expect(timeAgo(utc(3 * DAY))).toBe('3 days ago')
    expect(timeAgo(utc(8 * DAY))).toBe('1 week ago')
    expect(timeAgo(utc(62 * DAY))).toBe('2 months ago')
    expect(timeAgo('not a date')).toBe('')
    expect(shortDate(utc(0))).not.toBe('')
    expect(relationshipAge(NOW / 1000 - 3 * 86400)).toBe('3 days together')
    expect(relationshipAge(undefined)).toBe('Just created today')
    expect(projectTypeLabel('persona')).toBe('Persona')
    expect(projectTypeLabel(undefined)).toBe('Chat / LLM')
  })
})

describe('ProjectAvatar', () => {
  it('shows the picture, and the type icon when there is none or it fails to load', () => {
    const { rerender } = render(<ProjectAvatar url="http://hp/files/a.webp" name="Angel" projectType="persona" />)
    const img = screen.getByRole('img', { name: 'Angel' })
    expect(img.tagName).toBe('IMG')
    fireEvent.error(img)
    expect(screen.getByRole('img', { name: 'Angel' }).tagName).toBe('DIV')
    rerender(<ProjectAvatar url={null} name="Sunny" projectType="persona" />)
    expect(document.querySelector('.hp-project-avatar')).toHaveAttribute('data-kind', 'icon')
  })
})

describe('Conversation Hub', () => {
  const props = {
    projectId: 'p1',
    projectName: 'Angel',
    projectCreatedAt: NOW / 1000 - 12 * 86400,
    avatarUrl: 'http://hp/files/a.webp',
    projectType: 'persona',
    description: 'Fashion stylist',
  }

  it('leads with the project picture and identity, and shows the name once', async () => {
    mockApi([session('s1', 'voice', 4, 14 * MIN, false)], [{ id: 1, project_id: 'p1', category: 'preferences', key: 'k', value: 'Loves olive', confidence: 1, source_type: 'inferred', created_at: '', updated_at: '' }])
    render(
      <PersonaHubDrawer open title="Angel" onClose={() => {}}>
        <SessionPanel {...props} onOpenSession={() => {}} onOpenVoiceSession={() => {}} />
      </PersonaHubDrawer>,
    )
    const hub = screen.getByRole('dialog', { name: 'Angel — conversation hub' })
    await within(hub).findByRole('button', { name: /Continue conversation/ })
    expect(within(hub).getAllByText('Angel')).toHaveLength(1)
    expect(within(hub).getByRole('img', { name: 'Angel' })).toHaveAttribute('src', 'http://hp/files/a.webp')
    expect(within(hub).getByText('Persona')).toBeInTheDocument()
    expect(within(hub).getByText('12 days together')).toBeInTheDocument()
    expect(within(hub).getAllByText('1 memory stored').length).toBeGreaterThan(0)
    expect(within(hub).getByText('Fashion stylist')).toBeInTheDocument()
  })

  it('Continue shows the latest conversation and reopens it; voice and text sit side by side', async () => {
    mockApi([session('s1', 'voice', 4, 14 * MIN, false), session('s2', 'text', 12, 3 * DAY, true, 'Spring palette')])
    const onVoice = vi.fn()
    render(<SessionPanel {...props} onOpenSession={() => {}} onOpenVoiceSession={onVoice} />)
    const cont = await screen.findByRole('button', { name: 'Continue conversation: voice, 4 messages, 14 min ago' })
    expect(cont).toHaveTextContent('Voice · 4 messages')
    expect(screen.getByRole('button', { name: /Talk by Voice/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Chat by Text/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Fresh voice chat/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Fresh text chat/ })).toBeInTheDocument()
  })

  it('when the open conversation is empty, Continue reopens the most recent one with messages', async () => {
    mockApi([session('new', 'voice', 0, 1 * MIN, false), session('s2', 'text', 12, 3 * DAY, true)])
    const onText = vi.fn()
    render(<SessionPanel {...props} onOpenSession={onText} onOpenVoiceSession={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: /Continue conversation: text, 12 messages/ }))
    expect(onText).toHaveBeenCalledWith(expect.objectContaining({ id: 's2' }))
  })

  it('history rows show type, messages and last activity; the memory manager opens in place', async () => {
    const memories = [
      { id: 1, project_id: 'p1', category: 'preferences', key: 'a', value: 'Loves olive', confidence: 1, source_type: 'inferred', created_at: '', updated_at: '' },
      { id: 2, project_id: 'p1', category: 'events', key: 'b', value: 'Wedding in June', confidence: 1, source_type: 'user_statement', created_at: '', updated_at: '' },
    ]
    mockApi([session('s1', 'voice', 24, 8 * DAY, true, 'Wedding outfits'), session('s2', 'text', 12, 3 * DAY, true)], memories)
    render(<SessionPanel {...props} onOpenSession={() => {}} onOpenVoiceSession={() => {}} />)
    const history = (await screen.findByText('Conversation History')).closest('section') as HTMLElement
    expect(within(history).getByText(/Voice · 24 messages · 1 week ago/)).toBeInTheDocument()
    expect(within(history).getByText(/Text · 12 messages · 2 days ago/)).toBeInTheDocument()
    expect(within(history).getByText('Wedding outfits')).toBeInTheDocument()

    const viewAll = screen.getByRole('button', { name: /View All/ })
    expect(viewAll).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(viewAll)
    expect(screen.getByRole('button', { name: /Hide/ })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('button', { name: 'Forget: Wedding in June' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Forget all' })).toBeInTheDocument()
  })

  it('a brand-new persona is welcomed with its picture and the two ways to start', async () => {
    mockApi([])
    render(<SessionPanel {...props} onOpenSession={() => {}} onOpenVoiceSession={() => {}} />)
    await waitFor(() => expect(screen.getByText('Ready to meet you')).toBeInTheDocument())
    expect(screen.getByRole('img', { name: 'Angel' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Talk by Voice/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Continue conversation/ })).not.toBeInTheDocument()
  })
})

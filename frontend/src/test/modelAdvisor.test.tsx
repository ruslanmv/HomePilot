/**
 * Model Advisor card: FitLab's top models for this machine, a Fetch button that
 * degrades to the bundled list offline, explicit installs, and a "New" marker
 * after an update.
 */
import React from 'react'
import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ModelAdvisorCard } from '../ui/components/ModelAdvisorCard'
import {
  ADVISOR_SEEN_KEY,
  CHECK_INTERVAL_MS,
  type AdvisorResponse,
  advisorEnabled,
  advisorSignature,
  checkDue,
  lastCheck,
  markSeen,
  pickNotice,
  recordCheck,
  setAdvisorEnabled,
  snooze,
  useAdvisorUpdates,
  writeAdvisorPrefs,
} from '../ui/modelAdvisor'

function item(id: string, kind: any, extra: Record<string, any> = {}) {
  return {
    id, name: id, kind, hf_id: `org/${id}`, license: 'apache-2.0', verdict: 'fits', score: 0.8,
    reasons: ['Fits in 12 GB — needs about 7 GB', 'About 20 tokens/s (estimated)'],
    install: { provider: kind === 'image' || kind === 'video' ? 'comfyui' : 'ollama', model_type: kind, model_id: `${id}:tag` },
    installed: false, ...extra,
  }
}

const PAYLOAD: AdvisorResponse = {
  ok: true,
  enabled: true,
  app_version: '2.1.0',
  hardware: { kind: 'nvidia', name: 'NVIDIA GeForce RTX 3060', vram_gb: 12, bandwidth_gbs: 360, detected: true },
  feeds: {
    llm: { source: 'bundled', generated_at: '2026-10-07', ranking_version: '1.1' },
    media: { source: 'bundled', generated_at: '2026-10-09', ranking_version: '1.0' },
  },
  fetch: null,
  suggestions: {
    chat: ['qwen3-14b', 'qwen3-8b', 'qwen2.5-7b', 'granite-8b', 'gemma-12b'].map((id) => item(id, 'chat')) as any,
    vision: [item('qwen3-vl-8b', 'vision')] as any,
    image: [item('sdxl', 'image', { download_gb: 6.94 })] as any,
    video: [item('ltx', 'video', { installed: true })] as any,
  },
  attribution: 'Model data: FitLab',
}

function mockServer(overrides: { get?: any; fetch?: any; install?: any } = {}) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const json = (body: any, status = 200) =>
      Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }))
    if (url.includes('/models/install')) return json(overrides.install ?? { ok: true, message: 'Installed' })
    if (url.includes('/v1/model-advisor/fetch')) return json(overrides.fetch ?? PAYLOAD)
    if (url.includes('/v1/model-advisor')) return json(overrides.get ?? PAYLOAD)
    return json({})
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('ModelAdvisorCard', () => {
  it('shows this machine and the top five for the current tab, with where the data came from', async () => {
    mockServer()
    render(<ModelAdvisorCard backendUrl="http://hp" />)
    expect(await screen.findByText('qwen3-14b')).toBeInTheDocument()
    expect(screen.getByTestId('advisor-hardware')).toHaveTextContent('NVIDIA GeForce RTX 3060 · 12 GB VRAM')
    expect(within(screen.getByRole('tabpanel')).getAllByRole('listitem')).toHaveLength(5)
    expect(screen.getByTestId('advisor-source')).toHaveTextContent('bundled with HomePilot 2026-10-07')

    fireEvent.click(screen.getByRole('tab', { name: 'Video' }))
    expect(screen.getByText('ltx')).toBeInTheDocument()
    expect(screen.getByText('Installed')).toBeInTheDocument()
  })

  it('opens on the tab that matches the Models page', async () => {
    mockServer()
    render(<ModelAdvisorCard backendUrl="http://hp" initialKind="image" />)
    expect(await screen.findByText('sdxl')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Image' })).toHaveAttribute('aria-selected', 'true')
  })

  it('"Fetch suggestions" asks FitLab, and says plainly when it had to fall back', async () => {
    const spy = mockServer({
      fetch: { ...PAYLOAD, fetch: { ok: false, partial: false, network: true, errors: ['offline'] } },
    })
    render(<ModelAdvisorCard backendUrl="http://hp" />)
    await screen.findByText('qwen3-14b')
    fireEvent.click(screen.getByRole('button', { name: /Fetch definitions/ }))
    expect(await screen.findByRole('status')).toHaveTextContent(
      "Couldn't reach FitLab — showing the bundled with HomePilot 2026-10-07 list.")
    const post = spy.mock.calls.find(([u]) => String(u).includes('/v1/model-advisor/fetch'))
    expect(post?.[1]?.method).toBe('POST')
  })

  it('reports a successful fetch with the new data dates', async () => {
    const live = { ...PAYLOAD, feeds: { llm: { source: 'live', generated_at: '2026-10-14' }, media: { source: 'live', generated_at: '2026-10-14' } }, fetch: { ok: true, partial: false, network: true, errors: [] } }
    mockServer({ fetch: live })
    render(<ModelAdvisorCard backendUrl="http://hp" />)
    await screen.findByText('qwen3-14b')
    fireEvent.click(screen.getByRole('button', { name: /Fetch definitions/ }))
    expect(await screen.findByRole('status')).toHaveTextContent('Definitions updated from FitLab — models 2026-10-14')
    expect(lastCheck()?.ok).toBe(true)   // a manual fetch resets the automatic schedule
  })

  it('says "already up to date" when FitLab answered that nothing changed', async () => {
    mockServer({ fetch: { ...PAYLOAD, fetch: { ok: true, partial: false, changed: false, network: true, errors: [] } } })
    render(<ModelAdvisorCard backendUrl="http://hp" />)
    await screen.findByText('qwen3-14b')
    fireEvent.click(screen.getByRole('button', { name: /Fetch definitions/ }))
    expect(await screen.findByRole('status')).toHaveTextContent('Already up to date')
  })

  it('marks the model in use and the upgrade FitLab ranks above it', async () => {
    const withUpgrade = {
      ...PAYLOAD,
      upgrades: { chat: { kind: 'chat', current: { id: 'qwen2.5-7b', name: 'qwen2.5-7b', model_id: 'qwen2.5-7b:tag', score: 0.7, rank: 3 }, better: PAYLOAD.suggestions!.chat![0] } },
    }
    const spy = mockServer({ get: withUpgrade })
    render(<ModelAdvisorCard backendUrl="http://hp" current={{ chat: 'qwen2.5-7b:tag' }} />)
    await screen.findByTestId('advisor-upgrade')
    const rows = within(screen.getByRole('tabpanel')).getAllByRole('listitem')
    expect(within(rows[2]).getByText('In use')).toBeInTheDocument()
    expect(within(rows[0]).getByText('Upgrade')).toBeInTheDocument()
    expect(screen.getByTestId('advisor-upgrade')).toHaveTextContent('ranks above your current chat model')
    expect(String(spy.mock.calls[0][0])).toContain('current_chat=qwen2.5-7b%3Atag')
  })

  it('installs only after confirmation, through the existing install endpoint', async () => {
    const spy = mockServer()
    const onInstalled = vi.fn()
    render(<ModelAdvisorCard backendUrl="http://hp" initialKind="image" onInstalled={onInstalled} />)
    await screen.findByText('sdxl')
    fireEvent.click(screen.getByRole('button', { name: 'Install' }))
    expect(spy.mock.calls.some(([u]) => String(u).includes('/models/install'))).toBe(false)
    expect(screen.getByText('Download ~6.94 GB?')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Install' }))
    await waitFor(() => expect(onInstalled).toHaveBeenCalled())
    const call = spy.mock.calls.find(([u]) => String(u).includes('/models/install'))
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ provider: 'comfyui', model_type: 'image', model_id: 'sdxl:tag' })
  })

  it('renders nothing when the server has the advisor turned off', async () => {
    mockServer({ get: { ok: true, enabled: false } })
    const { container } = render(<ModelAdvisorCard backendUrl="http://hp" />)
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })

  it('marks suggestions that are new since the last look', async () => {
    localStorage.setItem(ADVISOR_SEEN_KEY, JSON.stringify({ sig: 'old', ids: { chat: ['qwen3-14b', 'qwen3-8b', 'qwen2.5-7b', 'granite-8b'] } }))
    mockServer()
    render(<ModelAdvisorCard backendUrl="http://hp" />)
    await screen.findByText('qwen3-14b')
    const rows = within(screen.getByRole('tabpanel')).getAllByRole('listitem')
    expect(within(rows[4]).getByText('New')).toBeInTheDocument()
    expect(within(rows[0]).queryByText('New')).not.toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem(ADVISOR_SEEN_KEY) || '{}').sig).toBe(advisorSignature(PAYLOAD))
  })
})

describe('automatic checks and notices', () => {
  const run = () => renderHook(() => useAdvisorUpdates('http://hp', { chat: 'qwen2.5-7b:tag' }))
  const posts = (spy: any) => spy.mock.calls.filter(([u]: any[]) => String(u).includes('/v1/model-advisor/fetch')).length

  it('checks FitLab once when due, then not again for a day', async () => {
    const spy = mockServer({ fetch: { ...PAYLOAD, fetch: { ok: true, partial: false, changed: false, network: true, errors: [] } } })
    expect(checkDue()).toBe(true)
    const first = run()
    await waitFor(() => expect(posts(spy)).toBe(1))
    expect(lastCheck()?.ok).toBe(true)
    first.unmount()
    run()
    await new Promise((r) => setTimeout(r, 30))
    expect(posts(spy)).toBe(1)
    expect(checkDue(Date.now() + CHECK_INTERVAL_MS + 1)).toBe(true)
  })

  it('a failed check is retried sooner than a good one', () => {
    recordCheck(false, 0)
    expect(checkDue(6 * 3600 * 1000)).toBe(true)
    recordCheck(true, 0)
    expect(checkDue(6 * 3600 * 1000)).toBe(false)
  })

  it('with automatic checks off, FitLab is only contacted by the button', async () => {
    writeAdvisorPrefs({ autoCheck: false })
    const spy = mockServer()
    run()
    await new Promise((r) => setTimeout(r, 30))
    expect(posts(spy)).toBe(0)
  })

  it('after an update the Models entry says New until the suggestions are opened', async () => {
    writeAdvisorPrefs({ autoCheck: false })
    mockServer()
    const { result } = run()
    await waitFor(() => expect(result.current.badge).toBe(true))
    expect(result.current.notice).toMatchObject({ type: 'updated', firstTime: true })
    act(() => markSeen(PAYLOAD))
    await waitFor(() => expect(result.current.badge).toBe(false))
  })

  it('an upgrade is the notice, and "Not now" keeps it quiet', async () => {
    writeAdvisorPrefs({ autoCheck: false })
    markSeen(PAYLOAD)
    const withUpgrade = { ...PAYLOAD, upgrades: { chat: { kind: 'chat', current: { id: 'q', name: 'Qwen 2.5 7B', model_id: 'qwen2.5-7b:tag', score: 0.7, rank: 3 }, better: PAYLOAD.suggestions!.chat![0] } } }
    mockServer({ get: withUpgrade })
    const a = run()
    await waitFor(() => expect(a.result.current.notice).toMatchObject({ type: 'upgrade', kind: 'chat', currentName: 'Qwen 2.5 7B' }))
    act(() => a.result.current.dismiss())
    expect(a.result.current.notice).toBeNull()
    a.unmount()
    const b = run()
    await new Promise((r) => setTimeout(r, 30))
    expect(b.result.current.notice).toBeNull()
    expect(b.result.current.badge).toBe(false)
  })

  it('notifications can be turned off without turning suggestions off', async () => {
    writeAdvisorPrefs({ autoCheck: false })
    mockServer()
    const { result } = run()
    await waitFor(() => expect(result.current.notice).not.toBeNull())
    act(() => result.current.turnOffNotifications())
    await waitFor(() => expect(result.current.notice).toBeNull())
    expect(result.current.badge).toBe(false)
    expect(advisorEnabled()).toBe(true)
  })

  it('turning suggestions off stops every request', async () => {
    setAdvisorEnabled(false)
    const spy = mockServer()
    const { result } = run()
    await new Promise((r) => setTimeout(r, 30))
    expect(result.current.badge).toBe(false)
    expect(spy).not.toHaveBeenCalled()
  })

  it('pickNotice prefers an upgrade and respects snoozes', () => {
    const up = { ...PAYLOAD, upgrades: { video: { kind: 'video', current: { id: 'svd', name: 'SVD', model_id: 'svd', score: 0.6, rank: 2 }, better: PAYLOAD.suggestions!.video![0] } } } as AdvisorResponse
    const n = pickNotice(up, false)
    expect(n).toMatchObject({ type: 'upgrade', kind: 'video' })
    snooze(n!.key)
    expect(pickNotice(up, false)).toMatchObject({ type: 'updated' })
    markSeen(up)
    expect(pickNotice(up, false)).toBeNull()
  })
})

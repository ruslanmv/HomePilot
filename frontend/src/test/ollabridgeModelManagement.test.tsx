/**
 * Model Management → Chat → OllaBridge: the Local and Cloud connection cards.
 *
 * Local talks to the user's own gateway straight from the browser (health, then
 * /v1/models); Cloud reuses the existing OllaBridge Cloud session. Picking a
 * model routes chat to that connection through the existing
 * `homepilot:use-gpu-node` route (provider openai_compat + the connection's base
 * URL). Every request here is mocked — no network.
 */
import React from 'react'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ModelsView from '../ui/Models'
import OllaBridgeModels from '../ui/components/OllaBridgeModels'
import OllaBridgeChatPanel from '../ui/components/ollabridge/OllaBridgeChatPanel'
import { normalizeCloudModels, normalizeLocalModels } from '../ui/components/ollabridge/models'
import { localGatewayApiKeyFor, normalizeGatewayRoot } from '../ui/components/ollabridge/ollabridgeLocal'
import { isOllaBridgeChatRoute } from '../ui/components/ollabridge/chatRoute'

const GATEWAY = 'http://localhost:11435'
const CLOUD = 'https://app.ollabridge.com'
// Placeholder credentials for the mocked gateway / Cloud — not real secrets.
const TEST_LOCAL_KEY = 'test-local-key'
const TEST_CLOUD_SESSION = 'test-cloud-session'

const LOCAL_MODELS = [
  { id: 'deepseek-r1:latest', object: 'model', owned_by: 'ollama', source: 'ollama', source_display_name: 'Ollama' },
  { id: 'llama3.2:3b', object: 'model', owned_by: 'ollama', source: 'ollama', source_display_name: 'Ollama' },
  { id: 'nomic-embed-text:latest', object: 'model', owned_by: 'ollama', source: 'ollama', source_display_name: 'Ollama' },
]

const DEVICES = [
  { id: 'dev-desk', name: 'Desk RTX', online: true, gpu_name: 'RTX 4090' },
  { id: 'dev-laptop', name: 'Old laptop', online: false },
]
const CLOUD_MODELS = [
  { id: 'llama3.1:8b', object: 'model', owned_by: 'relay:dev-desk', x_source: 'shared_device' },
  { id: 'qwen2.5:7b', object: 'model', owned_by: 'relay:dev-laptop', x_source: 'shared_device' },
  { id: 'free-best', object: 'model', owned_by: 'ollabridge', x_source: 'route_alias' },
]

type Handler = (url: string, init?: RequestInit) => Response | Error | undefined

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

function header(init: RequestInit | undefined, name: string): string | undefined {
  const h = (init?.headers || {}) as Record<string, string>
  return h[name]
}

/** Install a fetch mock made of handlers (first one that answers wins); unknown URLs 404. */
function installFetch(...handlers: Handler[]) {
  const calls: Array<{ url: string; init?: RequestInit }> = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: any, init?: any) => {
    const url = String(input)
    calls.push({ url, init })
    for (const h of handlers) {
      const r = h(url, init)
      if (r instanceof Error) throw r
      if (r) return r
    }
    return json({ detail: 'not found' }, 404)
  })
  return calls
}

function gateway(opts: { models?: () => unknown[]; authMode?: string; requireKey?: string } = {}): Handler {
  return (url, init) => {
    if (url === `${GATEWAY}/health`) {
      return init?.mode === 'no-cors' ? new Response('') : json({ status: 'ok', auth_mode: opts.authMode || 'local-trust' })
    }
    if (url === `${GATEWAY}/v1/models`) {
      if (opts.requireKey && header(init, 'Authorization') !== `Bearer ${opts.requireKey}`) {
        return json({ detail: 'Invalid or missing API key' }, 401)
      }
      return json({ object: 'list', data: opts.models ? opts.models() : LOCAL_MODELS })
    }
    return undefined
  }
}

/** Gateway that is up but answers no cross-origin request (CORS_ORIGINS lacks this page). */
const corsBlockedGateway: Handler = (url, init) => {
  if (!url.startsWith(GATEWAY)) return undefined
  return init?.mode === 'no-cors' ? new Response('') : new TypeError('Failed to fetch')
}

const gatewayDown: Handler = (url) => (url.startsWith(GATEWAY) ? new TypeError('Failed to fetch') : undefined)

function cloud(opts: { expired?: boolean; models?: unknown[] } = {}): Handler {
  return (url) => {
    if (url === `${CLOUD}/v1/devices`) return opts.expired ? json({ detail: 'expired' }, 401) : json(DEVICES)
    if (url === `${CLOUD}/ollama/v1/models`) {
      return opts.expired ? json({ detail: 'expired' }, 401) : json({ object: 'list', data: opts.models || CLOUD_MODELS })
    }
    if (url === `${CLOUD}/v1/auth/login`) return json({ token: TEST_CLOUD_SESSION })
    return undefined
  }
}

const localCard = () => screen.getByRole('region', { name: 'OllaBridge Local' })
const cloudCard = () => screen.getByRole('region', { name: 'OllaBridge Cloud' })
const optionTexts = (select: HTMLElement) => within(select).getAllByRole('option').map((o) => o.textContent)

async function connectLocal() {
  fireEvent.click(within(localCard()).getByRole('button', { name: /Connect Local/ }))
  await waitFor(() => expect(within(localCard()).getByRole('status')).toHaveTextContent('Connected'))
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

// ── Normalization ────────────────────────────────────────────────────────────

describe('model normalization', () => {
  it('labels gateway models with their origin, drops embeddings and merges duplicate ids', () => {
    const out = normalizeLocalModels({
      object: 'list',
      data: [
        ...LOCAL_MODELS,
        { id: 'persona:atlas', source: 'homepilot', source_display_name: 'HomePilot' },
        { id: 'gpt-4o-mini', source: 'byok:openai', source_display_name: 'OpenAI (BYOK)' },
        { id: 'llama3.2:3b', source: 'relay', source_display_name: 'Relay node abc123' },
        { id: 'mistral' }, // bare entry: no provenance at all
      ],
    })
    expect(out.map((m) => m.label)).toEqual([
      'deepseek-r1 (Ollama)',
      'llama3.2:3b (Ollama, Relay node)',
      'persona:atlas (HomePilot)',
      'gpt-4o-mini (OpenAI (BYOK))',
      'mistral (OllaBridge)',
    ])
    expect(out[0].id).toBe('deepseek-r1:latest') // the id sent to chat is never rewritten
    expect(normalizeLocalModels(['qwen2.5:7b'])).toEqual([{
      id: 'qwen2.5:7b', origin: 'OllaBridge', label: 'qwen2.5:7b (OllaBridge)', kind: 'model', hidden: false, available: true,
    }])
    expect(normalizeLocalModels(null)).toEqual([])
  })

  it('groups Cloud models: own shared models first, smart routes, and offline devices unavailable', () => {
    const out = normalizeCloudModels(
      [
        { id: 'free-best', x_source: 'route_alias' },
        ...CLOUD_MODELS.filter((m) => m.x_source === 'shared_device'),
        { id: 'qwen2.5:0.5b', x_source: 'cloud_catalog' },
        { id: 'llama3.1:8b', source: 'shared_device', device_id: 'dev-laptop' }, // legacy `source`, second device
      ],
      DEVICES,
    )
    expect(out).toEqual([
      { id: 'llama3.1:8b', group: 'shared', available: true, label: 'llama3.1:8b (Desk RTX, Old laptop)' },
      { id: 'qwen2.5:7b', group: 'shared', available: false, label: 'qwen2.5:7b (Old laptop) — offline' },
      { id: 'free-best', group: 'route', available: true, label: 'Free Best (Cloud route)' },
      { id: 'qwen2.5:0.5b', group: 'catalog', available: true, label: 'qwen2.5:0.5b (Cloud)' },
    ])
  })

  it('normalizes the gateway URL to its root', () => {
    expect(normalizeGatewayRoot('localhost:11435/v1/')).toBe(GATEWAY)
    expect(normalizeGatewayRoot(' http://127.0.0.1:11435// ')).toBe('http://127.0.0.1:11435')
    expect(normalizeGatewayRoot('')).toBe('')
  })
})

// ── OllaBridge Local ─────────────────────────────────────────────────────────

describe('OllaBridge Local card', () => {
  it('starts disconnected with the model dropdown and Fetch Models disabled', () => {
    const calls = installFetch()
    render(<OllaBridgeChatPanel />)
    const card = localCard()
    expect(within(card).getByRole('status')).toHaveTextContent('Not Connected')
    expect(within(card).getByLabelText('Gateway URL')).toHaveValue(GATEWAY)
    const model = within(card).getByLabelText('Model')
    expect(model).toBeDisabled()
    expect(model).toHaveDisplayValue('Connect first to load models')
    expect(within(card).getByRole('button', { name: /Fetch Models/ })).toBeDisabled()
    expect(within(card).getByText('Connect to your local OllaBridge gateway to discover available models.')).toBeInTheDocument()
    expect(calls).toHaveLength(0) // nothing is probed until the user connects
  })

  it('Connect Local checks health, lists the models and enables picking — no key, no Cloud sign-in', async () => {
    const calls = installFetch(gateway())
    render(<OllaBridgeChatPanel />)
    await connectLocal()
    const card = localCard()
    const model = within(card).getByLabelText('Model')
    expect(model).toBeEnabled()
    expect(optionTexts(model)).toEqual(['Select a model', 'deepseek-r1 (Ollama)', 'llama3.2:3b (Ollama)'])
    expect(within(card).getByRole('button', { name: /Fetch Models/ })).toBeEnabled()
    expect(within(card).queryByRole('button', { name: /Connect Local/ })).not.toBeInTheDocument()
    expect(calls.map((c) => c.url)).toEqual([`${GATEWAY}/health`, `${GATEWAY}/v1/models`])
    expect(header(calls[1].init, 'Authorization')).toBeUndefined()
    expect(header(calls[1].init, 'X-API-Key')).toBeUndefined()
    // Remembered for the next load; the Cloud card was never involved.
    expect(localStorage.getItem('homepilot_ollabridge_local_url')).toBe(GATEWAY)
    expect(localStorage.getItem('homepilot_ollabridge_local_connected')).toBe('1')
    expect(within(cloudCard()).getByRole('status')).toHaveTextContent('Not Connected')
  })

  it('a failed connect stays Not Connected with an inline reason', async () => {
    installFetch(gatewayDown)
    render(<OllaBridgeChatPanel />)
    fireEvent.click(within(localCard()).getByRole('button', { name: /Connect Local/ }))
    const alert = await within(localCard()).findByRole('alert')
    expect(alert).toHaveTextContent(`Can't reach an OllaBridge gateway at ${GATEWAY}`)
    expect(within(localCard()).getByRole('status')).toHaveTextContent('Not Connected')
    expect(within(localCard()).getByLabelText('Model')).toBeDisabled()
    expect(localStorage.getItem('homepilot_ollabridge_local_connected')).toBeNull()
  })

  it('explains a CORS block, and asks for an API key when the gateway requires one', async () => {
    installFetch(corsBlockedGateway)
    const { unmount } = render(<OllaBridgeChatPanel backendUrl="https://homepilot.example.test" />)
    fireEvent.click(within(localCard()).getByRole('button', { name: /Connect Local/ }))
    expect(await within(localCard()).findByRole('alert')).toHaveTextContent('CORS_ORIGINS')
    expect(within(localCard()).getByRole('status')).toHaveTextContent('Not Connected')
    unmount()
    vi.restoreAllMocks()

    const calls = installFetch(gateway({ authMode: 'required', requireKey: TEST_LOCAL_KEY }))
    render(<OllaBridgeChatPanel />)
    fireEvent.click(within(localCard()).getByRole('button', { name: /Connect Local/ }))
    expect(await within(localCard()).findByRole('alert')).toHaveTextContent('requires an API key (auth mode: required)')
    const key = within(localCard()).getByLabelText('API key (optional)')
    fireEvent.change(key, { target: { value: TEST_LOCAL_KEY } })
    await connectLocal()
    const last = calls[calls.length - 1]
    expect(last.url).toBe(`${GATEWAY}/v1/models`)
    expect(header(last.init, 'Authorization')).toBe(`Bearer ${TEST_LOCAL_KEY}`)
    // The key is used for chat to this gateway only — never for the Cloud relay or other URLs.
    expect(localGatewayApiKeyFor(`${GATEWAY}/v1`)).toBe(TEST_LOCAL_KEY)
    expect(localGatewayApiKeyFor(`${CLOUD}/ollama/v1`)).toBeUndefined()
    expect(localGatewayApiKeyFor('http://localhost:11434')).toBeUndefined()
  })

  it('falls back to the same-machine HomePilot server when CORS blocks the browser', async () => {
    const calls = installFetch(corsBlockedGateway, (url) =>
      url.startsWith('http://localhost:8002/models?') ? json({ ok: true, provider: 'openai_compat', models: ['deepseek-r1:latest'] }) : undefined,
    )
    render(<OllaBridgeChatPanel backendUrl="http://localhost:8002" />)
    await connectLocal()
    const serverCall = calls.find((c) => c.url.startsWith('http://localhost:8002/models?'))!
    const q = new URL(serverCall.url).searchParams
    expect(q.get('provider')).toBe('openai_compat')
    expect(q.get('base_url')).toBe(`${GATEWAY}/v1`)
    expect(optionTexts(within(localCard()).getByLabelText('Model'))).toEqual(['Select a model', 'deepseek-r1 (OllaBridge)'])
    expect(within(localCard()).getByText(/Listed through HomePilot’s server/)).toBeInTheDocument()
  })

  it('selecting a model routes chat to the gateway and persists provider, base URL and model', async () => {
    installFetch(gateway())
    const events: any[] = []
    const onRoute = (e: Event) => events.push((e as CustomEvent).detail)
    window.addEventListener('homepilot:use-gpu-node', onRoute)
    render(<OllaBridgeChatPanel />)
    await connectLocal()
    fireEvent.change(within(localCard()).getByLabelText('Model'), { target: { value: 'llama3.2:3b' } })
    window.removeEventListener('homepilot:use-gpu-node', onRoute)

    expect(localStorage.getItem('homepilot_provider_chat')).toBe('openai_compat')
    expect(localStorage.getItem('homepilot_base_url_chat')).toBe(`${GATEWAY}/v1`)
    expect(localStorage.getItem('homepilot_model_chat')).toBe('llama3.2:3b')
    expect(events).toEqual([{ baseUrl: `${GATEWAY}/v1`, model: 'llama3.2:3b', source: 'ollabridge-local' }])
    expect(within(localCard()).getByLabelText('Model')).toHaveValue('llama3.2:3b')
    expect(within(localCard()).getByText(/Chat uses llama3.2:3b \(Ollama\) through this gateway/)).toBeInTheDocument()
    expect(isOllaBridgeChatRoute('openai_compat', `${GATEWAY}/v1`)).toBe(true)
  })

  it('Fetch Models keeps the selected model and flags it unavailable when the gateway drops it', async () => {
    localStorage.setItem('homepilot_ollabridge_local_url', GATEWAY)
    localStorage.setItem('homepilot_ollabridge_local_connected', '1')
    localStorage.setItem('homepilot_provider_chat', 'openai_compat')
    localStorage.setItem('homepilot_base_url_chat', `${GATEWAY}/v1`)
    localStorage.setItem('homepilot_model_chat', 'deepseek-r1:latest')
    let served = LOCAL_MODELS
    installFetch(gateway({ models: () => served }))
    render(<OllaBridgeChatPanel />)

    // The remembered connection is re-verified on load and the selection restored.
    await waitFor(() => expect(within(localCard()).getByRole('status')).toHaveTextContent('Connected'))
    const model = within(localCard()).getByLabelText('Model')
    expect(model).toHaveValue('deepseek-r1:latest')

    served = LOCAL_MODELS.filter((m) => m.id !== 'deepseek-r1:latest')
    fireEvent.click(within(localCard()).getByRole('button', { name: /Fetch Models/ }))
    expect(await within(localCard()).findByText(/no longer offered by this gateway/)).toBeInTheDocument()
    expect(model).toHaveValue('deepseek-r1:latest')
    expect(model).toHaveDisplayValue('deepseek-r1 — unavailable')
    expect(localStorage.getItem('homepilot_model_chat')).toBe('deepseek-r1:latest') // never silently replaced
  })

  it('re-verifies on focus and reconnects with backoff when the gateway comes back', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    localStorage.setItem('homepilot_ollabridge_local_url', GATEWAY)
    localStorage.setItem('homepilot_ollabridge_local_connected', '1')
    let up = true
    const live = gateway()
    installFetch((url, init) => (up ? live(url, init) : gatewayDown(url)))
    render(<OllaBridgeChatPanel />)
    await waitFor(() => expect(within(localCard()).getByRole('status')).toHaveTextContent('Connected'))

    up = false
    fireEvent(window, new Event('focus'))
    await waitFor(() => expect(within(localCard()).getByRole('status')).toHaveTextContent('Connection lost'))
    expect(within(localCard()).getByRole('alert')).toHaveTextContent('Retrying automatically')
    expect(within(localCard()).getByLabelText('Model')).toBeDisabled()

    up = true
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
    await waitFor(() => expect(within(localCard()).getByRole('status')).toHaveTextContent('Connected'))
    expect(within(localCard()).getByLabelText('Model')).toBeEnabled()
  })

  it('a connected gateway with no models says what to do', async () => {
    installFetch(gateway({ models: () => [] }))
    render(<OllaBridgeChatPanel />)
    await connectLocal()
    expect(within(localCard()).getByText(/The gateway is running but has no models/)).toBeInTheDocument()
    expect(within(localCard()).getByLabelText('Model')).toHaveDisplayValue('No models available')
  })
})

// ── OllaBridge Cloud ─────────────────────────────────────────────────────────

describe('OllaBridge Cloud card', () => {
  it('starts Not Connected with the existing sign-in flow and disabled controls', () => {
    installFetch()
    render(<OllaBridgeChatPanel />)
    const card = cloudCard()
    expect(within(card).getByRole('status')).toHaveTextContent('Not Connected')
    expect(within(card).getByLabelText('Base URL')).toHaveValue(CLOUD)
    expect(within(card).getByLabelText('Model')).toBeDisabled()
    expect(within(card).getByRole('button', { name: /Fetch Models/ })).toBeDisabled()
    expect(within(card).getByPlaceholderText('OllaBridge email')).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Connect Cloud' })).toBeInTheDocument()
  })

  it('restores a saved session only after the Cloud accepts it, with grouped models', async () => {
    localStorage.setItem('homepilot_cloud_token', TEST_CLOUD_SESSION)
    const calls = installFetch(cloud())
    render(<OllaBridgeChatPanel />)
    expect(within(cloudCard()).getByRole('status')).toHaveTextContent('Connecting…')
    await waitFor(() => expect(within(cloudCard()).getByRole('status')).toHaveTextContent('Connected'))

    expect(calls.map((c) => c.url).sort()).toEqual([`${CLOUD}/ollama/v1/models`, `${CLOUD}/v1/devices`])
    expect(header(calls[0].init, 'Authorization')).toBe(`Bearer ${TEST_CLOUD_SESSION}`)
    const model = within(cloudCard()).getByLabelText('Model')
    expect(model).toBeEnabled()
    const groups = within(model).getAllByRole('group').map((g) => g.getAttribute('label'))
    expect(groups).toEqual(['My shared models', 'Cloud routes'])
    expect(within(model).getByRole('option', { name: 'Free Best (Cloud route)' })).toBeEnabled()
    expect(within(model).getByRole('option', { name: 'qwen2.5:7b (Old laptop) — offline' })).toBeDisabled()
    expect(within(cloudCard()).queryByPlaceholderText('OllaBridge email')).not.toBeInTheDocument()

    fireEvent.change(model, { target: { value: 'free-best' } })
    expect(localStorage.getItem('homepilot_provider_chat')).toBe('openai_compat')
    expect(localStorage.getItem('homepilot_base_url_chat')).toBe(`${CLOUD}/ollama/v1`)
    expect(localStorage.getItem('homepilot_model_chat')).toBe('free-best')
  })

  it('an expired session drops back to Not Connected and asks to sign in again', async () => {
    localStorage.setItem('homepilot_cloud_token', TEST_CLOUD_SESSION)
    installFetch(cloud({ expired: true }))
    render(<OllaBridgeChatPanel />)
    expect(await within(cloudCard()).findByRole('alert')).toHaveTextContent('session expired')
    expect(within(cloudCard()).getByRole('status')).toHaveTextContent('Not Connected')
    expect(within(cloudCard()).getByLabelText('Model')).toBeDisabled()
    expect(within(cloudCard()).getByPlaceholderText('OllaBridge email')).toBeInTheDocument()
    expect(localStorage.getItem('homepilot_cloud_token')).toBeNull()
  })

  it('signs in with the existing Cloud login and loads models', async () => {
    const calls = installFetch(cloud())
    render(<OllaBridgeChatPanel />)
    const card = cloudCard()
    fireEvent.change(within(card).getByPlaceholderText('OllaBridge email'), { target: { value: 'user@example.test' } })
    fireEvent.change(within(card).getByPlaceholderText('Password'), { target: { value: 'test-password' } })
    fireEvent.click(within(card).getByRole('button', { name: 'Connect Cloud' }))
    await waitFor(() => expect(within(cloudCard()).getByRole('status')).toHaveTextContent('Connected'))
    expect(calls[0].url).toBe(`${CLOUD}/v1/auth/login`)
    expect(localStorage.getItem('homepilot_cloud_token')).toBe(TEST_CLOUD_SESSION)
    expect(within(cloudCard()).getByLabelText('Model')).toBeEnabled()
  })
})

// ── Both cards ───────────────────────────────────────────────────────────────

describe('Local and Cloud are independent', () => {
  it('signing out of Cloud leaves Local connected, and disconnecting Local leaves Cloud connected', async () => {
    localStorage.setItem('homepilot_cloud_token', TEST_CLOUD_SESSION)
    installFetch(gateway(), cloud())
    render(<OllaBridgeChatPanel />)
    await connectLocal()
    await waitFor(() => expect(within(cloudCard()).getByRole('status')).toHaveTextContent('Connected'))

    fireEvent.click(within(localCard()).getByRole('button', { name: 'OllaBridge Local connection' }))
    fireEvent.click(within(localCard()).getByRole('menuitem', { name: 'Disconnect' }))
    expect(within(localCard()).getByRole('status')).toHaveTextContent('Not Connected')
    expect(within(cloudCard()).getByRole('status')).toHaveTextContent('Connected')
    expect(within(cloudCard()).getByLabelText('Model')).toBeEnabled()
    expect(localStorage.getItem('homepilot_cloud_token')).toBe(TEST_CLOUD_SESSION)

    await connectLocal()
    fireEvent.click(within(cloudCard()).getByRole('button', { name: 'OllaBridge Cloud connection' }))
    fireEvent.click(within(cloudCard()).getByRole('menuitem', { name: 'Sign out' }))
    expect(within(cloudCard()).getByRole('status')).toHaveTextContent('Not Connected')
    expect(within(localCard()).getByRole('status')).toHaveTextContent('Connected')
    expect(within(localCard()).getByLabelText('Model')).toBeEnabled()
    expect(localStorage.getItem('homepilot_ollabridge_local_connected')).toBe('1')
  })

  it('the same model id on both connections routes to the gateway it was picked on', async () => {
    localStorage.setItem('homepilot_cloud_token', TEST_CLOUD_SESSION)
    const shared = [{ id: 'llama3.1:8b', source: 'ollama', source_display_name: 'Ollama' }]
    installFetch(gateway({ models: () => shared }), cloud())
    render(<OllaBridgeChatPanel />)
    await connectLocal()
    await waitFor(() => expect(within(cloudCard()).getByRole('status')).toHaveTextContent('Connected'))

    fireEvent.change(within(cloudCard()).getByLabelText('Model'), { target: { value: 'llama3.1:8b' } })
    expect(localStorage.getItem('homepilot_base_url_chat')).toBe(`${CLOUD}/ollama/v1`)
    expect(within(cloudCard()).getByLabelText('Model')).toHaveValue('llama3.1:8b')
    expect(within(localCard()).getByLabelText('Model')).toHaveValue('')

    fireEvent.change(within(localCard()).getByLabelText('Model'), { target: { value: 'llama3.1:8b' } })
    expect(localStorage.getItem('homepilot_base_url_chat')).toBe(`${GATEWAY}/v1`)
    expect(within(localCard()).getByLabelText('Model')).toHaveValue('llama3.1:8b')
    expect(within(cloudCard()).getByLabelText('Model')).toHaveValue('')
  })
})

// ── The existing per-type OllaBridge panel (now on the shared Cloud client) ─

describe('OllaBridge panel on the other Model Types', () => {
  it('still syncs devices and models with the saved session and routes "Use for Chat" to the relay', async () => {
    localStorage.setItem('homepilot_cloud_token', TEST_CLOUD_SESSION)
    installFetch(cloud())
    const events: any[] = []
    const onRoute = (e: Event) => events.push((e as CustomEvent).detail)
    window.addEventListener('homepilot:use-gpu-node', onRoute)
    render(<OllaBridgeModels filterType="chat" />)
    expect(await screen.findByText('Desk RTX')).toBeInTheDocument()
    expect(screen.getByText('llama3.1:8b')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: /Use for Chat/ })[0])
    window.removeEventListener('homepilot:use-gpu-node', onRoute)
    expect(events[0]).toMatchObject({ baseUrl: `${CLOUD}/ollama/v1` })
    expect(localStorage.getItem('homepilot_base_url_chat')).toBe(`${CLOUD}/ollama/v1`)
  })

  it('drops an expired session back to its sign-in form', async () => {
    localStorage.setItem('homepilot_cloud_token', TEST_CLOUD_SESSION)
    installFetch(cloud({ expired: true }))
    render(<OllaBridgeModels filterType="image" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('OllaBridge session expired')
    expect(screen.getByRole('button', { name: 'Connect OllaBridge' })).toBeInTheDocument()
    expect(localStorage.getItem('homepilot_cloud_token')).toBeNull()
  })
})

// ── Model Management page ────────────────────────────────────────────────────

describe('Model Management page', () => {
  const BACKEND = 'http://backend.test'
  const backend: Handler = (url) => {
    if (url === `${BACKEND}/providers`) {
      return json({
        ok: true,
        providers: {
          ollama: { label: 'Ollama' },
          openai_compat: { label: 'OpenAI-compatible (vLLM)' },
          openai: { label: 'OpenAI' },
          claude: { label: 'Claude' },
          watsonx: { label: 'Watsonx' },
          comfyui: { label: 'ComfyUI' },
        },
      })
    }
    if (url.startsWith(`${BACKEND}/models?`)) return json({ provider: 'x', models: ['llama3.2:3b'] })
    return undefined
  }
  const CHAT_PROVIDERS = ['☁️ OllaBridge (your nodes)', 'Ollama', 'OpenAI-compatible (vLLM)', 'OpenAI', 'Claude', 'Watsonx']

  it('keeps every provider and the original controls; OllaBridge on Chat swaps in the two cards', async () => {
    installFetch(backend)
    render(<ModelsView backendUrl={BACKEND} providerChat="ollama" />)
    const providerSelect = screen.getByLabelText('Provider')
    await waitFor(() => expect(optionTexts(providerSelect)).toEqual(CHAT_PROVIDERS))

    // A non-OllaBridge provider renders exactly the original controls.
    expect(screen.getByLabelText('Base URL Override')).toBeInTheDocument()
    expect(screen.getByText('Available Models')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'OllaBridge Local' })).not.toBeInTheDocument()

    fireEvent.change(providerSelect, { target: { value: 'openai_compat' } })
    expect(screen.getByLabelText('Base URL Override')).toBeInTheDocument()
    expect(screen.getByText('Available Models')).toBeInTheDocument()

    fireEvent.change(providerSelect, { target: { value: 'ollabridge' } })
    expect(localCard()).toBeInTheDocument()
    expect(cloudCard()).toBeInTheDocument()
    expect(screen.queryByLabelText('Base URL Override')).not.toBeInTheDocument()
    expect(screen.queryByText('Available Models')).not.toBeInTheDocument()
    expect(optionTexts(screen.getByLabelText('Provider'))).toEqual(CHAT_PROVIDERS) // list unchanged

    // Other Model Types keep the existing OllaBridge panel.
    fireEvent.click(screen.getByRole('radio', { name: 'Image' }))
    expect(screen.getByText('OllaBridge — your remote HomePilot nodes')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'OllaBridge Local' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Base URL Override')).toBeInTheDocument()
  })

  it('reopens on OllaBridge when chat is routed to an OllaBridge connection', async () => {
    installFetch(backend)
    render(<ModelsView backendUrl={BACKEND} providerChat="openai_compat" baseUrlChat={`${CLOUD}/ollama/v1`} />)
    expect(screen.getByLabelText('Provider')).toHaveValue('ollabridge')
    expect(localCard()).toBeInTheDocument()
    await waitFor(() => expect(optionTexts(screen.getByLabelText('Provider'))).toEqual(CHAT_PROVIDERS))
  })

  it('leaves an ordinary OpenAI-compatible endpoint on its own provider', async () => {
    installFetch(backend)
    render(<ModelsView backendUrl={BACKEND} providerChat="openai_compat" baseUrlChat="http://llm.internal:8001/v1" />)
    // (the option itself appears once /providers has answered)
    await waitFor(() => expect(screen.getByLabelText('Provider')).toHaveValue('openai_compat'))
    expect(screen.getByLabelText('Base URL Override')).toHaveValue('http://llm.internal:8001/v1')
    expect(screen.queryByRole('region', { name: 'OllaBridge Local' })).not.toBeInTheDocument()
  })
})

/**
 * Models → Multimodal → OllaBridge: the same Local and Cloud cards as Chat, for images.
 *
 * Its own list and its own route (`homepilot_*_multimodal`), never chat's. A model is checked
 * with a known test image (`POST /v1/multimodal/check`) before images go to it: a gateway's
 * `vision: true` is only a claim — one flagged a text-only model and left real vision models
 * unflagged — and a route that drops the picture still gets a confident answer.
 */
import React from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import OllaBridgeChatPanel from '../ui/components/ollabridge/OllaBridgeChatPanel'
import { visionSuggest, visionStatus } from '../ui/components/ollabridge/visionCheck'
import { chatChoices } from '../ui/lib/modelShelf'

const GATEWAY = 'http://localhost:11435'
const BACKEND = 'http://backend.test'

const caps = (vision: boolean | null) => ({ chat: true, vision, tools: null, image_generation: null, structured_output: null })
const MODELS = [
  { id: 'openwebui/internal-gemma4-31b', owned_by: 'openwebui', name: 'internal-gemma4-31b', preset: false, category: 'chat',
    status: 'available', stale: false, capabilities: caps(true) },
  { id: 'openwebui/internal-gpt-oss-120b', owned_by: 'openwebui', name: 'internal-gpt-oss-120b', preset: false, category: 'chat',
    status: 'available', stale: false, capabilities: caps(true) },
  { id: 'openwebui/internal-qwen3-8-27b', owned_by: 'openwebui', name: 'internal-qwen3-8-27b', preset: false, category: 'chat',
    status: 'available', stale: false, capabilities: caps(null) },
  { id: 'openwebui/natro-destek-kou', owned_by: 'openwebui', name: 'Natro Destek Koçu', preset: true,
    category: 'preset_or_workflow', status: 'available', stale: false, capabilities: caps(true) },
]

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

/** Gateway + HomePilot backend. `sees` decides each model's check verdict. */
function installFetch(sees: Record<string, boolean>) {
  const checks: Array<Record<string, unknown>> = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: any, init?: any) => {
    const url = String(input)
    if (url === `${GATEWAY}/health`) return json({ status: 'ok', auth_mode: 'local-trust' })
    if (url === `${GATEWAY}/v1/models`) return json({ object: 'list', data: MODELS })
    if (url === `${BACKEND}/v1/multimodal/check`) {
      const body = JSON.parse(String(init?.body || '{}'))
      checks.push(body)
      const ok = sees[body.model] === true
      return json({ ok: true, sees_images: ok, answer: ok ? 'LEFT=yellow, RIGHT=blue' : 'NO IMAGE',
        reason: ok ? '' : 'The model answered without describing the test image.' })
    }
    return json({ detail: 'not found' }, 404)
  })
  return checks
}

const localCard = () => screen.getByRole('region', { name: 'OllaBridge Local' })
const options = () => within(within(localCard()).getByLabelText('Model')).getAllByRole('option').map((o) => o.textContent)

async function connectLocal() {
  render(<OllaBridgeChatPanel role="vision" backendUrl={BACKEND} />)
  fireEvent.click(within(localCard()).getByRole('button', { name: /Connect Local/ }))
  await waitFor(() => expect(within(localCard()).getByLabelText('Model')).toBeEnabled())
}

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('what Multimodal offers', () => {
  it('offers the models the gateway claims can see, marked as not yet checked — never assistants', async () => {
    installFetch({})
    await connectLocal()
    expect(options()).toEqual([
      'Select a model',
      'internal-gemma4-31b (Open WebUI) — claims vision · not checked',
      'internal-gpt-oss-120b (Open WebUI) — claims vision · not checked',
    ])
  })

  it('a verdict beats a claim, either way', () => {
    const suggest = visionSuggest((id) => (id === 'a' ? { sees: false, at: 1 } : id === 'b' ? { sees: true, at: 1 } : undefined))
    expect(suggest({ id: 'a', label: 'a', kind: 'model', vision: true })).toBe(false) // claimed, failed
    expect(suggest({ id: 'b', label: 'b', kind: 'model' })).toBe(true) // unclaimed, passed
    expect(suggest({ id: 'c', label: 'c', kind: 'model', vision: true })).toBe(true) // claimed, unchecked
    expect(suggest({ id: 'd', label: 'd', kind: 'assistant', vision: true })).toBe(false)
    expect(visionStatus({}, { sees: true, at: 1 })).toBe('✓ sees images')
  })
})

describe('choosing a model checks it first', () => {
  it('a model that passes the image check reads images from now on — chat is untouched', async () => {
    const checks = installFetch({ 'openwebui/internal-gemma4-31b': true })
    localStorage.setItem('homepilot_model_chat', 'deepseek-r1:latest')
    const events: unknown[] = []
    const onVision = (e: Event) => events.push((e as CustomEvent).detail)
    window.addEventListener('homepilot:use-vision-model', onVision)
    await connectLocal()

    fireEvent.change(within(localCard()).getByLabelText('Model'), { target: { value: 'openwebui/internal-gemma4-31b' } })
    await waitFor(() => expect(localStorage.getItem('homepilot_model_multimodal')).toBe('openwebui/internal-gemma4-31b'))
    window.removeEventListener('homepilot:use-vision-model', onVision)

    expect(checks).toEqual([{ provider: 'openai_compat', base_url: `${GATEWAY}/v1`, model: 'openwebui/internal-gemma4-31b' }])
    expect(localStorage.getItem('homepilot_provider_multimodal')).toBe('openai_compat')
    expect(localStorage.getItem('homepilot_base_url_multimodal')).toBe(`${GATEWAY}/v1`)
    expect(localStorage.getItem('homepilot_model_chat')).toBe('deepseek-r1:latest')
    expect(events).toEqual([{ provider: 'openai_compat', baseUrl: `${GATEWAY}/v1`, model: 'openwebui/internal-gemma4-31b' }])
    expect(options()).toContain('internal-gemma4-31b (Open WebUI) — ✓ sees images')
    expect(within(localCard()).getByText(/Images are read by internal-gemma4-31b/)).toBeInTheDocument()
  })

  it('a model that fails is not used — unless the person says so', async () => {
    installFetch({})
    await connectLocal()
    fireEvent.change(within(localCard()).getByLabelText('Model'), { target: { value: 'openwebui/internal-gpt-oss-120b' } })
    await waitFor(() => expect(within(localCard()).getByText(/did not pass the image check/)).toBeInTheDocument())
    expect(localStorage.getItem('homepilot_model_multimodal')).toBeNull()

    fireEvent.click(within(localCard()).getByRole('button', { name: 'Use anyway' }))
    expect(localStorage.getItem('homepilot_model_multimodal')).toBe('openwebui/internal-gpt-oss-120b')
  })

  it('a model that passed once is not checked again', async () => {
    const checks = installFetch({ 'openwebui/internal-gemma4-31b': true })
    await connectLocal()
    const select = () => within(localCard()).getByLabelText('Model')
    fireEvent.change(select(), { target: { value: 'openwebui/internal-gemma4-31b' } })
    await waitFor(() => expect(checks).toHaveLength(1))
    fireEvent.change(select(), { target: { value: 'openwebui/internal-gemma4-31b' } })
    await waitFor(() => expect(localStorage.getItem('homepilot_model_multimodal')).toBe('openwebui/internal-gemma4-31b'))
    expect(checks).toHaveLength(1)
  })
})

describe('kept apart from chat', () => {
  it('the Multimodal list never appears in Chat settings', async () => {
    installFetch({})
    await connectLocal()
    expect(chatChoices()).toEqual([])
  })
})

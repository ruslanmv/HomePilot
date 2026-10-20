/**
 * Settings → Models: when no local model can serve chat, the user gets a
 * download button with progress instead of "run ollama pull …" in prose, and
 * the banner explains the actual situation (docs/design/LOCAL_MODEL_RESOLUTION.md).
 */
import React from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ModelDownloadCard from '../ui/components/ModelDownloadCard'
import OllamaHealthBanner from '../ui/OllamaHealthBanner'
import { describeResolution } from '../ui/lib/modelResolution'

const BACKEND = 'http://backend.test'

function resolution(overrides: Partial<any> = {}, remedy: any = null) {
  const chat = {
    role: 'chat',
    configured: '',
    model: '',
    runtime_url: 'http://localhost:11434',
    source: 'none',
    reason: 'Ollama is reachable but has no models installed.',
    installed: [],
    alternatives: [],
    remedy,
    configured_installed: null,
    ...overrides,
  }
  return {
    ok: true,
    chat,
    vision: { ...chat, role: 'vision' },
    fast: { ...chat, role: 'fast' },
    runtimes: [{ url: 'http://localhost:11434', label: 'configured', reachable: true, models: [], error: '', latency_ms: 3 }],
    runtime_url: chat.runtime_url,
    suggested: [],
    fingerprint: 'x',
    environment: { wsl: false, docker: false },
    pulls: [],
  }
}

const PULL_REMEDY = {
  kind: 'pull',
  message: 'Ollama at http://localhost:11434 has no model for chat. Download one below, or run the command.',
  command: 'ollama pull llama3.2:3b',
  runtime_url: 'http://localhost:11434',
  suggested: [
    { name: 'llama3.2:3b', size_gb: 2.0, roles: ['chat', 'fast'], why: 'Small, fast general chat.' },
    { name: 'qwen2.5:7b', size_gb: 4.7, roles: ['chat'], why: 'Stronger answers.' },
  ],
}

function jsonResponse(body: any, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('ModelDownloadCard', () => {
  it('offers the suggested models with sizes when the runtime has none, and starts a download', async () => {
    const calls: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: any, init?: any) => {
      const url = String(input)
      calls.push(`${init?.method || 'GET'} ${url}`)
      if (url.includes('/v1/models/resolution')) return jsonResponse(resolution({}, PULL_REMEDY))
      if (url.endsWith('/v1/models/pull') && init?.method === 'POST') {
        expect(JSON.parse(init.body)).toMatchObject({ name: 'llama3.2:3b' })
        return jsonResponse({ ok: true, job: { name: 'llama3.2:3b', runtime_url: 'http://localhost:11434', status: 'queued', message: '', total: 0, completed: 0, pct: 0, error: '' } }, 202)
      }
      if (url.includes('/v1/models/pull/')) {
        return jsonResponse({ ok: true, job: { name: 'llama3.2:3b', runtime_url: 'http://localhost:11434', status: 'running', message: 'pulling 1a2b', total: 1000, completed: 420, pct: 42, error: '' } })
      }
      return jsonResponse({ ok: false }, 404)
    })

    render(<ModelDownloadCard backendUrl={BACKEND} role="chat" configured="" />)

    expect(await screen.findByText(/has no model for chat/i)).toBeTruthy()
    const list = await screen.findByLabelText('Models you can download')
    expect(list.textContent).toContain('llama3.2:3b')
    expect(list.textContent).toContain('2.0 GB')
    expect(list.textContent).toContain('qwen2.5:7b')
    // No shell command is shown when a download button exists.
    expect(screen.queryByText('ollama pull llama3.2:3b')).toBeNull()

    const buttons = screen.getAllByRole('button', { name: /download/i })
    await act(async () => {
      fireEvent.click(buttons[0])
    })

    await waitFor(() => expect(calls.some((c) => c.startsWith('POST') && c.endsWith('/v1/models/pull'))).toBe(true))
    expect(await screen.findByText(/Downloading…/)).toBeTruthy()
    await waitFor(() => expect(screen.getByText('42%')).toBeTruthy(), { timeout: 3000 })
  })

  it('shows which model chat will use when one is installed, and hides the download list', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: any) => {
      const url = String(input)
      if (url.includes('/v1/models/resolution')) {
        return jsonResponse(
          resolution({
            model: 'deepseek-r1:latest',
            source: 'fallback',
            configured: 'llama3:8b',
            reason: "Configured model 'llama3:8b' is not installed; using 'deepseek-r1:latest', which is already loaded in Ollama.",
            installed: ['deepseek-r1:latest'],
            runtime_url: 'http://172.20.16.1:11434',
          }),
        )
      }
      return jsonResponse({ ok: false }, 404)
    })

    render(<ModelDownloadCard backendUrl={BACKEND} role="chat" configured="llama3:8b" />)

    expect(await screen.findByText('deepseek-r1:latest (auto, Ollama on 172.20.16.1)')).toBeTruthy()
    expect(screen.getByText(/is not installed; using/)).toBeTruthy()
    expect(screen.queryByLabelText('Models you can download')).toBeNull()
    expect(screen.getByRole('button', { name: 'Download another model' })).toBeTruthy()
  })

  it('explains the WSL bridge problem with the command when no runtime answers', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: any) => {
      const url = String(input)
      if (url.includes('/v1/models/resolution')) {
        return jsonResponse(
          resolution(
            { runtime_url: '', reason: 'No Ollama runtime is reachable (tried http://localhost:11434, http://172.20.16.1:11434).' },
            { kind: 'wsl_bridge', message: 'Windows host refused the connection. Enable WSL mirrored networking.', command: 'ollama serve', probed: ['http://localhost:11434', 'http://172.20.16.1:11434'], suggested: [] },
          ),
        )
      }
      return jsonResponse({ ok: false }, 404)
    })

    render(<ModelDownloadCard backendUrl={BACKEND} role="chat" configured="" />)
    expect(await screen.findByText(/mirrored networking/)).toBeTruthy()
    expect(screen.queryByLabelText('Models you can download')).toBeNull()
  })
})

describe('OllamaHealthBanner', () => {
  it('names the real problem and offers a download for the pull remedy, without a vLLM button', () => {
    const onDownload = vi.fn()
    render(
      <OllamaHealthBanner
        show
        remedy={PULL_REMEDY as any}
        vllmAvailable={false}
        onSwitchToVllm={() => {}}
        onFetchModels={() => {}}
        onDownloadModel={onDownload}
        onDismiss={() => {}}
      />,
    )
    expect(screen.getByText('No chat model installed')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Download a model' }))
    expect(onDownload).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: 'Switch to vLLM' })).toBeNull()
  })

  it('shows the WSL bridge explanation and the probed URLs', () => {
    render(
      <OllamaHealthBanner
        show
        remedy={{ kind: 'wsl_bridge', message: 'Enable WSL mirrored networking.', command: 'ollama serve', probed: ['http://172.20.16.1:11434'] } as any}
        onSwitchToVllm={() => {}}
        onFetchModels={() => {}}
        onDismiss={() => {}}
      />,
    )
    expect(screen.getByText('Ollama is on Windows, but WSL cannot reach it')).toBeTruthy()
    expect(screen.getByText(/Tried: http:\/\/172\.20\.16\.1:11434/)).toBeTruthy()
  })
})

describe('describeResolution', () => {
  it('reads as one sentence', () => {
    expect(
      describeResolution({ model: 'llama3.2:3b', source: 'configured', runtime_url: 'http://localhost:11434', reason: '' } as any),
    ).toBe('llama3.2:3b (configured, Ollama on localhost)')
    expect(describeResolution({ model: '', source: 'none', runtime_url: '', reason: 'nothing' } as any)).toBe('nothing')
  })
})

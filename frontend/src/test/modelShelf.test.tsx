/**
 * The model shelf: Models decides which models are offered (level 1), and each chat picks one
 * of them in Chat settings (level 2). Nothing is hardcoded — the default list is the gateway's
 * own description of its models (base model vs. preset/assistant, hidden, available).
 */
import React from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import {
  chatChoices, deactivateSource, readShelf, rememberCatalog, setShown, shownModels, sourceKey,
} from '../ui/lib/modelShelf'
import { normalizeLocalModels, suggestedByGateway } from '../ui/components/ollabridge/models'
import { ModelShelfPicker } from '../ui/components/ModelShelfPicker'
import { ChatSettingsPopover, DEFAULT_CHAT_SETTINGS, type ChatScopedSettings } from '../ui/components/ChatSettingsPopover'

// What the user's gateway really returns (trimmed): one Ollama model, base models served
// through Open WebUI, and Open WebUI assistants marked as presets.
const GATEWAY = {
  object: 'list',
  data: [
    { id: 'deepseek-r1:latest', owned_by: 'ollama', source: 'ollama', source_display_name: 'Ollama' },
    { id: 'openwebui/internal-gemma4-31b', owned_by: 'openwebui', name: 'internal-gemma4-31b', preset: false,
      category: 'chat', status: 'available', stale: false, capabilities: { chat: true } },
    { id: 'openwebui/ext-claude-standard', owned_by: 'openwebui', name: 'ext-claude-standard', preset: false,
      category: 'chat', status: 'available', stale: false },
    { id: 'openwebui/natro-destek-kou', owned_by: 'openwebui', name: 'Natro Destek Koçu', preset: true,
      category: 'preset_or_workflow', status: 'available', stale: false },
    { id: 'openwebui/webnode-ai-agent', owned_by: 'openwebui', name: 'Webnode AI Agent', preset: true,
      hidden: false, category: 'preset_or_workflow', status: 'available' },
  ],
}
const BASE = 'http://localhost:11435/v1'
const KEY = sourceKey('openai_compat', BASE)

function remember() {
  const models = normalizeLocalModels(GATEWAY)
  return rememberCatalog(
    { title: 'OllaBridge Local', provider: 'openai_compat', baseUrl: BASE },
    models.map((m) => ({ id: m.id, label: m.label, kind: m.kind, group: m.origin, hidden: m.hidden, available: m.available })),
  )
}

beforeEach(() => window.localStorage.clear())
afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

describe('what the gateway says a model is', () => {
  it('tells base models from assistants by the gateway’s own metadata', () => {
    const models = normalizeLocalModels(GATEWAY)
    expect(models.filter(suggestedByGateway).map((m) => m.id)).toEqual([
      'deepseek-r1:latest', 'openwebui/internal-gemma4-31b', 'openwebui/ext-claude-standard',
    ])
    // An assistant is shown by the name people know it by, not its slug.
    expect(models.find((m) => m.id === 'openwebui/natro-destek-kou')?.label).toMatch(/^Natro Destek Koçu/)
  })
})

describe('level 1 — Models chooses what is offered', () => {
  it('offers the gateway’s suggestion until the user chooses', () => {
    const source = remember()
    expect(shownModels(source).map((m) => m.id)).toHaveLength(3)
    expect(source.mode).toBe('suggested')
  })

  it('keeps the user’s choice across a fresh fetch', () => {
    remember()
    setShown(KEY, 'custom', ['openwebui/internal-gemma4-31b', 'openwebui/natro-destek-kou'])
    const again = remember()
    expect(shownModels(again).map((m) => m.id)).toEqual(['openwebui/internal-gemma4-31b', 'openwebui/natro-destek-kou'])
  })

  it('stops offering a connection that was disconnected, and remembers its choice', () => {
    remember()
    setShown(KEY, 'custom', ['deepseek-r1:latest'])
    deactivateSource(KEY)
    expect(chatChoices()).toEqual([])
    expect(readShelf()[KEY].shown).toEqual(['deepseek-r1:latest'])
    expect(chatChoices(readShelf()).length).toBe(0)
    remember() // reconnect
    expect(chatChoices().map((g) => g.models.map((m) => m.id))).toEqual([['deepseek-r1:latest']])
  })

  it('lets the user pick assistants, and go back to the suggestion', () => {
    const source = remember()
    render(<ModelShelfPicker source={source} onClose={() => undefined} />)
    fireEvent.click(screen.getByRole('checkbox', { name: /Natro Destek Koçu/ }))
    expect(shownModels(readShelf()[KEY]).map((m) => m.id)).toContain('openwebui/natro-destek-kou')
    fireEvent.click(screen.getByRole('button', { name: /Suggested/ }))
    expect(readShelf()[KEY].mode).toBe('suggested')
  })
})

describe('level 2 — a chat picks one of the offered models', () => {
  function Popover({ initial, modelPicker }: { initial: ChatScopedSettings; modelPicker?: boolean }) {
    const [settings, setSettings] = React.useState(initial)
    ;(window as unknown as { __settings: ChatScopedSettings }).__settings = settings
    return <ChatSettingsPopover open onClose={() => undefined} settings={settings} onChange={setSettings} modelPicker={modelPicker} />
  }
  const latest = () => (window as unknown as { __settings: ChatScopedSettings }).__settings

  it('lists only the models offered in Models, and stores the choice for this chat', () => {
    remember()
    window.localStorage.setItem('homepilot_model_chat', 'deepseek-r1:latest')
    render(<Popover initial={DEFAULT_CHAT_SETTINGS} />)
    const select = screen.getByLabelText('Model') as HTMLSelectElement
    const labels = Array.from(select.options).map((o) => o.textContent)
    expect(labels[0]).toBe('Default · deepseek-r1')
    expect(labels.some((l) => l?.startsWith('internal-gemma4-31b (Open WebUI)'))).toBe(true)
    expect(labels.some((l) => l?.startsWith('Natro'))).toBe(false) // an assistant nobody offered

    const gemma = Array.from(select.options).find((o) => o.textContent?.startsWith('internal-gemma4-31b (Open WebUI)'))!
    fireEvent.change(select, { target: { value: gemma.value } })
    expect(latest().model).toEqual({
      provider: 'openai_compat', baseUrl: BASE, model: 'openwebui/internal-gemma4-31b', label: gemma.textContent,
    })

    fireEvent.change(select, { target: { value: '' } })
    expect(latest().model).toBeNull()
  })

  it('names the default the way Models does, not by its raw id', () => {
    remember()
    window.localStorage.setItem('homepilot_provider_chat', 'openai_compat')
    window.localStorage.setItem('homepilot_base_url_chat', BASE)
    window.localStorage.setItem('homepilot_model_chat', 'openwebui/internal-gemma4-31b')
    render(<Popover initial={DEFAULT_CHAT_SETTINGS} />)
    const first = (screen.getByLabelText('Model') as HTMLSelectElement).options[0]
    expect(first.textContent).toBe('Default · internal-gemma4-31b (Open WebUI)')
  })

  it('says so when this chat’s model is no longer offered', () => {
    remember()
    render(<Popover initial={{ ...DEFAULT_CHAT_SETTINGS, model: {
      provider: 'openai_compat', baseUrl: BASE, model: 'gone-model', label: 'gone-model (OllaBridge)',
    } }} />)
    expect(screen.getByText(/no longer offered in Models/)).toBeTruthy()
  })

  it('updates while open when Models changes the list', () => {
    remember()
    render(<Popover initial={DEFAULT_CHAT_SETTINGS} />)
    act(() => setShown(KEY, 'custom', ['openwebui/natro-destek-kou']))
    const labels = Array.from((screen.getByLabelText('Model') as HTMLSelectElement).options).map((o) => o.textContent)
    expect(labels.some((l) => l?.startsWith('Natro'))).toBe(true)
    expect(labels.some((l) => l?.startsWith('internal-gemma4-31b (Open WebUI)'))).toBe(false)
  })

  it('is not offered in a persona chat — the persona keeps its own setup', () => {
    remember()
    render(<Popover initial={DEFAULT_CHAT_SETTINGS} modelPicker={false} />)
    expect(screen.queryByLabelText('Model')).toBeNull()
    expect(screen.getByText('Incognito mode')).toBeTruthy()
  })
})

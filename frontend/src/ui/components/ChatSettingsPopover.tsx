import React, { useEffect, useId, useRef } from 'react'
import { Box, EyeOff, SlidersHorizontal } from 'lucide-react'
import { ChatAppearanceQuick } from './ChatAppearanceSettings'
import { chatChoices, sourceKey, useModelShelf } from '../lib/modelShelf'

/**
 * A model picked for one chat (level 2 of the model shelf — lib/modelShelf.ts). Only ever one
 * of the models offered in Models; `null` is the default chosen there.
 */
export type ChatModelChoice = {
  provider: string
  baseUrl: string
  model: string
  label: string
}

export type ChatScopedSettings = {
  advancedHelpEnabled: boolean
  askBeforeActing: boolean
  executionProfile: 'fast' | 'balanced' | 'quality'
  incognito: boolean
  model?: ChatModelChoice | null
}

export const DEFAULT_CHAT_SETTINGS: ChatScopedSettings = {
  advancedHelpEnabled: false,
  askBeforeActing: true,
  executionProfile: 'fast',
  incognito: false,
  model: null,
}

/** Asks the app to open Models, where the offered models are chosen. */
export const OPEN_MODELS_EVENT = 'homepilot:open-models'

export function parseChatModelChoice(raw: unknown): ChatModelChoice | null {
  if (!raw || typeof raw !== 'object') return null
  const v = raw as Record<string, unknown>
  const model = typeof v.model === 'string' ? v.model.trim() : ''
  const provider = typeof v.provider === 'string' ? v.provider.trim() : ''
  if (!model || !provider) return null
  return {
    provider,
    baseUrl: typeof v.baseUrl === 'string' ? v.baseUrl.trim() : '',
    model,
    label: typeof v.label === 'string' && v.label.trim() ? v.label : model,
  }
}

/** The model chosen in Models, by the same name Models shows it under. */
function defaultModelLabel(shelf: ReturnType<typeof useModelShelf>): string {
  try {
    const id = localStorage.getItem('homepilot_model_chat') || ''
    if (!id) return 'Auto'
    const provider = localStorage.getItem('homepilot_provider_chat') || 'ollama'
    const baseUrl = localStorage.getItem('homepilot_base_url_chat') || ''
    const known = shelf[sourceKey(provider, baseUrl)]?.models.find((m) => m.id === id)
    return known?.label || id.replace(/:latest$/i, '')
  } catch {
    return 'Auto'
  }
}

const SEP = '\u0000'

/** This chat's model: the default from Models, or one of the models offered there. */
function ChatModelPicker({ value, onChange }: { value: ChatModelChoice | null; onChange: (next: ChatModelChoice | null) => void }) {
  const id = useId()
  const shelf = useModelShelf()
  const groups = chatChoices(shelf)
  const current = value ? `${sourceKey(value.provider, value.baseUrl)}${SEP}${value.model}` : ''
  const offered = groups.some((g) => g.models.some((m) => `${g.source.key}${SEP}${m.id}` === current))
  const stale = !!value && !offered

  const pick = (key: string) => {
    if (!key) return onChange(null)
    const [sourceId, modelId] = key.split(SEP)
    const group = groups.find((g) => g.source.key === sourceId)
    const model = group?.models.find((m) => m.id === modelId)
    if (!group || !model) return
    onChange({ provider: group.source.provider, baseUrl: group.source.baseUrl, model: model.id, label: model.label })
  }

  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <label htmlFor={id} className="flex items-center gap-2 text-sm text-white/90">
          <Box size={14} className="text-white/40" aria-hidden /> Model
        </label>
        <button
          type="button"
          onClick={() => window.dispatchEvent(new CustomEvent(OPEN_MODELS_EVENT))}
          className="inline-flex items-center gap-1 text-[11px] text-white/50 hover:text-white"
        >
          <SlidersHorizontal size={11} aria-hidden /> Manage
        </button>
      </div>
      <select
        id={id}
        value={current}
        onChange={(e) => pick(e.target.value)}
        className="mt-2 h-9 w-full cursor-pointer rounded-xl border border-white/10 bg-white/5 px-2.5 text-xs text-white outline-none [color-scheme:dark] focus:border-white/25"
      >
        <option value="">Default · {defaultModelLabel(shelf)}</option>
        {stale && value ? <option value={current}>{value.label} — no longer offered</option> : null}
        {groups.map((g) => (
          <optgroup key={g.source.key} label={g.source.title}>
            {g.models.map((m) => (
              <option key={m.id} value={`${g.source.key}${SEP}${m.id}`} disabled={m.available === false}>
                {m.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      <div className={`mt-1.5 text-[11px] ${stale ? 'text-amber-200/80' : 'text-white/45'}`}>
        {stale
          ? 'This model is no longer offered in Models. Pick another, or go back to the default.'
          : groups.length
            ? 'For this chat only. The list is the models you offer in Models.'
            : 'Connect OllaBridge in Models to choose a model for each chat.'}
      </div>
    </div>
  )
}

function Toggle({
  value,
  onChange,
}: {
  value: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      className={[
        'w-10 h-6 rounded-full border transition-all relative',
        value ? 'bg-white/20 border-white/25' : 'bg-white/5 border-white/10',
      ].join(' ')}
      aria-pressed={value}
    >
      <span
        className={[
          'absolute top-1/2 -translate-y-1/2 w-4 h-4 rounded-full transition-all',
          value ? 'left-[22px] bg-white/80' : 'left-[4px] bg-white/40',
        ].join(' ')}
      />
    </button>
  )
}

export function ChatSettingsPopover({
  open,
  onClose,
  settings,
  onChange,
  modelPicker = true,
}: {
  open: boolean
  onClose: () => void
  settings: ChatScopedSettings
  onChange: (next: ChatScopedSettings) => void
  /** Off in persona chats: a persona keeps the model chosen in Models with its own setup. */
  modelPicker?: boolean
}) {
  const panelRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    const onMouseDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (panelRef.current && !panelRef.current.contains(t)) onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('mousedown', onMouseDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('mousedown', onMouseDown)
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      ref={panelRef}
      className="absolute right-0 top-full mt-2 w-[320px] max-w-[calc(100vw-2rem)] max-h-[calc(100dvh-5rem)] flex flex-col rounded-2xl border border-white/10 bg-black/80 backdrop-blur-xl shadow-2xl overflow-hidden"
    >
      <div className="px-4 py-3 border-b border-white/10">
        <div className="text-sm font-semibold text-white/90">Chat settings</div>
        <div className="text-[11px] text-white/45 mt-0.5">
          These apply only to this chat.
        </div>
      </div>

      <div className="px-4 py-3 space-y-4 min-h-0 overflow-y-auto">
        {modelPicker ? (
          <>
            <ChatModelPicker
              value={settings.model ?? null}
              onChange={(model) => onChange({ ...settings, model })}
            />
            <div className="border-t border-white/5" />
          </>
        ) : null}

        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm text-white/90">Advanced help</div>
            <div className="text-[11px] text-white/45">
              Enables optional smart actions when available.
            </div>
          </div>
          <Toggle
            value={settings.advancedHelpEnabled}
            onChange={(v) => onChange({ ...settings, advancedHelpEnabled: v })}
          />
        </div>

        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm text-white/90">Ask before acting</div>
            <div className="text-[11px] text-white/45">
              Confirm before running advanced actions.
            </div>
          </div>
          <Toggle
            value={settings.askBeforeActing}
            onChange={(v) => onChange({ ...settings, askBeforeActing: v })}
          />
        </div>

        {/* Divider */}
        <div className="border-t border-white/5" />

        <div className="flex items-center justify-between gap-3">
          <div className="flex items-start gap-2">
            <EyeOff size={14} className="text-white/40 mt-0.5 shrink-0" />
            <div>
              <div className="text-sm text-white/90">Incognito mode</div>
              <div className="text-[11px] text-white/45">
                No memories stored, no profile shared. Perfect for work tasks.
              </div>
            </div>
          </div>
          <Toggle
            value={settings.incognito}
            onChange={(v) => onChange({ ...settings, incognito: v })}
          />
        </div>

        <div>
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm text-white/90">Execution style</div>
              <div className="text-[11px] text-white/45">
                Speed vs quality preference.
              </div>
            </div>
          </div>

          <div className="mt-2 grid grid-cols-3 gap-2">
            {(['fast', 'balanced', 'quality'] as const).map((p) => {
              const active = settings.executionProfile === p
              return (
                <button
                  key={p}
                  type="button"
                  onClick={() => onChange({ ...settings, executionProfile: p })}
                  className={[
                    'px-3 py-2 rounded-xl text-xs font-semibold border transition-all',
                    active
                      ? 'bg-white/15 border-white/25 text-white'
                      : 'bg-white/5 border-white/10 text-white/70 hover:bg-white/10 hover:border-white/15',
                  ].join(' ')}
                >
                  {p === 'fast' ? 'Fast' : p === 'balanced' ? 'Balanced' : 'Quality'}
                </button>
              )
            })}
          </div>
        </div>

        {/* Appearance applies to every chat (Settings → Chat holds the same choices). */}
        <div className="border-t border-white/5 pt-4">
          <ChatAppearanceQuick />
        </div>
      </div>

      <div className="px-4 py-3 border-t border-white/10 flex justify-end">
        <button
          type="button"
          onClick={onClose}
          className="text-xs px-3 py-1.5 rounded-xl bg-white/10 hover:bg-white/15 border border-white/10 hover:border-white/20 text-white/80 hover:text-white transition-all"
        >
          Done
        </button>
      </div>
    </div>
  )
}

import React, { useEffect, useRef } from 'react'
import { EyeOff } from 'lucide-react'

export type ChatScopedSettings = {
  advancedHelpEnabled: boolean
  askBeforeActing: boolean
  executionProfile: 'fast' | 'balanced' | 'quality'
  incognito: boolean
}

export const DEFAULT_CHAT_SETTINGS: ChatScopedSettings = {
  advancedHelpEnabled: false,
  askBeforeActing: true,
  executionProfile: 'fast',
  incognito: false,
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
}: {
  open: boolean
  onClose: () => void
  settings: ChatScopedSettings
  onChange: (next: ChatScopedSettings) => void
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
      className="absolute right-0 mt-2 w-[320px] rounded-2xl border border-white/10 bg-black/80 backdrop-blur-xl shadow-2xl overflow-hidden"
    >
      <div className="px-4 py-3 border-b border-white/10">
        <div className="text-sm font-semibold text-white/90">Chat settings</div>
        <div className="text-[11px] text-white/45 mt-0.5">
          These apply only to this chat.
        </div>
      </div>

      <div className="px-4 py-3 space-y-4">
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

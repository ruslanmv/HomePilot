import React from 'react'
import { ChevronDown, Loader2, Orbit, Sparkles } from 'lucide-react'
import type { ViewAngle, ViewPreviewMap, ViewSource } from './viewPack'
import { VIEW_ANGLE_OPTIONS } from './viewPack'

interface AvatarViewPackPanelProps {
  open: boolean
  source: ViewSource
  previews: ViewPreviewMap
  loadingAngles: Partial<Record<ViewAngle, boolean>>
  busy?: boolean
  disableLatest?: boolean
  disableEquipped?: boolean
  onToggle: () => void
  onSourceChange: (value: ViewSource) => void
  onGenerateAngle: (angle: ViewAngle) => void
  onGenerateMissing: () => void
}

const SOURCE_OPTIONS: Array<{ id: ViewSource; label: string }> = [
  { id: 'anchor', label: 'Anchor' },
  { id: 'latest', label: 'Latest Outfit' },
  { id: 'equipped', label: 'Equipped' },
]

export function AvatarViewPackPanel({
  open,
  source,
  previews,
  loadingAngles,
  busy = false,
  disableLatest = false,
  disableEquipped = false,
  onToggle,
  onSourceChange,
  onGenerateAngle,
  onGenerateMissing,
}: AvatarViewPackPanelProps) {
  return (
    <div className="overflow-hidden rounded-2xl border border-white/[0.06] bg-white/[0.02]">
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <div className="flex items-center gap-2 text-sm font-semibold text-white">
          <Orbit size={15} className="text-cyan-300" />
          View Pack
        </div>
        <ChevronDown
          size={15}
          className={['text-white/45 transition-transform', open ? 'rotate-180' : ''].join(' ')}
        />
      </button>

      {open && (
        <div className="space-y-4 border-t border-white/[0.06] px-4 py-4">
          <div>
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Source
            </div>
            <div className="flex flex-wrap gap-2">
              {SOURCE_OPTIONS.map((option) => {
                const disabled =
                  (option.id === 'latest' && disableLatest) ||
                  (option.id === 'equipped' && disableEquipped)

                return (
                  <button
                    key={option.id}
                    onClick={() => !disabled && onSourceChange(option.id)}
                    disabled={disabled}
                    className={[
                      'rounded-lg border px-3 py-1.5 text-[11px] font-medium transition-all',
                      source === option.id
                        ? 'border-cyan-500/20 bg-cyan-500/[0.10] text-cyan-100'
                        : 'border-white/[0.08] bg-white/[0.03] text-white/55 hover:bg-white/[0.06]',
                      disabled ? 'cursor-not-allowed opacity-35' : '',
                    ].join(' ')}
                  >
                    {option.label}
                  </button>
                )
              })}
            </div>
          </div>

          <div>
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Angles
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {VIEW_ANGLE_OPTIONS.map((angle) => {
                const ready = Boolean(previews[angle.id])
                const loading = Boolean(loadingAngles[angle.id])

                return (
                  <button
                    key={angle.id}
                    onClick={() => onGenerateAngle(angle.id)}
                    disabled={loading}
                    className={[
                      'rounded-xl border px-3 py-3 text-left transition-all',
                      ready
                        ? 'border-emerald-500/18 bg-emerald-500/[0.07]'
                        : 'border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06]',
                    ].join(' ')}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm">
                        {loading ? <Loader2 size={14} className="animate-spin text-white/60" /> : angle.icon}
                      </span>
                      <span
                        className={[
                          'text-[10px] font-semibold',
                          ready ? 'text-emerald-200' : 'text-white/35',
                        ].join(' ')}
                      >
                        {ready ? 'Ready' : 'Generate'}
                      </span>
                    </div>
                    <div className="mt-2 text-xs font-medium text-white">{angle.label}</div>
                    <div className="mt-0.5 text-[10px] text-white/35">{angle.shortLabel}</div>
                  </button>
                )
              })}
            </div>
          </div>

          <button
            onClick={onGenerateMissing}
            disabled={busy}
            className={[
              'flex w-full items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-xs font-semibold transition-all',
              busy
                ? 'cursor-wait bg-white/[0.04] text-white/30'
                : 'bg-gradient-to-r from-cyan-600/90 to-blue-600/90 text-white hover:brightness-110',
            ].join(' ')}
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            Generate Missing Views
          </button>
        </div>
      )}
    </div>
  )
}

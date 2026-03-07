import React from 'react'
import { ChevronDown, Loader2, Orbit, RefreshCw, Sparkles, Trash2 } from 'lucide-react'
import type { ViewAngle, ViewPreviewMap, ViewSource, ViewTimestampMap } from './viewPack'
import { VIEW_ANGLE_OPTIONS } from './viewPack'

interface AvatarViewPackPanelProps {
  open: boolean
  source: ViewSource
  previews: ViewPreviewMap
  timestamps?: ViewTimestampMap
  loadingAngles: Partial<Record<ViewAngle, boolean>>
  busy?: boolean
  disableLatest?: boolean
  disableEquipped?: boolean
  onToggle: () => void
  onSourceChange: (value: ViewSource) => void
  onGenerateAngle: (angle: ViewAngle) => void
  onGenerateMissing: () => void
  onClearAll?: () => void
  hasAnyResults?: boolean
}

const SOURCE_OPTIONS: Array<{ id: ViewSource; label: string }> = [
  { id: 'anchor', label: 'Anchor' },
  { id: 'latest', label: 'Latest Outfit' },
  { id: 'equipped', label: 'Equipped' },
]

/** Format a unix timestamp as a short relative string. */
function timeAgo(ts: number): string {
  const seconds = Math.floor((Date.now() - ts) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function AvatarViewPackPanel({
  open,
  source,
  previews,
  timestamps = {},
  loadingAngles,
  busy = false,
  disableLatest = false,
  disableEquipped = false,
  onToggle,
  onSourceChange,
  onGenerateAngle,
  onGenerateMissing,
  onClearAll,
  hasAnyResults = false,
}: AvatarViewPackPanelProps) {
  const readyCount = VIEW_ANGLE_OPTIONS.filter((a) => previews[a.id]).length

  return (
    <div className="overflow-hidden rounded-2xl border border-white/[0.06] bg-white/[0.02]">
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <div className="flex items-center gap-2 text-sm font-semibold text-white">
          <Orbit size={15} className="text-cyan-300" />
          View Pack
          {readyCount > 0 && (
            <span className="ml-1 rounded-md bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-300">
              {readyCount}/{VIEW_ANGLE_OPTIONS.length}
            </span>
          )}
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
                const previewUrl = previews[angle.id]
                const ready = Boolean(previewUrl)
                const loading = Boolean(loadingAngles[angle.id])
                const ts = timestamps[angle.id]

                return (
                  <button
                    key={angle.id}
                    onClick={() => onGenerateAngle(angle.id)}
                    disabled={loading}
                    className={[
                      'group relative rounded-xl border text-left transition-all overflow-hidden',
                      ready
                        ? 'border-emerald-500/18 bg-emerald-500/[0.07]'
                        : 'border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06]',
                    ].join(' ')}
                  >
                    {/* Thumbnail preview when ready */}
                    {ready && previewUrl ? (
                      <div className="relative h-20 w-full overflow-hidden">
                        <img
                          src={previewUrl}
                          alt={angle.label}
                          className="h-full w-full object-cover object-top opacity-70 group-hover:opacity-90 transition-opacity"
                        />
                        <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/30 to-transparent" />
                        {/* Regenerate overlay on hover */}
                        <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                          <div className="flex items-center gap-1 rounded-lg bg-black/60 px-2 py-1 text-[10px] font-medium text-white/80 backdrop-blur-sm">
                            <RefreshCw size={10} />
                            Redo
                          </div>
                        </div>
                        {/* Bottom info bar */}
                        <div className="absolute bottom-0 left-0 right-0 flex items-end justify-between px-2 pb-1.5">
                          <div>
                            <div className="text-[11px] font-semibold text-white drop-shadow-sm">{angle.label}</div>
                            {ts && (
                              <div className="text-[9px] text-emerald-300/80 drop-shadow-sm">{timeAgo(ts)}</div>
                            )}
                          </div>
                          <span className="text-[10px] font-semibold text-emerald-300 drop-shadow-sm">
                            {angle.icon}
                          </span>
                        </div>
                      </div>
                    ) : (
                      /* Default empty tile */
                      <div className="px-3 py-3">
                        <div className="flex items-center justify-between">
                          <span className="text-sm">
                            {loading ? <Loader2 size={14} className="animate-spin text-white/60" /> : angle.icon}
                          </span>
                          <span className="text-[10px] font-semibold text-white/35">
                            Generate
                          </span>
                        </div>
                        <div className="mt-2 text-xs font-medium text-white">{angle.label}</div>
                        <div className="mt-0.5 text-[10px] text-white/35">{angle.shortLabel}</div>
                      </div>
                    )}

                    {/* Loading overlay */}
                    {loading && ready && (
                      <div className="absolute inset-0 flex items-center justify-center bg-black/50 backdrop-blur-[2px]">
                        <Loader2 size={18} className="animate-spin text-cyan-300" />
                      </div>
                    )}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="flex gap-2">
            <button
              onClick={onGenerateMissing}
              disabled={busy}
              className={[
                'flex flex-1 items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-xs font-semibold transition-all',
                busy
                  ? 'cursor-wait bg-white/[0.04] text-white/30'
                  : 'bg-gradient-to-r from-cyan-600/90 to-blue-600/90 text-white hover:brightness-110',
              ].join(' ')}
            >
              {busy ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              Generate Missing Views
            </button>
            {hasAnyResults && onClearAll && (
              <button
                onClick={onClearAll}
                disabled={busy}
                title="Clear all cached views"
                className="flex items-center justify-center rounded-xl border border-white/[0.08] bg-white/[0.03] px-3 py-2.5 text-xs text-white/45 transition-all hover:bg-red-500/10 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-35"
              >
                <Trash2 size={14} />
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

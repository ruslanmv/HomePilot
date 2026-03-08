import React, { useCallback, useState } from 'react'
import { ChevronDown, ClipboardCopy, Code2, Loader2, Orbit, Sparkles, Trash2, X } from 'lucide-react'
import type { ViewAngle, ViewPreviewMap, ViewSource, ViewTimestampMap } from './viewPack'
import { buildAnglePrompt, VIEW_ANGLE_OPTIONS } from './viewPack'

interface AvatarViewPackPanelProps {
  open: boolean
  source: ViewSource
  previews: ViewPreviewMap
  timestamps?: ViewTimestampMap
  loadingAngles: Partial<Record<ViewAngle, boolean>>
  busy?: boolean
  disableLatest?: boolean
  disableEquipped?: boolean
  /** The current outfit description used to build angle prompts. */
  outfitPrompt?: string
  onToggle: () => void
  onSourceChange: (value: ViewSource) => void
  onGenerateAngle: (angle: ViewAngle) => void
  onOpenAngle: (angle: ViewAngle) => void
  onDeleteAngle: (angle: ViewAngle) => void
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
  outfitPrompt = '',
  onToggle,
  onSourceChange,
  onGenerateAngle,
  onOpenAngle,
  onDeleteAngle,
  onGenerateMissing,
  onClearAll,
  hasAnyResults = false,
}: AvatarViewPackPanelProps) {
  const readyCount = VIEW_ANGLE_OPTIONS.filter((a) => previews[a.id]).length
  // Track which angle tile has its prompt tooltip expanded
  const [expandedPrompt, setExpandedPrompt] = useState<ViewAngle | null>(null)
  // Flash feedback after copying
  const [copiedAngle, setCopiedAngle] = useState<ViewAngle | null>(null)

  const handleCopyPrompt = useCallback(async (angle: ViewAngle) => {
    const prompt = buildAnglePrompt(angle, outfitPrompt)
    try {
      await navigator.clipboard.writeText(prompt)
    } catch {
      // Fallback for non-secure contexts
      const ta = document.createElement('textarea')
      ta.value = prompt
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    setCopiedAngle(angle)
    setTimeout(() => setCopiedAngle((prev) => (prev === angle ? null : prev)), 1500)
  }, [outfitPrompt])

  const togglePrompt = useCallback((angle: ViewAngle) => {
    setExpandedPrompt((prev) => (prev === angle ? null : angle))
  }, [])

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
                const isPromptExpanded = expandedPrompt === angle.id
                const isCopied = copiedAngle === angle.id

                return (
                  <div
                    key={angle.id}
                    className={[
                      'group relative rounded-xl border text-left transition-all overflow-hidden',
                      ready
                        ? 'border-emerald-500/18 bg-emerald-500/[0.07]'
                        : 'border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06]',
                    ].join(' ')}
                  >
                    {/* Thumbnail preview when ready — click to open in main stage */}
                    {ready && previewUrl ? (
                      <div
                        className="relative h-20 w-full overflow-hidden cursor-pointer"
                        onClick={() => onOpenAngle(angle.id)}
                      >
                        <img
                          src={previewUrl}
                          alt={angle.label}
                          className="h-full w-full object-cover object-top opacity-70 group-hover:opacity-90 transition-opacity"
                        />
                        <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/30 to-transparent" />
                        {/* Bottom info bar — label + timestamp */}
                        <div className="absolute bottom-0 left-0 right-0 flex items-end justify-between px-2 pb-1.5">
                          <div>
                            <div className="text-[11px] font-semibold text-white drop-shadow-sm">{angle.label}</div>
                            {ts && (
                              <div className="text-[9px] text-emerald-300/80 drop-shadow-sm">{timeAgo(ts)}</div>
                            )}
                          </div>
                        </div>
                      </div>
                    ) : (
                      /* Default empty tile — click to generate */
                      <button
                        onClick={() => onGenerateAngle(angle.id)}
                        disabled={loading}
                        className="w-full px-3 py-3 text-left"
                      >
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
                      </button>
                    )}

                    {/* Prompt inspect button — top-right corner, visible on hover */}
                    <button
                      onClick={(e) => { e.stopPropagation(); togglePrompt(angle.id) }}
                      className={[
                        'absolute top-1 right-1 w-5 h-5 rounded-md backdrop-blur-sm border flex items-center justify-center transition-all',
                        isPromptExpanded
                          ? 'bg-cyan-500/30 border-cyan-400/40 text-cyan-200 opacity-100'
                          : 'bg-black/60 border-white/15 text-white/50 opacity-0 group-hover:opacity-100 hover:!text-cyan-200 hover:!bg-cyan-500/20 hover:!border-cyan-400/30',
                      ].join(' ')}
                      title="View prompt"
                    >
                      <Code2 size={10} />
                    </button>

                    {/* Delete button — top-left corner, visible on hover */}
                    {ready && !loading && (
                      <button
                        onClick={(e) => { e.stopPropagation(); onDeleteAngle(angle.id) }}
                        className="absolute top-1 left-1 w-5 h-5 rounded-md bg-black/60 backdrop-blur-sm border border-white/15 flex items-center justify-center text-white/50 opacity-0 group-hover:opacity-100 hover:!text-red-300 hover:!bg-red-500/30 hover:!border-red-500/30 transition-all"
                        title={`Delete ${angle.label}`}
                      >
                        <X size={10} />
                      </button>
                    )}

                    {/* Loading overlay */}
                    {loading && ready && (
                      <div className="absolute inset-0 flex items-center justify-center bg-black/50 backdrop-blur-[2px]">
                        <Loader2 size={18} className="animate-spin text-cyan-300" />
                      </div>
                    )}

                    {/* Expanded prompt panel — below the tile */}
                    {isPromptExpanded && (
                      <div className="border-t border-white/[0.08] bg-black/40 px-2 py-2">
                        <div className="flex items-start justify-between gap-1 mb-1">
                          <span className="text-[9px] font-semibold uppercase tracking-wider text-white/40">Prompt</span>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleCopyPrompt(angle.id) }}
                            className={[
                              'flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-medium transition-all',
                              isCopied
                                ? 'bg-emerald-500/20 text-emerald-300'
                                : 'bg-white/[0.06] text-white/50 hover:bg-white/[0.12] hover:text-white/70',
                            ].join(' ')}
                            title="Copy to clipboard"
                          >
                            <ClipboardCopy size={9} />
                            {isCopied ? 'Copied' : 'Copy'}
                          </button>
                        </div>
                        <div className="max-h-24 overflow-y-auto rounded bg-black/30 px-2 py-1.5 text-[10px] leading-relaxed text-white/60 font-mono select-all">
                          {buildAnglePrompt(angle.id, outfitPrompt)}
                        </div>
                      </div>
                    )}
                  </div>
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

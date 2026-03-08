import React, { useState } from 'react'
import { Check, ChevronDown, Clipboard, Info, Loader2, Orbit, Sparkles, Trash2, X } from 'lucide-react'
import type { AvatarResult } from './types'
import type { ViewAngle, ViewPreviewMap, ViewResultMap, ViewSource, ViewTimestampMap } from './viewPack'
import { VIEW_ANGLE_OPTIONS } from './viewPack'

interface AvatarViewPackPanelProps {
  open: boolean
  source: ViewSource
  previews: ViewPreviewMap
  results?: ViewResultMap
  timestamps?: ViewTimestampMap
  loadingAngles: Partial<Record<ViewAngle, boolean>>
  busy?: boolean
  disableLatest?: boolean
  disableEquipped?: boolean
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

/** Inline prompt detail popover for a generated angle. */
function PromptDetailPopover({ result, label, onClose }: { result: AvatarResult; label: string; onClose: () => void }) {
  const [copied, setCopied] = useState<'positive' | 'negative' | null>(null)
  const prompt = (result.metadata?.view_prompt as string) || (result.metadata?.prompt as string) || ''
  const negative = (result.metadata?.view_negative as string) || ''

  const copyText = async (text: string, which: 'positive' | 'negative') => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(which)
      setTimeout(() => setCopied(null), 1500)
    } catch { /* clipboard not available */ }
  }

  return (
    <div className="absolute inset-0 z-30 flex flex-col bg-black/90 backdrop-blur-sm rounded-xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
      {/* Header */}
      <div className="flex items-center justify-between px-2.5 py-1.5 border-b border-white/10">
        <span className="text-[10px] font-semibold text-cyan-300">{label} Prompt</span>
        <button onClick={onClose} className="w-4 h-4 flex items-center justify-center text-white/50 hover:text-white transition-colors">
          <X size={10} />
        </button>
      </div>
      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto px-2.5 py-2 space-y-2 custom-scrollbar">
        {prompt && (
          <div>
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-[8px] font-semibold uppercase tracking-wider text-emerald-400/70">Positive</span>
              <button
                onClick={() => copyText(prompt, 'positive')}
                className="flex items-center gap-0.5 text-[8px] text-white/40 hover:text-white/70 transition-colors"
                title="Copy positive prompt"
              >
                {copied === 'positive' ? <Check size={8} className="text-emerald-400" /> : <Clipboard size={8} />}
              </button>
            </div>
            <div className="text-[9px] text-white/60 leading-relaxed break-words">{prompt}</div>
          </div>
        )}
        {negative && (
          <div>
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-[8px] font-semibold uppercase tracking-wider text-red-400/70">Negative</span>
              <button
                onClick={() => copyText(negative, 'negative')}
                className="flex items-center gap-0.5 text-[8px] text-white/40 hover:text-white/70 transition-colors"
                title="Copy negative prompt"
              >
                {copied === 'negative' ? <Check size={8} className="text-emerald-400" /> : <Clipboard size={8} />}
              </button>
            </div>
            <div className="text-[9px] text-red-300/50 leading-relaxed break-words">{negative}</div>
          </div>
        )}
        {!prompt && !negative && (
          <div className="text-[9px] text-white/30 italic">No prompt metadata stored for this view.</div>
        )}
      </div>
    </div>
  )
}

export function AvatarViewPackPanel({
  open,
  source,
  previews,
  results = {},
  timestamps = {},
  loadingAngles,
  busy = false,
  disableLatest = false,
  disableEquipped = false,
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
  const [promptDetail, setPromptDetail] = useState<ViewAngle | null>(null)

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
                const result = results[angle.id]
                const showingPrompt = promptDetail === angle.id

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

                    {/* Prompt info button — top-right corner, visible on hover */}
                    {ready && !loading && result && (
                      <button
                        onClick={(e) => { e.stopPropagation(); setPromptDetail(showingPrompt ? null : angle.id) }}
                        className={[
                          'absolute top-1 right-1 w-5 h-5 rounded-md bg-black/60 backdrop-blur-sm border flex items-center justify-center transition-all',
                          showingPrompt
                            ? 'border-cyan-500/40 text-cyan-300 opacity-100'
                            : 'border-white/15 text-white/50 opacity-0 group-hover:opacity-100 hover:!text-cyan-300 hover:!border-cyan-500/30',
                        ].join(' ')}
                        title="View generation prompt"
                      >
                        <Info size={10} />
                      </button>
                    )}

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

                    {/* Prompt detail popover overlay */}
                    {showingPrompt && result && (
                      <PromptDetailPopover
                        result={result}
                        label={angle.label}
                        onClose={() => setPromptDetail(null)}
                      />
                    )}

                    {/* Loading overlay */}
                    {loading && ready && (
                      <div className="absolute inset-0 flex items-center justify-center bg-black/50 backdrop-blur-[2px]">
                        <Loader2 size={18} className="animate-spin text-cyan-300" />
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

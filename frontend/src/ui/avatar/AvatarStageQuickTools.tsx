import React from 'react'
import { Camera, Loader2, PackagePlus } from 'lucide-react'
import type { ViewAngle, ViewPreviewMap } from './viewPack'
import { VIEW_ANGLE_OPTIONS } from './viewPack'

interface AvatarStageQuickToolsProps {
  previews: ViewPreviewMap
  loadingAngles: Partial<Record<ViewAngle, boolean>>
  busy?: boolean
  onGenerateAngle: (angle: ViewAngle) => void
  onOpenAngle: (angle: ViewAngle) => void
  onGenerateMissing: () => void
}

export function AvatarStageQuickTools({
  previews,
  loadingAngles,
  busy = false,
  onGenerateAngle,
  onOpenAngle,
  onGenerateMissing,
}: AvatarStageQuickToolsProps) {
  return (
    <div className="space-y-2 rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">
          <Camera size={12} />
          Quick Views
        </div>
        <button
          onClick={onGenerateMissing}
          disabled={busy}
          className={[
            'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[10px] font-medium transition-all',
            busy
              ? 'cursor-wait border-white/[0.06] bg-white/[0.03] text-white/30'
              : 'border-cyan-500/20 bg-cyan-500/[0.08] text-cyan-200 hover:bg-cyan-500/[0.14]',
          ].join(' ')}
        >
          {busy ? <Loader2 size={11} className="animate-spin" /> : <PackagePlus size={11} />}
          Generate Missing
        </button>
      </div>

      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        {VIEW_ANGLE_OPTIONS.map((angle) => {
          const available = Boolean(previews[angle.id])
          const loading = Boolean(loadingAngles[angle.id])

          return (
            <button
              key={angle.id}
              onClick={() => (available ? onOpenAngle(angle.id) : onGenerateAngle(angle.id))}
              disabled={loading}
              className={[
                'relative rounded-xl border px-2 py-2.5 text-center transition-all',
                available
                  ? 'border-emerald-500/18 bg-emerald-500/[0.07] text-emerald-200 hover:bg-emerald-500/[0.12]'
                  : 'border-white/[0.08] bg-white/[0.03] text-white/65 hover:bg-white/[0.06]',
                loading ? 'cursor-wait opacity-80' : '',
              ].join(' ')}
              title={available ? `Open ${angle.label}` : `Generate ${angle.label}`}
            >
              <div className="mb-1 flex items-center justify-center text-sm">
                {loading ? <Loader2 size={14} className="animate-spin" /> : <span>{angle.icon}</span>}
              </div>
              <div className="text-[10px] font-semibold">{angle.shortLabel}</div>
              <div className="mt-0.5 text-[9px] opacity-60">{available ? 'Ready' : 'Missing'}</div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

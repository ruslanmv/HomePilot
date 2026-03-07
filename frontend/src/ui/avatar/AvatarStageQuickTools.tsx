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
  const missingCount = VIEW_ANGLE_OPTIONS.filter((a) => !previews[a.id]).length

  return (
    <div className="flex items-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.02] px-2 py-1.5">
      <Camera size={11} className="text-white/30 flex-shrink-0" />

      {VIEW_ANGLE_OPTIONS.map((angle) => {
        const available = Boolean(previews[angle.id])
        const loading = Boolean(loadingAngles[angle.id])

        return (
          <button
            key={angle.id}
            onClick={() => (available ? onOpenAngle(angle.id) : onGenerateAngle(angle.id))}
            disabled={loading}
            className={[
              'flex items-center justify-center w-7 h-7 rounded-md text-[10px] font-bold transition-all',
              available
                ? 'bg-emerald-500/[0.12] text-emerald-300 border border-emerald-500/20 hover:bg-emerald-500/[0.20]'
                : 'bg-white/[0.04] text-white/40 border border-white/[0.08] hover:bg-white/[0.08] hover:text-white/60',
              loading ? 'cursor-wait opacity-60' : '',
            ].join(' ')}
            title={available ? `View ${angle.label}` : `Generate ${angle.label}`}
          >
            {loading ? <Loader2 size={10} className="animate-spin" /> : angle.shortLabel}
          </button>
        )
      })}

      {missingCount > 0 && (
        <button
          onClick={onGenerateMissing}
          disabled={busy}
          className={[
            'ml-auto flex items-center gap-1 rounded-md border px-2 py-1 text-[9px] font-semibold transition-all flex-shrink-0',
            busy
              ? 'cursor-wait border-white/[0.06] bg-white/[0.03] text-white/25'
              : 'border-cyan-500/20 bg-cyan-500/[0.08] text-cyan-300 hover:bg-cyan-500/[0.14]',
          ].join(' ')}
        >
          {busy ? <Loader2 size={9} className="animate-spin" /> : <PackagePlus size={9} />}
          {missingCount}
        </button>
      )}
    </div>
  )
}

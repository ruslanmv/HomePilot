/**
 * ActionFeedback - Toast notification for completed actions.
 *
 * Shows non-intrusive confirmation when actions complete,
 * including version info and quick action buttons.
 */

import React, { useEffect, useState } from 'react'
import { CheckCircle, Eye, RotateCcw, X, Download } from 'lucide-react'
import { resolveFileUrl } from '../resolveFileUrl'

export interface ActionFeedbackProps {
  /** Action that was performed (e.g., "Enhanced", "BG Removed") */
  action: string
  /** Version number or identifier */
  version?: number | string
  /** Additional details (e.g., "Strength 15") */
  details?: string
  /** URL to the result image */
  resultUrl?: string
  /** Callback to view the result */
  onView?: () => void
  /** Callback to undo/revert */
  onUndo?: () => void
  /** Auto-dismiss after milliseconds (0 = no auto-dismiss) */
  autoDismiss?: number
  /** Callback when dismissed */
  onDismiss?: () => void
}

/**
 * ActionFeedback component shows a small toast notification
 * after an action completes successfully.
 *
 * @example
 * ```tsx
 * <ActionFeedback
 *   action="Blur BG"
 *   version={7}
 *   details="Strength 15"
 *   resultUrl={resultImage}
 *   onView={() => setActiveImage(resultImage)}
 *   onUndo={handleUndo}
 *   autoDismiss={5000}
 *   onDismiss={() => setShowFeedback(false)}
 * />
 * ```
 */
export function ActionFeedback({
  action,
  version,
  details,
  resultUrl,
  onView,
  onUndo,
  autoDismiss = 5000,
  onDismiss,
}: ActionFeedbackProps) {
  const [visible, setVisible] = useState(true)
  const [progress, setProgress] = useState(100)

  useEffect(() => {
    if (autoDismiss <= 0) return

    // Animate progress bar
    const startTime = Date.now()
    const interval = setInterval(() => {
      const elapsed = Date.now() - startTime
      const remaining = Math.max(0, 100 - (elapsed / autoDismiss) * 100)
      setProgress(remaining)

      if (remaining === 0) {
        clearInterval(interval)
        handleDismiss()
      }
    }, 50)

    return () => clearInterval(interval)
  }, [autoDismiss])

  const handleDismiss = () => {
    setVisible(false)
    setTimeout(() => onDismiss?.(), 200) // Allow exit animation
  }

  if (!visible) {
    return null
  }

  return (
    <div
      className={`
        fixed bottom-24 left-1/2 -translate-x-1/2 z-50
        flex items-center gap-3 px-4 py-3
        bg-green-950/90 border border-green-500/30
        rounded-xl backdrop-blur-xl shadow-2xl
        animate-in slide-in-from-bottom-5 fade-in duration-300
        ${!visible ? 'animate-out slide-out-to-bottom-5 fade-out duration-200' : ''}
      `}
    >
      {/* Progress bar at top */}
      {autoDismiss > 0 && (
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-green-900/50 rounded-t-xl overflow-hidden">
          <div
            className="h-full bg-green-500 transition-all duration-50"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}

      {/* Thumbnail */}
      {resultUrl && (
        <div className="w-12 h-12 rounded-lg overflow-hidden bg-white/10 shrink-0">
          <img src={resolveFileUrl(resultUrl)} alt="Result" className="w-full h-full object-cover" />
        </div>
      )}

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 text-green-300">
          <CheckCircle size={14} />
          <span className="font-medium text-sm">
            {version ? `v${version}` : ''} {action}
          </span>
        </div>
        {details && (
          <div className="text-[10px] text-green-400/60 mt-0.5">
            {details}
          </div>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-1.5">
        {onView && (
          <button
            onClick={() => { onView(); handleDismiss(); }}
            className="p-1.5 rounded-lg bg-green-500/20 text-green-300 hover:bg-green-500/30 transition-colors"
            title="View"
          >
            <Eye size={14} />
          </button>
        )}
        {resultUrl && (
          <a
            href={resultUrl}
            download
            className="p-1.5 rounded-lg bg-green-500/20 text-green-300 hover:bg-green-500/30 transition-colors"
            title="Download"
          >
            <Download size={14} />
          </a>
        )}
        {onUndo && (
          <button
            onClick={() => { onUndo(); handleDismiss(); }}
            className="p-1.5 rounded-lg bg-white/10 text-white/60 hover:bg-white/20 transition-colors"
            title="Undo"
          >
            <RotateCcw size={14} />
          </button>
        )}
        <button
          onClick={handleDismiss}
          className="p-1.5 rounded-lg text-white/40 hover:text-white/60 transition-colors"
          title="Dismiss"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  )
}

export default ActionFeedback

/**
 * ConfirmForgetDialog — AWS-style confirmation for destructive memory actions.
 *
 * The user must type the persona name exactly to enable the confirm button.
 * This prevents accidental deletions while keeping the UX lightweight
 * (no password re-entry needed).
 *
 * Used for:
 *  - Forgetting a single memory
 *  - Forgetting ALL memories for a persona
 *
 * Safety: memories are deleted, the persona itself is NEVER deleted.
 */
import React, { useState, useRef, useEffect } from 'react'
import { AlertTriangle, Brain, X } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ConfirmForgetDialogProps {
  /** What we're confirming — drives the copy & styling */
  mode: 'single' | 'all'
  /** Persona display name — user must type this to confirm */
  personaName: string
  /** How many memories will be deleted (shown in "all" mode) */
  memoryCount?: number
  /** Description of the single memory being deleted */
  memoryLabel?: string
  /** Category of the single memory */
  memoryCategory?: string
  /** Called when user confirms the deletion */
  onConfirm: () => void
  /** Called when user cancels */
  onCancel: () => void
  /** Show loading spinner on the confirm button */
  loading?: boolean
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ConfirmForgetDialog({
  mode,
  personaName,
  memoryCount = 0,
  memoryLabel,
  memoryCategory,
  onConfirm,
  onCancel,
  loading = false,
}: ConfirmForgetDialogProps) {
  const [typed, setTyped] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // Auto-focus the input on mount
  useEffect(() => {
    const t = setTimeout(() => inputRef.current?.focus(), 80)
    return () => clearTimeout(t)
  }, [])

  const nameMatches = typed.trim().toLowerCase() === personaName.trim().toLowerCase()
  const canConfirm = nameMatches && !loading

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && canConfirm) onConfirm()
    if (e.key === 'Escape') onCancel()
  }

  return (
    <div
      className="fixed inset-0 z-[250] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onCancel() }}
    >
      <div
        className="w-full max-w-md rounded-3xl border border-white/10 bg-[#0b0b0b] shadow-2xl shadow-black/40 overflow-hidden animate-[fadeIn_200ms_ease-out]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {mode === 'all' ? (
              <div className="w-9 h-9 rounded-xl bg-red-500/10 border border-red-500/20 flex items-center justify-center">
                <Brain size={18} className="text-red-400" />
              </div>
            ) : (
              <div className="w-9 h-9 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center">
                <AlertTriangle size={18} className="text-amber-400" />
              </div>
            )}
            <div>
              <div className="text-white/90 font-semibold text-sm">
                {mode === 'all' ? 'Forget All Memories?' : 'Forget This Memory?'}
              </div>
              <div className="text-[11px] text-white/40">
                This action cannot be undone
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="p-2 rounded-xl hover:bg-white/5 text-white/40 hover:text-white/70 transition-all"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          {/* What's being deleted */}
          {mode === 'single' && memoryLabel && (
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              <div className="text-sm text-white/85 leading-relaxed">
                &ldquo;{memoryLabel}&rdquo;
              </div>
              {memoryCategory && (
                <div className="text-[11px] text-white/40 mt-1">
                  category: {memoryCategory}
                </div>
              )}
            </div>
          )}

          {mode === 'all' && (
            <div className="rounded-2xl border border-red-500/15 bg-red-500/5 px-4 py-3 space-y-1">
              <div className="text-sm text-red-300/90">
                This will erase{' '}
                <span className="font-semibold text-red-300">
                  {memoryCount === 1 ? '1 memory' : `all ${memoryCount} memories`}
                </span>{' '}
                stored for <span className="font-semibold text-red-300">{personaName}</span>.
              </div>
              <div className="text-[11px] text-white/40">
                The persona itself will NOT be deleted — only memories will be cleared.
              </div>
            </div>
          )}

          {mode === 'single' && (
            <div className="text-[12px] text-white/50 leading-relaxed">
              This memory will be permanently removed from{' '}
              <span className="text-white/70 font-medium">{personaName}</span>.
              The persona itself will not be affected.
            </div>
          )}

          {/* Type-to-confirm input */}
          <div className="space-y-2">
            <label className="text-[12px] text-white/50">
              Type <span className="text-white/80 font-semibold">{personaName}</span> to confirm
            </label>
            <input
              ref={inputRef}
              type="text"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={personaName}
              className={[
                'w-full px-4 py-3 rounded-2xl border text-sm text-white outline-none transition-all',
                'bg-white/5 placeholder:text-white/15',
                nameMatches
                  ? 'border-green-500/30 bg-green-500/5'
                  : 'border-white/10 focus:border-white/20',
              ].join(' ')}
              autoComplete="off"
              spellCheck={false}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-white/10 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2.5 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-sm text-white/70 transition-all"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!canConfirm}
            className={[
              'px-5 py-2.5 rounded-2xl border text-sm font-semibold transition-all',
              canConfirm
                ? 'bg-red-500/15 hover:bg-red-500/25 border-red-500/25 hover:border-red-500/40 text-red-400 cursor-pointer'
                : 'bg-white/5 border-white/10 text-white/25 cursor-not-allowed',
            ].join(' ')}
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <span className="w-3.5 h-3.5 border-2 border-red-400/30 border-t-red-400 rounded-full animate-spin" />
                Forgetting...
              </span>
            ) : mode === 'all' ? (
              `Forget All (${memoryCount})`
            ) : (
              'Forget Memory'
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * IdentityTools - Optional identity-aware edit buttons for Edit Studio.
 *
 * Additive + non-destructive:
 *   - Only rendered when avatar identity models are installed
 *   - Does NOT replace or modify existing Quick Enhance / Background tools
 *   - Controlled by parent via `show` / capability booleans
 *
 * Basic Pack (InsightFace + InstantID):
 *   - Fix Faces+ (identity-aware face restoration)
 *   - Inpaint (Preserve Person)
 *   - Change BG (Preserve Person)
 *
 * Full Pack (+ InSwapper):
 *   - Face Swap
 */

import React, { useState } from 'react'
import { Loader2, UserCheck, Scan, ImageOff, Repeat, Shield } from 'lucide-react'
import {
  applyIdentityTool,
  IDENTITY_TOOLS,
  type IdentityToolType,
} from '../enhance/identityApi'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface IdentityToolsProps {
  backendUrl: string
  apiKey?: string
  imageUrl: string | null
  onResult: (resultUrl: string, toolType: IdentityToolType) => void
  onError: (error: string) => void
  disabled?: boolean
  /** Basic identity models installed (AntelopeV2 + InstantID) */
  hasBasicIdentity: boolean
  /** Face swap model installed (InSwapper) */
  hasFaceSwap: boolean
  /** Optional mask data URL for inpaint_identity */
  maskDataUrl?: string | null
}

// ---------------------------------------------------------------------------
// Icon map
// ---------------------------------------------------------------------------

function getIcon(id: IdentityToolType) {
  switch (id) {
    case 'fix_faces_identity':
      return <UserCheck size={18} className="text-cyan-400" />
    case 'inpaint_identity':
      return <Scan size={18} className="text-cyan-400" />
    case 'change_bg_identity':
      return <ImageOff size={18} className="text-cyan-400" />
    case 'face_swap':
      return <Repeat size={18} className="text-cyan-400" />
    default:
      return <Shield size={18} className="text-cyan-400" />
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function IdentityTools({
  backendUrl,
  apiKey,
  imageUrl,
  onResult,
  onError,
  disabled = false,
  hasBasicIdentity,
  hasFaceSwap,
  maskDataUrl,
}: IdentityToolsProps) {
  const [loading, setLoading] = useState<IdentityToolType | null>(null)

  // Don't render at all if no identity models installed
  if (!hasBasicIdentity) return null

  const anyLoading = loading !== null
  const isDisabled = disabled || !imageUrl

  const handleTool = async (toolType: IdentityToolType) => {
    if (!imageUrl || anyLoading || isDisabled) return

    setLoading(toolType)
    try {
      const result = await applyIdentityTool({
        backendUrl,
        apiKey,
        imageUrl,
        toolType,
        maskDataUrl: toolType === 'inpaint_identity' && maskDataUrl ? maskDataUrl : undefined,
      })

      const resultUrl = result?.media?.images?.[0]
      if (resultUrl) {
        onResult(resultUrl, toolType)
      } else {
        onError('Identity tool completed but no image was returned.')
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Identity tool failed')
    } finally {
      setLoading(null)
    }
  }

  // Filter visible tools based on installed models
  const visibleTools = IDENTITY_TOOLS.filter((tool) => {
    if (tool.pack === 'full') return hasFaceSwap
    return true // basic pack tools always visible when hasBasicIdentity
  })

  return (
    <div className="space-y-3">
      {/* Section header */}
      <div className="text-xs uppercase tracking-wider text-white/40 font-semibold flex items-center gap-2">
        <Shield size={14} />
        Identity Tools
        <span className="text-[8px] px-1.5 py-0.5 rounded-full bg-cyan-500/15 border border-cyan-500/20 text-cyan-300/60 font-medium normal-case tracking-normal">
          Beta
        </span>
      </div>

      <p className="text-[10px] text-white/25 leading-relaxed -mt-1">
        Edit while preserving facial identity. Uses installed Avatar &amp; Identity models.
      </p>

      {/* Tool buttons */}
      <div className="grid grid-cols-1 gap-2">
        {visibleTools.map((tool) => (
          <button
            key={tool.id}
            onClick={() => handleTool(tool.id)}
            disabled={isDisabled || anyLoading}
            className={`
              w-full flex items-center gap-3 p-3 rounded-xl border transition-all text-left
              ${loading === tool.id
                ? 'bg-cyan-500/20 border-cyan-500/40 text-cyan-300'
                : isDisabled || anyLoading
                  ? 'bg-white/5 border-white/5 text-white/30 cursor-not-allowed'
                  : 'bg-white/5 border-white/10 text-white/80 hover:bg-cyan-500/10 hover:border-cyan-500/30 hover:text-cyan-200'
              }
            `}
          >
            <div className={`
              w-9 h-9 rounded-lg flex items-center justify-center
              ${loading === tool.id ? 'bg-cyan-500/30' : 'bg-white/10'}
            `}>
              {loading === tool.id ? (
                <Loader2 size={18} className="animate-spin text-cyan-400" />
              ) : (
                getIcon(tool.id)
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium flex items-center gap-2">
                {tool.label}
                <span className="text-[9px] px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-300/40">
                  {tool.pack === 'full' ? 'Full Pack' : 'Identity'}
                </span>
              </div>
              <div className="text-[10px] text-white/40 truncate">
                {tool.description}
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

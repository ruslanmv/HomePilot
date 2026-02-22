/**
 * SaveAsPersonaModal — lightweight modal for saving an avatar as a Persona.
 *
 * Additive component — does not modify PersonaWizard or any existing code.
 *
 * Two paths:
 *   1. "Quick Create" — creates a Custom persona project immediately
 *   2. "Open in Wizard" — opens PersonaWizard with pre-filled draft (full customization)
 */

import React, { useState, useCallback, useMemo } from 'react'
import { X, Sparkles, User, Loader2, ChevronRight, Shirt, Camera } from 'lucide-react'
import type { GalleryItem } from './galleryTypes'
import type { PersonaClassId, PersonaWizardDraft } from '../personaTypes'
import { PERSONA_BLUEPRINTS } from '../personaTypes'
import { draftFromGalleryItem, getVisibleBlueprints } from './personaBridge'
import { createPersonaProject } from '../personaApi'
import { resolveFileUrl } from '../resolveFileUrl'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface SaveAsPersonaModalProps {
  item: GalleryItem
  /** Outfit gallery items belonging to this character (parentId match) */
  outfitItems?: GalleryItem[]
  /** Sibling images from the same generation batch (included as extra portraits) */
  batchSiblings?: GalleryItem[]
  backendUrl: string
  apiKey?: string
  onClose: () => void
  /** Open PersonaWizard with pre-filled draft for full customization */
  onOpenWizard: (draft: PersonaWizardDraft) => void
  /** Called after quick-create succeeds */
  onCreated?: (project: any) => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveUrl(url: string, backendUrl: string): string {
  return resolveFileUrl(url, backendUrl)
}

function readNsfwMode(): boolean {
  try {
    return localStorage.getItem('homepilot_nsfw_mode') === 'true'
  } catch {
    return false
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SaveAsPersonaModal({
  item,
  outfitItems,
  batchSiblings,
  backendUrl,
  apiKey,
  onClose,
  onOpenWizard,
  onCreated,
}: SaveAsPersonaModalProps) {
  const [name, setName] = useState('')
  const [classId, setClassId] = useState<PersonaClassId>('custom')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isSpicy = readNsfwMode()
  const blueprints = useMemo(() => getVisibleBlueprints(isSpicy), [isSpicy])

  const imgUrl = resolveUrl(item.url, backendUrl)

  const handleOpenWizard = useCallback(() => {
    const draft = draftFromGalleryItem(item, name.trim() || 'My Persona', classId, outfitItems, batchSiblings)
    onOpenWizard(draft)
  }, [item, name, classId, outfitItems, batchSiblings, onOpenWizard])

  const handleQuickCreate = useCallback(async () => {
    if (!name.trim()) return
    setSaving(true)
    setError(null)

    try {
      const draft = draftFromGalleryItem(item, name.trim(), classId, outfitItems, batchSiblings)
      const result = await createPersonaProject({
        backendUrl,
        apiKey,
        name: name.trim(),
        persona_agent: draft.persona_agent,
        persona_appearance: draft.persona_appearance as Record<string, unknown>,
        agentic: draft.agentic as Record<string, unknown>,
      })
      onCreated?.(result.project || result)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create persona')
    } finally {
      setSaving(false)
    }
  }, [item, name, classId, outfitItems, batchSiblings, backendUrl, apiKey, onCreated, onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-md mx-4 rounded-2xl border border-white/10 bg-[#0a0a0a] shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/5">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-emerald-500 to-cyan-500 flex items-center justify-center">
              <User size={18} className="text-white" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-white">Save as Persona Avatar</h3>
              <p className="text-[10px] text-white/40 mt-0.5">Create a persona with this avatar</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-white/30 hover:text-white/60 hover:bg-white/5 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          {/* Avatar preview */}
          <div className="flex items-center gap-4">
            <div className="w-20 h-20 rounded-xl overflow-hidden border border-white/10 flex-shrink-0">
              <img src={imgUrl} alt="Avatar preview" className="w-full h-full object-cover" />
            </div>
            <div className="text-xs text-white/30 space-y-1">
              {item.seed !== undefined && <div className="font-mono">Seed: {item.seed}</div>}
              {item.prompt && <div className="truncate max-w-[200px]">{item.prompt}</div>}
              <div className="text-white/20">Mode: {item.mode}</div>
              {batchSiblings && batchSiblings.length > 0 && (
                <div className="flex items-center gap-1 text-pink-400/70">
                  <Camera size={11} />
                  {batchSiblings.length + 1} portrait{batchSiblings.length > 0 ? 's' : ''} included
                </div>
              )}
              {outfitItems && outfitItems.length > 0 && (
                <div className="flex items-center gap-1 text-cyan-400/70">
                  <Shirt size={11} />
                  {outfitItems.length} outfit{outfitItems.length !== 1 ? 's' : ''} included
                </div>
              )}
            </div>
          </div>

          {/* Name input */}
          <div>
            <label className="text-xs text-white/40 font-medium uppercase tracking-wider block mb-1.5">
              Persona Name
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Elena, Assistant, Maya..."
              autoFocus
              className="w-full px-3 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder:text-white/25 focus:outline-none focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/20 transition-all"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && name.trim()) handleQuickCreate()
              }}
            />
          </div>

          {/* Class selector */}
          <div>
            <label className="text-xs text-white/40 font-medium uppercase tracking-wider block mb-1.5">
              Persona Class
            </label>
            <div className="flex flex-wrap gap-1.5">
              {blueprints.map((bp) => (
                <button
                  key={bp.id}
                  onClick={() => setClassId(bp.id)}
                  className={`px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                    classId === bp.id
                      ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                      : 'border-white/8 bg-white/[0.03] text-white/50 hover:bg-white/5 hover:text-white/70'
                  }`}
                >
                  <span className="mr-1">{bp.icon}</span>
                  {bp.label}
                </button>
              ))}
            </div>
          </div>

          {/* Error */}
          {error && (
            <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-white/5 flex items-center justify-between gap-3">
          <button
            onClick={handleOpenWizard}
            className="flex items-center gap-2 px-4 py-2 rounded-xl border border-white/10 bg-white/5 text-white/70 text-sm hover:bg-white/8 hover:text-white transition-all"
          >
            <Sparkles size={14} />
            Open in Wizard
            <ChevronRight size={14} className="text-white/30" />
          </button>
          <button
            onClick={handleQuickCreate}
            disabled={!name.trim() || saving}
            className={`flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-semibold transition-all ${
              name.trim() && !saving
                ? 'bg-gradient-to-r from-emerald-600 to-cyan-600 text-white shadow-lg shadow-emerald-500/20 hover:shadow-emerald-500/30 hover:scale-[1.02] active:scale-[0.98]'
                : 'bg-white/5 text-white/25 cursor-not-allowed'
            }`}
          >
            {saving ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                Creating...
              </>
            ) : (
              'Quick Create'
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

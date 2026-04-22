/**
 * SaveAsPersonaModal — lightweight modal for saving an avatar as a Persona.
 *
 * Additive component — does not modify PersonaWizard or any existing code.
 *
 * Two paths:
 *   1. "Quick Create" — creates a Custom persona project immediately
 *   2. "Open in Wizard" — opens PersonaWizard with pre-filled draft (full customization)
 */
import React, { useState, useCallback, useMemo } from 'react';
import { X, Sparkles, User, Loader2, ChevronRight, Shirt, Camera, RotateCcw } from 'lucide-react';
import { draftFromGalleryItem, getVisibleBlueprints, professionToPersonaClass } from './personaBridge';
import { createPersonaProject } from '../personaApi';
import { resolveFileUrl } from '../resolveFileUrl';
// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function resolveUrl(url, backendUrl) {
    return resolveFileUrl(url, backendUrl);
}
function readNsfwMode() {
    try {
        return localStorage.getItem('homepilot_nsfw_mode') === 'true';
    }
    catch {
        return false;
    }
}
// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function SaveAsPersonaModal({ item, outfitItems, batchSiblings, backendUrl, apiKey, onClose, onOpenWizard, onCreated, }) {
    const [name, setName] = useState('');
    // Auto-select persona class from wizard profession if available
    const [classId, setClassId] = useState(() => item.wizardMeta?.professionId ? professionToPersonaClass(item.wizardMeta.professionId) : 'custom');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);
    const isSpicy = readNsfwMode();
    const blueprints = useMemo(() => getVisibleBlueprints(isSpicy), [isSpicy]);
    const imgUrl = resolveUrl(item.url, backendUrl);
    // Count outfits that have 3D angle views (view_pack with at least 2 angles)
    const outfits3dCount = useMemo(() => {
        if (!outfitItems)
            return 0;
        return outfitItems.filter((oi) => {
            // Check GalleryItem.view_pack field
            if (oi.view_pack && Object.keys(oi.view_pack).length >= 2)
                return true;
            // Fallback: check localStorage cache
            try {
                const raw = localStorage.getItem(`hp_viewpack_${oi.id}`);
                if (raw) {
                    const parsed = JSON.parse(raw);
                    const results = parsed?.results ?? parsed;
                    if (results && typeof results === 'object') {
                        const count = ['front', 'left', 'right', 'back'].filter((a) => results[a]?.url).length;
                        return count >= 2;
                    }
                }
            }
            catch { /* ignore */ }
            return false;
        }).length;
    }, [outfitItems]);
    const handleOpenWizard = useCallback(() => {
        const draft = draftFromGalleryItem(item, name.trim() || 'My Persona', classId, outfitItems, batchSiblings);
        onOpenWizard(draft);
    }, [item, name, classId, outfitItems, batchSiblings, onOpenWizard]);
    const handleQuickCreate = useCallback(async () => {
        if (!name.trim())
            return;
        setSaving(true);
        setError(null);
        try {
            const draft = draftFromGalleryItem(item, name.trim(), classId, outfitItems, batchSiblings);
            const description = draft.persona_agent.role || item.wizardMeta?.professionDescription || '';
            const result = await createPersonaProject({
                backendUrl,
                apiKey,
                name: name.trim(),
                description,
                persona_agent: {
                    ...draft.persona_agent,
                    persona_class: draft.persona_class,
                    memory_mode: draft.memory_mode,
                },
                persona_appearance: draft.persona_appearance,
                agentic: draft.agentic,
            });
            onCreated?.(result.project || result);
            onClose();
        }
        catch (e) {
            setError(e instanceof Error ? e.message : 'Failed to create persona');
        }
        finally {
            setSaving(false);
        }
    }, [item, name, classId, outfitItems, batchSiblings, backendUrl, apiKey, onCreated, onClose]);
    return (<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm" onClick={(e) => { if (e.target === e.currentTarget)
        onClose(); }}>
      <div className="w-full max-w-md mx-4 rounded-2xl border border-white/10 bg-[#0a0a0a] shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/5">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-emerald-500 to-cyan-500 flex items-center justify-center">
              <User size={18} className="text-white"/>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-white">Export to Persona</h3>
              <p className="text-[10px] text-white/40 mt-0.5">Create a persona with this avatar</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-white/30 hover:text-white/60 hover:bg-white/5 transition-colors">
            <X size={18}/>
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          {/* Avatar preview */}
          <div className="flex items-center gap-4">
            <div className="w-20 h-20 rounded-xl overflow-hidden border border-white/10 flex-shrink-0">
              <img src={imgUrl} alt="Avatar preview" className="w-full h-full object-cover"/>
            </div>
            <div className="text-xs text-white/30 space-y-1">
              {item.seed !== undefined && <div className="font-mono">Seed: {item.seed}</div>}
              {item.prompt && <div className="truncate max-w-[200px]">{item.prompt}</div>}
              <div className="text-white/20">Mode: {item.mode}</div>
              {batchSiblings && batchSiblings.length > 0 && (<div className="flex items-center gap-1 text-pink-400/70">
                  <Camera size={11}/>
                  {batchSiblings.length + 1} portrait{batchSiblings.length > 0 ? 's' : ''} included
                </div>)}
              {outfitItems && outfitItems.length > 0 && (<div className="flex items-center gap-1 text-purple-400/70">
                  <Shirt size={11}/>
                  {outfitItems.length} outfit{outfitItems.length !== 1 ? 's' : ''} included
                  {outfits3dCount > 0 && (<span className="inline-flex items-center gap-0.5 ml-1 px-1.5 py-0 rounded-full bg-cyan-500/15 border border-cyan-500/20 text-cyan-300/80 text-[9px] font-medium">
                      <RotateCcw size={8}/> {outfits3dCount} 360°
                    </span>)}
                </div>)}
            </div>
          </div>

          {/* Wizard profession info (if available) */}
          {item.wizardMeta?.professionLabel && (<div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-3 space-y-1">
              <div className="text-[9px] text-white/25 font-medium uppercase tracking-wider">From Avatar Wizard</div>
              <div className="text-xs text-white/60 font-medium">{item.wizardMeta.professionLabel}</div>
              {item.wizardMeta.professionDescription && (<div className="text-[10px] text-white/30">{item.wizardMeta.professionDescription}</div>)}
              {item.wizardMeta.tone && (<div className="text-[10px] text-white/20">Tone: {item.wizardMeta.tone}</div>)}
            </div>)}

          {/* Name input */}
          <div>
            <label className="text-xs text-white/40 font-medium uppercase tracking-wider block mb-1.5">
              Persona Name
            </label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Elena, Assistant, Maya..." autoFocus className="w-full px-3 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder:text-white/25 focus:outline-none focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/20 transition-all" onKeyDown={(e) => {
            if (e.key === 'Enter' && name.trim())
                handleQuickCreate();
        }}/>
          </div>

          {/* Class selector */}
          <div>
            <label className="text-xs text-white/40 font-medium uppercase tracking-wider block mb-1.5">
              Persona Class
            </label>
            <div className="flex flex-wrap gap-1.5">
              {blueprints.map((bp) => (<button key={bp.id} onClick={() => setClassId(bp.id)} className={`px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-all ${classId === bp.id
                ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                : 'border-white/8 bg-white/[0.03] text-white/50 hover:bg-white/5 hover:text-white/70'}`}>
                  <span className="mr-1">{bp.icon}</span>
                  {bp.label}
                </button>))}
            </div>
          </div>

          {/* Error */}
          {error && (<div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
              {error}
            </div>)}
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-white/5 flex items-center justify-between gap-3">
          <button onClick={handleOpenWizard} className="flex items-center gap-2 px-4 py-2 rounded-xl border border-white/10 bg-white/5 text-white/70 text-sm hover:bg-white/8 hover:text-white transition-all">
            <Sparkles size={14}/>
            Open in Wizard
            <ChevronRight size={14} className="text-white/30"/>
          </button>
          <button onClick={handleQuickCreate} disabled={!name.trim() || saving} className={`flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-semibold transition-all ${name.trim() && !saving
            ? 'bg-gradient-to-r from-emerald-600 to-cyan-600 text-white shadow-lg shadow-emerald-500/20 hover:shadow-emerald-500/30 hover:scale-[1.02] active:scale-[0.98]'
            : 'bg-white/5 text-white/25 cursor-not-allowed'}`}>
            {saving ? (<>
                <Loader2 size={14} className="animate-spin"/>
                Creating...
              </>) : ('Quick Create')}
          </button>
        </div>
      </div>
    </div>);
}

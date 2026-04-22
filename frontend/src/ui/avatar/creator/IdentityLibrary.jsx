/**
 * IdentityLibrary — Left-panel section showing character identities for the
 * current wizard session.
 *
 * Only shows identities that were:
 *   1. Created during this wizard session (sessionIds)
 *   2. Imported from the full library (importedIds)
 *
 * An "Import from Library" picker lets users bring in pre-existing identities
 * without cluttering the view with every identity ever created.
 */
import React, { useState } from 'react';
import { Plus, Download, X, Sparkles } from 'lucide-react';
// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function IdentityLibrary({ items, sessionIds, importedIds, activeIdentityId, onSelectIdentity, onNewIdentity, onImportIdentity, resolveUrl, }) {
    const [showPicker, setShowPicker] = useState(false);
    // All root identities from the full gallery
    const allIdentities = items.filter((i) => i.role === 'anchor' && !i.parentId);
    // Session-scoped: created here + imported
    const visibleIds = new Set([...sessionIds, ...importedIds]);
    const sessionIdentities = allIdentities.filter((i) => visibleIds.has(i.id));
    // Library identities available for import (not already visible)
    const libraryIdentities = allIdentities.filter((i) => !visibleIds.has(i.id));
    return (<div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Sparkles size={10} className="text-purple-400/60"/>
          <span className="text-[9px] text-white/35 font-semibold uppercase tracking-wider">
            My Identities
          </span>
        </div>
        <span className="text-[9px] text-white/20">{sessionIdentities.length}</span>
      </div>

      <div className="grid grid-cols-3 gap-1.5">
        {sessionIdentities.slice(0, 9).map((identity) => {
            const active = activeIdentityId === identity.id;
            const isImported = importedIds.has(identity.id);
            return (<button key={identity.id} onClick={() => onSelectIdentity(identity)} className={[
                    'relative aspect-square rounded-lg overflow-hidden border-2 transition-all group',
                    active
                        ? 'border-purple-500/60 ring-1 ring-purple-500/20 scale-105'
                        : 'border-white/[0.08] hover:border-white/20 hover:scale-105',
                ].join(' ')} title={identity.wizardMeta?.professionLabel || `Seed ${identity.seed ?? '?'}`}>
              <img src={resolveUrl(identity.url)} alt={identity.wizardMeta?.professionLabel || 'Identity'} className="w-full h-full object-cover" loading="lazy"/>
              {/* Seed overlay on hover */}
              <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end justify-center pb-1">
                <span className="text-[8px] text-white/70 font-mono">
                  {identity.seed ?? '—'}
                </span>
              </div>
              {/* Imported badge */}
              {isImported && (<div className="absolute top-0.5 left-0.5">
                  <Download size={8} className="text-cyan-400/80"/>
                </div>)}
              {/* Active indicator */}
              {active && (<div className="absolute top-0.5 right-0.5 w-2 h-2 rounded-full bg-purple-400 shadow-[0_0_4px_rgba(168,85,247,0.6)]"/>)}
            </button>);
        })}

        {/* New identity slot */}
        <button onClick={onNewIdentity} className="aspect-square rounded-lg border-2 border-dashed border-white/[0.08] hover:border-white/15 flex items-center justify-center transition-colors group" title="Create new identity">
          <Plus size={14} className="text-white/15 group-hover:text-white/35 transition-colors"/>
        </button>
      </div>

      {sessionIdentities.length === 0 && (<p className="text-[10px] text-white/15 text-center py-2">
          No identities yet
        </p>)}

      {/* Import from Library button */}
      {libraryIdentities.length > 0 && (<button onClick={() => setShowPicker(!showPicker)} className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg text-[9px] font-medium text-cyan-400/60 hover:text-cyan-300/80 hover:bg-cyan-500/[0.06] border border-cyan-500/10 hover:border-cyan-500/20 transition-all">
          <Download size={10}/>
          Import from Library ({libraryIdentities.length})
        </button>)}

      {/* Library Picker Overlay */}
      {showPicker && (<div className="rounded-xl border border-white/[0.08] bg-black/60 backdrop-blur-sm p-2 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[9px] text-white/40 font-semibold uppercase tracking-wider">
              Library
            </span>
            <button onClick={() => setShowPicker(false)} className="text-white/25 hover:text-white/50 transition-colors">
              <X size={12}/>
            </button>
          </div>
          <div className="grid grid-cols-3 gap-1.5 max-h-[120px] overflow-y-auto scrollbar-hide">
            {libraryIdentities.map((identity) => (<button key={identity.id} onClick={() => {
                    onImportIdentity(identity);
                    setShowPicker(false);
                }} className="relative aspect-square rounded-lg overflow-hidden border-2 border-white/[0.06] hover:border-cyan-500/40 transition-all group" title={identity.wizardMeta?.professionLabel || `Seed ${identity.seed ?? '?'}`}>
                <img src={resolveUrl(identity.url)} alt={identity.wizardMeta?.professionLabel || 'Identity'} className="w-full h-full object-cover" loading="lazy"/>
                <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end justify-center pb-1">
                  <span className="text-[8px] text-white/70 font-mono">
                    {identity.seed ?? '—'}
                  </span>
                </div>
              </button>))}
          </div>
        </div>)}
    </div>);
}

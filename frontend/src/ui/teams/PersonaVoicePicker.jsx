/**
 * PersonaVoicePicker — Dropdown to choose a browser TTS voice per persona.
 *
 * Additive component. Reads available voices from window.SpeechService.
 * Used inside the Meeting Voice Settings panel.
 */
import React, { useMemo, useState, useCallback } from 'react';
import { Volume2 } from 'lucide-react';
// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function PersonaVoicePicker({ personaId, label, value, onChange }) {
    const [previewing, setPreviewing] = useState(false);
    const voices = useMemo(() => {
        return window.SpeechService?.getVoices?.() || [];
    }, []);
    const handlePreview = useCallback(() => {
        if (!window.SpeechService?.speakWithConfig || previewing)
            return;
        setPreviewing(true);
        window.SpeechService.speakWithConfig(`Hi, I'm ${label}.`, value || {}, { onEnd: () => setPreviewing(false), onError: () => setPreviewing(false) });
    }, [label, value, previewing]);
    return (<div className="flex items-center justify-between gap-2 py-1.5">
      {/* Persona label */}
      <div className="flex-1 min-w-0">
        <div className="text-[11px] text-white/70 font-medium truncate">{label}</div>
      </div>

      {/* Voice dropdown */}
      <select className="w-44 px-2 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-[10px] text-white/70 focus:outline-none focus:border-cyan-500/40 transition-colors truncate" value={value?.voiceURI || ''} onChange={(e) => onChange({ ...(value || { voiceURI: '' }), voiceURI: e.target.value })}>
        <option value="" className="bg-[#111]">
          Default voice
        </option>
        {voices.map((v) => (<option key={v.voiceURI} value={v.voiceURI} className="bg-[#111]">
            {v.name} ({v.lang})
          </option>))}
      </select>

      {/* Preview button */}
      <button onClick={handlePreview} disabled={previewing} className={`p-1.5 rounded-lg transition-colors ${previewing
            ? 'text-cyan-300 bg-cyan-500/10'
            : 'text-white/25 hover:text-white/50 hover:bg-white/[0.04]'}`} title={`Preview ${label}'s voice`}>
        <Volume2 size={12}/>
      </button>
    </div>);
}

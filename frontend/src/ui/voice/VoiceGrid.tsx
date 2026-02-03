/**
 * Voice Grid Component
 *
 * 2x3 grid for selecting voice personas in the Voice UI.
 */

import React from 'react';
import { VOICES, VoiceDef, VoiceId } from './voices';

interface VoiceGridProps {
  activeVoice: VoiceDef;
  onSelect: (voice: VoiceDef) => void;
}

export default function VoiceGrid({ activeVoice, onSelect }: VoiceGridProps) {
  const btnInactive =
    'bg-[#1F1F1F] border border-transparent hover:bg-[#2A2A2A] hover:border-white/5';
  const btnActive = 'bg-[#2A2A2A] border border-white/20';

  return (
    <div className="flex flex-col gap-3">
      <span className="text-sm font-bold text-white">Voice</span>
      <div className="grid grid-cols-2 gap-2">
        {VOICES.map((voice) => (
          <button
            key={voice.id}
            onClick={() => onSelect(voice)}
            className={`
              flex flex-col items-start p-3 rounded-[16px] transition-all text-left
              ${activeVoice.id === voice.id ? btnActive : btnInactive}
            `}
          >
            <span className="text-[13px] font-bold text-white">{voice.name}</span>
            <span className="text-[11px] text-white/40">{voice.description}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

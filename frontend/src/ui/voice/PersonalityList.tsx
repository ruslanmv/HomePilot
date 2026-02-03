/**
 * Personality List Component
 *
 * Dropdown list for selecting AI personality modes.
 */

import React, { useState } from 'react';
import { ChevronDown, Check } from 'lucide-react';
import { PERSONALITIES, PersonalityDef } from './personalities';

interface PersonalityListProps {
  activePersonality: PersonalityDef;
  onSelect: (personality: PersonalityDef) => void;
}

export default function PersonalityList({
  activePersonality,
  onSelect,
}: PersonalityListProps) {
  const [showList, setShowList] = useState(false);

  const btnInactive =
    'bg-[#1F1F1F] border border-transparent hover:bg-[#2A2A2A] hover:border-white/5';
  const panelBg =
    'bg-[#121212]/95 backdrop-blur-xl border border-white/10 shadow-[0_20px_50px_rgba(0,0,0,0.9)]';

  const Icon = activePersonality.icon;

  return (
    <div className="flex flex-col gap-3 relative">
      <span className="text-sm font-bold text-white">Personality</span>

      {/* Trigger button */}
      <button
        onClick={() => setShowList(!showList)}
        className={`w-full h-[48px] px-4 rounded-[16px] flex items-center justify-between transition-colors ${btnInactive}`}
      >
        <div className="flex items-center gap-3">
          <Icon size={16} className="text-white/70" />
          <span className="text-[13px] font-medium text-white">
            {activePersonality.label}
          </span>
        </div>
        <ChevronDown
          size={14}
          className={`text-white/40 transition-transform ${showList ? 'rotate-180' : ''}`}
        />
      </button>

      {/* Floating personality list */}
      {showList && (
        <div
          className={`absolute bottom-[-20px] left-[105%] w-[260px] max-h-[480px] rounded-[18px] overflow-y-auto hp-scroll flex flex-col p-2 z-50 ${panelBg}`}
        >
          {PERSONALITIES.map((p) => {
            const PIcon = p.icon;
            const isActive = activePersonality.id === p.id;
            return (
              <button
                key={p.id}
                onClick={() => {
                  onSelect(p);
                  setShowList(false);
                }}
                className={`
                  flex items-center gap-3 p-3 rounded-[12px] text-left transition-all
                  ${isActive ? 'bg-white/10 text-white' : 'text-white/50 hover:bg-white/5 hover:text-white'}
                `}
              >
                <PIcon size={18} className={isActive ? 'text-white' : 'opacity-60'} />
                <span className="text-[13px] font-medium flex-1">
                  {p.label}
                  {p.mature && (
                    <span className="text-[10px] text-white/30 ml-1">18+</span>
                  )}
                </span>
                {isActive && <Check size={14} className="text-white" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

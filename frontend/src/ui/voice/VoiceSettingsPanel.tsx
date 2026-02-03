/**
 * Voice Settings Panel Component
 *
 * Floating popover panel containing:
 * - Voice persona grid (2x3)
 * - Personality/agent selector
 * - Speed slider
 *
 * Note: Advanced audio settings have been moved to System Settings (SettingsModal)
 */

import React from 'react';
import VoiceGrid from './VoiceGrid';
import PersonalityList from './PersonalityList';
import SpeedSlider from './SpeedSlider';
import { VoiceDef } from './voices';
import { PersonalityDef } from './personalities';

interface VoiceSettingsPanelProps {
  isOpen: boolean;
  activeVoice: VoiceDef;
  setActiveVoice: (voice: VoiceDef) => void;
  activePersonality: PersonalityDef;
  setActivePersonality: (personality: PersonalityDef) => void;
  speed: number;
  setSpeed: (speed: number) => void;
}

export default function VoiceSettingsPanel({
  isOpen,
  activeVoice,
  setActiveVoice,
  activePersonality,
  setActivePersonality,
  speed,
  setSpeed,
}: VoiceSettingsPanelProps) {
  if (!isOpen) return null;

  const panelBg =
    'bg-[#121212]/95 backdrop-blur-xl border border-white/10 shadow-[0_20px_50px_rgba(0,0,0,0.9)]';

  return (
    <div
      className={`absolute bottom-[60px] left-0 w-[340px] rounded-[24px] overflow-visible hp-fade-in z-[60] ${panelBg}`}
    >
      <div className="p-5 flex flex-col gap-5 max-h-[60vh] overflow-y-auto hp-scroll">
        {/* Voice Persona Grid Section */}
        <VoiceGrid activeVoice={activeVoice} onSelect={setActiveVoice} />

        {/* Personality Section */}
        <PersonalityList
          activePersonality={activePersonality}
          onSelect={setActivePersonality}
        />

        {/* Speed Section */}
        <div className="pb-2">
          <SpeedSlider value={speed} onChange={setSpeed} />
        </div>

        {/* Footer Info */}
        <div className="text-[10px] text-white/25 text-center pt-2 border-t border-white/5">
          HomePilot Voice • Studio Quality
        </div>
      </div>
    </div>
  );
}

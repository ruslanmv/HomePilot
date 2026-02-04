/**
 * Voice Settings Panel Component
 *
 * Floating popover panel containing:
 * - Voice persona grid (2x3)
 * - Personality/agent selector
 * - Custom instructions textarea (when personality = Custom)
 * - Speed slider
 */

import React, { useState, useEffect } from 'react';
import VoiceGrid from './VoiceGrid';
import PersonalityList from './PersonalityList';
import SpeedSlider from './SpeedSlider';
import { VoiceDef } from './voices';
import { PersonalityDef } from './personalities';

const LS_CUSTOM_PERSONALITY_PROMPT = 'homepilot_custom_personality_prompt';

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
  // Custom personality instructions state
  const [customPrompt, setCustomPrompt] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem(LS_CUSTOM_PERSONALITY_PROMPT) || '';
    }
    return '';
  });
  const [customDirty, setCustomDirty] = useState(false);

  // Reload saved instructions when switching to custom personality
  useEffect(() => {
    if (activePersonality.id === 'custom' && typeof window !== 'undefined') {
      const saved = localStorage.getItem(LS_CUSTOM_PERSONALITY_PROMPT) || '';
      setCustomPrompt(saved);
      setCustomDirty(false);
    }
  }, [activePersonality.id]);

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

        {/* Custom Instructions - only when Custom personality is selected */}
        {activePersonality.id === 'custom' && (
          <div className="rounded-[20px] bg-white/5 border border-white/10 p-4">
            <div className="text-sm font-bold text-white mb-2">Instructions</div>

            <textarea
              value={customPrompt}
              onChange={(e) => {
                setCustomPrompt(e.target.value);
                setCustomDirty(true);
              }}
              placeholder="Describe the behavior, tone, and response style you want..."
              className="w-full min-h-[120px] rounded-[16px] bg-black/30 border border-white/10 p-3 text-sm text-white/90 placeholder-white/30 outline-none focus:border-white/30 resize-none hp-scroll"
            />

            <div className="mt-3 flex justify-end">
              <button
                type="button"
                disabled={!customDirty}
                onClick={() => {
                  localStorage.setItem(LS_CUSTOM_PERSONALITY_PROMPT, customPrompt.trim());
                  setCustomDirty(false);
                }}
                className={`h-9 px-4 rounded-full text-sm font-semibold transition-colors ${
                  customDirty
                    ? 'bg-white text-black hover:bg-gray-200'
                    : 'bg-white/10 text-white/40 cursor-not-allowed'
                }`}
              >
                Save
              </button>
            </div>
          </div>
        )}

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

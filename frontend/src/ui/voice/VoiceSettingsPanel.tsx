/**
 * Voice Settings Panel Component
 *
 * Floating popover panel containing:
 * - Voice persona grid (2x3)
 * - Personality/agent selector
 * - Custom instructions textarea (when personality = Custom)
 * - Speed slider
 */

import React, { useState, useEffect, useRef } from 'react';
import VoiceGrid from './VoiceGrid';
import PersonalityList from './PersonalityList';
import SpeedSlider from './SpeedSlider';
import { VoiceDef } from './voices';
import { PersonalityDef } from './personalities';

const LS_CUSTOM_PERSONALITY_PROMPT = 'homepilot_custom_personality_prompt';
const MAX_CUSTOM_PROMPT_LENGTH = 1500;

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
  const [savedFlash, setSavedFlash] = useState(false);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reload saved instructions when switching to custom personality
  useEffect(() => {
    if (activePersonality.id === 'custom' && typeof window !== 'undefined') {
      const saved = localStorage.getItem(LS_CUSTOM_PERSONALITY_PROMPT) || '';
      setCustomPrompt(saved);
      setCustomDirty(false);
      setSavedFlash(false);
    }
  }, [activePersonality.id]);

  // Cleanup flash timer on unmount
  useEffect(() => {
    return () => {
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    };
  }, []);

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
          <div className="rounded-[20px] bg-white/[0.03] p-4">
            <div className="text-sm font-bold text-white">Instructions</div>
            <div className="text-[11px] text-white/35 mt-1 mb-3">
              Define how the AI should behave, speak, and respond.
            </div>

            <textarea
              value={customPrompt}
              onChange={(e) => {
                const val = e.target.value.slice(0, MAX_CUSTOM_PROMPT_LENGTH);
                setCustomPrompt(val);
                setCustomDirty(true);
                setSavedFlash(false);
              }}
              placeholder={"e.g. You are a witty British butler. Be dry, formal, and slightly sarcastic. Keep answers short."}
              className="w-full min-h-[100px] rounded-[14px] bg-black/30 border border-white/[0.06] p-3 text-[13px] leading-relaxed text-white/90 placeholder-white/20 outline-none focus:border-white/20 resize-none hp-scroll transition-colors"
            />

            <div className="mt-2 flex items-center justify-between">
              <span className={`text-[10px] tabular-nums ${
                customPrompt.length > MAX_CUSTOM_PROMPT_LENGTH * 0.9
                  ? 'text-orange-400/60'
                  : 'text-white/20'
              }`}>
                {customPrompt.length}/{MAX_CUSTOM_PROMPT_LENGTH}
              </span>

              <button
                type="button"
                disabled={!customDirty}
                onClick={() => {
                  localStorage.setItem(LS_CUSTOM_PERSONALITY_PROMPT, customPrompt.trim());
                  setCustomDirty(false);
                  setSavedFlash(true);
                  if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
                  flashTimerRef.current = setTimeout(() => setSavedFlash(false), 2000);
                }}
                className={`h-8 px-4 rounded-full text-[12px] font-semibold transition-all duration-200 ${
                  savedFlash
                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                    : customDirty
                      ? 'bg-white text-black hover:bg-gray-200'
                      : 'bg-white/[0.06] text-white/30 cursor-not-allowed'
                }`}
              >
                {savedFlash ? 'Saved' : 'Save'}
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

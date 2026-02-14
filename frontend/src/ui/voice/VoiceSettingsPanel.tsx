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
import { User } from 'lucide-react';
import VoiceGrid from './VoiceGrid';
import PersonalityList from './PersonalityList';
import SpeedSlider from './SpeedSlider';
import { VoiceDef } from './voices';
import { PersonalityDef } from './personalities';
import { isPersonasEnabled, LS_PERSONA_CACHE } from './personalityGating';

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

  // Persona projects for voice (fetched when toggle is on, or when project is edited)
  const [personaEntries, setPersonaEntries] = useState<PersonalityDef[]>([]);

  // Shared fetch function — reusable from effect and event listener
  const fetchPersonaProjects = useRef(() => {
    if (!isPersonasEnabled()) {
      setPersonaEntries([]);
      return;
    }
    const backendUrl =
      (typeof window !== 'undefined' && localStorage.getItem('homepilot_backend_url')) ||
      'http://localhost:8000';
    const apiKey =
      typeof window !== 'undefined' ? localStorage.getItem('homepilot_api_key') || '' : '';

    const headers: Record<string, string> = {};
    if (apiKey) headers['x-api-key'] = apiKey;

    fetch(`${backendUrl.replace(/\/+$/, '')}/projects`, { headers })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data?.projects) return;
        const personaProjects = (data.projects as any[]).filter(
          (p: any) => p.project_type === 'persona' && p.persona_agent
        );
        // Cache for prompt assembly in App.tsx — include full appearance data
        const cache = personaProjects.map((p: any) => {
          const pap = p.persona_appearance || {};
          const selected = pap.selected || {};
          const avatarSettings = pap.avatar_settings || {};

          // Build photo catalog (same logic as backend projects.py)
          const photos: Array<{ label: string; outfit: string; url: string; isDefault: boolean }> = [];
          const baseOutfitDesc = avatarSettings.outfit_prompt || pap.style_preset || '';

          // Base portraits
          for (const s of (pap.sets || [])) {
            for (const img of (s.images || [])) {
              if (!img.url) continue;
              const isDefault = img.id === selected.image_id &&
                (img.set_id || s.set_id || '') === (selected.set_id || '');
              photos.push({
                label: isDefault ? 'Default Look' : 'Portrait',
                outfit: baseOutfitDesc,
                url: img.url,
                isDefault,
              });
            }
          }

          // Outfit variations
          for (const outfit of (pap.outfits || [])) {
            const oLabel = outfit.label || 'Outfit';
            const oDesc = outfit.outfit_prompt || oLabel;
            for (const img of (outfit.images || [])) {
              if (!img.url) continue;
              const isDefault = img.id === selected.image_id &&
                (img.set_id || '') === (selected.set_id || '');
              photos.push({ label: oLabel, outfit: oDesc, url: img.url, isDefault });
            }
          }

          // Ensure at least one default
          if (photos.length > 0 && !photos.some((ph) => ph.isDefault)) {
            photos[0].isDefault = true;
          }

          return {
            id: p.id,
            label: p.persona_agent?.label || p.name || 'Persona',
            role: p.persona_agent?.role || '',
            tone: p.persona_agent?.response_style?.tone || '',
            system_prompt: p.persona_agent?.system_prompt || '',
            style_preset: pap.style_preset || '',
            character_desc: avatarSettings.character_prompt || '',
            created_at: p.created_at || 0,
            photos,
          };
        });
        localStorage.setItem(LS_PERSONA_CACHE, JSON.stringify(cache));

        // Map to PersonalityDef entries
        const entries: PersonalityDef[] = personaProjects.map((p: any) => ({
          id: `persona:${p.id}`,
          label: p.persona_agent?.label || p.name || 'Persona',
          icon: User,
          prompt: p.persona_agent?.system_prompt || '',
          isPersona: true,
          personaSystemPrompt: p.persona_agent?.system_prompt || '',
          personaTone: p.persona_agent?.response_style?.tone || '',
          personaRole: p.persona_agent?.role || '',
        }));
        setPersonaEntries(entries);
      })
      .catch((err) => {
        console.warn('[VoiceSettingsPanel] Failed to fetch persona projects:', err);
        setPersonaEntries([]);
      });
  }).current;

  // Fetch on open
  useEffect(() => {
    if (!isOpen) {
      setPersonaEntries([]);
      return;
    }
    fetchPersonaProjects();
  }, [isOpen]);

  // Auto-sync: re-fetch when a persona project is saved elsewhere
  useEffect(() => {
    const handler = () => fetchPersonaProjects();
    window.addEventListener('hp:persona_project_saved', handler);
    return () => window.removeEventListener('hp:persona_project_saved', handler);
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
          personas={personaEntries}
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

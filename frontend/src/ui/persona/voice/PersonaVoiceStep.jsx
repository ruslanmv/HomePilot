/**
 * PersonaVoiceStep — Wizard step for choosing a persona's voice.
 *
 * Added after Appearance in the persona creation wizard.
 * Lets the user:
 *   1. Pick from available system voices (Web Speech API)
 *   2. Auto-suggest a voice based on gender
 *   3. Adjust rate / pitch / volume
 *   4. Test the voice with a preview button
 *
 * Additive — no existing wizard behaviour is changed.
 */
import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { Volume2, RefreshCcw } from 'lucide-react';
// ---------------------------------------------------------------------------
// Heuristic gender hints for browser voice names
// ---------------------------------------------------------------------------
const FEMALE_HINTS = [
    'female', 'woman', 'zira', 'susan', 'emma', 'samantha', 'victoria',
    'karen', 'moira', 'fiona', 'serena', 'alice', 'amelie', 'sara',
    'tessa', 'ellen', 'joana', 'kathy', 'vicki', 'google us english',
];
const MALE_HINTS = [
    'male', 'man', 'david', 'mark', 'george', 'daniel', 'alex',
    'thomas', 'oliver', 'james', 'tom', 'fred', 'lee', 'ralph',
    'rishi', 'aaron',
];
// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function PersonaVoiceStep({ gender, personaName, value, onChange, }) {
    const [ready, setReady] = useState(false);
    const [testText, setTestText] = useState('');
    const [speaking, setSpeaking] = useState(false);
    // Set initial test text from persona name
    useEffect(() => {
        setTestText(`Hi, I'm ${personaName || 'your persona'}. This is my voice.`);
    }, [personaName]);
    // Web Speech voices load asynchronously in many browsers
    useEffect(() => {
        const timer = setTimeout(() => setReady(true), 300);
        return () => clearTimeout(timer);
    }, []);
    const voices = useMemo(() => {
        return window.SpeechService?.getVoices?.() || [];
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ready]);
    const currentURI = value?.voiceURI || '';
    const currentRate = value?.rate ?? 1.0;
    const currentPitch = value?.pitch ?? 1.0;
    const currentVolume = value?.volume ?? 1.0;
    // ── Suggest a voice based on gender ──
    const pickSuggestedVoiceURI = useCallback(() => {
        if (!voices.length)
            return '';
        // Prefer English voices
        const english = voices.filter((v) => (v.lang || '').toLowerCase().startsWith('en'));
        const pool = english.length ? english : voices;
        const nameLower = (v) => (v.name || '').toLowerCase();
        const hints = gender === 'female' ? FEMALE_HINTS : gender === 'male' ? MALE_HINTS : [];
        const hinted = hints.length
            ? pool.filter((v) => hints.some((h) => nameLower(v).includes(h)))
            : [];
        const finalPool = hinted.length ? hinted : pool;
        const pick = finalPool[Math.floor(Math.random() * finalPool.length)];
        return pick?.voiceURI || '';
    }, [voices, gender]);
    const applySuggested = useCallback(() => {
        const uri = pickSuggestedVoiceURI();
        const v = voices.find((x) => x.voiceURI === uri);
        onChange({
            provider: 'web_speech',
            voiceURI: uri,
            name: v?.name,
            lang: v?.lang,
            rate: 1.0,
            pitch: 1.0,
            volume: 1.0,
        });
    }, [pickSuggestedVoiceURI, voices, onChange]);
    // Auto-suggest on first mount if no voice selected yet
    useEffect(() => {
        if (!value?.voiceURI && voices.length > 0) {
            applySuggested();
        }
        // Only on first load when voices become available
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [voices.length]);
    // ── Test voice ──
    const testSpeak = useCallback(async () => {
        const svc = window.SpeechService;
        if (!svc?.speakWithConfig || speaking)
            return;
        setSpeaking(true);
        await svc.speakWithConfig(testText, { voiceURI: currentURI, rate: currentRate, pitch: currentPitch, volume: currentVolume }, { onEnd: () => setSpeaking(false), onError: () => setSpeaking(false) });
        setSpeaking(false);
    }, [testText, currentURI, currentRate, currentPitch, currentVolume, speaking]);
    // ── Helpers for partial updates ──
    const update = useCallback((partial) => {
        onChange({ ...(value || { provider: 'web_speech' }), ...partial });
    }, [value, onChange]);
    // ── Selected voice display name ──
    const selectedVoice = useMemo(() => voices.find((v) => v.voiceURI === currentURI), [voices, currentURI]);
    return (<div className="space-y-5">
      {/* Title */}
      <div className="text-center mb-2">
        <h3 className="text-xl font-bold text-white mb-1">Voice</h3>
        <p className="text-sm text-white/50">
          Choose how this persona sounds on your device. If missing on import, HomePilot falls back to default.
        </p>
      </div>

      {/* Suggest banner */}
      <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-xs text-white/60 font-medium">
              Suggested for: <span className="text-purple-300">{gender}</span>
            </div>
            <div className="text-[11px] text-white/30 mt-0.5">
              Auto-pick a voice that matches the persona's gender.
            </div>
          </div>
          <button type="button" onClick={applySuggested} className="px-3 py-2 rounded-lg bg-white/[0.04] border border-white/[0.08] text-xs text-white/70 hover:bg-white/[0.08] transition-colors flex items-center gap-2">
            <RefreshCcw size={13}/>
            Suggest
          </button>
        </div>
      </div>

      {/* Voice dropdown */}
      <div>
        <div className="text-xs text-white/55 font-medium mb-1.5">System Voice</div>
        <select value={currentURI} onChange={(e) => {
            const uri = e.target.value;
            const v = voices.find((x) => x.voiceURI === uri);
            update({ voiceURI: uri, name: v?.name, lang: v?.lang });
        }} className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-sm text-white/80 focus:outline-none focus:border-purple-500/40 transition-colors">
          <option value="" className="bg-[#1a1a2e]">
            Default voice
          </option>
          {voices.map((v) => (<option key={v.voiceURI} value={v.voiceURI} className="bg-[#1a1a2e]">
              {v.name} · {v.lang}
            </option>))}
        </select>
        <div className="text-[10px] text-white/25 mt-1">
          Available voices depend on your OS and browser. Chrome/Edge usually have the most.
        </div>
      </div>

      {/* Rate / Pitch / Volume sliders */}
      <div className="grid grid-cols-3 gap-3">
        <SliderControl label="Rate" value={currentRate} min={0.7} max={1.3} step={0.01} onChange={(v) => update({ rate: v })}/>
        <SliderControl label="Pitch" value={currentPitch} min={0.7} max={1.3} step={0.01} onChange={(v) => update({ pitch: v })}/>
        <SliderControl label="Volume" value={currentVolume} min={0.2} max={1.0} step={0.01} onChange={(v) => update({ volume: v })}/>
      </div>

      {/* Test voice */}
      <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-4">
        <div className="text-xs text-white/55 font-medium mb-2">Test voice</div>
        <div className="flex gap-2">
          <input value={testText} onChange={(e) => setTestText(e.target.value)} className="flex-1 px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-sm text-white/80 focus:outline-none focus:border-purple-500/40 transition-colors"/>
          <button type="button" onClick={testSpeak} disabled={speaking} className={`px-4 py-2.5 rounded-xl border text-sm font-medium flex items-center gap-2 transition-colors ${speaking
            ? 'bg-purple-500/20 border-purple-500/30 text-purple-300'
            : 'bg-purple-500/80 border-purple-500/50 text-white hover:bg-purple-500'}`}>
            <Volume2 size={15} className={speaking ? 'animate-pulse' : ''}/>
            {speaking ? 'Speaking...' : 'Speak'}
          </button>
        </div>
        {selectedVoice && (<div className="text-[10px] text-white/25 mt-2">
            Using: {selectedVoice.name} ({selectedVoice.lang})
          </div>)}
      </div>
    </div>);
}
// ---------------------------------------------------------------------------
// Slider sub-component (local to this file)
// ---------------------------------------------------------------------------
function SliderControl({ label, value, min, max, step, onChange, }) {
    return (<div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[11px] text-white/55 font-medium">{label}</span>
        <span className="text-[10px] text-white/35 font-mono tabular-nums">{value.toFixed(2)}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(parseFloat(e.target.value))} className="w-full h-1 mt-1 rounded-full bg-white/[0.06] appearance-none cursor-pointer accent-purple-400 [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:appearance-none"/>
    </div>);
}

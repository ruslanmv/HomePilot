import React, { useEffect, useMemo, useRef, useState } from "react";
import { Mic, MicOff, Settings, Volume2, VolumeX, Zap, Radio, X } from "lucide-react";
import { createVAD } from "./voice/vad";

declare global {
  interface Window {
    SpeechService?: any;
  }
}

// Grok-like colors and styles
const THEME = {
  bg: "bg-[#0a0a0a]",
  surface: "bg-[#161616]",
  surfaceHover: "hover:bg-[#202020]",
  border: "border-[#2a2a2a]",
  text: "text-[#e0e0e0]",
  textDim: "text-[#888]",
  accent: "text-white",
  active: "bg-white text-black",
};

export default function VoiceMode({
  onSendText,
}: {
  onSendText: (text: string) => void;
}) {
  const svc = useMemo(() => window.SpeechService, []);
  const [handsFree, setHandsFree] = useState(false);
  const [interim, setInterim] = useState("");
  const [listening, setListening] = useState(false);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [selectedVoice, setSelectedVoice] = useState<string>(() => {
    return localStorage.getItem('homepilot_voice_uri') || '';
  });
  const [showVoiceSettings, setShowVoiceSettings] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState<boolean>(() => {
    return localStorage.getItem('homepilot_tts_enabled') !== 'false';
  });

  const vadRef = useRef<ReturnType<typeof createVAD> | null>(null);

  // --- Logic Section ---

  useEffect(() => {
    if (!svc) return;

    const loadVoices = () => {
      const availableVoices = svc.getVoices();
      setVoices(availableVoices);

      if (!selectedVoice && availableVoices.length > 0) {
        // Auto-select a natural voice
        const defaultVoice = availableVoices.find((v: SpeechSynthesisVoice) =>
          v.name.toLowerCase().includes('google') && v.lang.startsWith('en')
        ) || availableVoices.find((v: SpeechSynthesisVoice) => v.default) || availableVoices[0];

        // Use voiceURI for consistency with speech service
        setSelectedVoice(defaultVoice.voiceURI);
        localStorage.setItem('homepilot_voice_uri', defaultVoice.voiceURI);
      }
    };

    loadVoices();
    if (window.speechSynthesis.onvoiceschanged !== undefined) {
      window.speechSynthesis.onvoiceschanged = loadVoices;
    }
  }, [svc, selectedVoice]);

  useEffect(() => {
    if (!svc || !selectedVoice) return;
    // Set the preferred voice URI in the speech service
    svc.setPreferredVoiceURI?.(selectedVoice);
  }, [svc, selectedVoice]);

  useEffect(() => {
    localStorage.setItem('homepilot_tts_enabled', String(ttsEnabled));
  }, [ttsEnabled]);

  useEffect(() => {
    if (!svc) return;

    svc.setRecognitionCallbacks({
      onStart: () => {
        setListening(true);
        if (handsFree && vadRef.current) vadRef.current.stop();
      },
      onEnd: () => {
        setListening(false);
        if (handsFree && vadRef.current) vadRef.current.start().catch(console.warn);
      },
      onInterim: (t: string) => setInterim(t),
      onResult: (finalText: string) => {
        setInterim("");
        if (finalText?.trim()) onSendText(finalText.trim());
      },
      onError: (msg: string) => {
        setListening(false);
        console.warn("STT error:", msg);
      },
    });
  }, [svc, onSendText, handsFree]);

  useEffect(() => {
    if (!handsFree) return;
    vadRef.current = createVAD(
      () => {
        if (svc?.stopSpeaking) svc.stopSpeaking();
        svc?.startSTT?.({});
      },
      () => svc?.stopSTT?.(),
      { threshold: 0.035, minSpeechMs: 250, silenceMs: 900 }
    );
    vadRef.current.start().catch((e) => console.warn("VAD start failed", e));
    return () => {
      vadRef.current?.stop?.();
      vadRef.current = null;
    };
  }, [handsFree, svc]);

  if (!svc) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className={`${THEME.surface} border ${THEME.border} rounded-3xl p-8 text-center max-w-md`}>
          <div className="text-6xl mb-4">🎤</div>
          <div className="text-xl font-semibold text-white mb-2">Voice Mode</div>
          <div className={`text-sm ${THEME.textDim}`}>
            Speech service not loaded. Please refresh the page.
          </div>
        </div>
      </div>
    );
  }

  // --- UI Section (Grok Style) ---

  return (
    <div className="flex-1 flex items-center justify-center px-4 py-8">
      <div className={`w-full max-w-2xl mx-auto rounded-3xl border ${THEME.border} ${THEME.surface} overflow-hidden shadow-2xl transition-all duration-300`}>
        {/* Header */}
        <div className={`flex items-center justify-between px-6 py-4 border-b ${THEME.border}`}>
          <div className="flex items-center gap-3">
            {/* HomePilot Voice Icon */}
            <div className="w-8 h-8 flex items-center justify-center bg-white text-black rounded-lg">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM12 6C13.66 6 15 7.34 15 9C15 10.66 13.66 12 12 12C10.34 12 9 10.66 9 9C9 7.34 10.34 6 12 6ZM12 20C9.33 20 7 18 7 15.5C7 15.22 7.22 15 7.5 15H16.5C16.78 15 17 15.22 17 15.5C17 18 14.67 20 12 20Z" fill="currentColor"/>
              </svg>
            </div>
            <span className={`text-sm font-semibold tracking-tight ${THEME.accent}`}>HomePilot Voice</span>
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => setShowVoiceSettings(!showVoiceSettings)}
              className={`p-2 rounded-full ${THEME.textDim} hover:text-white ${THEME.surfaceHover} transition-colors`}
            >
              {showVoiceSettings ? <X size={18} /> : <Settings size={18} />}
            </button>
          </div>
        </div>

        {/* Main Visualizer Area */}
        <div className="relative h-64 flex flex-col items-center justify-center p-6 bg-gradient-to-b from-transparent to-black/20">

          {/* Pulsing Orb */}
          <div className="relative mb-6">
            <div className={`w-24 h-24 rounded-full flex items-center justify-center transition-all duration-500 ${listening ? 'scale-110 bg-white shadow-[0_0_40px_rgba(255,255,255,0.3)]' : 'bg-[#222] scale-100'}`}>
              {listening ? (
                <div className="space-y-1 flex gap-1 h-8 items-center">
                  <div className="w-1.5 bg-black animate-[bounce_1s_infinite] h-4"></div>
                  <div className="w-1.5 bg-black animate-[bounce_1.2s_infinite] h-6"></div>
                  <div className="w-1.5 bg-black animate-[bounce_0.8s_infinite] h-5"></div>
                  <div className="w-1.5 bg-black animate-[bounce_1.1s_infinite] h-4"></div>
                </div>
              ) : (
                <MicOff className="text-white/30" size={28} />
              )}
            </div>
            {listening && (
              <div className="absolute inset-0 rounded-full border border-white/20 animate-ping"></div>
            )}
          </div>

          {/* Text Output */}
          <div className="text-center min-h-[3rem] max-w-lg px-4">
            {interim ? (
              <div className="space-y-2">
                <span className={`text-lg font-medium ${THEME.accent} animate-pulse`}>{interim}</span>
                <div className="flex justify-center gap-1">
                  <div className="w-1.5 h-1.5 bg-white/60 rounded-full animate-bounce"></div>
                  <div className="w-1.5 h-1.5 bg-white/60 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }}></div>
                  <div className="w-1.5 h-1.5 bg-white/60 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                </div>
              </div>
            ) : (
              <span className={`text-sm ${THEME.textDim}`}>
                {listening ? "Listening..." : handsFree ? "Waiting for speech..." : "Tap mic to start"}
              </span>
            )}
          </div>
        </div>

        {/* Settings Expandable */}
        {showVoiceSettings && (
          <div className={`px-6 py-4 border-t ${THEME.border} bg-[#111] animate-in slide-in-from-top-2`}>
            <label className={`text-xs font-semibold uppercase tracking-wider ${THEME.textDim} mb-3 block`}>Voice Persona</label>
            <select
              className={`w-full bg-[#1a1a1a] border ${THEME.border} rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-white/30 transition-colors appearance-none cursor-pointer`}
              value={selectedVoice}
              onChange={(e) => {
                setSelectedVoice(e.target.value);
                localStorage.setItem('homepilot_voice_uri', e.target.value);
              }}
            >
              {voices.length === 0 && <option value="">Loading voices...</option>}
              {voices.map((voice) => (
                <option key={voice.voiceURI} value={voice.voiceURI}>
                  {voice.name} ({voice.lang})
                </option>
              ))}
            </select>
            <div className={`mt-2 text-[10px] ${THEME.textDim}`}>
              Choose from {voices.length} available voices
            </div>
          </div>
        )}

        {/* Control Footer */}
        <div className={`p-4 border-t ${THEME.border} grid grid-cols-3 gap-3 bg-[#0f0f0f]`}>

          {/* TTS Toggle */}
          <button
            onClick={() => setTtsEnabled(!ttsEnabled)}
            className={`flex flex-col items-center justify-center gap-1 py-3 rounded-xl border border-transparent transition-all ${
              ttsEnabled ? "bg-white/10 text-white" : "hover:bg-white/5 text-[#666]"
            }`}
          >
            {ttsEnabled ? <Volume2 size={20} /> : <VolumeX size={20} />}
            <span className="text-[10px] font-medium uppercase tracking-wide">TTS {ttsEnabled ? 'On' : 'Off'}</span>
          </button>

          {/* Main Mic Trigger */}
          <button
            onClick={() => {
              if (listening) {
                svc.stopSTT();
              } else {
                svc.stopSpeaking?.();
                svc.startSTT?.({});
              }
            }}
            className={`flex flex-col items-center justify-center gap-1 py-3 rounded-xl transition-all shadow-lg ${
              listening
                ? "bg-red-500/10 text-red-500 border border-red-500/20 hover:bg-red-500/20"
                : "bg-white text-black hover:bg-gray-200"
            }`}
          >
            <Mic size={24} strokeWidth={2.5} />
          </button>

          {/* Hands Free Toggle */}
          <button
            onClick={() => setHandsFree((v) => !v)}
            className={`flex flex-col items-center justify-center gap-1 py-3 rounded-xl border transition-all ${
              handsFree
                ? "bg-white text-black border-white"
                : "border-white/10 text-[#666] hover:text-white hover:bg-white/5"
            }`}
          >
            {handsFree ? <Zap size={20} fill="currentColor" /> : <Radio size={20} />}
            <span className="text-[10px] font-medium uppercase tracking-wide">
              {handsFree ? 'Auto' : 'Manual'}
            </span>
          </button>

        </div>
      </div>
    </div>
  );
}

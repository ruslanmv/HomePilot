import React, { useState } from "react";
import { Mic, MicOff, Settings, Volume2, VolumeX, Zap, Radio, X } from "lucide-react";
import { useVoiceController, VoiceState } from "./voice/useVoiceController";

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

// State-based status messages
const STATE_MESSAGES: Record<VoiceState, string> = {
  OFF: "Tap mic to start",
  IDLE: "Listening for speech...",
  LISTENING: "Listening...",
  THINKING: "Processing...",
  SPEAKING: "Speaking...",
};

export default function VoiceMode({
  onSendText,
}: {
  onSendText: (text: string) => void;
}) {
  const [showVoiceSettings, setShowVoiceSettings] = useState(false);

  const voice = useVoiceController(onSendText);

  // Check if speech service is available
  if (!window.SpeechService) {
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

  const isListening = voice.state === 'LISTENING';
  const isActive = voice.state !== 'OFF';

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

            {/* State indicator */}
            <div className={`px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider ${
              voice.state === 'OFF' ? 'bg-gray-800 text-gray-400' :
              voice.state === 'LISTENING' ? 'bg-green-900/50 text-green-400' :
              voice.state === 'SPEAKING' ? 'bg-blue-900/50 text-blue-400' :
              voice.state === 'THINKING' ? 'bg-yellow-900/50 text-yellow-400' :
              'bg-gray-700 text-gray-300'
            }`}>
              {voice.state}
            </div>
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
            <div className={`w-24 h-24 rounded-full flex items-center justify-center transition-all duration-500 ${
              isListening
                ? 'scale-110 bg-white shadow-[0_0_40px_rgba(255,255,255,0.3)]'
                : voice.state === 'SPEAKING'
                  ? 'scale-105 bg-blue-500 shadow-[0_0_30px_rgba(59,130,246,0.3)]'
                  : voice.state === 'THINKING'
                    ? 'scale-100 bg-yellow-500 shadow-[0_0_20px_rgba(234,179,8,0.3)]'
                    : 'bg-[#222] scale-100'
            }`}>
              {isListening ? (
                <div className="space-y-1 flex gap-1 h-8 items-center">
                  <div className="w-1.5 bg-black animate-[bounce_1s_infinite] h-4"></div>
                  <div className="w-1.5 bg-black animate-[bounce_1.2s_infinite] h-6"></div>
                  <div className="w-1.5 bg-black animate-[bounce_0.8s_infinite] h-5"></div>
                  <div className="w-1.5 bg-black animate-[bounce_1.1s_infinite] h-4"></div>
                </div>
              ) : voice.state === 'SPEAKING' ? (
                <Volume2 className="text-white" size={28} />
              ) : voice.state === 'THINKING' ? (
                <div className="w-6 h-6 border-2 border-black border-t-transparent rounded-full animate-spin" />
              ) : (
                <MicOff className="text-white/30" size={28} />
              )}
            </div>
            {isListening && (
              <div className="absolute inset-0 rounded-full border border-white/20 animate-ping"></div>
            )}
          </div>

          {/* Audio Level Visualization (hands-free mode) */}
          {voice.isHandsFree && voice.state !== 'OFF' && (
            <div className="w-full max-w-xs mb-4">
              <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-green-500 to-green-300 transition-all duration-100"
                  style={{ width: `${Math.min(voice.audioLevel * 500, 100)}%` }}
                />
              </div>
              <div className="flex justify-between text-[9px] text-gray-500 mt-1">
                <span>Noise: {voice.noiseFloor.toFixed(3)}</span>
                <span>Level: {voice.audioLevel.toFixed(3)}</span>
                <span>Threshold: {voice.threshold.toFixed(3)}</span>
              </div>
            </div>
          )}

          {/* Text Output */}
          <div className="text-center min-h-[3rem] max-w-lg px-4">
            {voice.interimText ? (
              <div className="space-y-2">
                <span className={`text-lg font-medium ${THEME.accent} animate-pulse`}>{voice.interimText}</span>
                <div className="flex justify-center gap-1">
                  <div className="w-1.5 h-1.5 bg-white/60 rounded-full animate-bounce"></div>
                  <div className="w-1.5 h-1.5 bg-white/60 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }}></div>
                  <div className="w-1.5 h-1.5 bg-white/60 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                </div>
              </div>
            ) : (
              <span className={`text-sm ${THEME.textDim}`}>
                {STATE_MESSAGES[voice.state]}
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
              value={voice.selectedVoice}
              onChange={(e) => voice.setSelectedVoice(e.target.value)}
            >
              {voice.voices.length === 0 && <option value="">Loading voices...</option>}
              {voice.voices.map((v) => (
                <option key={v.voiceURI} value={v.voiceURI}>
                  {v.name} ({v.lang})
                </option>
              ))}
            </select>
            <div className={`mt-2 text-[10px] ${THEME.textDim}`}>
              Choose from {voice.voices.length} available voices
            </div>
          </div>
        )}

        {/* Control Footer */}
        <div className={`p-4 border-t ${THEME.border} grid grid-cols-3 gap-3 bg-[#0f0f0f]`}>

          {/* TTS Toggle */}
          <button
            onClick={() => voice.setTtsEnabled(!voice.isTtsEnabled)}
            className={`flex flex-col items-center justify-center gap-1 py-3 rounded-xl border border-transparent transition-all ${
              voice.isTtsEnabled ? "bg-white/10 text-white" : "hover:bg-white/5 text-[#666]"
            }`}
          >
            {voice.isTtsEnabled ? <Volume2 size={20} /> : <VolumeX size={20} />}
            <span className="text-[10px] font-medium uppercase tracking-wide">TTS {voice.isTtsEnabled ? 'On' : 'Off'}</span>
          </button>

          {/* Main Mic Trigger */}
          <button
            onClick={() => {
              if (isListening) {
                voice.stopManualListening();
              } else if (voice.state === 'SPEAKING') {
                voice.stopSpeaking();
              } else {
                voice.startManualListening();
              }
            }}
            className={`flex flex-col items-center justify-center gap-1 py-3 rounded-xl transition-all shadow-lg ${
              isListening
                ? "bg-red-500/10 text-red-500 border border-red-500/20 hover:bg-red-500/20"
                : voice.state === 'SPEAKING'
                  ? "bg-blue-500/10 text-blue-500 border border-blue-500/20 hover:bg-blue-500/20"
                  : "bg-white text-black hover:bg-gray-200"
            }`}
          >
            {voice.state === 'SPEAKING' ? (
              <VolumeX size={24} strokeWidth={2.5} />
            ) : (
              <Mic size={24} strokeWidth={2.5} />
            )}
          </button>

          {/* Hands Free Toggle */}
          <button
            onClick={() => voice.setHandsFree(!voice.isHandsFree)}
            className={`flex flex-col items-center justify-center gap-1 py-3 rounded-xl border transition-all ${
              voice.isHandsFree
                ? "bg-white text-black border-white"
                : "border-white/10 text-[#666] hover:text-white hover:bg-white/5"
            }`}
          >
            {voice.isHandsFree ? <Zap size={20} fill="currentColor" /> : <Radio size={20} />}
            <span className="text-[10px] font-medium uppercase tracking-wide">
              {voice.isHandsFree ? 'Auto' : 'Manual'}
            </span>
          </button>

        </div>
      </div>
    </div>
  );
}

import React, { useState, useEffect, useRef } from "react";
import { Mic, MicOff, Settings, Volume2, VolumeX, Zap, Radio, X } from "lucide-react";
import { useVoiceController, VoiceState } from "./voice/useVoiceController";

/**
 * Smoothed audio level hook with attack/release dynamics
 * Fast attack for responsiveness, slower release for natural decay
 */
function useSmoothedLevel(level: number) {
  const [smooth, setSmooth] = useState(0);
  const lastRef = useRef(0);
  const frameRef = useRef<number>();

  useEffect(() => {
    const update = () => {
      const attack = 0.55;
      const release = 0.12;
      const target = Math.max(0, Math.min(1, level));

      const prev = lastRef.current;
      const next = target > prev
        ? prev + (target - prev) * attack
        : prev + (target - prev) * release;

      lastRef.current = next;
      setSmooth(next);
      frameRef.current = requestAnimationFrame(update);
    };

    frameRef.current = requestAnimationFrame(update);
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
    };
  }, [level]);

  return smooth;
}

/**
 * Intensity-based color mapping for professional audio meter look
 * Low = cool white/gray, Medium = icy blue, High = purple, Peak = warm orange
 */
function intensityColor(level01: number): string {
  if (level01 < 0.35) return 'rgba(255,255,255,0.65)';
  if (level01 < 0.70) return 'rgba(151,196,255,0.85)';  // icy blue
  if (level01 < 0.90) return 'rgba(190,120,255,0.90)';  // purple
  return 'rgba(255,170,100,0.95)';                       // warm/hot
}

/**
 * Professional mini studio meter - enterprise-quality audio visualization
 * Features: attack/release smoothing, intensity-based colors, micro jitter for liveliness
 */
function MiniStudioMeter({
  audioLevel,
  isUserActive,
  isAiSpeaking,
}: {
  audioLevel: number;     // voice.audioLevel (0..~0.2)
  isUserActive: boolean;  // LISTENING/IDLE in hands-free
  isAiSpeaking: boolean;  // SPEAKING state
}) {
  // Normalize audioLevel to 0..1 range (multiplier tuned for sensitivity)
  const norm = Math.max(0, Math.min(1, audioLevel * 8));
  const level = useSmoothedLevel(norm);

  // Idle mode: subtle static bars
  const idle = !isUserActive || level < 0.04;

  // Micro jitter only when active for "alive" feel
  const jitterRef = useRef(0);
  useEffect(() => {
    if (!idle) {
      const interval = setInterval(() => {
        jitterRef.current = Math.random() * 0.06 - 0.03;
      }, 50);
      return () => clearInterval(interval);
    }
  }, [idle]);

  // 5 bars with different sensitivity thresholds
  const barThresholds = [0.10, 0.22, 0.38, 0.55, 0.72];
  const bars = barThresholds.map((t) => {
    const v = (level - (t - 0.12)) / 0.25;
    const clamped = Math.max(0, Math.min(1, v));
    return idle ? 0.18 : Math.max(0.12, clamped + (idle ? 0 : jitterRef.current));
  });

  // Color by intensity, shift to neutral white when AI speaking
  const baseColor = intensityColor(level);
  const barColor = isAiSpeaking ? 'rgba(233,232,231,0.85)' : baseColor;

  // Glow effect based on state
  const glowStyle = idle
    ? {}
    : isAiSpeaking
      ? { filter: 'drop-shadow(0 0 6px rgba(233,232,231,0.25))' }
      : { filter: `drop-shadow(0 0 ${4 + level * 8}px ${barColor})` };

  return (
    <div
      className={`flex items-end gap-[2px] h-4 transition-opacity duration-200 ${
        idle ? 'opacity-55' : 'opacity-100'
      }`}
      style={glowStyle}
      aria-hidden="true"
    >
      {bars.map((b, i) => (
        <span
          key={i}
          className="rounded-full transition-transform duration-[70ms]"
          style={{
            width: '2.5px',
            height: '100%',
            background: idle ? 'rgba(255,255,255,0.28)' : barColor,
            transform: `scaleY(${b})`,
            transformOrigin: 'bottom',
          }}
        />
      ))}
    </div>
  );
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

          {/* Main Mic Trigger with Mini Level Meter */}
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
            className={`flex items-center justify-center gap-3 py-3 px-5 rounded-full transition-all shadow-lg ${
              isListening
                ? "bg-[#1a1a1a] text-white border border-white/20 hover:bg-[#252525]"
                : voice.state === 'SPEAKING'
                  ? "bg-[#1a1a1a] text-blue-400 border border-blue-500/30 hover:bg-[#252525]"
                  : "bg-[#1a1a1a] text-white/60 border border-white/10 hover:bg-[#252525] hover:text-white"
            }`}
          >
            {/* Mini Studio Meter */}
            <MiniStudioMeter
              audioLevel={voice.audioLevel}
              isUserActive={isListening || voice.state === 'IDLE'}
              isAiSpeaking={voice.state === 'SPEAKING'}
            />

            {/* Mic Icon */}
            {voice.state === 'SPEAKING' ? (
              <VolumeX size={20} strokeWidth={2} />
            ) : (
              <Mic size={20} strokeWidth={2} className={isListening ? 'text-white' : ''} />
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

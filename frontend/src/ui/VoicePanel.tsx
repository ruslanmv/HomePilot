import React, { useState, useMemo } from "react";
import { useVoiceController, VoiceState } from "./voice/useVoiceController";

declare global {
  interface Window {
    SpeechService?: any;
  }
}

/**
 * Mini audio level meter - Grok-style tiny equalizer bars
 * Shows 5 vertical bars that respond to audio level
 */
function MiniLevelMeter({
  level,
  active,
  speaking,
}: {
  level: number;
  active: boolean;
  speaking: boolean;
}) {
  const norm = Math.max(0, Math.min(1, level * 6));

  const bars = useMemo(() => {
    const thresholds = [0.15, 0.30, 0.50, 0.70, 0.90];
    return thresholds.map((t) => {
      const v = Math.max(0, Math.min(1, (norm - (t - 0.15)) / 0.25));
      return v;
    });
  }, [norm]);

  const barColor = speaking
    ? 'bg-blue-400'
    : active
      ? 'bg-white'
      : 'bg-white/30';

  return (
    <div
      className={`flex items-end gap-[2px] h-3 transition-opacity duration-200 ${
        active || speaking ? 'opacity-100' : 'opacity-50'
      }`}
      aria-hidden="true"
    >
      {bars.map((b, i) => (
        <span
          key={i}
          className={`w-[2px] rounded-full ${barColor} transition-all duration-75`}
          style={{
            height: `${Math.max(25, b * 100)}%`,
            opacity: active || speaking ? 0.7 + b * 0.3 : 0.4,
          }}
        />
      ))}
    </div>
  );
}

// State-based status messages for compact display
const STATE_MESSAGES: Record<VoiceState, string> = {
  OFF: "Click 'Talk' to speak",
  IDLE: "Listening for voice...",
  LISTENING: "Listening...",
  THINKING: "Processing...",
  SPEAKING: "Speaking...",
};

export default function VoicePanel({
  onSendText,
  ttsEnabled,
  setTtsEnabled,
}: {
  onSendText: (text: string) => void;
  ttsEnabled: boolean;
  setTtsEnabled: (v: boolean) => void;
}) {
  const [showVoiceSettings, setShowVoiceSettings] = useState(false);

  const voice = useVoiceController(onSendText);

  // Sync TTS enabled state with parent
  React.useEffect(() => {
    voice.setTtsEnabled(ttsEnabled);
  }, [ttsEnabled, voice.setTtsEnabled]);

  if (!window.SpeechService) {
    return null; // Speech service not loaded
  }

  const isListening = voice.state === 'LISTENING';

  return (
    <div className="w-full rounded-2xl border border-white/10 bg-white/5 p-3">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="text-sm font-bold text-white">Voice Assistant</div>
          {/* State indicator badge */}
          <div className={`px-1.5 py-0.5 rounded text-[9px] uppercase tracking-wider ${
            voice.state === 'OFF' ? 'bg-gray-800 text-gray-400' :
            voice.state === 'LISTENING' ? 'bg-green-900/50 text-green-400' :
            voice.state === 'SPEAKING' ? 'bg-blue-900/50 text-blue-400' :
            voice.state === 'THINKING' ? 'bg-yellow-900/50 text-yellow-400' :
            'bg-gray-700 text-gray-300'
          }`}>
            {voice.state}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-white/70 flex items-center gap-2">
            <input
              type="checkbox"
              checked={ttsEnabled}
              onChange={(e) => setTtsEnabled(e.target.checked)}
            />
            TTS
          </label>
          <button
            className="text-white/70 hover:text-white text-xs px-2 py-1 rounded border border-white/10"
            onClick={() => setShowVoiceSettings(v => !v)}
            title="Voice Settings"
          >
            {showVoiceSettings ? "Hide" : "Settings"}
          </button>
        </div>
      </div>

      {/* Voice Settings Panel */}
      {showVoiceSettings && (
        <div className="mb-3 p-3 rounded-lg bg-black/30 border border-white/5">
          <label className="block text-xs text-white/60 mb-2">Assistant Voice</label>
          <select
            className="w-full bg-black border border-white/10 rounded-lg px-3 py-2 text-xs text-white"
            value={voice.selectedVoice}
            onChange={(e) => voice.setSelectedVoice(e.target.value)}
          >
            {voice.voices.length === 0 && <option>Loading voices...</option>}
            {voice.voices.map((v) => (
              <option key={v.voiceURI} value={v.voiceURI}>
                {v.name} ({v.lang})
              </option>
            ))}
          </select>
          <div className="mt-2 text-[10px] text-white/40">
            Choose the voice personality for the assistant's responses
          </div>

          {/* Audio level debug (only in hands-free mode) */}
          {voice.isHandsFree && (
            <div className="mt-3 pt-3 border-t border-white/10">
              <div className="text-[10px] text-white/40 mb-1">Audio Levels</div>
              <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-green-500 to-green-300 transition-all duration-100"
                  style={{ width: `${Math.min(voice.audioLevel * 500, 100)}%` }}
                />
              </div>
              <div className="flex justify-between text-[9px] text-white/30 mt-1">
                <span>Noise: {voice.noiseFloor.toFixed(3)}</span>
                <span>Threshold: {voice.threshold.toFixed(3)}</span>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-2">
        <button
          className={`flex-1 flex items-center justify-center gap-3 px-4 py-3 rounded-2xl font-bold transition-all ${
            isListening
              ? "bg-[#1a1a1a] border border-white/20 hover:bg-[#252525]"
              : voice.state === 'SPEAKING'
                ? "bg-[#1a1a1a] border border-blue-500/30 hover:bg-[#252525]"
                : "bg-[#1a1a1a] border border-white/10 hover:bg-[#252525]"
          } text-white`}
          onClick={() => {
            if (isListening) {
              voice.stopManualListening();
            } else if (voice.state === 'SPEAKING') {
              voice.stopSpeaking();
            } else {
              voice.startManualListening();
            }
          }}
        >
          {/* Mini Level Meter */}
          <MiniLevelMeter
            level={voice.audioLevel}
            active={isListening || voice.state === 'IDLE'}
            speaking={voice.state === 'SPEAKING'}
          />
          <span>{isListening ? "Stop" : voice.state === 'SPEAKING' ? "Stop TTS" : "Talk"}</span>
        </button>

        <button
          className={`px-4 py-3 rounded-2xl border border-white/10 font-bold transition-all ${
            voice.isHandsFree
              ? "bg-yellow-500/30 text-yellow-200 border-yellow-500/30"
              : "bg-white/5 text-white/80 hover:bg-white/10"
          }`}
          onClick={() => voice.setHandsFree(!voice.isHandsFree)}
          title="Hands-free mode: automatically detect when you start speaking"
        >
          {voice.isHandsFree ? "Auto" : "Manual"}
        </button>
      </div>

      <div className="mt-2 text-xs text-white/70 min-h-[18px]">
        {voice.interimText ? (
          <span>{voice.interimText}</span>
        ) : (
          STATE_MESSAGES[voice.state]
        )}
      </div>
    </div>
  );
}

import React, { useState } from "react";
import { useVoiceController, VoiceState } from "./voice/useVoiceController";
import { microphoneDebug } from "./media/microphoneDebug";

declare global {
  interface Window {
    SpeechService?: any;
  }
}

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

  React.useEffect(() => {
    voice.setTtsEnabled(ttsEnabled);
  }, [ttsEnabled, voice.setTtsEnabled]);

  if (!window.SpeechService) return null;

  const isListening = voice.state === 'LISTENING';

  const handleTalkClick = () => {
    const action = isListening
      ? 'stop_listening'
      : voice.state === 'SPEAKING'
        ? 'stop_tts'
        : 'start_listening';
    microphoneDebug('chat', 'talk_button_click', {
      action,
      state: voice.state,
      handsFree: voice.isHandsFree,
      sttSupported: voice.sttSupported,
    });

    if (isListening) {
      voice.stopManualListening();
    } else if (voice.state === 'SPEAKING') {
      voice.stopSpeaking();
    } else {
      void voice.startManualListening();
    }
  };

  return (
    <div className="w-full rounded-2xl border border-white/10 bg-white/5 p-3">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="text-sm font-bold text-white">Voice Assistant</div>
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
          className={`flex-1 px-4 py-3 rounded-2xl font-bold transition-all ${
            isListening
              ? "bg-red-600 hover:bg-red-700"
              : voice.state === 'SPEAKING'
                ? "bg-blue-600 hover:bg-blue-700"
                : "bg-blue-600 hover:bg-blue-700"
          } text-white`}
          onClick={handleTalkClick}
        >
          {isListening ? "Stop" : voice.state === 'SPEAKING' ? "Stop TTS" : "Talk"}
        </button>

        <button
          className={`px-4 py-3 rounded-2xl border border-white/10 font-bold transition-all ${
            voice.isHandsFree
              ? "bg-yellow-500/30 text-yellow-200 border-yellow-500/30"
              : "bg-white/5 text-white/80 hover:bg-white/10"
          }`}
          onClick={() => {
            microphoneDebug('chat', 'handsfree_button_click', {
              enabled: !voice.isHandsFree,
              state: voice.state,
            });
            voice.setHandsFree(!voice.isHandsFree);
          }}
          title="Hands-free mode: automatically detect when you start speaking"
        >
          {voice.isHandsFree ? "Auto" : "Manual"}
        </button>
      </div>

      <div className="mt-2 text-xs text-white/70 min-h-[18px]">
        {voice.interimText ? <span>{voice.interimText}</span> : STATE_MESSAGES[voice.state]}
      </div>
    </div>
  );
}

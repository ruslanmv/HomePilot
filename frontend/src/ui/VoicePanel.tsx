import React, { useEffect, useMemo, useRef, useState } from "react";
import { createVAD } from "./voice/vad";

declare global {
  interface Window {
    SpeechService?: any;
  }
}

export default function VoicePanel({
  onSendText,
  ttsEnabled,
  setTtsEnabled,
}: {
  onSendText: (text: string) => void;
  ttsEnabled: boolean;
  setTtsEnabled: (v: boolean) => void;
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

  const vadRef = useRef<ReturnType<typeof createVAD> | null>(null);

  // Load voices when speech service is ready
  useEffect(() => {
    if (!svc) return;

    const loadVoices = () => {
      const availableVoices = svc.getVoices();
      setVoices(availableVoices);

      // If no voice selected, use default
      if (!selectedVoice && availableVoices.length > 0) {
        const defaultVoice = availableVoices.find((v: SpeechSynthesisVoice) => v.default) || availableVoices[0];
        setSelectedVoice(defaultVoice.voiceURI);
        localStorage.setItem('homepilot_voice_uri', defaultVoice.voiceURI);
      }
    };

    loadVoices();

    // Voices might load asynchronously
    if (window.speechSynthesis.onvoiceschanged !== undefined) {
      window.speechSynthesis.onvoiceschanged = loadVoices;
    }
  }, [svc, selectedVoice]);

  // Update speech service when voice changes
  useEffect(() => {
    if (!svc || !selectedVoice) return;

    // Set the preferred voice URI in the speech service
    svc.setPreferredVoiceURI?.(selectedVoice);
  }, [svc, selectedVoice]);

  useEffect(() => {
    if (!svc) return;

    svc.setRecognitionCallbacks({
      onStart: () => {
        setListening(true);
        // Pause VAD while recognition is active to avoid mic conflicts
        if (handsFree && vadRef.current) {
          vadRef.current.stop();
        }
      },
      onEnd: () => {
        setListening(false);
        // Resume VAD when recognition ends
        if (handsFree && vadRef.current) {
          vadRef.current.start().catch((e) => console.warn("VAD resume failed", e));
        }
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

    // Hands-free mode: VAD triggers start/stop of STT
    vadRef.current = createVAD(
      () => {
        // Barge-in: stop TTS immediately when user starts speaking
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
    return null; // Speech service not loaded
  }

  return (
    <div className="w-full rounded-2xl border border-white/10 bg-white/5 p-3">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-bold text-white">Voice Assistant</div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-white/70 flex items-center gap-2">
            <input type="checkbox" checked={ttsEnabled} onChange={(e) => setTtsEnabled(e.target.checked)} />
            TTS
          </label>
          <button
            className="text-white/70 hover:text-white text-xs px-2 py-1 rounded border border-white/10"
            onClick={() => setShowVoiceSettings(v => !v)}
            title="Voice Settings"
          >
            {showVoiceSettings ? "Hide" : "⚙️"}
          </button>
        </div>
      </div>

      {/* Voice Settings Panel */}
      {showVoiceSettings && (
        <div className="mb-3 p-3 rounded-lg bg-black/30 border border-white/5">
          <label className="block text-xs text-white/60 mb-2">Assistant Voice</label>
          <select
            className="w-full bg-black border border-white/10 rounded-lg px-3 py-2 text-xs text-white"
            value={selectedVoice}
            onChange={(e) => {
              setSelectedVoice(e.target.value);
              localStorage.setItem('homepilot_voice_uri', e.target.value);
            }}
          >
            {voices.length === 0 && <option>Loading voices...</option>}
            {voices.map((voice) => (
              <option key={voice.voiceURI} value={voice.voiceURI}>
                {voice.name} ({voice.lang})
              </option>
            ))}
          </select>
          <div className="mt-2 text-[10px] text-white/40">
            Choose the voice personality for the assistant's responses
          </div>
        </div>
      )}

      <div className="flex items-center gap-2">
        <button
          className={`flex-1 px-4 py-3 rounded-2xl font-bold transition-all ${
            listening
              ? "bg-red-600 hover:bg-red-700"
              : "bg-blue-600 hover:bg-blue-700"
          } text-white`}
          onClick={() => {
            if (listening) {
              svc.stopSTT();
            } else {
              svc.stopSpeaking?.();
              svc.startSTT?.({});
            }
          }}
        >
          {listening ? "🔴 Stop" : "🎤 Talk"}
        </button>

        <button
          className={`px-4 py-3 rounded-2xl border border-white/10 font-bold transition-all ${
            handsFree
              ? "bg-yellow-500/30 text-yellow-200 border-yellow-500/30"
              : "bg-white/5 text-white/80 hover:bg-white/10"
          }`}
          onClick={() => setHandsFree((v) => !v)}
          title="Hands-free mode: automatically detect when you start speaking"
        >
          {handsFree ? "🔥 Hands-free" : "🤚 Manual"}
        </button>
      </div>

      <div className="mt-2 text-xs text-white/70 min-h-[18px]">
        {interim ? `💭 ${interim}` : handsFree ? "🎙️ Listening for voice..." : "Click 'Talk' to speak"}
      </div>
    </div>
  );
}

import React, { useEffect, useMemo, useRef, useState } from "react";
import { createVAD } from "./voice/vad";

declare global {
  interface Window {
    SpeechService?: any;
  }
}

export default function VoiceMode({
  onSendText,
}: {
  onSendText: (text: string) => void;
}) {
  const svc = useMemo(() => window.SpeechService, []);
  const [handsFree, setHandsFree] = useState(false);
  const [interim, setInterim] = useState("");
  const [listening, setListening] = useState(false);
  const [conversationLog, setConversationLog] = useState<Array<{ role: 'user' | 'assistant', text: string }>>([]);

  const vadRef = useRef<ReturnType<typeof createVAD> | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when log updates
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [conversationLog, interim]);

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
          vadRef.current.start().catch((e: any) => console.warn("VAD resume failed", e));
        }
      },
      onInterim: (t: string) => setInterim(t),
      onResult: (finalText: string) => {
        setInterim("");
        if (finalText?.trim()) {
          // Add to conversation log
          setConversationLog(prev => [...prev, { role: 'user', text: finalText.trim() }]);
          // Send to chat backend
          onSendText(finalText.trim());
        }
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

    vadRef.current.start().catch((e: any) => console.warn("VAD start failed", e));

    return () => {
      vadRef.current?.stop?.();
      vadRef.current = null;
    };
  }, [handsFree, svc]);

  if (!svc) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center px-6">
        <div className="text-center">
          <div className="text-6xl mb-4">🎤</div>
          <div className="text-xl font-semibold text-white mb-2">Voice Mode</div>
          <div className="text-sm text-white/50">
            Speech service not loaded. Please refresh the page.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col h-full w-full max-w-[52rem] mx-auto">
      {/* Voice Mode Header */}
      <div className="px-4 py-6 border-b border-white/5">
        <div className="flex items-center gap-3 mb-2">
          <div className="text-4xl">🎤</div>
          <div>
            <div className="text-2xl font-bold text-white">Voice Mode</div>
            <div className="text-sm text-white/50">Speak naturally with HomePilot</div>
          </div>
        </div>
      </div>

      {/* Conversation Log */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
        {conversationLog.length === 0 && !interim && (
          <div className="text-center text-white/40 py-12">
            <div className="text-6xl mb-4">👋</div>
            <div className="text-lg mb-2">Start a voice conversation</div>
            <div className="text-sm">
              Click <span className="font-bold">Talk</span> to speak, or enable <span className="font-bold">Hands-free</span> for continuous listening
            </div>
          </div>
        )}

        {conversationLog.map((entry, idx) => (
          <div
            key={idx}
            className={`flex gap-4 ${entry.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {entry.role === 'assistant' && (
              <div className="w-8 h-8 rounded-full bg-white text-black flex items-center justify-center flex-shrink-0 font-bold text-sm mt-1">
                /
              </div>
            )}
            <div
              className={[
                'max-w-[85%] px-5 py-3 rounded-2xl',
                entry.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-white/5 text-white',
              ].join(' ')}
            >
              <div className="text-sm leading-relaxed">{entry.text}</div>
            </div>
          </div>
        ))}

        {/* Interim (what user is currently saying) */}
        {interim && (
          <div className="flex justify-end gap-4">
            <div className="max-w-[85%] px-5 py-3 rounded-2xl bg-blue-600/50 text-white border-2 border-blue-400">
              <div className="text-sm leading-relaxed italic">💭 {interim}</div>
            </div>
          </div>
        )}

        <div ref={logEndRef} />
      </div>

      {/* Voice Controls */}
      <div className="px-4 py-4 border-t border-white/5">
        <div className="flex items-center gap-3 mb-3">
          <button
            className={`flex-1 px-6 py-4 rounded-2xl font-bold text-lg transition-all ${
              listening
                ? "bg-red-600 hover:bg-red-700 text-white"
                : "bg-blue-600 hover:bg-blue-700 text-white"
            }`}
            onClick={() => {
              if (listening) {
                svc.stopSTT();
              } else {
                svc.stopSpeaking?.();
                svc.startSTT?.({});
              }
            }}
          >
            {listening ? "🔴 Stop Listening" : "🎤 Start Talking"}
          </button>

          <button
            className={`px-6 py-4 rounded-2xl border-2 font-bold text-lg transition-all ${
              handsFree
                ? "bg-yellow-500/30 text-yellow-200 border-yellow-500/50"
                : "bg-white/5 text-white/80 border-white/10 hover:bg-white/10"
            }`}
            onClick={() => setHandsFree((v) => !v)}
            title="Hands-free mode: automatically detect when you start speaking"
          >
            {handsFree ? "🔥 Hands-free ON" : "🤚 Hands-free OFF"}
          </button>
        </div>

        {/* Status */}
        <div className="text-center text-sm text-white/60 min-h-[20px]">
          {listening && !interim && "🎙️ Listening..."}
          {!listening && handsFree && "🔥 Hands-free active - speak naturally"}
          {!listening && !handsFree && "Click 'Start Talking' to begin"}
        </div>
      </div>
    </div>
  );
}

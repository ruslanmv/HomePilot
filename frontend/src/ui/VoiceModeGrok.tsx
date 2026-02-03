/**
 * VoiceModeGrok.tsx
 *
 * Modern Grok-style Voice UI for HomePilot.
 * Full-screen voice interface with starfield background, voice grid, and personality selector.
 *
 * Features:
 * - Starfield animated background
 * - Bottom voice bar with glow effect
 * - Voice persona grid (2x3)
 * - Personality/agent selector with icons
 * - Speed slider for speech rate
 * - Real-time voice state visualization
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Settings,
  Mic,
  Volume2,
  VolumeX,
  SlidersHorizontal,
  ChevronDown,
  Share,
  PenLine,
  Zap,
  Radio,
  AlertCircle,
} from 'lucide-react';

// Import voice module components
import './voice/voiceMode.css';
import Starfield from './voice/Starfield';
import VoiceSettingsPanel from './voice/VoiceSettingsPanel';
import SettingsModal from './voice/SettingsModal';
import { useVoiceController, VoiceState } from './voice/useVoiceController';
import {
  VOICES,
  VoiceDef,
  getDefaultVoice,
  getVoiceById,
  findBrowserVoice,
  LS_VOICE_ID,
} from './voice/voices';
import {
  PERSONALITIES,
  PersonalityDef,
  getDefaultPersonality,
  getPersonalityById,
  LS_PERSONALITY_ID,
} from './voice/personalities';

// localStorage keys
const LS_SPEED = 'homepilot_speech_speed';
const LS_MUTED = 'homepilot_voice_muted';
const LS_HANDSFREE = 'homepilot_voice_handsfree';
const LS_SHOW_METER = 'homepilot_voice_show_meter';

// Message type
interface Message {
  role: 'user' | 'assistant';
  text: string;
}

// State messages
const STATE_MESSAGES: Record<VoiceState, string> = {
  OFF: 'You may start speaking',
  IDLE: 'Listening for voice...',
  LISTENING: 'Listening...',
  THINKING: 'Processing...',
  SPEAKING: 'Speaking...',
};

/**
 * Typewriter Component - Grok-style void typing effect
 *
 * Renders text character by character with a blinking cursor,
 * creating a premium "AI is typing" experience.
 */
function Typewriter({
  text,
  speed = 10,
  onProgress,
}: {
  text: string;
  speed?: number;
  onProgress?: () => void;
}) {
  const [displayed, setDisplayed] = useState('');
  const idxRef = useRef(0);

  // Reset when text changes
  useEffect(() => {
    setDisplayed('');
    idxRef.current = 0;
  }, [text]);

  // Typewriter effect
  useEffect(() => {
    if (!text) return;

    const interval = setInterval(() => {
      if (idxRef.current < text.length) {
        idxRef.current += 1;
        setDisplayed(text.slice(0, idxRef.current));
        onProgress?.();
      } else {
        clearInterval(interval);
      }
    }, speed);

    return () => clearInterval(interval);
  }, [text, speed, onProgress]);

  const isTyping = displayed.length < text.length;

  return (
    <span>
      {displayed}
      {isTyping && <span className="inline-block w-[2px] h-[1em] bg-white/80 ml-[1px] hp-cursor align-middle" />}
    </span>
  );
}

interface VoiceModeGrokProps {
  onSendText: (text: string) => void;
  onClose?: () => void;
}

export default function VoiceModeGrok({ onSendText, onClose }: VoiceModeGrokProps) {
  // Messages state
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState('');

  // Settings panel states
  const [showVoiceSettings, setShowVoiceSettings] = useState(false);
  const [showSystemSettings, setShowSystemSettings] = useState(false);

  // Voice configuration
  const [activeVoice, setActiveVoice] = useState<VoiceDef>(() => {
    if (typeof window !== 'undefined') {
      const savedId = localStorage.getItem(LS_VOICE_ID);
      if (savedId) {
        const voice = getVoiceById(savedId as any);
        if (voice) return voice;
      }
    }
    return getDefaultVoice();
  });

  const [activePersonality, setActivePersonality] = useState<PersonalityDef>(() => {
    if (typeof window !== 'undefined') {
      const savedId = localStorage.getItem(LS_PERSONALITY_ID);
      if (savedId) {
        const personality = getPersonalityById(savedId as any);
        if (personality) return personality;
      }
    }
    return getDefaultPersonality();
  });

  const [speed, setSpeed] = useState(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem(LS_SPEED);
      if (saved) return parseFloat(saved);
    }
    return 1.0;
  });

  const [isMuted, setIsMuted] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem(LS_MUTED) === 'true';
    }
    return false;
  });

  // Audio meter visibility (can be toggled in settings) - OFF by default
  const [showAudioMeter, setShowAudioMeter] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem(LS_SHOW_METER) === 'true'; // Default to false
    }
    return false;
  });

  // Refs
  const menuRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Use the existing voice controller
  const voice = useVoiceController(handleVoiceInput);

  // Restore hands-free preference (Alexa-like behavior) - DEFAULT TO ON for best UX
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const saved = localStorage.getItem(LS_HANDSFREE);
    // Default to hands-free ON if no preference saved (best user experience)
    if (saved === null || saved === 'true') {
      voice.setHandsFree(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist hands-free preference
  useEffect(() => {
    if (typeof window === 'undefined') return;
    localStorage.setItem(LS_HANDSFREE, String(voice.isHandsFree));
  }, [voice.isHandsFree]);

  // Persist audio meter visibility
  useEffect(() => {
    if (typeof window === 'undefined') return;
    localStorage.setItem(LS_SHOW_METER, String(showAudioMeter));
  }, [showAudioMeter]);

  // Handle voice input
  function handleVoiceInput(text: string) {
    if (!text.trim()) return;

    // Add user message
    const userMsg: Message = { role: 'user', text: text.trim() };
    setMessages((prev) => [...prev, userMsg]);

    // Forward to parent handler
    onSendText(text.trim());
  }

  // Persist voice selection
  useEffect(() => {
    localStorage.setItem(LS_VOICE_ID, activeVoice.id);

    // Update speech service with new voice settings
    if (window.SpeechService) {
      const browserVoices = window.SpeechService.getVoices?.() || [];
      const matchedVoice = findBrowserVoice(activeVoice, browserVoices);
      if (matchedVoice) {
        window.SpeechService.setPreferredVoiceURI?.(matchedVoice.voiceURI);
      }
      window.SpeechService.setVoiceConfig?.({
        rate: activeVoice.rate * speed,
        pitch: activeVoice.pitch,
      });
    }
  }, [activeVoice, speed]);

  // Persist personality selection
  useEffect(() => {
    localStorage.setItem(LS_PERSONALITY_ID, activePersonality.id);
  }, [activePersonality]);

  // Persist speed
  useEffect(() => {
    localStorage.setItem(LS_SPEED, speed.toString());
    if (window.SpeechService) {
      window.SpeechService.setVoiceConfig?.({
        rate: activeVoice.rate * speed,
      });
    }
  }, [speed, activeVoice.rate]);

  // Persist muted state
  useEffect(() => {
    localStorage.setItem(LS_MUTED, isMuted.toString());
    voice.setTtsEnabled(!isMuted);
  }, [isMuted, voice.setTtsEnabled]);

  // Close settings panel on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowVoiceSettings(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Auto-scroll messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  // Scroll to bottom helper - used by Typewriter for continuous scroll
  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  // Listen for assistant messages from App.tsx (event bridge)
  useEffect(() => {
    const handler = (e: CustomEvent<{ id: string; text: string }>) => {
      const text = e?.detail?.text;
      if (!text) return;

      // Add assistant message for typewriter rendering
      setMessages((prev) => [...prev, { role: 'assistant', text: String(text) }]);
    };

    window.addEventListener('hp:assistant_message', handler as EventListener);
    return () => window.removeEventListener('hp:assistant_message', handler as EventListener);
  }, []);

  // Handle text input submit
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText.trim()) return;

    handleVoiceInput(inputText);
    setInputText('');
  };

  // Toggle mic
  const toggleMic = () => {
    if (voice.state === 'LISTENING') {
      voice.stopManualListening();
    } else if (voice.state === 'SPEAKING') {
      voice.stopSpeaking();
    } else {
      voice.startManualListening();
    }
  };

  // Clear conversation
  const clearConversation = () => {
    setMessages([]);
  };

  const isListening = voice.state === 'LISTENING';
  const isThinking = voice.state === 'THINKING';
  const isSpeaking = voice.state === 'SPEAKING';
  const isIdle = voice.state === 'IDLE';

  // Dynamic glow intensity based on voice state (crystal reflection effect)
  const glowOpacity =
    isSpeaking ? 0.38 :   // Brighter glow when AI speaks
    isThinking ? 0.18 :
    isListening ? 0.15 :
    isIdle ? 0.10 :
    0.06;

  // Typing speed synced with TTS state for premium feel
  const typingSpeed =
    isSpeaking ? 7 :   // Fast while TTS is speaking
    isThinking ? 12 :  // Medium while processing
    9;                 // Default

  // Error message mapping for user-friendly display
  const getErrorMessage = (error: string | null): string | null => {
    if (!error) return null;
    switch (error) {
      case 'stt_not_supported':
        return 'Speech recognition not supported. Try Chrome (HTTPS).';
      case 'not-allowed':
        return 'Microphone permission denied. Enable in browser settings.';
      case 'audio-capture':
        return 'Microphone not available. Check your audio device.';
      case 'network':
        return 'Network error. Check your internet connection.';
      case 'vad_start_failed':
        return 'Voice detection failed to start. Try refreshing.';
      default:
        return `Voice error: ${error}`;
    }
  };

  // Check if speech service is available
  if (!window.SpeechService) {
    return (
      <div className="hp-voice-root flex items-center justify-center">
        <Starfield />
        <div className="relative z-10 text-center p-8">
          <div className="text-6xl mb-4">🎤</div>
          <div className="text-xl font-semibold text-white mb-2">HomePilot Voice</div>
          <div className="text-sm text-white/50">
            Speech service not loaded. Please refresh the page.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="hp-voice-root">
      {/* Settings Modal - Contains advanced audio settings */}
      <SettingsModal
        isOpen={showSystemSettings}
        onClose={() => setShowSystemSettings(false)}
        showAudioMeter={showAudioMeter}
        setShowAudioMeter={setShowAudioMeter}
        browserVoices={voice.voices}
        selectedBrowserVoice={voice.selectedVoice}
        setSelectedBrowserVoice={voice.setSelectedVoice}
      />

      {/* Starfield Background */}
      <Starfield />

      {/* Top Header */}
      <header className="absolute top-0 right-0 z-30 p-4 flex items-center gap-2 hp-fade-in">
        <button
          onClick={() => setShowSystemSettings(true)}
          className="w-9 h-9 flex items-center justify-center rounded-full bg-white/5 border border-white/10 text-white/60 hover:bg-white/10 hover:text-white transition-colors"
          title="System Settings"
        >
          <Settings size={18} />
        </button>
        {messages.length > 0 && (
          <>
            <button className="h-9 px-4 flex items-center gap-2 rounded-full bg-white/5 border border-white/10 text-white/70 hover:bg-white/10 transition-colors text-sm font-medium">
              <Share size={14} />
              Share
            </button>
            <button
              onClick={clearConversation}
              className="w-9 h-9 flex items-center justify-center rounded-full bg-white/5 border border-white/10 text-white/60 hover:bg-white/10 transition-colors"
              title="New Chat"
            >
              <PenLine size={16} />
            </button>
          </>
        )}
      </header>

      {/* Center Content Area */}
      <div
        className="flex-1 flex flex-col items-center justify-center px-6 overflow-y-auto pb-48 hp-scroll relative z-10"
        ref={scrollRef}
      >
        {messages.length === 0 ? (
          /* Idle State */
          <div className="flex flex-col items-center gap-4 text-white/50 hp-fade-in">
            {/* Waveform icon */}
            <div className="flex gap-1 items-end h-6">
              <div
                className="w-[3px] bg-white/60 rounded-full hp-pulse"
                style={{ height: '8px', animationDelay: '0s' }}
              />
              <div
                className="w-[3px] bg-white/60 rounded-full hp-pulse"
                style={{ height: '16px', animationDelay: '0.1s' }}
              />
              <div
                className="w-[3px] bg-white/60 rounded-full hp-pulse"
                style={{ height: '24px', animationDelay: '0.2s' }}
              />
              <div
                className="w-[3px] bg-white/60 rounded-full hp-pulse"
                style={{ height: '16px', animationDelay: '0.3s' }}
              />
              <div
                className="w-[3px] bg-white/60 rounded-full hp-pulse"
                style={{ height: '8px', animationDelay: '0.4s' }}
              />
            </div>
            <p className="text-base font-medium">
              {voice.interimText || STATE_MESSAGES[voice.state]}
            </p>

            {/* Voice diagnostics - STT support and error messages */}
            {!voice.sttSupported && (
              <div className="flex items-center gap-2 text-sm text-amber-300/80 max-w-md text-center px-4 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
                <AlertCircle size={16} className="shrink-0" />
                <span>Speech recognition not supported in this browser. Try Chrome (HTTPS/localhost).</span>
              </div>
            )}
            {voice.lastError && (
              <div className="flex items-center gap-2 text-sm text-red-300/80 max-w-md text-center px-4 py-2 rounded-lg bg-red-500/10 border border-red-500/20">
                <AlertCircle size={16} className="shrink-0" />
                <span>{getErrorMessage(voice.lastError)}</span>
              </div>
            )}

            {/* Hands-free mode indicator */}
            {voice.isHandsFree && voice.state === 'IDLE' && (
              <div className="flex items-center gap-2 text-xs text-white/40">
                <Zap size={12} />
                <span>Hands-free mode active</span>
              </div>
            )}
          </div>
        ) : (
          /* Conversation View */
          <div className="w-full max-w-3xl space-y-6 pt-16 hp-slide-up">
            {messages.map((msg, idx) => (
              <div key={idx} className={msg.role === 'user' ? 'flex justify-end' : ''}>
                {msg.role === 'user' ? (
                  <div className="hp-message-user">
                    <p className="text-white/90 text-[17px] leading-relaxed">{msg.text}</p>
                  </div>
                ) : (
                  <div className="hp-message-assistant text-[17px]">
                    {msg.text.split('\n').map((line, i) => {
                      const isBullet = line.trim().startsWith('•');
                      const content = isBullet ? line.substring(line.indexOf('•') + 1).trim() : line;

                      if (isBullet) {
                        return (
                          <div key={i} className="ml-4 my-1 flex gap-2">
                            <span>•</span>
                            <span>
                              <Typewriter text={content} speed={typingSpeed} onProgress={scrollToBottom} />
                            </span>
                          </div>
                        );
                      }
                      return line ? (
                        <p key={i} className="my-2">
                          <Typewriter text={line} speed={typingSpeed} onProgress={scrollToBottom} />
                        </p>
                      ) : (
                        <div key={i} className="h-2"></div>
                      );
                    })}
                  </div>
                )}
              </div>
            ))}

            {/* Show interim text while listening */}
            {voice.interimText && (
              <div className="flex justify-end">
                <div className="hp-message-user opacity-70">
                  <p className="text-white/70 text-[17px] leading-relaxed italic">
                    {voice.interimText}...
                  </p>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Bottom Voice Bar */}
      <div className="absolute bottom-0 left-0 right-0 p-4 z-40">
        <div className="max-w-3xl mx-auto">
          <div className="hp-voicebar">
            {/* Dynamic Glow Effect - Crystal reflection based on voice state */}
            <div className="hp-glow-wrap absolute -left-[60px] -right-[60px] -bottom-[62px] h-[100px] overflow-hidden rounded-b-[28px]">
              <div
                className={`absolute inset-0 transition-opacity duration-500 ${isSpeaking ? 'hp-glow-breath' : ''}`}
                style={{ opacity: glowOpacity }}
              >
                <div className="g1 absolute top-0 bottom-0 left-0 w-[60%]"></div>
                <div className="g2 absolute top-0 bottom-0 left-0 w-full"></div>
                <div className="g3 absolute top-0 bottom-0 right-0 w-[60%]"></div>
              </div>
            </div>

            <div className="relative p-4 pb-16">
              {/* Audio Level Monitor - Visible when hands-free mode is ON */}
              {voice.isHandsFree && voice.state !== 'OFF' && showAudioMeter && (
                <div className="mb-3 px-1">
                  <div className="h-2 bg-white/10 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-100 ${
                        isListening
                          ? 'bg-gradient-to-r from-green-400 to-green-300'
                          : 'bg-white/50'
                      }`}
                      style={{ width: `${Math.min(voice.audioLevel * 500, 100)}%` }}
                    />
                  </div>
                  <div className="mt-1 flex justify-between text-[10px] text-white/35 font-mono">
                    <span>Noise {voice.noiseFloor.toFixed(3)}</span>
                    <span>Level {voice.audioLevel.toFixed(3)}</span>
                    <span>Thresh {voice.threshold.toFixed(3)}</span>
                  </div>
                </div>
              )}

              {/* Text Input */}
              <form onSubmit={handleSubmit}>
                <input
                  type="text"
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  placeholder={
                    isListening
                      ? 'Listening...'
                      : voice.isHandsFree
                        ? 'Hands-free mode - speak anytime...'
                        : 'How can HomePilot help?'
                  }
                  className="hp-input"
                />
              </form>

              {/* Controls Row */}
              <div
                className="absolute left-3 right-3 bottom-3 flex items-center justify-between"
                ref={menuRef}
              >
                <div className="flex items-center gap-2 relative">
                  {/* Mic Button */}
                  <button
                    onClick={toggleMic}
                    className={`h-10 px-4 rounded-full border flex items-center gap-2.5 transition-all ${
                      isListening
                        ? 'bg-[#97C4FF]/20 border-[#97C4FF]/40 text-white'
                        : 'bg-white/5 border-white/10 text-white/70 hover:bg-white/10'
                    }`}
                  >
                    {isListening ? (
                      <div className="flex gap-[3px] items-end h-3.5">
                        {[0.4, 0.7, 1, 0.7, 0.4].map((h, i) => (
                          <div
                            key={i}
                            className="w-[2px] bg-[#97C4FF] rounded-full hp-pulse"
                            style={{ height: `${h * 100}%`, animationDelay: `${i * 0.1}s` }}
                          />
                        ))}
                      </div>
                    ) : (
                      <>
                        <div className="flex gap-[2px] items-end h-3.5 opacity-40">
                          <div className="w-[2px] h-2 bg-white rounded-full"></div>
                          <div className="w-[2px] h-3 bg-white rounded-full"></div>
                          <div className="w-[2px] h-2 bg-white rounded-full"></div>
                        </div>
                        <Mic size={18} />
                      </>
                    )}
                  </button>

                  {/* Volume Toggle */}
                  <button
                    onClick={() => setIsMuted(!isMuted)}
                    className="w-10 h-10 rounded-full border border-white/10 bg-white/5 flex items-center justify-center text-white/70 hover:bg-white/10 transition-colors"
                  >
                    {isMuted ? (
                      <VolumeX size={18} className="opacity-50" />
                    ) : (
                      <Volume2 size={18} />
                    )}
                  </button>

                  {/* Voice Settings Trigger */}
                  <button
                    onClick={() => setShowVoiceSettings(!showVoiceSettings)}
                    className={`h-10 px-3.5 rounded-full border flex items-center gap-2 transition-all text-sm ${
                      showVoiceSettings
                        ? 'bg-white/10 border-white/20'
                        : 'bg-white/5 border-white/10 hover:bg-white/10'
                    }`}
                  >
                    <SlidersHorizontal size={16} className="text-white/50" />
                    <span className="font-semibold text-white/90">{activeVoice.name}</span>
                    <span className="text-white/40 font-medium">
                      · {activePersonality.label}
                    </span>
                    <ChevronDown
                      size={14}
                      className={`text-white/40 transition-transform ${
                        showVoiceSettings ? 'rotate-180' : ''
                      }`}
                    />
                  </button>

                  {/* Voice Settings Panel */}
                  {/* Voice Settings Panel - Voice persona, personality, speed */}
                  <VoiceSettingsPanel
                    isOpen={showVoiceSettings}
                    activeVoice={activeVoice}
                    setActiveVoice={setActiveVoice}
                    activePersonality={activePersonality}
                    setActivePersonality={setActivePersonality}
                    speed={speed}
                    setSpeed={setSpeed}
                  />
                </div>

                {/* Hands-Free Toggle (Auto/Manual) - Replaces close button */}
                <button
                  onClick={() => voice.setHandsFree(!voice.isHandsFree)}
                  className={`w-10 h-10 rounded-full flex items-center justify-center transition-all shadow-lg ${
                    voice.isHandsFree
                      ? 'bg-white text-black hover:bg-gray-200'
                      : 'bg-white/10 border border-white/20 text-white/80 hover:bg-white/20'
                  }`}
                  title={
                    voice.isHandsFree
                      ? 'Hands-free mode ON (Auto) - Click to switch to Manual'
                      : 'Manual mode - Click to enable Hands-free (Auto)'
                  }
                >
                  {voice.isHandsFree ? (
                    <Zap size={20} />
                  ) : (
                    <Radio size={20} />
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

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
  PenLine,
  Zap,
  Radio,
  AlertCircle,
  X,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Download,
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
import { User } from 'lucide-react';
import {
  LS_PERSONA_CACHE,
} from './voice/personalityGating';

// localStorage keys
const LS_SPEED = 'homepilot_speech_speed';
const LS_MUTED = 'homepilot_voice_muted';
const LS_HANDSFREE = 'homepilot_voice_handsfree';
const LS_SHOW_METER = 'homepilot_voice_show_meter';

// ---------------------------------------------------------------------------
// Markdown-aware helpers for Voice mode
// ---------------------------------------------------------------------------

/** Regex matching markdown images: ![alt](url) */
const RE_MD_IMAGE = /!\[([^\]]*)\]\(([^)]+)\)/g;
/** Regex matching markdown links: [text](url) */
const RE_MD_LINK = /\[([^\]]*)\]\(([^)]+)\)/g;

/**
 * Strip markdown images and links from text for TTS.
 * - ![alt](url) → removes entirely (image should be seen, not read)
 * - [text](url) → keeps only the link text (the URL is not spoken)
 * - Collapses leftover whitespace so speech sounds natural.
 */
export function stripMarkdownForSpeech(text: string): string {
  return text
    // Remove image markdown entirely (the user sees the image, no need to speak it)
    .replace(RE_MD_IMAGE, '')
    // Replace link markdown with just the visible text
    .replace(RE_MD_LINK, '$1')
    // Clean up arrows pointing to removed images (e.g. "outfit → " becomes "outfit")
    .replace(/\s*→\s*$/gm, '')
    // Collapse multiple spaces / blank lines left behind
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/**
 * Parse a single line of text and return React nodes,
 * rendering inline markdown images ![alt](url) and links [text](url)
 * as actual <img> / <a> elements. Everything else is plain text.
 */
function parseInlineMarkdown(
  line: string,
  onImageClick?: (src: string) => void,
): React.ReactNode[] {
  // Combined regex: images first (so ![...] doesn't match as [...]  link)
  const RE_INLINE = /(!?\[([^\]]*)\]\(([^)]+)\))/g;
  const nodes: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = RE_INLINE.exec(line)) !== null) {
    // Push text before this match
    if (match.index > lastIndex) {
      nodes.push(line.slice(lastIndex, match.index));
    }
    const fullMatch = match[1];
    const alt = match[2];
    const url = match[3];
    const isImage = fullMatch.startsWith('!');

    if (isImage) {
      nodes.push(
        <img
          key={`img-${match.index}`}
          src={url}
          alt={alt || 'Photo'}
          className="inline-block max-h-72 max-w-72 w-auto h-auto object-contain rounded-xl border border-white/10 bg-black/20 cursor-zoom-in hover:opacity-90 transition-opacity my-2"
          loading="lazy"
          onClick={() => onImageClick?.(url)}
        />
      );
    } else {
      // It's a link [text](url) — render as clickable image if URL looks like an image,
      // otherwise render as a styled link.
      const looksLikeImage = /\.(png|jpe?g|gif|webp|svg|bmp)|\/view\?filename=|\/uploads\//i.test(url);
      if (looksLikeImage) {
        // Treat as an image (LLMs often drop the ! prefix)
        nodes.push(
          <img
            key={`lnkimg-${match.index}`}
            src={url}
            alt={alt || 'Photo'}
            className="inline-block max-h-72 max-w-72 w-auto h-auto object-contain rounded-xl border border-white/10 bg-black/20 cursor-zoom-in hover:opacity-90 transition-opacity my-2"
            loading="lazy"
            onClick={() => onImageClick?.(url)}
          />
        );
      } else {
        nodes.push(
          <a
            key={`lnk-${match.index}`}
            href={url}
            target="_blank"
            rel="noreferrer"
            className="text-blue-400 underline hover:text-blue-300"
          >
            {alt}
          </a>
        );
      }
    }
    lastIndex = match.index + fullMatch.length;
  }

  // Push any remaining text after the last match
  if (lastIndex < line.length) {
    nodes.push(line.slice(lastIndex));
  }

  return nodes.length > 0 ? nodes : [line];
}

// Message type with stable ID for deduplication
interface Message {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  media?: {
    images?: string[];
    video_url?: string;
  } | null;
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
 * useSmoothedLevel Hook - Smooth audio level with attack/release
 *
 * Fast attack (responds quickly to loud sounds), slow release (fades smoothly).
 * Creates professional-feeling meter animation.
 */
function useSmoothedLevel(level: number) {
  const [smooth, setSmooth] = useState(0);
  const lastRef = useRef(0);

  useEffect(() => {
    // Attack fast (0.55), release slower (0.12) for natural feel
    const attack = 0.55;
    const release = 0.12;
    const target = Math.max(0, Math.min(1, level));

    const prev = lastRef.current;
    const next = target > prev
      ? prev + (target - prev) * attack
      : prev + (target - prev) * release;

    lastRef.current = next;
    setSmooth(next);
  }, [level]);

  return smooth;
}

/**
 * intensityColor - Maps audio level to intensity-based color gradient
 *
 * Creates a professional "heat map" effect:
 * - Low: cool white/gray
 * - Medium: icy blue
 * - High: purple/magenta
 * - Peak: warm orange
 */
function intensityColor(level01: number): string {
  if (level01 < 0.35) return 'rgba(255,255,255,0.65)';     // cool white/gray
  if (level01 < 0.70) return 'rgba(151,196,255,0.85)';     // icy blue
  if (level01 < 0.90) return 'rgba(190,120,255,0.90)';     // purple/magenta
  return 'rgba(255,170,100,0.95)';                          // warm orange (peak)
}

/**
 * MiniStudioMeter Component - Professional studio-quality audio visualizer
 *
 * Features:
 * - Attack/release smoothing for natural animation
 * - Intensity-based color gradient (not just green)
 * - Idle state: subtle gray dots
 * - Active state: dynamic glowing bars
 * - Micro jitter for liveliness when speaking
 * - Different tint when AI is speaking
 */
function MiniStudioMeter({
  audioLevel,
  isUserActive,
  isAiSpeaking,
}: {
  audioLevel: number;     // voice.audioLevel (0..~0.2)
  isUserActive: boolean;  // LISTENING/IDLE in hands-free mode
  isAiSpeaking: boolean;  // SPEAKING state
}) {
  // Map audioLevel into usable 0..1 range (multiplier tuned for sensitivity)
  const norm = Math.max(0, Math.min(1, audioLevel * 8));
  const level = useSmoothedLevel(norm);

  // Idle mode: almost static, subtle dots/bars
  const idle = !isUserActive || level < 0.04;

  // Add micro jitter only when active to feel "alive"
  const jitter = !idle ? (Math.random() * 0.06 - 0.03) : 0;

  // Create 5 bars with different sensitivity thresholds
  // Lower thresholds = more sensitive (bars light up earlier)
  const bars = [0.10, 0.22, 0.38, 0.54, 0.72].map((t) => {
    // Boost higher bars more for detailed look at high levels
    const v = (level - (t - 0.12)) / 0.26;
    const clamped = Math.max(0, Math.min(1, v));
    return idle ? 0.18 : Math.max(0.14, clamped + jitter);
  });

  // Color by intensity, but shift when AI speaking
  const baseColor = intensityColor(level);
  const barColor = isAiSpeaking ? 'rgba(233,232,231,0.85)' : baseColor;

  return (
    <div
      className={`hp-mini-studio ${idle ? 'hp-mini-studio--idle' : 'hp-mini-studio--hot'} ${
        isAiSpeaking ? 'hp-mini-studio--ai' : ''
      }`}
      style={{ ['--hp-meter-color' as string]: barColor }}
      aria-hidden="true"
    >
      {bars.map((b, i) => (
        <span
          key={i}
          className="hp-mini-studio-bar"
          style={{ transform: `scaleY(${b})` }}
        />
      ))}
    </div>
  );
}

/**
 * useTypewriterText Hook - Single timeline typewriter for entire message
 *
 * Types text character by character across the entire message (including newlines),
 * creating a sequential "AI is typing" experience instead of parallel paragraphs.
 */
function useTypewriterText(
  text: string,
  speed: number,
  onProgress?: () => void,
  enabled: boolean = true
) {
  const [displayed, setDisplayed] = useState(enabled ? '' : text);
  const idxRef = useRef(0);
  const intervalRef = useRef<number | null>(null);
  const speedRef = useRef(speed);

  // Update speed without restarting typing (prevents restart when TTS state changes)
  useEffect(() => {
    speedRef.current = speed;
  }, [speed]);

  // Restart typing ONLY when text changes (or enabled toggles)
  useEffect(() => {
    // If not enabled, show full text immediately
    if (!enabled) {
      setDisplayed(text);
      return;
    }

    // Reset when a new text starts typing
    setDisplayed('');
    idxRef.current = 0;

    // Clear any previous interval
    if (intervalRef.current) window.clearInterval(intervalRef.current);

    intervalRef.current = window.setInterval(() => {
      if (idxRef.current >= text.length) {
        if (intervalRef.current) window.clearInterval(intervalRef.current);
        intervalRef.current = null;
        return;
      }

      idxRef.current += 1;
      setDisplayed(text.slice(0, idxRef.current));
      onProgress?.();
    }, speedRef.current);

    return () => {
      if (intervalRef.current) window.clearInterval(intervalRef.current);
      intervalRef.current = null;
    };
  }, [text, onProgress, enabled]); // speed removed - uses speedRef instead

  const isTyping = enabled && displayed.length < text.length;
  return { displayed, isTyping };
}

/**
 * RenderTypedMessage Component - Formats partially-typed text with proper styling
 *
 * Renders the typewriter output with:
 * - Paragraph formatting
 * - Bullet lines (starting with "•")
 * - Blank line spacing
 * - Cursor only at end of currently typing line
 * - Click-to-expand lightbox for generated images
 */
function RenderTypedMessage({
  fullText,
  typingSpeed,
  onProgress,
  animate,
  media,
  onImageClick,
}: {
  fullText: string;
  typingSpeed: number;
  onProgress?: () => void;
  animate: boolean;
  media?: Message['media'];
  onImageClick?: (src: string) => void;
}) {
  const { displayed, isTyping } = useTypewriterText(fullText, typingSpeed, onProgress, animate);
  const lines = displayed.split('\n');

  return (
    <div className="hp-message-assistant text-[17px]">
      {lines.map((line, i) => {
        const isLastLine = i === lines.length - 1;
        const showCursor = isTyping && isLastLine;

        const trimmed = line.trim();
        const isBullet = trimmed.startsWith('•');
        const content = isBullet ? line.substring(line.indexOf('•') + 1).trim() : line;

        if (trimmed === '') {
          // Preserve blank lines (paragraph spacing)
          return <div key={i} className="h-2" />;
        }

        if (isBullet) {
          return (
            <div key={i} className="ml-4 my-1 flex gap-2">
              <span>•</span>
              <span>
                {parseInlineMarkdown(content, onImageClick)}
                {showCursor && (
                  <span className="inline-block w-[2px] h-[1em] bg-white/80 ml-[1px] hp-cursor align-middle" />
                )}
              </span>
            </div>
          );
        }

        return (
          <p key={i} className="my-2">
            {parseInlineMarkdown(line, onImageClick)}
            {showCursor && (
              <span className="inline-block w-[2px] h-[1em] bg-white/80 ml-[1px] hp-cursor align-middle" />
            )}
          </p>
        );
      })}

      {/* Render generated images - larger display with click-to-expand */}
      {media?.images?.length ? (
        <div className="mt-3 flex gap-3 overflow-x-auto">
          {media.images.map((src, i) => (
            <img
              key={i}
              src={src}
              alt={`Generated ${i + 1}`}
              className="max-h-80 max-w-80 w-auto h-auto object-contain rounded-xl border border-white/10 bg-black/20 cursor-zoom-in hover:opacity-90 transition-opacity"
              loading="lazy"
              onClick={() => onImageClick?.(src)}
            />
          ))}
        </div>
      ) : null}

      {/* Render generated video */}
      {media?.video_url ? (
        <div className="mt-3">
          <video
            src={media.video_url}
            controls
            playsInline
            className="w-full max-w-xl rounded-xl border border-white/10 bg-black/20"
          />
        </div>
      ) : null}
    </div>
  );
}

/**
 * VoiceLightbox Component - Full-screen image viewer for voice mode
 *
 * Displays generated images at full resolution with zoom controls and download.
 * Click backdrop or X to close.
 */
function VoiceLightbox({ src, onClose }: { src: string; onClose: () => void }) {
  const [zoom, setZoom] = useState(100);

  const handleDownload = async () => {
    try {
      const response = await fetch(src);
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `homepilot-${Date.now()}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Download failed:', error);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/95 backdrop-blur-sm flex flex-col"
      onClick={onClose}
    >
      {/* Top Controls */}
      <div className="absolute top-0 left-0 right-0 flex items-center justify-between p-4 bg-gradient-to-b from-black/80 to-transparent z-10">
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => { e.stopPropagation(); handleDownload(); }}
            className="p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-colors text-white"
            title="Download"
          >
            <Download size={18} />
          </button>
          <div className="w-px h-6 bg-white/20" />
          <button
            onClick={(e) => { e.stopPropagation(); setZoom((z) => Math.max(z - 25, 25)); }}
            className="p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-colors text-white"
            title="Zoom out"
            disabled={zoom <= 25}
          >
            <ZoomOut size={18} />
          </button>
          <span className="text-sm font-medium px-2 min-w-[4rem] text-center text-white">
            {zoom}%
          </span>
          <button
            onClick={(e) => { e.stopPropagation(); setZoom((z) => Math.min(z + 25, 300)); }}
            className="p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-colors text-white"
            title="Zoom in"
            disabled={zoom >= 300}
          >
            <ZoomIn size={18} />
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); setZoom(100); }}
            className="p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-colors text-white"
            title="Reset zoom"
          >
            <Maximize2 size={18} />
          </button>
        </div>
        <button
          onClick={onClose}
          className="p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-colors text-white"
          aria-label="Close"
        >
          <X size={24} />
        </button>
      </div>

      {/* Image */}
      <div className="flex-1 flex items-center justify-center p-16 overflow-auto">
        <img
          src={src}
          onClick={(e) => e.stopPropagation()}
          className="rounded-lg shadow-2xl border border-white/10 transition-transform"
          style={{
            transform: `scale(${zoom / 100})`,
            maxWidth: '90vw',
            maxHeight: '80vh',
            objectFit: 'contain',
          }}
          alt="Generated image preview"
        />
      </div>
    </div>
  );
}

interface VoiceModeGrokProps {
  onSendText: (text: string) => void;
  onClose?: () => void;
  onNewChat?: () => void;
}

export default function VoiceModeGrok({ onSendText, onClose, onNewChat }: VoiceModeGrokProps) {
  // Messages state
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState('');

  // Lightbox state for full-screen image viewing
  const [lightbox, setLightbox] = useState<string | null>(null);

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
        // Restore persona selection from cache
        if (savedId.startsWith('persona:')) {
          try {
            const cached = localStorage.getItem(LS_PERSONA_CACHE);
            if (cached) {
              const personas = JSON.parse(cached) as Array<{ id: string; label: string; role: string; tone: string; system_prompt: string }>;
              const projId = savedId.slice('persona:'.length);
              const persona = personas.find((p) => p.id === projId);
              if (persona) {
                return {
                  id: savedId,
                  label: persona.label,
                  icon: User,
                  prompt: persona.system_prompt || '',
                  isPersona: true,
                  personaSystemPrompt: persona.system_prompt,
                  personaTone: persona.tone,
                  personaRole: persona.role,
                };
              }
            }
          } catch { /* fall through to default */ }
        }
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

    // Add user message with unique ID
    const userMsg: Message = { id: `user-${Date.now()}`, role: 'user', text: text.trim() };
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
  // Ignores clicks inside portaled dropdowns (PersonalityList) so selections can complete
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement;

      // Ignore clicks inside portaled voice dropdowns (PersonalityList overlay/panel)
      if (target?.closest?.('[data-hp-voice-portal="true"]')) {
        return;
      }

      if (menuRef.current && !menuRef.current.contains(target)) {
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
  // Deduplicates by ID to prevent double-append from StrictMode, retries, or TTS events
  useEffect(() => {
    const handler = (e: CustomEvent<{ id: string; text: string; media?: Message['media'] }>) => {
      const id = e?.detail?.id;
      const text = e?.detail?.text;
      const media = e?.detail?.media;
      if (!id || !text) return;

      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.id === id);
        if (idx >= 0) {
          // Update existing message (streaming update)
          const copy = [...prev];
          copy[idx] = { ...copy[idx], text: String(text), media: media ?? copy[idx].media };
          return copy;
        }
        // New message
        return [...prev, { id, role: 'assistant', text: String(text), media: media ?? null }];
      });
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

  // Clear conversation — reset local messages AND tell App.tsx to
  // generate a new voiceConversationId so backend personality memory
  // starts fresh (the old conversation ID's memory will be GC'd).
  const clearConversation = () => {
    setMessages([]);
    onNewChat?.();
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
        <button
          onClick={clearConversation}
          className="w-9 h-9 flex items-center justify-center rounded-full bg-white/5 border border-white/10 text-white/60 hover:bg-white/10 hover:text-white transition-colors"
          title="New Chat"
        >
          <PenLine size={16} />
        </button>
      </header>

      {/* Center Content Area */}
      <div
        className="flex-1 flex flex-col items-center px-6 overflow-y-auto pb-48 hp-scroll relative z-10"
        style={{ minHeight: 0 }}
        ref={scrollRef}
      >
        {messages.length === 0 ? (
          /* Idle State */
          <div className="flex-1 flex flex-col items-center justify-center gap-4 text-white/50 hp-fade-in">
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
              <div key={msg.id} className={msg.role === 'user' ? 'flex justify-end' : ''}>
                {msg.role === 'user' ? (
                  <div className="hp-message-user">
                    <p className="text-white/90 text-[17px] leading-relaxed">{msg.text}</p>
                  </div>
                ) : (
                  <RenderTypedMessage
                    fullText={msg.text}
                    typingSpeed={typingSpeed}
                    onProgress={scrollToBottom}
                    animate={idx === messages.length - 1}
                    media={msg.media}
                    onImageClick={(src) => setLightbox(src)}
                  />
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
                  {/* Mic Button with Mini Level Meter */}
                  <button
                    onClick={toggleMic}
                    className={`h-10 px-4 rounded-full border flex items-center gap-2.5 transition-all ${
                      isListening
                        ? 'bg-[#97C4FF]/20 border-[#97C4FF]/40 text-white'
                        : 'bg-white/5 border-white/10 text-white/70 hover:bg-white/10'
                    }`}
                  >
                    <MiniStudioMeter
                      audioLevel={voice.audioLevel}
                      isUserActive={voice.state === 'LISTENING' || voice.state === 'IDLE'}
                      isAiSpeaking={voice.state === 'SPEAKING'}
                    />
                    <Mic size={18} />
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

      {/* Full-screen image lightbox */}
      {lightbox && (
        <VoiceLightbox
          src={lightbox}
          onClose={() => setLightbox(null)}
        />
      )}
    </div>
  );
}

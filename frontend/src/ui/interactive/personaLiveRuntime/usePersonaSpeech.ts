/**
 * usePersonaSpeech — browser TTS for the Persona Live runtime.
 *
 * Why Web Speech API
 * ------------------
 * The user wants the AI to "speak" in Persona Live (candy.ai-style
 * companion experience). The repo's ``synthesize_voice_clip`` is a
 * Phase-1 placeholder that doesn't actually produce audio, and
 * wiring an external provider (ElevenLabs / Azure TTS / Coqui) is
 * a sizable scope decision that needs API keys + cost-budget +
 * voice-library curation. The browser's Web Speech API gives us a
 * zero-dep, zero-latency v1 that works offline and degrades cleanly
 * (the hook silently no-ops if the API is missing).
 *
 * Additive + non-destructive: this hook adds NO backend calls and
 * does NOT replace any existing voice plumbing — when a server-side
 * TTS provider lands later, the hook can swap its body to play an
 * ``<audio src=audio_url>`` tag without changing call sites.
 *
 * Behaviour
 * ---------
 *   * ``speak(text)`` — cancels any in-flight utterance, queues a
 *     new one. Silent on unsupported browsers.
 *   * ``cancel()`` — stops playback immediately.
 *   * ``speaking`` — boolean state for the lip-sync / portrait
 *     animation flag the runtime already has.
 *   * ``enabled`` / ``setEnabled(bool)`` — localStorage-backed
 *     master toggle. Default ON because a silent companion isn't a
 *     companion. User can toggle off via the volume button.
 *   * ``voices`` / ``selectedVoice`` / ``setSelectedVoice(uri)`` —
 *     surfaces the browser's voice list so a future settings panel
 *     can let the user pick "Soft female / Whisper / ..." voices.
 */
import { useCallback, useEffect, useRef, useState } from "react";

const STORAGE_KEY_ENABLED = "homepilot_persona_speech";
const STORAGE_KEY_VOICE = "homepilot_persona_voice";

function _supported(): boolean {
  return typeof globalThis !== "undefined"
    && typeof globalThis.speechSynthesis !== "undefined"
    && typeof globalThis.SpeechSynthesisUtterance !== "undefined";
}

function _readEnabled(): boolean {
  try {
    // Per-runtime explicit override wins.
    const explicit = globalThis.localStorage?.getItem(STORAGE_KEY_ENABLED);
    if (explicit === "1") return true;
    if (explicit === "0") return false;

    // Default to app-global Voice Assistant settings so Persona Live
    // follows Enterprise Settings out of the box.
    const globalToggle = globalThis.localStorage?.getItem("homepilot_tts_enabled");
    const enabledByGlobalToggle = globalToggle !== "false";
    const cfgRaw = globalThis.localStorage?.getItem("homepilot_voice_config");
    if (!cfgRaw) return enabledByGlobalToggle;
    const cfg = JSON.parse(cfgRaw);
    const voiceCfgEnabled = cfg?.enabled !== false;
    return enabledByGlobalToggle && voiceCfgEnabled;
  } catch {
    return true;
  }
}

function _writeEnabled(next: boolean): void {
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY_ENABLED, next ? "1" : "0");
  } catch {
    /* private browsing / quota — non-fatal */
  }
}

function _readSelectedVoice(): string {
  try {
    const explicit = globalThis.localStorage?.getItem(STORAGE_KEY_VOICE) || "";
    if (explicit) return explicit;
    const cfgRaw = globalThis.localStorage?.getItem("homepilot_voice_config");
    if (cfgRaw) {
      const cfg = JSON.parse(cfgRaw);
      const uri = String(cfg?.voiceURI || "").trim();
      if (uri) return uri;
    }
    return globalThis.localStorage?.getItem("homepilot_voice_uri") || "";
  } catch {
    return "";
  }
}

function _writeSelectedVoice(uri: string): void {
  try {
    if (uri) globalThis.localStorage?.setItem(STORAGE_KEY_VOICE, uri);
    else globalThis.localStorage?.removeItem(STORAGE_KEY_VOICE);
  } catch {
    /* swallow */
  }
}

/**
 * Pick a sensible default voice when the user hasn't selected one.
 *
 * Heuristics tuned for the companion vibe: prefer female voices,
 * prefer English locales, prefer browser-local (better quality than
 * cloud-throttled fallbacks on most platforms).
 */
function _pickDefaultVoice(
  voices: SpeechSynthesisVoice[],
  preferLang = "en",
): SpeechSynthesisVoice | null {
  if (!voices || voices.length === 0) return null;
  const langMatch = voices.filter(
    (v) => v.lang?.toLowerCase().startsWith(preferLang),
  );
  const pool = langMatch.length > 0 ? langMatch : voices;
  // Female-coded voice names across platforms. Order matters —
  // earlier wins when multiple match. Apple Samantha + Google's
  // English (US) voices land at the top of the list on most desktop
  // browsers and produce the warm-companion tone we want.
  const FEMALE_HINTS = [
    "samantha", "victoria", "karen", "moira", "tessa",
    "alex", // Apple's neutral default — kept as a fallback
    "google us english", "google uk english female",
    "microsoft zira", "microsoft hazel",
    "female",
  ];
  for (const hint of FEMALE_HINTS) {
    const found = pool.find((v) => v.name.toLowerCase().includes(hint));
    if (found) return found;
  }
  return pool[0] || null;
}

export interface PersonaSpeech {
  /** True while an utterance is being read aloud. Useful for lip-sync. */
  speaking: boolean;
  /** True if the browser supports Web Speech synthesis. */
  supported: boolean;
  /** Master on/off toggle, persisted across reloads. */
  enabled: boolean;
  setEnabled: (next: boolean) => void;
  /** All voices the browser exposes; populated asynchronously. */
  voices: SpeechSynthesisVoice[];
  /** voiceURI of the currently active voice (or "" for default). */
  selectedVoice: string;
  setSelectedVoice: (voiceURI: string) => void;
  /**
   * Speak the given text. Cancels any in-flight utterance first —
   * the companion shouldn't talk over herself when the user fires
   * actions back-to-back.
   */
  speak: (text: string) => void;
  /** Stop any in-flight utterance immediately. */
  cancel: () => void;
}

export function usePersonaSpeech(): PersonaSpeech {
  const supported = _supported();
  const [enabled, setEnabledState] = useState<boolean>(() => _readEnabled());
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [selectedVoice, setSelectedVoiceState] = useState<string>(() => _readSelectedVoice());
  const [speaking, setSpeaking] = useState(false);
  // Track the active utterance so cancel() can null its handlers
  // before stopping (avoids a phantom ``onend`` firing after cancel
  // and flipping speaking=false on the NEXT utterance's onstart).
  const activeRef = useRef<SpeechSynthesisUtterance | null>(null);

  // Voices are loaded asynchronously by the browser. Subscribe to
  // ``voiceschanged`` so we re-render when they arrive.
  useEffect(() => {
    if (!supported) return;
    const sync = () => {
      const list = globalThis.speechSynthesis?.getVoices?.() || [];
      setVoices(Array.from(list));
    };
    sync();
    globalThis.speechSynthesis.addEventListener?.("voiceschanged", sync);
    return () => {
      globalThis.speechSynthesis.removeEventListener?.("voiceschanged", sync);
    };
  }, [supported]);

  const cancel = useCallback(() => {
    if (!supported) return;
    const u = activeRef.current;
    if (u) {
      u.onstart = null;
      u.onend = null;
      u.onerror = null;
    }
    activeRef.current = null;
    try { globalThis.speechSynthesis.cancel(); } catch { /* no-op */ }
    setSpeaking(false);
  }, [supported]);

  const speak = useCallback(
    (text: string) => {
      if (!supported) return;
      if (!enabled) return;
      const trimmed = String(text || "").trim();
      if (!trimmed) return;
      // Cancel anything currently speaking — the companion shouldn't
      // talk over herself when the user fires actions in succession.
      cancel();
      const utt = new globalThis.SpeechSynthesisUtterance(trimmed);
      // Voice selection — explicit choice wins; otherwise pick a
      // companion-coded default.
      const voiceList = voices.length > 0
        ? voices
        : (globalThis.speechSynthesis?.getVoices?.() || []);
      const explicit = selectedVoice
        ? voiceList.find((v) => v.voiceURI === selectedVoice)
        : null;
      const chosen = explicit || _pickDefaultVoice(voiceList, "en");
      if (chosen) utt.voice = chosen;
      // Slight rate + pitch nudges for a warmer companion read.
      // Browsers vary widely; these are conservative.
      utt.rate = 0.97;
      utt.pitch = 1.05;
      utt.volume = 1.0;
      utt.onstart = () => setSpeaking(true);
      utt.onend = () => {
        // Only flip if still the active utterance — guards against
        // out-of-order onend from a prior cancel().
        if (activeRef.current === utt) {
          activeRef.current = null;
          setSpeaking(false);
        }
      };
      utt.onerror = () => {
        if (activeRef.current === utt) {
          activeRef.current = null;
          setSpeaking(false);
        }
      };
      activeRef.current = utt;
      try { globalThis.speechSynthesis.speak(utt); }
      catch { /* swallow — quota / not-allowed errors */ }
    },
    [cancel, enabled, selectedVoice, supported, voices],
  );

  // Cancel on unmount so a navigation mid-utterance doesn't leave
  // the browser monologuing into an empty page.
  useEffect(() => {
    return () => {
      try { globalThis.speechSynthesis?.cancel(); }
      catch { /* swallow */ }
    };
  }, []);

  const setEnabled = useCallback((next: boolean) => {
    setEnabledState(next);
    _writeEnabled(next);
    if (!next) {
      // Toggling off mid-sentence should stop immediately.
      try { globalThis.speechSynthesis?.cancel(); }
      catch { /* swallow */ }
      setSpeaking(false);
    }
  }, []);

  const setSelectedVoice = useCallback((uri: string) => {
    setSelectedVoiceState(uri);
    _writeSelectedVoice(uri);
  }, []);

  return {
    speaking,
    supported,
    enabled,
    setEnabled,
    voices,
    selectedVoice,
    setSelectedVoice,
    speak,
    cancel,
  };
}

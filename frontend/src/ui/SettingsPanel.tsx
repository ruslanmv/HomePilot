import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Settings as SettingsIcon,
  Link2,
  Server,
  Boxes,
  SlidersHorizontal,
  ShieldCheck,
  AudioLines,
  Eye,
  EyeOff,
  Users,
  Wrench,
  Grid3x3,
  Code2,
  FlaskConical,
  Info,
  Copy,
  Check,
  Loader2,
  Cloud,
} from "lucide-react";
import OllamaHealthBanner from "./OllamaHealthBanner";
import OllaBridgeLink from "./components/OllaBridgeLink";
import ProfileSettingsModal from "./ProfileSettingsModal";
import TtsEngineSection from "./components/TtsEngineSection";
// Side-effect import: registers the bundled TTS providers (web-speech-api,
// piper-wasm). Importing here guarantees the registry is populated the
// first time the Settings panel mounts, before TtsEngineSection reads it.
import "./tts";
import {
  getActiveTtsEngineId,
  onActiveTtsEngineChange,
} from "./tts";
import { resolveBackendUrl } from "./lib/backendUrl";
import {
  getModelSettings,
  getPresetDescription,
  detectArchitecture,
  getArchitectureLabel,
  type PresetName,
} from "./modelPresets";

type ProviderInfo = {
  label: string;
  base_url: string;
  default_model: string;
  capabilities?: {
    chat?: boolean;
    images?: boolean;
    video?: boolean;
    models_list?: boolean;
  };
};

export type ProviderKey = string;

export type HardwarePresetUI = "low" | "med" | "high" | "ultra" | "custom";

export type SettingsModelV2 = {
  backendUrl: string;
  apiKey: string;

  providerChat: ProviderKey;
  providerImages: ProviderKey;
  providerVideo: ProviderKey;

  baseUrlChat?: string;
  baseUrlImages?: string;
  baseUrlVideo?: string;

  modelChat: string;
  modelImages: string;
  modelVideo: string;

  preset: HardwarePresetUI;

  // Voice settings
  ttsEnabled?: boolean;
  selectedVoice?: string;

  // NSFW/Spice mode
  nsfwMode?: boolean;

  // Memory Engine (off | v1 | v2)
  memoryEngine?: 'off' | 'v1' | 'v2';

  // Experimental features
  experimentalCivitai?: boolean;
  civitaiApiKey?: string;  // Optional API key for Civitai NSFW content

  // Prompt refinement (AI enhancement of image prompts)
  promptRefinement?: boolean;

  // ComfyUI VRAM mode — controls how aggressively ComfyUI offloads
  // model weights between calls. "high" keeps them resident (best
  // for 8+ GB GPUs); "normal" is ComfyUI's default smart-offload;
  // "low" minimises VRAM at the cost of speed. Undefined = keep
  // current shell env (COMFY_VRAM_MODE) value. Takes effect on
  // the next ComfyUI restart.
  comfyVramMode?: 'high' | 'normal' | 'low' | 'gpu-only';

  // Multimodal (Vision) settings — additive, optional
  providerMultimodal?: ProviderKey;
  baseUrlMultimodal?: string;
  modelMultimodal?: string;
  multimodalAuto?: boolean;  // Auto-trigger vision on image upload (default: true)
  multimodalTopology?: 'direct' | 'smart' | 'agent' | 'knowledge';  // Vision routing: direct (default), smart (Vision → Main LLM), agent (autonomous tool loop), or knowledge (agent + RAG + memory)

  // Legacy generation parameters (kept for compatibility)
  textTemperature?: number;
  textMaxTokens?: number;
  imgWidth?: number;
  imgHeight?: number;
  imgSteps?: number;
  imgCfg?: number;
  imgSeed?: number;
  vidSeconds?: number;
  vidFps?: number;
  vidMotion?: string;
  // Video preset settings (synced with hardware preset)
  vidWidth?: number;
  vidHeight?: number;
  vidFrames?: number;
  vidSteps?: number;
  vidCfg?: number;
  vidDenoise?: number;
  vidPreset?: string;  // Backend preset name: 'low', 'medium', 'high', 'ultra'

  // MatrixHub integration (optional secondary MCP catalog)
  matrixHubEnabled?: boolean;
  matrixHubUrl?: string;

  // OllaBridge integration — expose personas as OpenAI-compatible API
  ollaBridgeEnabled?: boolean;
  ollaBridgeApiKey?: string;

  // Teams concurrent LLM calls (1-3, default 1)
  teamsConcurrentCalls?: number;

};

// ─────────────────────────────────────────────────────────────────────────
// Reusable enterprise settings primitives
// ─────────────────────────────────────────────────────────────────────────

const INPUT_CLS =
  // 16px on mobile (text-base) prevents iOS Safari from auto-zooming on focus;
  // 14px (text-sm) from sm: up keeps the dense desktop look.
  "w-full h-11 sm:h-10 bg-[#050505] border border-white/10 rounded-xl px-3 text-base sm:text-sm text-white " +
  "placeholder:text-white/30 outline-none focus:border-[#9b5cff]/60 focus:ring-2 " +
  "focus:ring-[#9b5cff]/25 transition-colors [color-scheme:dark]";

const SELECT_CLS = INPUT_CLS + " pr-8 cursor-pointer";

/** Card container — a single settings group, stacked vertically. */
function SettingsCard({
  title,
  description,
  icon,
  children,
  right,
}: {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <section className="bg-[#1b1c20] border border-white/[0.09] rounded-2xl p-5 sm:p-6">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="flex items-start gap-2.5 min-w-0">
          {icon && <div className="text-[#9b5cff] mt-0.5 shrink-0">{icon}</div>}
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-white/95">{title}</h3>
            {description && (
              <p className="text-xs text-white/45 mt-0.5 leading-relaxed">{description}</p>
            )}
          </div>
        </div>
        {right && <div className="shrink-0">{right}</div>}
      </div>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

/** Predictable row: label + helper text on the left, control on the right. */
function Row({
  label,
  description,
  htmlFor,
  children,
  stack,
}: {
  label: string;
  description?: string;
  htmlFor?: string;
  children?: React.ReactNode;
  stack?: boolean;
}) {
  return (
    <div
      className={
        stack
          ? "space-y-2"
          : "flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"
      }
    >
      <div className="min-w-0">
        <label htmlFor={htmlFor} className="text-sm text-white/85 font-medium block">
          {label}
        </label>
        {description && (
          <p className="text-xs text-white/40 mt-0.5 leading-relaxed">{description}</p>
        )}
      </div>
      {children != null && (
        <div className={stack ? "" : "sm:w-72 sm:shrink-0"}>{children}</div>
      )}
    </div>
  );
}

/** Accessible on/off switch. */
function Toggle({
  checked,
  onChange,
  tone = "accent",
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  tone?: "accent" | "danger" | "success" | "blue";
  label: string;
}) {
  const onColor =
    tone === "danger"
      ? "bg-red-600"
      : tone === "success"
        ? "bg-emerald-500"
        : tone === "blue"
          ? "bg-blue-600"
          : "bg-[#9b5cff]";
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={[
        "relative inline-flex h-6 w-11 items-center rounded-full transition-colors shrink-0",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#9b5cff]/75 focus-visible:ring-offset-2 focus-visible:ring-offset-[#1b1c20]",
        checked ? onColor : "bg-white/10",
      ].join(" ")}
    >
      <span
        className={[
          "inline-block h-4 w-4 transform rounded-full bg-white transition-transform",
          checked ? "translate-x-6" : "translate-x-1",
        ].join(" ")}
      />
    </button>
  );
}

/** Health / capability status pill. */
function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={[
        "inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full border",
        ok
          ? "bg-emerald-500/12 border-emerald-500/30 text-emerald-300"
          : "bg-white/5 border-white/10 text-white/45",
      ].join(" ")}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${ok ? "bg-emerald-400" : "bg-white/25"}`} />
      {label}
    </span>
  );
}

const SECTIONS = [
  { id: "general", label: "General", Icon: SettingsIcon },
  { id: "connection", label: "Connection", Icon: Link2 },
  { id: "linking", label: "OllaBridge Link", Icon: Cloud },
  { id: "providers", label: "Providers", Icon: Server },
  { id: "models", label: "Models", Icon: Boxes },
  { id: "generation", label: "Generation", Icon: SlidersHorizontal },
  { id: "memory", label: "Memory & Safety", Icon: ShieldCheck },
  { id: "voice", label: "Voice", Icon: AudioLines },
  { id: "vision", label: "Vision", Icon: Eye },
  { id: "teams", label: "Teams", Icon: Users },
  { id: "tools", label: "Tools & Agents", Icon: Wrench },
  { id: "matrixhub", label: "MatrixHub", Icon: Grid3x3 },
  { id: "ollabridge", label: "OllaBridge API", Icon: Code2 },
  { id: "advanced", label: "Advanced", Icon: FlaskConical },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

// ── Agentic Status sub-component (Phase 1, additive) ─────────────────────────
function AgenticStatus({ backendUrl, apiKey }: { backendUrl: string; apiKey: string }) {
  const [status, setStatus] = React.useState<{
    enabled: boolean; configured: boolean; reachable: boolean; admin_configured: boolean;
  } | null>(null);
  const [adminUrl, setAdminUrl] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);

  const headers: Record<string, string> = {};
  if (apiKey) headers["X-API-Key"] = apiKey;

  const fetchStatus = React.useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await fetch(`${backendUrl}/v1/agentic/status`, { headers });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setStatus(data);
      if (data.admin_configured) {
        try {
          const ar = await fetch(`${backendUrl}/v1/agentic/admin`, { headers });
          if (ar.ok) {
            const ad = await ar.json();
            setAdminUrl(ad.admin_url || null);
          }
        } catch { /* ignore */ }
      }
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [backendUrl, apiKey]);

  React.useEffect(() => { fetchStatus(); }, [fetchStatus]);

  if (loading && !status) {
    return <div className="text-xs text-white/40">Checking advanced tools...</div>;
  }
  if (err) {
    return (
      <div className="space-y-2">
        <div className="text-xs text-red-400/80">Could not reach agentic layer: {err}</div>
        <button type="button" onClick={fetchStatus}
          className="text-[11px] px-3 py-1 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/60 hover:text-white/80 transition-all">
          Retry
        </button>
      </div>
    );
  }
  if (!status) return null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <StatusPill ok={status.enabled} label="Enabled" />
        <StatusPill ok={status.configured} label="Configured" />
        <StatusPill ok={status.reachable} label="Gateway reachable" />
        <StatusPill ok={status.admin_configured} label="Admin ready" />
      </div>
      <div className="flex items-center gap-2">
        {adminUrl && (
          <a href={adminUrl} target="_blank" rel="noopener noreferrer"
            className="text-[11px] px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-white/20 text-white/70 hover:text-white transition-all">
            Open Tool &amp; Agent Manager
          </a>
        )}
        <button type="button" onClick={fetchStatus}
          className="text-[11px] px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-white/20 text-white/70 hover:text-white transition-all">
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>
    </div>
  );
}

export default function SettingsPanel({
  value,
  onChangeDraft,
  onSave,
  onClose,
}: {
  value: SettingsModelV2;
  onChangeDraft: (next: SettingsModelV2) => void;
  onSave: () => void;
  onClose: () => void;
}) {
  const [providers, setProviders] = useState<Record<string, ProviderInfo>>({});
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [providersErr, setProvidersErr] = useState<string | null>(null);

  const [models, setModels] = useState<Record<string, string[]>>({});
  const [modelsLoading, setModelsLoading] = useState<Record<string, boolean>>({});
  const [modelsErr, setModelsErr] = useState<Record<string, string | null>>({});

  const [health, setHealth] = useState<any>(null);
  const [healthErr, setHealthErr] = useState<string | null>(null);
  const [dismissOllamaBanner, setDismissOllamaBanner] = useState(false);

  // Voice state
  const [availableVoices, setAvailableVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [ttsEngineId, setTtsEngineId] = useState<string>(() => getActiveTtsEngineId());
  useEffect(() => onActiveTtsEngineChange(setTtsEngineId), []);
  const [voicesInitialized, setVoicesInitialized] = useState(false);

  // Video presets state (fetched from backend based on selected model)
  const [videoPresets, setVideoPresets] = useState<Record<string, { width: number; height: number; fps: number; frames: number; steps: number; cfg: number; denoise: number }>>({});
  const [videoPresetsLoading, setVideoPresetsLoading] = useState(false);

  // Profile & Integrations modal (additive)
  const [showProfileSettings, setShowProfileSettings] = useState(false);

  // ── Enterprise modal shell state ───────────────────────────────────────
  const [activeSection, setActiveSection] = useState<SectionId>("connection");
  const [showApiKey, setShowApiKey] = useState(false);
  const [copiedKey, setCopiedKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [dirty, setDirty] = useState(false);
  // Baseline used by "Reset" — tracks the last clean (unedited) state so a
  // Reset reverts the user's unsaved edits without fighting the automatic
  // model/preset auto-population effects below.
  const baselineRef = useRef<string>(JSON.stringify(value));

  // Any user-driven edit goes through commit() so we can track unsaved
  // changes. The automatic effects (model auto-select, preset apply) call
  // onChangeDraft directly and are intentionally NOT treated as user edits.
  const commit = React.useCallback(
    (next: SettingsModelV2) => {
      setDirty(true);
      onChangeDraft(next);
    },
    [onChangeDraft],
  );

  const isValidUrl = (u: string) => {
    try {
      const p = new URL(u);
      return p.protocol === "http:" || p.protocol === "https:";
    } catch {
      return false;
    }
  };
  const backendUrlValid = !value.backendUrl || isValidUrl(value.backendUrl);
  const online = !!health && !healthErr;

  const requestClose = React.useCallback(() => {
    if (dirty && !window.confirm("You have unsaved changes. Discard them?")) return;
    onClose();
  }, [dirty, onClose]);

  const handleSave = React.useCallback(() => {
    onSave();
    baselineRef.current = JSON.stringify(value);
    setDirty(false);
  }, [onSave, value]);

  const handleReset = React.useCallback(() => {
    try {
      onChangeDraft(JSON.parse(baselineRef.current));
    } catch { /* ignore */ }
    setDirty(false);
  }, [onChangeDraft]);

  const copyApiKey = React.useCallback(async () => {
    try {
      await navigator.clipboard.writeText(value.apiKey || "");
      setCopiedKey(true);
      setTimeout(() => setCopiedKey(false), 1500);
    } catch { /* ignore */ }
  }, [value.apiKey]);

  async function fetchHealth() {
    setHealthErr(null);
    try {
      const res = await fetch(`${resolveBackendUrl(value.backendUrl)}/health`);
      const data = await res.json();
      setHealth(data);
    } catch (e: any) {
      setHealthErr(e?.message || String(e));
    }
  }

  const testConnection = React.useCallback(async () => {
    setTesting(true);
    try {
      await fetchHealth();
    } finally {
      setTesting(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.backendUrl]);

  async function fetchProviders() {
    setLoadingProviders(true);
    setProvidersErr(null);
    try {
      const res = await fetch(`${resolveBackendUrl(value.backendUrl)}/providers`);
      const data = await res.json();
      if (!data.ok) throw new Error(data.message || "Failed to load providers");
      setProviders(data.providers || {});
    } catch (e: any) {
      setProvidersErr(e?.message || String(e));
    } finally {
      setLoadingProviders(false);
    }
  }

  async function fetchModelsFor(providerKey: string, baseUrlOverride?: string, modelType?: 'image' | 'video' | 'multimodal') {
    // Use compound key for storing models by provider + type (to separate image vs video models)
    const stateKey = modelType ? `${providerKey}_${modelType}` : providerKey;
    setModelsLoading((m) => ({ ...m, [stateKey]: true }));
    setModelsErr((m) => ({ ...m, [stateKey]: null }));
    try {
      const base = baseUrlOverride || providers?.[providerKey]?.base_url || "";
      const url = `${value.backendUrl}/models?provider=${encodeURIComponent(providerKey)}&base_url=${encodeURIComponent(base)}${modelType ? `&model_type=${encodeURIComponent(modelType)}` : ''}`;
      const res = await fetch(url);
      const data = await res.json();
      if (!data.ok) throw new Error(data.message || "Failed to fetch models");
      setModels((prev) => ({ ...prev, [stateKey]: data.models || [] }));
      if (!data.models || data.models.length === 0) {
        setModelsErr((m) => ({ ...m, [stateKey]: "No models returned by provider." }));
      }
    } catch (e: any) {
      setModelsErr((m) => ({ ...m, [stateKey]: e?.message || String(e) }));
    } finally {
      setModelsLoading((m) => ({ ...m, [stateKey]: false }));
    }
  }

  // Detect video model type from model name
  function detectVideoModelType(modelName: string | undefined): string {
    if (!modelName) return "ltx"; // Default to LTX
    const lower = modelName.toLowerCase();
    if (lower.includes("ltx")) return "ltx";
    if (lower.includes("svd")) return "svd";
    if (lower.includes("wan")) return "wan";
    if (lower.includes("hunyuan")) return "hunyuan";
    if (lower.includes("mochi")) return "mochi";
    if (lower.includes("cog")) return "cogvideo";
    return "ltx"; // Default
  }

  // Fetch video presets from backend for a specific model
  async function fetchVideoPresets(modelName: string | undefined) {
    const modelType = detectVideoModelType(modelName);
    setVideoPresetsLoading(true);
    try {
      const presetLevels = ["low", "medium", "high", "ultra"];
      const fetchedPresets: Record<string, any> = {};

      // Fetch all preset levels in parallel
      await Promise.all(
        presetLevels.map(async (preset) => {
          const url = `${value.backendUrl}/video-presets?model=${encodeURIComponent(modelType)}&preset=${preset}`;
          const res = await fetch(url);
          const data = await res.json();
          if (data.ok && data.values) {
            fetchedPresets[preset === "medium" ? "med" : preset] = data.values;
          }
        })
      );

      // Only update if we got some presets
      if (Object.keys(fetchedPresets).length > 0) {
        setVideoPresets(fetchedPresets);
        console.log(`[SettingsPanel] Loaded video presets for ${modelType}:`, fetchedPresets);
      }
    } catch (e: any) {
      console.error("[SettingsPanel] Error fetching video presets:", e);
    } finally {
      setVideoPresetsLoading(false);
    }
  }

  function loadVoices() {
    if ('speechSynthesis' in window) {
      const voices = window.speechSynthesis.getVoices();
      setAvailableVoices(voices);
      if (voices.length > 0) {
        console.log(`[SettingsPanel] Loaded ${voices.length} voices`);

        // Auto-select a natural-sounding voice on first load if none is selected
        if (!voicesInitialized && !value.selectedVoice && voices.length > 0) {
          // Prefer Google voices, female voices, or US English
          const preferred = voices.find(
            (v) =>
              v.name.toLowerCase().includes('google') &&
              v.name.toLowerCase().includes('us') &&
              v.name.toLowerCase().includes('english')
          ) ||
            voices.find((v) => v.name.toLowerCase().includes('google') && v.lang.startsWith('en')) ||
            voices.find((v) => v.name.toLowerCase().includes('female') && v.lang.startsWith('en')) ||
            voices.find((v) => v.lang.startsWith('en-US')) ||
            voices[0];

          if (preferred) {
            console.log(`[SettingsPanel] Auto-selected voice: ${preferred.name}`);
            onChangeDraft({ ...value, selectedVoice: preferred.name });
          }
          setVoicesInitialized(true);
        }
      }
    }
  }

  useEffect(() => {
    fetchHealth();
    fetchProviders();

    // Fetch video presets for the current video model
    fetchVideoPresets(value.modelVideo);

    // Load voices for TTS
    loadVoices();

    // Voices may load asynchronously (especially on Chrome/Quest)
    if ('speechSynthesis' in window && window.speechSynthesis.onvoiceschanged !== undefined) {
      window.speechSynthesis.onvoiceschanged = loadVoices;
    }

    // Cleanup
    return () => {
      if ('speechSynthesis' in window) {
        window.speechSynthesis.onvoiceschanged = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.backendUrl]);

  // Keep the Reset baseline in sync with automatic (non-user) changes so that
  // Reset only ever reverts genuine user edits.
  useEffect(() => {
    if (!dirty) baselineRef.current = JSON.stringify(value);
  }, [value, dirty]);

  // ESC closes the modal (respecting the unsaved-changes guard).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        requestClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [requestClose]);

  // Fetch video presets when video model changes
  useEffect(() => {
    if (value.modelVideo) {
      fetchVideoPresets(value.modelVideo);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.modelVideo]);

  // ── Auto-fetch models on panel open (zero-config UX) ──────────────────
  const autoFetchedRef = React.useRef(false);
  useEffect(() => {
    if (autoFetchedRef.current || Object.keys(providers).length === 0) return;
    autoFetchedRef.current = true;

    if (value.providerChat) {
      const base = value.baseUrlChat || providers?.[value.providerChat]?.base_url || "";
      fetchModelsFor(value.providerChat, base).then(() => { /* selection handled below */ });
    }
    if (value.providerImages) {
      const base = value.baseUrlImages || providers?.[value.providerImages]?.base_url || "";
      const modelType = value.providerImages === 'comfyui' ? 'image' as const : undefined;
      fetchModelsFor(value.providerImages, base, modelType);
    }
    if (value.providerVideo) {
      const base = value.baseUrlVideo || providers?.[value.providerVideo]?.base_url || "";
      const modelType = value.providerVideo === 'comfyui' ? 'video' as const : undefined;
      fetchModelsFor(value.providerVideo, base, modelType);
    }
    if (value.providerMultimodal) {
      const base = value.baseUrlMultimodal || providers?.[value.providerMultimodal]?.base_url || "";
      fetchModelsFor(value.providerMultimodal, base, 'multimodal');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providers]);

  // Auto-select first available model when models arrive and current selection is empty
  useEffect(() => {
    const chatKey = value.providerChat;
    const imgKey = value.providerImages === 'comfyui' ? `${value.providerImages}_image` : value.providerImages;
    const vidKey = value.providerVideo === 'comfyui' ? `${value.providerVideo}_video` : value.providerVideo;
    const mmKey = value.providerMultimodal ? `${value.providerMultimodal}_multimodal` : '';

    const updates: Partial<typeof value> = {};
    if (!value.modelChat && models[chatKey]?.length) updates.modelChat = models[chatKey][0];
    if (!value.modelImages && models[imgKey]?.length) updates.modelImages = models[imgKey][0];
    if (!value.modelVideo && models[vidKey]?.length) updates.modelVideo = models[vidKey][0];
    if (!value.modelMultimodal && mmKey && models[mmKey]?.length) updates.modelMultimodal = models[mmKey][0];

    if (Object.keys(updates).length > 0) {
      console.log('[SettingsPanel] Auto-selecting models:', updates);
      onChangeDraft({ ...value, ...updates });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [models]);

  const providerOptions = useMemo(() => Object.entries(providers), [providers]);

  // Fallback presets (used when backend fetch fails or hasn't completed)
  const FALLBACK_VIDEO_PRESETS: Record<string, { width: number; height: number; fps: number; frames: number; steps: number; cfg: number; denoise: number }> = {
    low:    { width: 512, height: 288, fps: 16, frames: 25, steps: 20, cfg: 3.5, denoise: 0.80 },
    med:    { width: 640, height: 360, fps: 16, frames: 33, steps: 24, cfg: 4.0, denoise: 0.80 },
    high:   { width: 704, height: 400, fps: 24, frames: 41, steps: 28, cfg: 4.0, denoise: 0.80 },
    ultra:  { width: 768, height: 432, fps: 24, frames: 49, steps: 32, cfg: 4.0, denoise: 0.80 },
  };

  const VIDEO_PRESETS = Object.keys(videoPresets).length > 0 ? videoPresets : FALLBACK_VIDEO_PRESETS;

  const currentModelSettings = useMemo(() => {
    const model = value.modelImages || "dreamshaper_8.safetensors";
    const preset = value.preset === "custom" ? "high" : value.preset;
    return getModelSettings(model, "1:1", preset);
  }, [value.modelImages, value.preset]);

  const currentArchitecture = useMemo(() => {
    return detectArchitecture(value.modelImages || "");
  }, [value.modelImages]);

  const currentVideoSettings = useMemo(() => {
    const presetKey = value.preset === "custom" ? "high" : (value.preset === "med" ? "med" : value.preset);
    return VIDEO_PRESETS[presetKey] || VIDEO_PRESETS.med;
  }, [value.preset]);

  // Auto-apply preset settings when preset or model changes (except in custom mode)
  useEffect(() => {
    if (value.preset !== "custom") {
      const imgSettings = currentModelSettings;
      const vidSettings = currentVideoSettings;
      const backendPresetName = value.preset === "med" ? "medium" : value.preset;

      const needsImageUpdate =
        value.imgWidth !== imgSettings.width ||
        value.imgHeight !== imgSettings.height ||
        value.imgSteps !== imgSettings.steps ||
        value.imgCfg !== imgSettings.cfg;

      const needsVideoUpdate =
        value.vidWidth !== vidSettings.width ||
        value.vidHeight !== vidSettings.height ||
        value.vidFps !== vidSettings.fps ||
        value.vidFrames !== vidSettings.frames ||
        value.vidSteps !== vidSettings.steps ||
        value.vidCfg !== vidSettings.cfg ||
        value.vidDenoise !== vidSettings.denoise ||
        value.vidPreset !== backendPresetName;

      if (needsImageUpdate || needsVideoUpdate) {
        onChangeDraft({
          ...value,
          imgWidth: imgSettings.width,
          imgHeight: imgSettings.height,
          imgSteps: imgSettings.steps,
          imgCfg: imgSettings.cfg,
          vidWidth: vidSettings.width,
          vidHeight: vidSettings.height,
          vidFps: vidSettings.fps,
          vidFrames: vidSettings.frames,
          vidSteps: vidSettings.steps,
          vidCfg: vidSettings.cfg,
          vidDenoise: vidSettings.denoise,
          vidPreset: backendPresetName,
        });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.preset, value.modelImages, currentModelSettings, currentVideoSettings]);

  const ollamaSelected =
    value.providerChat === "ollama" ||
    value.providerImages === "ollama" ||
    value.providerVideo === "ollama";

  const ollamaDown =
    ollamaSelected && health?.providers?.ollama && health.providers.ollama.ok === false;

  const showOllamaBanner = !!ollamaDown && !dismissOllamaBanner;

  // ── Control builders (dark-themed, reused across sections) ─────────────
  function providerSelectRow(label: string, description: string, provider: ProviderKey, setProvider: (k: ProviderKey) => void) {
    return (
      <Row label={label} description={description}>
        <select
          className={SELECT_CLS}
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
        >
          {providerOptions.map(([k, info]) => (
            <option key={k} value={k}>
              {info.label}
            </option>
          ))}
        </select>
      </Row>
    );
  }

  function baseUrlRow(
    label: string,
    providerKey: ProviderKey,
    valueUrl: string | undefined,
    setUrl: (v: string) => void
  ) {
    const info = providers?.[providerKey];
    const hint = info?.base_url || '';
    return (
      <Row
        label={label}
        description="Leave blank to use the backend default (e.g. Ollama on http://localhost:11434)."
        stack
      >
        <input
          className={INPUT_CLS}
          value={valueUrl ?? ''}
          placeholder={hint ? `Default: ${hint}` : 'Optional'}
          onChange={(e) => setUrl(e.target.value)}
        />
      </Row>
    );
  }

  function modelSelectRow(
    label: string,
    providerKey: ProviderKey,
    modelValue: string,
    setModel: (m: string) => void,
    baseUrlOverride?: string,
    modelType?: 'image' | 'video' | 'multimodal'
  ) {
    const stateKey = modelType ? `${providerKey}_${modelType}` : providerKey;
    const list = models[stateKey] || [];
    const loading = !!modelsLoading[stateKey];
    const err = modelsErr[stateKey];

    return (
      <Row label={label} stack>
        <div className="flex items-center gap-2">
          <select
            className={SELECT_CLS}
            value={modelValue}
            onChange={(e) => setModel(e.target.value)}
          >
            {modelValue && !list.includes(modelValue) ? <option value={modelValue}>{modelValue} (current)</option> : null}
            {list.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => fetchModelsFor(providerKey, baseUrlOverride, modelType)}
            className="shrink-0 h-10 px-3 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 text-xs text-white font-semibold disabled:opacity-50 whitespace-nowrap"
            disabled={loading || !providerKey}
          >
            {loading ? "Fetching..." : "Fetch models"}
          </button>
        </div>
        {err ? <div className="mt-2 text-[11px] text-red-400">{err}</div> : null}
      </Row>
    );
  }

  // ── Section renderers ──────────────────────────────────────────────────
  function renderGeneral() {
    return (
      <>
        <SettingsCard
          title="HomePilot Enterprise"
          description="Workspace identity and connection overview."
          icon={<SettingsIcon size={16} />}
          right={<StatusPill ok={online} label={online ? "Connected" : "Offline"} />}
        >
          <div className="rounded-xl bg-[#050505] border border-white/10 px-4 py-3">
            <div className="text-[11px] uppercase tracking-wider text-white/40 font-semibold">Connected to</div>
            <div className="text-sm text-white/85 font-mono mt-1 break-all">
              {resolveBackendUrl(value.backendUrl)}
            </div>
          </div>
          <Row
            label="Profile &amp; Integrations"
            description="Manage your profile, connected accounts, and integrations."
          >
            <button
              type="button"
              onClick={() => setShowProfileSettings(true)}
              className="h-10 px-4 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-white/20 text-sm text-white/80 hover:text-white transition-all w-full sm:w-auto"
            >
              Open Profile &amp; Integrations
            </button>
          </Row>
        </SettingsCard>
      </>
    );
  }

  function renderConnection() {
    return (
      <SettingsCard
        title="Backend Connection"
        description="Where the app talks to your HomePilot backend."
        icon={<Link2 size={16} />}
        right={<StatusPill ok={online} label={online ? "Online" : healthErr ? "Offline" : "Unknown"} />}
      >
        <Row label="Backend URL" description="The base URL of your HomePilot API." stack>
          <input
            id="backend-url"
            className={INPUT_CLS + (!backendUrlValid ? " border-red-500/60 focus:border-red-500/60 focus:ring-red-500/25" : "")}
            value={value.backendUrl}
            onChange={(e) => commit({ ...value, backendUrl: e.target.value })}
            placeholder="https://your-backend.example.com"
            aria-invalid={!backendUrlValid}
          />
          {!backendUrlValid && (
            <div className="mt-1.5 text-[11px] text-red-400">Enter a valid http(s) URL.</div>
          )}
        </Row>

        <Row label="API Key" description="Optional. Masked by default; used as Bearer / X-API-Key." stack>
          <div className="relative">
            <input
              id="api-key"
              type={showApiKey ? "text" : "password"}
              className={INPUT_CLS + " pr-16 font-mono"}
              value={value.apiKey}
              onChange={(e) => commit({ ...value, apiKey: e.target.value })}
              placeholder="Optional"
              autoComplete="off"
            />
            <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
              <button
                type="button"
                aria-label={showApiKey ? "Hide API key" : "Show API key"}
                onClick={() => setShowApiKey((v) => !v)}
                className="w-7 h-7 flex items-center justify-center rounded-lg text-white/45 hover:text-white/80 hover:bg-white/5"
              >
                {showApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
              <button
                type="button"
                aria-label="Copy API key"
                onClick={copyApiKey}
                className="w-7 h-7 flex items-center justify-center rounded-lg text-white/45 hover:text-white/80 hover:bg-white/5"
              >
                {copiedKey ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
              </button>
            </div>
          </div>
        </Row>

        <Row label="Status" description="Verify the backend is reachable.">
          <div className="flex items-center gap-3">
            <StatusPill ok={online} label={online ? "Online" : healthErr ? "Offline" : "Unknown"} />
            <button
              type="button"
              onClick={testConnection}
              disabled={testing}
              className="h-9 px-3 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 text-xs text-white font-semibold disabled:opacity-50 inline-flex items-center gap-1.5"
            >
              {testing ? (<><Loader2 size={13} className="animate-spin" /> Testing…</>) : "Test Connection"}
            </button>
          </div>
        </Row>
        {healthErr && (
          <div className="text-[11px] text-yellow-300/80">Health check failed: {healthErr}</div>
        )}
      </SettingsCard>
    );
  }

  function renderProviders() {
    return (
      <SettingsCard
        title="Providers"
        description="Choose which backend powers each capability."
        icon={<Server size={16} />}
        right={
          <button
            type="button"
            onClick={fetchProviders}
            disabled={loadingProviders}
            className="h-9 px-3 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 text-xs text-white font-semibold disabled:opacity-50"
          >
            {loadingProviders ? "Loading…" : "Refresh"}
          </button>
        }
      >
        {providersErr && <div className="text-[11px] text-red-400">{providersErr}</div>}
        {providerSelectRow("Chat Provider", "Used for text conversations and prompt refinement.", value.providerChat, (k) => commit({ ...value, providerChat: k }))}
        {providerSelectRow("Image Provider", "Used for image generation.", value.providerImages, (k) => commit({ ...value, providerImages: k }))}
        {providerSelectRow("Video Provider", "Used for video generation.", value.providerVideo, (k) => commit({ ...value, providerVideo: k }))}
        {providerSelectRow("Multimodal Provider", "Used for image understanding (vision).", value.providerMultimodal || 'ollama', (k) => commit({ ...value, providerMultimodal: k }))}
      </SettingsCard>
    );
  }

  function renderModels() {
    return (
      <SettingsCard
        title="Model Endpoints"
        description="Optional base URLs and the specific model for each provider."
        icon={<Boxes size={16} />}
      >
        {baseUrlRow("Chat Base URL", value.providerChat, value.baseUrlChat, (v) => commit({ ...value, baseUrlChat: v }))}
        {modelSelectRow("Chat Model", value.providerChat, value.modelChat, (m) => commit({ ...value, modelChat: m }), value.baseUrlChat)}

        {baseUrlRow("Image Base URL", value.providerImages, value.baseUrlImages, (v) => commit({ ...value, baseUrlImages: v }))}
        {modelSelectRow("Image Model (if supported)", value.providerImages, value.modelImages, (m) => commit({ ...value, modelImages: m }), value.baseUrlImages, value.providerImages === 'comfyui' ? 'image' : undefined)}

        {baseUrlRow("Video Base URL", value.providerVideo, value.baseUrlVideo, (v) => commit({ ...value, baseUrlVideo: v }))}
        {modelSelectRow("Video Model (if supported)", value.providerVideo, value.modelVideo, (m) => commit({ ...value, modelVideo: m }), value.baseUrlVideo, value.providerVideo === 'comfyui' ? 'video' : undefined)}

        {baseUrlRow("Multimodal Base URL", value.providerMultimodal || 'ollama', value.baseUrlMultimodal, (v) => commit({ ...value, baseUrlMultimodal: v }))}
        {modelSelectRow("Multimodal Model", value.providerMultimodal || 'ollama', value.modelMultimodal || '', (m) => commit({ ...value, modelMultimodal: m }), value.baseUrlMultimodal, 'multimodal')}
      </SettingsCard>
    );
  }

  function renderGeneration() {
    return (
      <SettingsCard
        title="Generation"
        description="Quality presets, prompt refinement, and generation parameters."
        icon={<SlidersHorizontal size={16} />}
      >
        {/* Hardware Preset */}
        <Row label="Hardware Preset" description="Choose generation quality and resource usage." stack>
          <div className="grid grid-cols-5 gap-1.5">
            {(["low", "med", "high", "ultra", "custom"] as HardwarePresetUI[]).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => commit({ ...value, preset: p })}
                className={[
                  "px-2 py-2 rounded-lg text-xs font-semibold transition-all",
                  value.preset === p ? "bg-[#9b5cff] text-white" : "bg-white/5 text-white/60 hover:bg-white/10 hover:text-white/80",
                ].join(" ")}
              >
                {p === "low" ? "Low" : p === "med" ? "Med" : p === "high" ? "High" : p === "ultra" ? "Ultra" : "Custom"}
              </button>
            ))}
          </div>
          <div className="text-[10px] text-white/35 mt-2">
            {value.preset === "low" && `✓ Low: ${getPresetDescription(value.modelImages || "", "low")}`}
            {value.preset === "med" && `✓ Med: ${getPresetDescription(value.modelImages || "", "med")}`}
            {value.preset === "high" && `✓ High: ${getPresetDescription(value.modelImages || "", "high")}`}
            {value.preset === "ultra" && `✓ Ultra: ${getPresetDescription(value.modelImages || "", "ultra")}`}
            {value.preset === "custom" && "✓ Custom: Manual control (values below)"}
          </div>
          {value.preset !== "custom" && (
            <div className="text-[10px] text-green-400/70 mt-1">
              {videoPresetsLoading ? (
                <span className="text-white/40">Loading video presets...</span>
              ) : (
                <>
                  Video ({detectVideoModelType(value.modelVideo).toUpperCase()}): {currentVideoSettings.width}×{currentVideoSettings.height}, {currentVideoSettings.frames}f @ {currentVideoSettings.fps}fps, {currentVideoSettings.steps} steps
                </>
              )}
            </div>
          )}
          {value.modelImages && (
            <div className="mt-2 text-[10px] text-blue-400/70 bg-blue-500/10 border border-blue-500/20 rounded-lg px-3 py-1.5">
              <span className="font-semibold">Model:</span> {value.modelImages}
              <span className="mx-2">→</span>
              <span className="font-semibold">{getArchitectureLabel(currentArchitecture)}</span>
              {currentArchitecture === "sd15" && <span className="ml-2 text-yellow-400/70">(Safe res: max 768px)</span>}
              {currentArchitecture === "flux_schnell" && <span className="ml-2 text-purple-400/70">(Turbo: 4 steps)</span>}
            </div>
          )}
        </Row>

        {/* Prompt Refinement */}
        <Row label="AI Prompt Refinement" description="Enhance image prompts using the selected chat model (requires Ollama).">
          <Toggle label="AI Prompt Refinement" tone="success" checked={!!value.promptRefinement} onChange={(v) => commit({ ...value, promptRefinement: v })} />
        </Row>
        {value.promptRefinement ? (
          <div className="text-[10px] text-green-400/80 bg-green-500/10 border border-green-500/20 rounded-lg px-3 py-2">
            <span className="font-semibold">Enabled:</span> Prompts are enhanced using your Chat Model. Thinking models (DeepSeek R1, QwQ) auto-fallback to llama3:8b. Falls back to direct mode if Ollama is unavailable.
          </div>
        ) : (
          <div className="text-[10px] text-white/50 bg-white/5 border border-white/10 rounded-lg px-3 py-2">
            <span className="font-semibold">⚡ Direct Mode:</span> Prompts sent directly to ComfyUI without enhancement. Faster but requires detailed prompts.
          </div>
        )}

        {/* Keep model in GPU (ComfyUI VRAM mode) */}
        {(value.providerImages === 'comfyui' || value.providerVideo === 'comfyui') && (
          <Row label="Keep model in GPU memory" description="Recommended for faster repeated responses. Applies on next ComfyUI restart.">
            <select
              aria-label="ComfyUI VRAM mode"
              value={value.comfyVramMode ?? 'high'}
              onChange={(e) => commit({ ...value, comfyVramMode: (e.target.value || 'high') as 'high' | 'normal' | 'low' | 'gpu-only' })}
              className={SELECT_CLS}
            >
              <option value="high">High (recommended)</option>
              <option value="normal">Normal (ComfyUI default)</option>
              <option value="gpu-only">GPU-only (maximum)</option>
              <option value="low">Low (save VRAM)</option>
            </select>
          </Row>
        )}

        {/* Custom Generation Parameters (shown when preset is custom) */}
        {value.preset === "custom" && (
          <div className="space-y-4 border-t border-white/[0.06] pt-4">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">Text Generation</div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-white/50">Temperature</label>
                  <input type="number" className={INPUT_CLS + " h-9"} value={value.textTemperature ?? 0.7} onChange={(e) => commit({ ...value, textTemperature: parseFloat(e.target.value) })} step="0.1" min="0" max="2" />
                </div>
                <div>
                  <label className="text-[10px] text-white/50">Max Tokens</label>
                  <input type="number" className={INPUT_CLS + " h-9"} value={value.textMaxTokens ?? 2048} onChange={(e) => commit({ ...value, textMaxTokens: parseInt(e.target.value) })} step="256" min="256" max="8192" />
                </div>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-2">
                <div className="text-[11px] uppercase tracking-wider text-white/40 font-semibold">Image Generation</div>
                <button
                  type="button"
                  onClick={() => {
                    const settings = getModelSettings(value.modelImages || "", "1:1", "med");
                    commit({ ...value, imgWidth: settings.width, imgHeight: settings.height, imgSteps: settings.steps, imgCfg: settings.cfg });
                  }}
                  className="text-[10px] text-blue-400 hover:text-blue-300 underline"
                >
                  Reset to recommended
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-white/50">Width <span className="text-white/30">(rec: {currentModelSettings.width})</span></label>
                  <input type="number" className={INPUT_CLS + " h-9"} value={value.imgWidth ?? currentModelSettings.width} onChange={(e) => commit({ ...value, imgWidth: parseInt(e.target.value) })} step="64" min="256" max="2048" />
                </div>
                <div>
                  <label className="text-[10px] text-white/50">Height <span className="text-white/30">(rec: {currentModelSettings.height})</span></label>
                  <input type="number" className={INPUT_CLS + " h-9"} value={value.imgHeight ?? currentModelSettings.height} onChange={(e) => commit({ ...value, imgHeight: parseInt(e.target.value) })} step="64" min="256" max="2048" />
                </div>
                <div>
                  <label className="text-[10px] text-white/50">Steps <span className="text-white/30">(rec: {currentModelSettings.steps})</span></label>
                  <input type="number" className={INPUT_CLS + " h-9"} value={value.imgSteps ?? currentModelSettings.steps} onChange={(e) => commit({ ...value, imgSteps: parseInt(e.target.value) })} step="1" min="1" max="100" />
                </div>
                <div>
                  <label className="text-[10px] text-white/50">CFG Scale <span className="text-white/30">(rec: {currentModelSettings.cfg})</span></label>
                  <input type="number" className={INPUT_CLS + " h-9"} value={value.imgCfg ?? currentModelSettings.cfg} onChange={(e) => commit({ ...value, imgCfg: parseFloat(e.target.value) })} step="0.5" min="1" max="20" />
                </div>
                <div className="col-span-2">
                  <label className="text-[10px] text-white/50">Seed (0 = random)</label>
                  <input type="number" className={INPUT_CLS + " h-9"} value={value.imgSeed ?? 0} onChange={(e) => commit({ ...value, imgSeed: parseInt(e.target.value) })} step="1" min="0" />
                </div>
              </div>
              {currentArchitecture === "sd15" && (value.imgWidth ?? 0) > 768 && (
                <div className="mt-2 text-[10px] text-yellow-400/80 bg-yellow-500/10 border border-yellow-500/20 rounded-lg px-3 py-1.5">⚠️ SD 1.5 models work best at max 768px. Higher resolutions may cause duplicate subjects.</div>
              )}
              {currentArchitecture === "flux_schnell" && (value.imgSteps ?? 0) > 6 && (
                <div className="mt-2 text-[10px] text-yellow-400/80 bg-yellow-500/10 border border-yellow-500/20 rounded-lg px-3 py-1.5">⚠️ Flux Schnell is optimized for 4 steps. Higher values may cause over-processing.</div>
              )}
            </div>

            <div>
              <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">Video Generation</div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-white/50">Duration (seconds)</label>
                  <input type="number" className={INPUT_CLS + " h-9"} value={value.vidSeconds ?? 5} onChange={(e) => commit({ ...value, vidSeconds: parseInt(e.target.value) })} step="1" min="1" max="30" />
                </div>
                <div>
                  <label className="text-[10px] text-white/50">FPS</label>
                  <input type="number" className={INPUT_CLS + " h-9"} value={value.vidFps ?? 24} onChange={(e) => commit({ ...value, vidFps: parseInt(e.target.value) })} step="1" min="8" max="60" />
                </div>
                <div className="col-span-2">
                  <label className="text-[10px] text-white/50">Motion Bucket</label>
                  <input type="text" className={INPUT_CLS + " h-9"} value={value.vidMotion ?? "127"} onChange={(e) => commit({ ...value, vidMotion: e.target.value })} placeholder="127" />
                </div>
              </div>
            </div>
          </div>
        )}
      </SettingsCard>
    );
  }

  function renderMemory() {
    return (
      <SettingsCard
        title="Memory & Safety"
        description="How assistants remember context, and sensitive content controls."
        icon={<ShieldCheck size={16} />}
      >
        <Row label="Memory Mode" description="Controls how assistants remember and forget context." stack>
          <select
            className={SELECT_CLS}
            value={value.memoryEngine || 'v2'}
            onChange={(e) => commit({ ...value, memoryEngine: e.target.value as any })}
          >
            <option value="off">Off</option>
            <option value="v1">Basic Memory</option>
            <option value="v2">Adaptive Memory</option>
          </select>
          <div className="text-[10px] text-white/35 mt-2">
            {(value.memoryEngine || 'v2') === 'v2'
              ? 'Adaptive Memory learns over time and forgets what’s no longer relevant. Best for companions and personal assistants.'
              : (value.memoryEngine || 'v2') === 'v1'
                ? 'Basic Memory only remembers what is explicitly saved. Best for deterministic enterprise workflows.'
                : 'Memory is disabled. No facts or preferences will be remembered across sessions.'}
          </div>
        </Row>

        <div className="border-t border-white/[0.06] pt-4">
          <Row label="Spice Mode (NSFW)" description="Enable uncensored content generation.">
            <Toggle label="Spice Mode" tone="danger" checked={!!value.nsfwMode} onChange={(v) => commit({ ...value, nsfwMode: v })} />
          </Row>
          {value.nsfwMode && (
            <div className="mt-2 text-[10px] text-red-400/80 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
              <span className="font-semibold">⚠ Warning:</span> Uncensored mode enabled. Use responsibly and ensure compliance with local laws.
            </div>
          )}
        </div>
      </SettingsCard>
    );
  }

  function renderVoice() {
    return (
      <SettingsCard
        title="Voice Assistant"
        description="Text-to-speech output and voice selection."
        icon={<AudioLines size={16} />}
      >
        <Row label="Enable Text-to-Speech" description="Speak assistant replies aloud.">
          <Toggle label="Enable Text-to-Speech" checked={value.ttsEnabled ?? true} onChange={(v) => commit({ ...value, ttsEnabled: v })} />
        </Row>

        {ttsEngineId === 'web-speech-api' && (
          <Row label="Assistant Voice" description={availableVoices.length > 0 ? `Choose from ${availableVoices.length} available voices.` : 'Loading voices…'} stack>
            <select
              className={SELECT_CLS}
              value={value.selectedVoice ?? ''}
              onChange={(e) => commit({ ...value, selectedVoice: e.target.value })}
            >
              <option value="">System Default</option>
              {availableVoices.map((voice) => (
                <option key={voice.voiceURI} value={voice.name}>
                  {voice.name} ({voice.lang})
                </option>
              ))}
            </select>
          </Row>
        )}

        <div className="border-t border-white/[0.06] pt-4">
          <TtsEngineSection systemVoices={availableVoices} />
        </div>
      </SettingsCard>
    );
  }

  function renderVision() {
    return (
      <SettingsCard
        title="Multimodal Vision"
        description="Enable image understanding in chat & voice. Uploading an image auto-triggers a vision model."
        icon={<Eye size={16} />}
      >
        <Row label="Auto-analyze images" description="Automatically describe uploaded images in chat.">
          <Toggle label="Auto-analyze images" checked={value.multimodalAuto ?? true} onChange={(v) => commit({ ...value, multimodalAuto: v })} />
        </Row>

        {providerSelectRow("Multimodal Provider", "Provider used for vision.", value.providerMultimodal || 'ollama', (k) => commit({ ...value, providerMultimodal: k }))}
        {baseUrlRow("Multimodal Base URL", value.providerMultimodal || 'ollama', value.baseUrlMultimodal, (v) => commit({ ...value, baseUrlMultimodal: v }))}
        {modelSelectRow("Multimodal Model", value.providerMultimodal || 'ollama', value.modelMultimodal || '', (m) => commit({ ...value, modelMultimodal: m }), value.baseUrlMultimodal, 'multimodal')}

        <Row label="Vision Topology" description="How vision results are processed." stack>
          <select
            value={value.multimodalTopology || 'smart'}
            onChange={(e) => commit({ ...value, multimodalTopology: e.target.value as 'direct' | 'smart' | 'agent' | 'knowledge' })}
            className={SELECT_CLS}
          >
            <option value="smart">Smart (Vision + Assistant) — Recommended</option>
            <option value="direct">Fast (Direct Vision)</option>
            <option value="agent">Agent (Autonomous Tools)</option>
            <option value="knowledge">Knowledge (Agent + RAG + Memory)</option>
          </select>
          <div className="text-[10px] text-white/30 mt-1">
            {(value.multimodalTopology || 'smart') === 'knowledge'
              ? 'Full companion mode: agent uses knowledge base, long-term memory, vision, and web search together.'
              : (value.multimodalTopology || 'smart') === 'agent'
                ? 'LLM autonomously decides when to call vision and other tools, then synthesizes a final answer.'
                : (value.multimodalTopology || 'smart') === 'smart'
                  ? 'Vision analysis is sent to your main chat LLM for a refined, conversational answer (default).'
                  : 'Vision model output is shown directly (fastest, no follow-up Q&A).'}
          </div>
        </Row>

        <div className="text-[10px] text-purple-400/80 bg-purple-500/10 border border-purple-500/20 rounded-lg px-3 py-2">
          <span className="font-semibold">Recommended:</span> Install Moondream (1.6 GB) or Gemma 3 Vision (3 GB) from the Models page &gt; Multimodal tab.
        </div>
      </SettingsCard>
    );
  }

  function renderTeams() {
    return (
      <SettingsCard
        title="Teams"
        description="Multi-agent team meeting behavior."
        icon={<Users size={16} />}
      >
        <Row label="Concurrent LLM Calls" description="Max parallel requests to your LLM provider during team meetings." stack>
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={1}
              max={3}
              step={1}
              value={value.teamsConcurrentCalls ?? 1}
              onChange={(e) => commit({ ...value, teamsConcurrentCalls: parseInt(e.target.value) })}
              className="flex-1 h-1.5 rounded-full appearance-none bg-white/10 accent-[#9b5cff]"
            />
            <span className="text-sm font-mono text-white/70 w-6 text-center">{value.teamsConcurrentCalls ?? 1}</span>
          </div>
          <div className="text-[10px] text-white/30 mt-1">
            Use 1 for single-GPU setups (Ollama default). Increase to 2-3 if your provider supports parallel inference.
          </div>
        </Row>
      </SettingsCard>
    );
  }

  function renderTools() {
    return (
      <SettingsCard
        title="Tools & Agents"
        description="Tool gateway and agent manager status."
        icon={<Wrench size={16} />}
      >
        <AgenticStatus backendUrl={value.backendUrl} apiKey={value.apiKey} />
      </SettingsCard>
    );
  }

  function renderMatrixHub() {
    return (
      <SettingsCard
        title="MatrixHub Catalog"
        description="Browse MCP servers from the MatrixHub public catalog."
        icon={<Grid3x3 size={16} />}
      >
        <Row label="Enable MatrixHub" description="When enabled, a MatrixHub tab appears in Discover MCP Servers.">
          <Toggle label="Enable MatrixHub" checked={!!value.matrixHubEnabled} onChange={(v) => commit({ ...value, matrixHubEnabled: v })} />
        </Row>
        {value.matrixHubEnabled && (
          <Row label="MatrixHub URL" description="The endpoint URL for your MatrixHub instance." stack>
            <input
              type="text"
              value={value.matrixHubUrl || ''}
              onChange={(e) => commit({ ...value, matrixHubUrl: e.target.value })}
              placeholder="http://localhost:8080"
              className={INPUT_CLS + " font-mono"}
            />
          </Row>
        )}
      </SettingsCard>
    );
  }

  function renderOllaBridge() {
    return (
      <SettingsCard
        title="OllaBridge API"
        description="Expose personas as an OpenAI-compatible API for OllaBridge & 3D Avatar."
        icon={<Code2 size={16} />}
      >
        <Row label="Enable Shared API" description="Expose personas as an OpenAI-compatible endpoint.">
          <Toggle label="Enable Shared API" tone="success" checked={!!value.ollaBridgeEnabled} onChange={(v) => commit({ ...value, ollaBridgeEnabled: v })} />
        </Row>
        {value.ollaBridgeEnabled && (
          <>
            <Row label="API Key" description="Used as Bearer token or X-API-Key header by external clients." stack>
              <input
                type="text"
                value={value.ollaBridgeApiKey || 'my-secret'}
                onChange={(e) => commit({ ...value, ollaBridgeApiKey: e.target.value })}
                placeholder="my-secret"
                className={INPUT_CLS + " font-mono"}
              />
            </Row>
            <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2">
              <div className="text-[10px] text-emerald-400 font-semibold mb-1">Endpoint Ready</div>
              <div className="text-[10px] text-white/50 font-mono break-all">
                {resolveBackendUrl(value.backendUrl)}/v1/chat/completions
              </div>
              <div className="text-[10px] text-white/30 mt-1">
                Point OllaBridge or any OpenAI SDK to this URL with the API key above.
              </div>
            </div>
          </>
        )}
      </SettingsCard>
    );
  }

  function renderAdvanced() {
    return (
      <SettingsCard
        title="Advanced"
        description="Experimental and developer options. Change with care."
        icon={<FlaskConical size={16} />}
      >
        <Row label="Experimental: Civitai" description="Enable Civitai model downloads (image/video only).">
          <Toggle label="Experimental Civitai" tone="blue" checked={!!value.experimentalCivitai} onChange={(v) => commit({ ...value, experimentalCivitai: v })} />
        </Row>
        {value.experimentalCivitai && (
          <div className="text-[10px] text-blue-400/80 bg-blue-500/10 border border-blue-500/20 rounded-lg px-3 py-2">
            <span className="font-semibold">ℹ️ Experimental:</span> Download and search models from Civitai.com in the Models page. Not all models may work correctly.
          </div>
        )}
        {value.experimentalCivitai && value.nsfwMode && (
          <Row label="Civitai API Key" description="Only needed for adult content." stack>
            <input
              type="password"
              value={value.civitaiApiKey || ""}
              onChange={(e) => commit({ ...value, civitaiApiKey: e.target.value })}
              placeholder="Optional — only needed for adult content"
              className={INPUT_CLS}
              autoComplete="off"
            />
            <div className="text-[9px] text-purple-300/50 mt-1.5">
              Get your API key at <a href="https://civitai.com/user/account" target="_blank" rel="noopener noreferrer" className="text-purple-400 hover:text-purple-300 underline">civitai.com/user/account</a>
            </div>
          </Row>
        )}
      </SettingsCard>
    );
  }

  function renderSection() {
    switch (activeSection) {
      case "general": return renderGeneral();
      case "connection": return renderConnection();
      case "linking": return <OllaBridgeLink />;
      case "providers": return renderProviders();
      case "models": return renderModels();
      case "generation": return renderGeneration();
      case "memory": return renderMemory();
      case "voice": return renderVoice();
      case "vision": return renderVision();
      case "teams": return renderTeams();
      case "tools": return renderTools();
      case "matrixhub": return renderMatrixHub();
      case "ollabridge": return renderOllaBridge();
      case "advanced": return renderAdvanced();
      default: return null;
    }
  }

  return (
    <div
      className="fixed inset-0 z-[200] flex items-stretch sm:items-center justify-center p-0 sm:p-6 bg-black/65 backdrop-blur-[10px]"
      onMouseDown={requestClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Enterprise Settings"
        onMouseDown={(e) => e.stopPropagation()}
        className="relative flex flex-col w-full h-[100dvh] rounded-none sm:w-[min(1120px,calc(100vw-32px))] sm:h-[min(780px,calc(100vh-32px))] sm:rounded-[18px] bg-[#111214] border border-white/10 shadow-[0_24px_80px_rgba(0,0,0,0.65)] overflow-hidden"
      >
        {/* Header */}
        <header className="flex items-center justify-between gap-3 px-5 sm:px-6 py-4 pt-[max(1rem,env(safe-area-inset-top))] sm:pt-4 border-b border-white/[0.08] shrink-0">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-white">Enterprise Settings</h2>
            <p className="text-xs text-white/45 mt-0.5 hidden sm:block">
              Configure backend access, providers, models, and system capabilities.
            </p>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {dirty && (
              <span className="hidden sm:inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full bg-amber-500/12 border border-amber-500/30 text-amber-300">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" /> Unsaved changes
              </span>
            )}
            <button
              type="button"
              onClick={requestClose}
              className="text-white/50 hover:text-white w-8 h-8 flex items-center justify-center rounded-lg hover:bg-white/5 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#9b5cff]/75"
              aria-label="Close settings"
            >
              ✕
            </button>
          </div>
        </header>

        {/* Body: sidebar + content */}
        <div className="flex-1 min-h-0 flex flex-col md:flex-row">
          {/* Desktop sidebar */}
          <nav
            aria-label="Settings sections"
            className="hidden md:flex md:flex-col gap-1 w-56 shrink-0 p-3 border-r border-white/[0.08] bg-[#17181a] overflow-y-auto"
          >
            {SECTIONS.map(({ id, label, Icon }) => {
              const active = activeSection === id;
              return (
                <button
                  key={id}
                  type="button"
                  aria-current={active ? "page" : undefined}
                  onClick={() => setActiveSection(id)}
                  className={[
                    "flex items-center gap-2.5 px-3 py-2 rounded-[10px] text-sm text-left transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#9b5cff]/75",
                    active
                      ? "bg-[#9b5cff]/[0.16] border border-[#9b5cff]/45 text-white"
                      : "border border-transparent text-white/58 hover:text-white/85 hover:bg-white/[0.04]",
                  ].join(" ")}
                >
                  <Icon size={16} className={active ? "text-[#b98bff]" : "text-white/40"} />
                  <span className="truncate">{label}</span>
                  {id === "connection" && (
                    <span className={`ml-auto w-1.5 h-1.5 rounded-full ${online ? "bg-emerald-400" : "bg-white/25"}`} />
                  )}
                </button>
              );
            })}
          </nav>

          {/* Mobile top tabs */}
          <nav
            aria-label="Settings sections"
            className="md:hidden flex gap-1.5 overflow-x-auto px-3 py-2 border-b border-white/[0.08] bg-[#17181a] shrink-0"
          >
            {SECTIONS.map(({ id, label, Icon }) => {
              const active = activeSection === id;
              return (
                <button
                  key={id}
                  type="button"
                  aria-current={active ? "page" : undefined}
                  onClick={() => setActiveSection(id)}
                  className={[
                    "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs whitespace-nowrap transition-colors",
                    active
                      ? "bg-[#9b5cff]/[0.16] border border-[#9b5cff]/45 text-white"
                      : "border border-white/10 text-white/55 hover:text-white/80",
                  ].join(" ")}
                >
                  <Icon size={13} />
                  {label}
                </button>
              );
            })}
          </nav>

          {/* Scrollable content (visible scrollbar on the right) */}
          <div className="flex-1 min-h-0 overflow-y-auto px-4 sm:px-6 py-5 space-y-4 bg-[#151619]">
            <OllamaHealthBanner
              show={showOllamaBanner}
              onDismiss={() => setDismissOllamaBanner(true)}
              onSwitchToVllm={() => {
                commit({
                  ...value,
                  providerChat: value.providerChat === "ollama" ? "openai_compat" : value.providerChat,
                  providerImages: value.providerImages === "ollama" ? "openai_compat" : value.providerImages,
                  providerVideo: value.providerVideo === "ollama" ? "openai_compat" : value.providerVideo,
                });
                setDismissOllamaBanner(false);
              }}
              onFetchModels={() => {
                fetchModelsFor(value.providerChat, providers?.[value.providerChat]?.base_url);
              }}
            />
            {renderSection()}
          </div>
        </div>

        {/* Sticky footer */}
        <footer className="flex items-center justify-end sm:justify-between gap-3 px-4 sm:px-6 py-3.5 pb-[max(0.875rem,env(safe-area-inset-bottom))] sm:pb-3.5 border-t border-white/[0.08] bg-[#141519] shrink-0">
          {/* Hint is desktop-only — on a phone it would squeeze the buttons and
              clip "Save". */}
          <div className="hidden sm:flex items-center gap-2 text-xs text-white/45 min-w-0">
            <Info size={14} className="shrink-0" />
            <span className="truncate">Changes apply after Save.</span>
          </div>
          <div className="flex items-center gap-2 shrink-0 w-full sm:w-auto justify-end">
            <button
              type="button"
              onClick={handleReset}
              disabled={!dirty}
              className="h-10 sm:h-9 px-3.5 sm:px-4 rounded-xl text-sm text-white/60 hover:text-white hover:bg-white/5 disabled:opacity-40 disabled:hover:bg-transparent transition-colors"
            >
              Reset
            </button>
            <button
              type="button"
              onClick={requestClose}
              className="h-10 sm:h-9 px-3.5 sm:px-4 rounded-xl text-sm text-white/70 hover:text-white bg-white/5 hover:bg-white/10 border border-white/10 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              className="h-10 sm:h-9 px-4 sm:px-5 rounded-xl bg-[#9b5cff] hover:bg-[#a970ff] text-white text-sm font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#9b5cff]/75 focus-visible:ring-offset-2 focus-visible:ring-offset-[#141519]"
            >
              {/* Short label on mobile so it never clips. */}
              <span className="sm:hidden">Save</span>
              <span className="hidden sm:inline">Save Settings</span>
            </button>
          </div>
        </footer>
      </div>

      {/* Profile & Integrations modal (additive) */}
      {showProfileSettings ? (
        <ProfileSettingsModal
          backendUrl={value.backendUrl}
          apiKey={value.apiKey}
          nsfwMode={!!value.nsfwMode}
          onClose={() => setShowProfileSettings(false)}
        />
      ) : null}
    </div>
  );
}

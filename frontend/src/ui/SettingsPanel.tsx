import React, { useEffect, useMemo, useState } from "react";
import OllamaHealthBanner from "./OllamaHealthBanner";
import ProfileSettingsModal from "./ProfileSettingsModal";
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
};

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

  const dot = (ok: boolean) => (
    <span className={`inline-block w-2 h-2 rounded-full ${ok ? "bg-green-400" : "bg-white/20"}`} />
  );

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <span className="text-white/50 flex items-center gap-1.5">{dot(status.enabled)} Enabled</span>
        <span className="text-white/50 flex items-center gap-1.5">{dot(status.configured)} Configured</span>
        <span className="text-white/50 flex items-center gap-1.5">{dot(status.reachable)} Gateway reachable</span>
        <span className="text-white/50 flex items-center gap-1.5">{dot(status.admin_configured)} Admin ready</span>
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
  const [voicesInitialized, setVoicesInitialized] = useState(false);

  // Video presets state (fetched from backend based on selected model)
  const [videoPresets, setVideoPresets] = useState<Record<string, { width: number; height: number; fps: number; frames: number; steps: number; cfg: number; denoise: number }>>({});
  const [videoPresetsLoading, setVideoPresetsLoading] = useState(false);

  // Profile & Integrations modal (additive)
  const [showProfileSettings, setShowProfileSettings] = useState(false);

  async function fetchHealth() {
    setHealthErr(null);
    try {
      const res = await fetch(`${value.backendUrl}/health`);
      const data = await res.json();
      setHealth(data);
    } catch (e: any) {
      setHealthErr(e?.message || String(e));
    }
  }

  async function fetchProviders() {
    setLoadingProviders(true);
    setProvidersErr(null);
    try {
      const res = await fetch(`${value.backendUrl}/providers`);
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

  // Fetch video presets when video model changes
  useEffect(() => {
    if (value.modelVideo) {
      fetchVideoPresets(value.modelVideo);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.modelVideo]);

  const providerOptions = useMemo(() => Object.entries(providers), [providers]);

  // Fallback presets (used when backend fetch fails or hasn't completed)
  const FALLBACK_VIDEO_PRESETS: Record<string, { width: number; height: number; fps: number; frames: number; steps: number; cfg: number; denoise: number }> = {
    low:    { width: 512, height: 288, fps: 16, frames: 25, steps: 20, cfg: 3.5, denoise: 0.80 },
    med:    { width: 640, height: 360, fps: 16, frames: 33, steps: 24, cfg: 4.0, denoise: 0.80 },
    high:   { width: 704, height: 400, fps: 24, frames: 41, steps: 28, cfg: 4.0, denoise: 0.80 },
    ultra:  { width: 768, height: 432, fps: 24, frames: 49, steps: 32, cfg: 4.0, denoise: 0.80 },
  };

  // Use fetched presets if available, otherwise fallback
  const VIDEO_PRESETS = Object.keys(videoPresets).length > 0 ? videoPresets : FALLBACK_VIDEO_PRESETS;

  // Compute model-specific settings based on selected image model and preset
  const currentModelSettings = useMemo(() => {
    const model = value.modelImages || "dreamshaper_8.safetensors";
    const preset = value.preset === "custom" ? "high" : value.preset;
    return getModelSettings(model, "1:1", preset);
  }, [value.modelImages, value.preset]);

  const currentArchitecture = useMemo(() => {
    return detectArchitecture(value.modelImages || "");
  }, [value.modelImages]);

  // Get current video preset settings
  const currentVideoSettings = useMemo(() => {
    const presetKey = value.preset === "custom" ? "high" : (value.preset === "med" ? "med" : value.preset);
    return VIDEO_PRESETS[presetKey] || VIDEO_PRESETS.med;
  }, [value.preset]);

  // Auto-apply preset settings when preset or model changes (except in custom mode)
  // Syncs both image AND video settings
  useEffect(() => {
    if (value.preset !== "custom") {
      const imgSettings = currentModelSettings;
      const vidSettings = currentVideoSettings;
      const backendPresetName = value.preset === "med" ? "medium" : value.preset;

      // Check if any values need updating
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
          // Image settings
          imgWidth: imgSettings.width,
          imgHeight: imgSettings.height,
          imgSteps: imgSettings.steps,
          imgCfg: imgSettings.cfg,
          // Video settings
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

  function providerSelectRow(label: string, provider: ProviderKey, setProvider: (k: ProviderKey) => void) {
    return (
      <div>
        <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">{label}</div>
        <select
          className="w-full bg-black border border-white/10 rounded-xl px-3 py-2 text-xs text-white"
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
        >
          {providerOptions.map(([k, info]) => (
            <option key={k} value={k}>
              {info.label}
            </option>
          ))}
        </select>
      </div>
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
      <div className="border-t border-white/5 pt-3">
        <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">{label}</div>
        <input
          className="w-full bg-black border border-white/10 rounded-xl px-3 py-2 text-xs text-white"
          value={valueUrl ?? ''}
          placeholder={hint ? `Default: ${hint}` : 'Optional'}
          onChange={(e) => setUrl(e.target.value)}
        />
        <div className="mt-1 text-[10px] text-white/35">
          Leave blank to use the backend default. Useful when running services locally (e.g. Ollama on http://localhost:11434).
        </div>
      </div>
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
    // Use compound key for provider + type (to separate image vs video models)
    const stateKey = modelType ? `${providerKey}_${modelType}` : providerKey;
    const list = models[stateKey] || [];
    const loading = !!modelsLoading[stateKey];
    const err = modelsErr[stateKey];

    return (
      <div className="border-t border-white/5 pt-3">
        <div className="flex items-center justify-between mb-2">
          <div className="text-[11px] uppercase tracking-wider text-white/40 font-semibold">{label}</div>
          <button
            type="button"
            onClick={() => fetchModelsFor(providerKey, baseUrlOverride, modelType)}
            className="px-3 py-1.5 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 text-xs text-white font-semibold disabled:opacity-50"
            disabled={loading || !providerKey}
          >
            {loading ? "Fetching..." : "Fetch models"}
          </button>
        </div>

        <select
          className="w-full bg-black border border-white/10 rounded-xl px-3 py-2 text-xs text-white"
          value={modelValue}
          onChange={(e) => setModel(e.target.value)}
        >
          {/* keep current value visible even if not in list */}
          {modelValue && !list.includes(modelValue) ? <option value={modelValue}>{modelValue} (current)</option> : null}
          {list.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>

        {err ? <div className="mt-2 text-[11px] text-red-400">{err}</div> : null}
      </div>
    );
  }

  return (
    <div className="absolute bottom-16 left-0 right-0 mx-2 max-h-[70vh] overflow-y-auto bg-[#181818] border border-white/15 rounded-2xl p-4 shadow-2xl z-50">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-bold text-white">Enterprise Settings</h3>
        <button
          type="button"
          onClick={onClose}
          className="text-white/50 hover:text-white p-1 rounded-lg hover:bg-white/5"
          aria-label="Close settings"
        >
          ✕
        </button>
      </div>

      <OllamaHealthBanner
        show={showOllamaBanner}
        onDismiss={() => setDismissOllamaBanner(true)}
        onSwitchToVllm={() => {
          // switch all selected ollama providers to openai_compat (vLLM)
          onChangeDraft({
            ...value,
            providerChat: value.providerChat === "ollama" ? "openai_compat" : value.providerChat,
            providerImages: value.providerImages === "ollama" ? "openai_compat" : value.providerImages,
            providerVideo: value.providerVideo === "ollama" ? "openai_compat" : value.providerVideo,
          });
          // also clear banner dismiss so it can show again if needed
          setDismissOllamaBanner(false);
        }}
        onFetchModels={() => {
          // best effort: fetch models for whichever provider is active for chat
          fetchModelsFor(value.providerChat, providers?.[value.providerChat]?.base_url);
        }}
      />

      {healthErr ? <div className="mb-2 text-[11px] text-yellow-300/80">Health check failed: {healthErr}</div> : null}

      {/* Backend URL + API Key */}
      <div className="space-y-3">
        <div>
          <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">Backend URL</div>
          <input
            className="w-full bg-black border border-white/10 rounded-xl px-3 py-2 text-xs text-white"
            value={value.backendUrl}
            onChange={(e) => onChangeDraft({ ...value, backendUrl: e.target.value })}
          />
        </div>

        <div>
          <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">API Key (optional)</div>
          <input
            type="password"
            className="w-full bg-black border border-white/10 rounded-xl px-3 py-2 text-xs text-white"
            value={value.apiKey}
            onChange={(e) => onChangeDraft({ ...value, apiKey: e.target.value })}
          />
        </div>

        <div className="border-t border-white/5 pt-3">
          <div className="flex items-center justify-between">
            <div className="text-[11px] uppercase tracking-wider text-white/40 font-semibold">Providers</div>
            <button
              type="button"
              onClick={fetchProviders}
              className="px-3 py-1.5 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 text-xs text-white font-semibold disabled:opacity-50"
              disabled={loadingProviders}
            >
              {loadingProviders ? "Loading..." : "Refresh"}
            </button>
          </div>
          {providersErr ? <div className="mt-2 text-[11px] text-red-400">{providersErr}</div> : null}
        </div>

        <div className="grid grid-cols-1 gap-3">
          {providerSelectRow("Chat Provider", value.providerChat, (k) => onChangeDraft({ ...value, providerChat: k }))}
          {providerSelectRow("Image Provider", value.providerImages, (k) => onChangeDraft({ ...value, providerImages: k }))}
          {providerSelectRow("Video Provider", value.providerVideo, (k) => onChangeDraft({ ...value, providerVideo: k }))}
        </div>

        {baseUrlRow("Chat Base URL", value.providerChat, value.baseUrlChat, (v) => onChangeDraft({ ...value, baseUrlChat: v }))}
        {modelSelectRow("Chat Model", value.providerChat, value.modelChat, (m) => onChangeDraft({ ...value, modelChat: m }), value.baseUrlChat)}

        {baseUrlRow("Image Base URL", value.providerImages, value.baseUrlImages, (v) => onChangeDraft({ ...value, baseUrlImages: v }))}
        {modelSelectRow("Image Model (if supported)", value.providerImages, value.modelImages, (m) => onChangeDraft({ ...value, modelImages: m }), value.baseUrlImages, value.providerImages === 'comfyui' ? 'image' : undefined)}

        {baseUrlRow("Video Base URL", value.providerVideo, value.baseUrlVideo, (v) => onChangeDraft({ ...value, baseUrlVideo: v }))}
        {modelSelectRow("Video Model (if supported)", value.providerVideo, value.modelVideo, (m) => onChangeDraft({ ...value, modelVideo: m }), value.baseUrlVideo, value.providerVideo === 'comfyui' ? 'video' : undefined)}

        {/* NSFW/Spice Mode Toggle */}
        <div className="border-t border-white/5 pt-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-white/40 font-semibold">Spice Mode (NSFW)</div>
              <div className="text-[10px] text-white/35 mt-1">Enable uncensored content generation</div>
            </div>
            <button
              type="button"
              onClick={() => onChangeDraft({ ...value, nsfwMode: !value.nsfwMode })}
              className={[
                "relative inline-flex h-6 w-11 items-center rounded-full transition-colors",
                value.nsfwMode ? "bg-red-600" : "bg-white/10",
              ].join(" ")}
            >
              <span
                className={[
                  "inline-block h-4 w-4 transform rounded-full bg-white transition-transform",
                  value.nsfwMode ? "translate-x-6" : "translate-x-1",
                ].join(" ")}
              />
            </button>
          </div>
          {value.nsfwMode && (
            <div className="mt-2 text-[10px] text-red-400/80 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
              <span className="font-semibold">⚠ Warning:</span> Uncensored mode enabled. Use responsibly and ensure compliance with local laws.
            </div>
          )}
        </div>

        {/* Memory Mode Selector */}
        <div className="border-t border-white/5 pt-3">
          <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">Memory Mode</div>
          <select
            className="w-full bg-black border border-white/10 rounded-xl px-3 py-2 text-sm text-white outline-none focus:border-white/20"
            value={value.memoryEngine || 'v2'}
            onChange={(e) => onChangeDraft({ ...value, memoryEngine: e.target.value as any })}
          >
            <option value="off">Off</option>
            <option value="v1">Basic Memory</option>
            <option value="v2">Adaptive Memory</option>
          </select>
          <div className="text-[10px] text-white/35 mt-2">
            {(value.memoryEngine || 'v2') === 'v2'
              ? 'Adaptive Memory learns over time and forgets what\u2019s no longer relevant. Best for companions and personal assistants.'
              : (value.memoryEngine || 'v2') === 'v1'
                ? 'Basic Memory only remembers what is explicitly saved. Best for deterministic enterprise workflows.'
                : 'Memory is disabled. No facts or preferences will be remembered across sessions.'}
          </div>
        </div>

        {/* Experimental Civitai Toggle */}
        <div className="border-t border-white/5 pt-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-white/40 font-semibold">🧪 Experimental: Civitai</div>
              <div className="text-[10px] text-white/35 mt-1">Enable Civitai model downloads (image/video only)</div>
            </div>
            <button
              type="button"
              onClick={() => onChangeDraft({ ...value, experimentalCivitai: !value.experimentalCivitai })}
              className={[
                "relative inline-flex h-6 w-11 items-center rounded-full transition-colors",
                value.experimentalCivitai ? "bg-blue-600" : "bg-white/10",
              ].join(" ")}
            >
              <span
                className={[
                  "inline-block h-4 w-4 transform rounded-full bg-white transition-transform",
                  value.experimentalCivitai ? "translate-x-6" : "translate-x-1",
                ].join(" ")}
              />
            </button>
          </div>
          {value.experimentalCivitai && (
            <div className="mt-2 text-[10px] text-blue-400/80 bg-blue-500/10 border border-blue-500/20 rounded-lg px-3 py-2">
              <span className="font-semibold">ℹ️ Experimental:</span> Download and search models from Civitai.com in the Models page. Not all models may work correctly.
            </div>
          )}

          {/* Civitai API Key (shown when both Civitai and NSFW are enabled) */}
          {value.experimentalCivitai && value.nsfwMode && (
            <div className="mt-3 p-3 bg-purple-500/5 border border-purple-500/20 rounded-lg">
              <label className="text-[10px] text-purple-400/80 font-semibold uppercase tracking-wider block mb-2">
                Civitai API Key (for NSFW content)
              </label>
              <input
                type="password"
                value={value.civitaiApiKey || ""}
                onChange={(e) => onChangeDraft({ ...value, civitaiApiKey: e.target.value })}
                placeholder="Optional - only needed for adult content"
                className="w-full bg-black border border-purple-500/30 rounded-lg px-3 py-2 text-xs text-white placeholder:text-white/30 focus:border-purple-500/50 outline-none transition-colors"
              />
              <div className="text-[9px] text-purple-300/50 mt-1.5">
                Get your API key at <a href="https://civitai.com/user/account" target="_blank" rel="noopener noreferrer" className="text-purple-400 hover:text-purple-300 underline">civitai.com/user/account</a>
              </div>
            </div>
          )}
        </div>

        {/* Prompt Refinement Toggle */}
        <div className="border-t border-white/5 pt-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-white/40 font-semibold">AI Prompt Refinement</div>
              <div className="text-[10px] text-white/35 mt-1">Enhance image prompts using LLM (requires Ollama)</div>
            </div>
            <button
              type="button"
              onClick={() => onChangeDraft({ ...value, promptRefinement: !value.promptRefinement })}
              className={[
                "relative inline-flex h-6 w-11 items-center rounded-full transition-colors",
                value.promptRefinement ? "bg-green-600" : "bg-white/10",
              ].join(" ")}
            >
              <span
                className={[
                  "inline-block h-4 w-4 transform rounded-full bg-white transition-transform",
                  value.promptRefinement ? "translate-x-6" : "translate-x-1",
                ].join(" ")}
              />
            </button>
          </div>
          {value.promptRefinement && (
            <div className="mt-2 text-[10px] text-green-400/80 bg-green-500/10 border border-green-500/20 rounded-lg px-3 py-2">
              <span className="font-semibold">Enabled:</span> Your prompts will be enhanced using your Chat Model. Thinking models (DeepSeek R1, QwQ) auto-fallback to llama3:8b for stability. Falls back to direct mode if Ollama is unavailable.
            </div>
          )}
          {!value.promptRefinement && (
            <div className="mt-2 text-[10px] text-white/50 bg-white/5 border border-white/10 rounded-lg px-3 py-2">
              <span className="font-semibold">⚡ Direct Mode:</span> Prompts sent directly to ComfyUI without enhancement. Faster but requires detailed prompts.
            </div>
          )}
        </div>

        {/* Hardware Preset */}
        <div className="border-t border-white/5 pt-3">
          <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">Hardware Preset</div>
          <div className="grid grid-cols-5 gap-1.5">
            {(["low", "med", "high", "ultra", "custom"] as HardwarePresetUI[]).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => onChangeDraft({ ...value, preset: p })}
                className={[
                  "px-2 py-1.5 rounded-lg text-xs font-semibold transition-all",
                  value.preset === p ? "bg-blue-600 text-white" : "bg-white/5 text-white/60 hover:bg-white/10 hover:text-white/80",
                ].join(" ")}
              >
                {p === "low" ? "Low" : p === "med" ? "Med" : p === "high" ? "High" : p === "ultra" ? "Ultra" : "Custom"}
              </button>
            ))}
          </div>

          {/* Image settings preview */}
          <div className="text-[10px] text-white/35 mt-2">
            {value.preset === "low" && `✓ Low: ${getPresetDescription(value.modelImages || "", "low")}`}
            {value.preset === "med" && `✓ Med: ${getPresetDescription(value.modelImages || "", "med")}`}
            {value.preset === "high" && `✓ High: ${getPresetDescription(value.modelImages || "", "high")}`}
            {value.preset === "ultra" && `✓ Ultra: ${getPresetDescription(value.modelImages || "", "ultra")}`}
            {value.preset === "custom" && "✓ Custom: Manual control (values below)"}
          </div>

          {/* Video settings preview */}
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

          {/* Architecture indicator */}
          {value.modelImages && (
            <div className="mt-2 text-[10px] text-blue-400/70 bg-blue-500/10 border border-blue-500/20 rounded-lg px-3 py-1.5">
              <span className="font-semibold">Model:</span> {value.modelImages}
              <span className="mx-2">→</span>
              <span className="font-semibold">{getArchitectureLabel(currentArchitecture)}</span>
              {currentArchitecture === "sd15" && (
                <span className="ml-2 text-yellow-400/70">(Safe res: max 768px)</span>
              )}
              {currentArchitecture === "flux_schnell" && (
                <span className="ml-2 text-purple-400/70">(Turbo: 4 steps)</span>
              )}
            </div>
          )}
        </div>

        {/* Custom Generation Parameters (shown when preset is custom) */}
        {value.preset === "custom" && (
          <div className="border-t border-white/5 pt-3 space-y-3">
            {/* Text Generation */}
            <div>
              <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">Text Generation</div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-white/50">Temperature</label>
                  <input
                    type="number"
                    className="w-full bg-black border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white"
                    value={value.textTemperature ?? 0.7}
                    onChange={(e) => onChangeDraft({ ...value, textTemperature: parseFloat(e.target.value) })}
                    step="0.1"
                    min="0"
                    max="2"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-white/50">Max Tokens</label>
                  <input
                    type="number"
                    className="w-full bg-black border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white"
                    value={value.textMaxTokens ?? 2048}
                    onChange={(e) => onChangeDraft({ ...value, textMaxTokens: parseInt(e.target.value) })}
                    step="256"
                    min="256"
                    max="8192"
                  />
                </div>
              </div>
            </div>

            {/* Image Generation */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <div className="text-[11px] uppercase tracking-wider text-white/40 font-semibold">Image Generation</div>
                <button
                  type="button"
                  onClick={() => {
                    // Reset to model-recommended values
                    const settings = getModelSettings(value.modelImages || "", "1:1", "med");
                    onChangeDraft({
                      ...value,
                      imgWidth: settings.width,
                      imgHeight: settings.height,
                      imgSteps: settings.steps,
                      imgCfg: settings.cfg,
                    });
                  }}
                  className="text-[10px] text-blue-400 hover:text-blue-300 underline"
                >
                  Reset to recommended
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-white/50">
                    Width <span className="text-white/30">(rec: {currentModelSettings.width})</span>
                  </label>
                  <input
                    type="number"
                    className="w-full bg-black border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white"
                    value={value.imgWidth ?? currentModelSettings.width}
                    onChange={(e) => onChangeDraft({ ...value, imgWidth: parseInt(e.target.value) })}
                    step="64"
                    min="256"
                    max="2048"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-white/50">
                    Height <span className="text-white/30">(rec: {currentModelSettings.height})</span>
                  </label>
                  <input
                    type="number"
                    className="w-full bg-black border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white"
                    value={value.imgHeight ?? currentModelSettings.height}
                    onChange={(e) => onChangeDraft({ ...value, imgHeight: parseInt(e.target.value) })}
                    step="64"
                    min="256"
                    max="2048"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-white/50">
                    Steps <span className="text-white/30">(rec: {currentModelSettings.steps})</span>
                  </label>
                  <input
                    type="number"
                    className="w-full bg-black border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white"
                    value={value.imgSteps ?? currentModelSettings.steps}
                    onChange={(e) => onChangeDraft({ ...value, imgSteps: parseInt(e.target.value) })}
                    step="1"
                    min="1"
                    max="100"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-white/50">
                    CFG Scale <span className="text-white/30">(rec: {currentModelSettings.cfg})</span>
                  </label>
                  <input
                    type="number"
                    className="w-full bg-black border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white"
                    value={value.imgCfg ?? currentModelSettings.cfg}
                    onChange={(e) => onChangeDraft({ ...value, imgCfg: parseFloat(e.target.value) })}
                    step="0.5"
                    min="1"
                    max="20"
                  />
                </div>
                <div className="col-span-2">
                  <label className="text-[10px] text-white/50">Seed (0 = random)</label>
                  <input
                    type="number"
                    className="w-full bg-black border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white"
                    value={value.imgSeed ?? 0}
                    onChange={(e) => onChangeDraft({ ...value, imgSeed: parseInt(e.target.value) })}
                    step="1"
                    min="0"
                  />
                </div>
              </div>
              {currentArchitecture === "sd15" && (value.imgWidth ?? 0) > 768 && (
                <div className="mt-2 text-[10px] text-yellow-400/80 bg-yellow-500/10 border border-yellow-500/20 rounded-lg px-3 py-1.5">
                  ⚠️ SD 1.5 models work best at max 768px. Higher resolutions may cause duplicate subjects.
                </div>
              )}
              {currentArchitecture === "flux_schnell" && (value.imgSteps ?? 0) > 6 && (
                <div className="mt-2 text-[10px] text-yellow-400/80 bg-yellow-500/10 border border-yellow-500/20 rounded-lg px-3 py-1.5">
                  ⚠️ Flux Schnell is optimized for 4 steps. Higher values may cause over-processing.
                </div>
              )}
            </div>

            {/* Video Generation */}
            <div>
              <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">Video Generation</div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-white/50">Duration (seconds)</label>
                  <input
                    type="number"
                    className="w-full bg-black border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white"
                    value={value.vidSeconds ?? 5}
                    onChange={(e) => onChangeDraft({ ...value, vidSeconds: parseInt(e.target.value) })}
                    step="1"
                    min="1"
                    max="30"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-white/50">FPS</label>
                  <input
                    type="number"
                    className="w-full bg-black border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white"
                    value={value.vidFps ?? 24}
                    onChange={(e) => onChangeDraft({ ...value, vidFps: parseInt(e.target.value) })}
                    step="1"
                    min="8"
                    max="60"
                  />
                </div>
                <div className="col-span-2">
                  <label className="text-[10px] text-white/50">Motion Bucket</label>
                  <input
                    type="text"
                    className="w-full bg-black border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white"
                    value={value.vidMotion ?? "127"}
                    onChange={(e) => onChangeDraft({ ...value, vidMotion: e.target.value })}
                    placeholder="127"
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Voice Settings */}
        <div className="border-t border-white/5 pt-3">
          <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">Voice Assistant</div>
          <div className="space-y-3">
            {/* TTS Toggle */}
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={value.ttsEnabled ?? true}
                onChange={(e) => onChangeDraft({ ...value, ttsEnabled: e.target.checked })}
                className="w-4 h-4 rounded"
              />
              <span className="text-xs text-white">Enable Text-to-Speech (TTS)</span>
            </label>

            {/* Voice Selection */}
            <div>
              <label className="block text-[10px] text-white/50 mb-2">Assistant Voice</label>
              <select
                className="w-full bg-black border border-white/10 rounded-lg px-3 py-2 text-xs text-white"
                value={value.selectedVoice ?? ''}
                onChange={(e) => onChangeDraft({ ...value, selectedVoice: e.target.value })}
              >
                <option value="">System Default</option>
                {availableVoices.map((voice) => (
                  <option key={voice.voiceURI} value={voice.name}>
                    {voice.name} ({voice.lang})
                  </option>
                ))}
              </select>
              <div className="mt-1 text-[10px] text-white/40">
                {availableVoices.length > 0
                  ? `Choose from ${availableVoices.length} available voices`
                  : 'Loading voices...'}
              </div>
            </div>
          </div>
        </div>

        {/* Multimodal (Vision) Settings — additive */}
        <div className="border-t border-white/5 pt-3">
          <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">Multimodal (Vision)</div>
          <div className="text-[10px] text-white/35 mb-3">
            Enable image understanding in chat &amp; voice. When active, uploading an image or asking about a picture auto-triggers a vision model.
          </div>

          <div className="space-y-3">
            {/* Auto-trigger toggle */}
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs text-white/70">Auto-analyze images</div>
                <div className="text-[10px] text-white/35">Automatically describe uploaded images in chat</div>
              </div>
              <button
                type="button"
                onClick={() => onChangeDraft({ ...value, multimodalAuto: !(value.multimodalAuto ?? true) })}
                className={[
                  "relative inline-flex h-6 w-11 items-center rounded-full transition-colors",
                  (value.multimodalAuto ?? true) ? "bg-purple-600" : "bg-white/10",
                ].join(" ")}
              >
                <span
                  className={[
                    "inline-block h-4 w-4 transform rounded-full bg-white transition-transform",
                    (value.multimodalAuto ?? true) ? "translate-x-6" : "translate-x-1",
                  ].join(" ")}
                />
              </button>
            </div>

            {/* Multimodal Provider */}
            {providerSelectRow("Multimodal Provider", value.providerMultimodal || 'ollama', (k) => onChangeDraft({ ...value, providerMultimodal: k }))}

            {/* Multimodal Base URL */}
            {baseUrlRow("Multimodal Base URL", value.providerMultimodal || 'ollama', value.baseUrlMultimodal, (v) => onChangeDraft({ ...value, baseUrlMultimodal: v }))}

            {/* Multimodal Model */}
            {modelSelectRow("Multimodal Model", value.providerMultimodal || 'ollama', value.modelMultimodal || '', (m) => onChangeDraft({ ...value, modelMultimodal: m }), value.baseUrlMultimodal, 'multimodal')}

            {/* Vision Topology (Smart vs Direct) */}
            <div>
              <div className="text-xs text-white/70 mb-1">Vision Topology</div>
              <div className="text-[10px] text-white/35 mb-1.5">How vision results are processed</div>
              <select
                value={value.multimodalTopology || 'smart'}
                onChange={(e) => onChangeDraft({ ...value, multimodalTopology: e.target.value as 'direct' | 'smart' | 'agent' | 'knowledge' })}
                className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs text-white/80 focus:outline-none focus:border-purple-500/50"
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
            </div>

            <div className="text-[10px] text-purple-400/80 bg-purple-500/10 border border-purple-500/20 rounded-lg px-3 py-2">
              <span className="font-semibold">Recommended:</span> Install Moondream (1.6 GB) or Gemma 3 Vision (3 GB) from the Models page &gt; Multimodal tab.
            </div>
          </div>
        </div>

        {/* Advanced Tools (Agentic AI) */}
        <div className="border-t border-white/5 pt-3">
          <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">Advanced Tools</div>
          <AgenticStatus backendUrl={value.backendUrl} apiKey={value.apiKey} />
        </div>

        {/* Bottom actions */}
        <div className="border-t border-white/5 pt-4 mt-2 space-y-3">
          <div className="text-[11px] text-white/40">Changes apply after Save.</div>
          <div className="flex items-center justify-between gap-4">
            <button
              type="button"
              onClick={() => setShowProfileSettings(true)}
              className="text-[11px] px-4 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-white/20 text-white/70 hover:text-white transition-all"
            >
              Profile &amp; Integrations
            </button>
            <button
              type="button"
              onClick={onSave}
              className="px-5 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm font-bold transition-colors"
            >
              Save Settings
            </button>
          </div>
        </div>
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

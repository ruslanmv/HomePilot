import React, { useEffect, useMemo, useState } from "react";
import OllamaHealthBanner from "./OllamaHealthBanner";
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

export type HardwarePresetUI = "low" | "med" | "high" | "custom";

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

  // Experimental features
  experimentalCivitai?: boolean;
  civitaiApiKey?: string;  // Optional API key for Civitai NSFW content

  // Prompt refinement (AI enhancement of image prompts)
  promptRefinement?: boolean;

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
};

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

  async function fetchModelsFor(providerKey: string, baseUrlOverride?: string, modelType?: 'image' | 'video') {
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

  const providerOptions = useMemo(() => Object.entries(providers), [providers]);

  // Compute model-specific settings based on selected image model and preset
  const currentModelSettings = useMemo(() => {
    const model = value.modelImages || "dreamshaper_8.safetensors";
    const preset = value.preset === "custom" ? "med" : value.preset;
    return getModelSettings(model, "1:1", preset);
  }, [value.modelImages, value.preset]);

  const currentArchitecture = useMemo(() => {
    return detectArchitecture(value.modelImages || "");
  }, [value.modelImages]);

  // Auto-apply preset settings when preset or model changes (except in custom mode)
  useEffect(() => {
    if (value.preset !== "custom") {
      const settings = currentModelSettings;
      // Only update if values differ to prevent infinite loops
      if (
        value.imgWidth !== settings.width ||
        value.imgHeight !== settings.height ||
        value.imgSteps !== settings.steps ||
        value.imgCfg !== settings.cfg
      ) {
        onChangeDraft({
          ...value,
          imgWidth: settings.width,
          imgHeight: settings.height,
          imgSteps: settings.steps,
          imgCfg: settings.cfg,
        });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.preset, value.modelImages, currentModelSettings]);

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
    modelType?: 'image' | 'video'
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
    <div className="absolute bottom-16 left-4 w-[420px] max-h-[80vh] overflow-y-auto bg-[#121212] border border-white/10 rounded-2xl p-4 shadow-2xl z-30 ring-1 ring-white/10">
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
              <span className="font-semibold">✨ Enabled:</span> Your prompts will be enhanced for better results. Falls back to direct mode if Ollama is unavailable.
            </div>
          )}
          {!value.promptRefinement && (
            <div className="mt-2 text-[10px] text-white/50 bg-white/5 border border-white/10 rounded-lg px-3 py-2">
              <span className="font-semibold">⚡ Direct Mode:</span> Prompts sent directly to ComfyUI without enhancement. Faster but requires detailed prompts.
            </div>
          )}
        </div>

        {/* Hardware */}
        <div className="border-t border-white/5 pt-3">
          <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">Hardware Preset</div>
          <div className="grid grid-cols-4 gap-2">
            {(["low", "med", "high", "custom"] as HardwarePresetUI[]).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => onChangeDraft({ ...value, preset: p })}
                className={[
                  "px-2 py-1.5 rounded-lg text-xs font-semibold transition-all",
                  value.preset === p ? "bg-blue-600 text-white" : "bg-white/5 text-white/60 hover:bg-white/10 hover:text-white/80",
                ].join(" ")}
              >
                {p === "low" ? "Low" : p === "med" ? "Med" : p === "high" ? "High" : "Custom"}
              </button>
            ))}
          </div>
          <div className="text-[10px] text-white/35 mt-2">
            {value.preset === "low" && `✓ Low: ${getPresetDescription(value.modelImages || "", "low")}`}
            {value.preset === "med" && `✓ Med: ${getPresetDescription(value.modelImages || "", "med")}`}
            {value.preset === "high" && `✓ High: ${getPresetDescription(value.modelImages || "", "high")}`}
            {value.preset === "custom" && "✓ Custom: Manual control (values below)"}
          </div>

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

        {/* Bottom actions */}
        <div className="border-t border-white/5 pt-3 flex items-center justify-between">
          <div className="text-[11px] text-white/40">Changes apply after Save.</div>
          <button
            type="button"
            onClick={onSave}
            className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm font-bold"
          >
            Save Settings
          </button>
        </div>
      </div>
    </div>
  );
}

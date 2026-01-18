import React, { useEffect, useMemo, useState } from "react";
import OllamaHealthBanner from "./OllamaHealthBanner";

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

  async function fetchModelsFor(providerKey: string, baseUrlOverride?: string) {
    setModelsLoading((m) => ({ ...m, [providerKey]: true }));
    setModelsErr((m) => ({ ...m, [providerKey]: null }));
    try {
      const base = baseUrlOverride || providers?.[providerKey]?.base_url || "";
      const url = `${value.backendUrl}/models?provider=${encodeURIComponent(providerKey)}&base_url=${encodeURIComponent(base)}`;
      const res = await fetch(url);
      const data = await res.json();
      if (!data.ok) throw new Error(data.message || "Failed to fetch models");
      setModels((prev) => ({ ...prev, [providerKey]: data.models || [] }));
      if (!data.models || data.models.length === 0) {
        setModelsErr((m) => ({ ...m, [providerKey]: "No models returned by provider." }));
      }
    } catch (e: any) {
      setModelsErr((m) => ({ ...m, [providerKey]: e?.message || String(e) }));
    } finally {
      setModelsLoading((m) => ({ ...m, [providerKey]: false }));
    }
  }

  useEffect(() => {
    fetchHealth();
    fetchProviders();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.backendUrl]);

  const providerOptions = useMemo(() => Object.entries(providers), [providers]);

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

  function modelSelectRow(
    label: string,
    providerKey: ProviderKey,
    modelValue: string,
    setModel: (m: string) => void,
    baseUrlOverride?: string
  ) {
    const list = models[providerKey] || [];
    const loading = !!modelsLoading[providerKey];
    const err = modelsErr[providerKey];

    return (
      <div className="border-t border-white/5 pt-3">
        <div className="flex items-center justify-between mb-2">
          <div className="text-[11px] uppercase tracking-wider text-white/40 font-semibold">{label}</div>
          <button
            type="button"
            onClick={() => fetchModelsFor(providerKey, baseUrlOverride)}
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

        {modelSelectRow("Chat Model", value.providerChat, value.modelChat, (m) => onChangeDraft({ ...value, modelChat: m }))}
        {modelSelectRow("Image Model (if supported)", value.providerImages, value.modelImages, (m) => onChangeDraft({ ...value, modelImages: m }))}
        {modelSelectRow("Video Model (if supported)", value.providerVideo, value.modelVideo, (m) => onChangeDraft({ ...value, modelVideo: m }))}

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
            {value.preset === "low" && "✓ Low: Quick iterations, lower quality (768x768, 16 steps)"}
            {value.preset === "med" && "✓ Med: Balanced quality and speed (1024x1024, 24 steps)"}
            {value.preset === "high" && "✓ High: Best quality, slower (1536x1536, 40 steps)"}
            {value.preset === "custom" && "✓ Custom: Manual control"}
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

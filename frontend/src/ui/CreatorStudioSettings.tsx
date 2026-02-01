import React, { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, RefreshCw, Settings2, Sliders, X, Lock } from "lucide-react";

export type CreatorStudioGenerationParams = {
  enabled: boolean;

  // Core generation knobs (shared conceptually across image/video)
  steps: number;          // e.g. diffusion steps
  cfgScale: number;       // guidance
  creativity: number;     // denoise/strength-ish knob (0..1)

  // Optional overrides
  useCustomNegativePrompt: boolean;
  customNegativePrompt: string;

  lockSeed: boolean;
  seed: number;
};

export const CREATOR_STUDIO_PARAM_DEFAULTS: CreatorStudioGenerationParams = {
  enabled: false,
  steps: 30,
  cfgScale: 3.5,
  creativity: 0.85,
  useCustomNegativePrompt: false,
  customNegativePrompt: "",
  lockSeed: false,
  seed: Math.floor(Math.random() * 2147483647),
};

type Props = {
  value: CreatorStudioGenerationParams;
  onChange: (next: CreatorStudioGenerationParams) => void;

  // Optional: if you want this to render as a floating panel
  floating?: boolean;
  show?: boolean;
  onRequestClose?: () => void;
};

export function CreatorStudioSettings({
  value,
  onChange,
  floating = false,
  show = true,
  onRequestClose,
}: Props) {
  const [advancedMode, setAdvancedMode] = useState(true);

  const presetDefaults = useMemo(() => CREATOR_STUDIO_PARAM_DEFAULTS, []);

  const reset = () => onChange({ ...presetDefaults, enabled: value.enabled });

  const panelBody = (
    <div className="p-5 space-y-6 max-h-[70vh] overflow-y-auto">
      {/* Enable toggle */}
      <div className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/10">
        <div>
          <div className="text-sm font-medium text-white/90">Enable Parameters</div>
          <div className="text-xs text-white/40">Override generation defaults for images & videos</div>
        </div>
        <button
          type="button"
          onClick={() => onChange({ ...value, enabled: !value.enabled })}
          className={`w-10 h-5 rounded-full transition-colors relative ${
            value.enabled ? "bg-purple-500" : "bg-white/20"
          }`}
          aria-label="Enable Parameters"
        >
          <div
            className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
              value.enabled ? "translate-x-5" : "translate-x-0.5"
            }`}
          />
        </button>
      </div>

      {/* Advanced Controls accordion */}
      <button
        type="button"
        onClick={() => setAdvancedMode(!advancedMode)}
        className={`w-full flex items-center justify-between p-3 rounded-xl border transition-colors ${
          advancedMode
            ? "bg-purple-500/20 border-purple-500/40 text-purple-300"
            : "bg-white/5 border-white/10 text-white/60 hover:border-white/20"
        }`}
      >
        <span className="flex items-center gap-2 font-medium text-sm">
          <Sliders size={16} />
          Advanced Controls
        </span>
        {advancedMode ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>

      {advancedMode && (
        <div className="space-y-4 animate-in fade-in slide-in-from-top-2 duration-200">
          {/* Steps */}
          <div className={`space-y-2 ${!value.enabled ? "opacity-50 pointer-events-none" : ""}`}>
            <div className="flex justify-between text-xs">
              <span className="uppercase tracking-wider text-white/40 font-semibold">Steps</span>
              <span className="text-white/60">{value.steps}</span>
            </div>
            <input
              type="range"
              min={10}
              max={50}
              value={value.steps}
              onChange={(e) => onChange({ ...value, steps: Number(e.target.value) })}
              className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer
                         [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
                         [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"
            />
          </div>

          {/* CFG Scale */}
          <div className={`space-y-2 ${!value.enabled ? "opacity-50 pointer-events-none" : ""}`}>
            <div className="flex justify-between text-xs">
              <span className="uppercase tracking-wider text-white/40 font-semibold">CFG Scale</span>
              <span className="text-white/60">{value.cfgScale.toFixed(1)}</span>
            </div>
            <input
              type="range"
              min={1}
              max={15}
              step={0.5}
              value={value.cfgScale}
              onChange={(e) => onChange({ ...value, cfgScale: Number(e.target.value) })}
              className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer
                         [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
                         [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"
            />
          </div>

          {/* Creativity */}
          <div className={`space-y-2 ${!value.enabled ? "opacity-50 pointer-events-none" : ""}`}>
            <div className="flex justify-between text-xs">
              <span className="uppercase tracking-wider text-white/40 font-semibold">Creativity</span>
              <span className="text-white/60">{value.creativity.toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-[10px] text-white/30 mb-1">
              <span>More Faithful</span>
              <span>More Creative</span>
            </div>
            <input
              type="range"
              min={0.1}
              max={1.0}
              step={0.05}
              value={value.creativity}
              onChange={(e) => onChange({ ...value, creativity: Number(e.target.value) })}
              className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer
                         [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
                         [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"
            />
          </div>

          {/* Custom Negative Prompt */}
          <div className={`space-y-2 ${!value.enabled ? "opacity-50 pointer-events-none" : ""}`}>
            <div className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/10">
              <span className="text-sm text-white/80">Custom Negative Prompt</span>
              <button
                type="button"
                onClick={() => onChange({ ...value, useCustomNegativePrompt: !value.useCustomNegativePrompt })}
                className={`w-10 h-5 rounded-full transition-colors relative ${
                  value.useCustomNegativePrompt ? "bg-purple-500" : "bg-white/20"
                }`}
                aria-label="Custom Negative Prompt"
              >
                <div
                  className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                    value.useCustomNegativePrompt ? "translate-x-5" : "translate-x-0.5"
                  }`}
                />
              </button>
            </div>

            {value.useCustomNegativePrompt && (
              <div className="space-y-2">
                <textarea
                  value={value.customNegativePrompt}
                  onChange={(e) => onChange({ ...value, customNegativePrompt: e.target.value })}
                  placeholder="text, watermark, logo, low quality, blurry, flicker, jitter, deformed"
                  className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2 text-sm text-white
                             focus:border-purple-500/50 focus:outline-none resize-none h-20"
                />
                <p className="text-[10px] text-white/40">Separate terms with commas. Leave empty to use scene/model default.</p>
              </div>
            )}
          </div>

          {/* Lock Seed */}
          <div className={`space-y-2 ${!value.enabled ? "opacity-50 pointer-events-none" : ""}`}>
            <div className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/10">
              <span className="text-sm text-white/80 flex items-center gap-2">
                <Lock size={14} className="text-white/60" />
                Lock Seed
              </span>
              <button
                type="button"
                onClick={() => {
                  const nextLock = !value.lockSeed;
                  onChange({
                    ...value,
                    lockSeed: nextLock,
                    seed: nextLock ? value.seed || Math.floor(Math.random() * 2147483647) : value.seed,
                  });
                }}
                className={`w-10 h-5 rounded-full transition-colors relative ${value.lockSeed ? "bg-purple-500" : "bg-white/20"}`}
                aria-label="Lock Seed"
              >
                <div
                  className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                    value.lockSeed ? "translate-x-5" : "translate-x-0.5"
                  }`}
                />
              </button>
            </div>

            {value.lockSeed && (
              <input
                type="number"
                value={value.seed}
                onChange={(e) => onChange({ ...value, seed: Number(e.target.value) })}
                className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2 text-sm text-white font-mono
                           focus:border-purple-500/50 focus:outline-none"
                placeholder="Seed value"
              />
            )}
          </div>
        </div>
      )}

      <div className="p-4 rounded-xl bg-purple-900/10 border border-purple-500/20 text-xs text-purple-200/70 leading-relaxed">
        <span className="font-bold text-purple-400 block mb-1">PRO TIP</span>
        Enable Parameters to override defaults. Use Lock Seed to regenerate with the same composition.
      </div>
    </div>
  );

  // Inline mode (inside Project Settings modal)
  if (!floating) {
    return (
      <div className="bg-black/30 border border-white/10 rounded-2xl overflow-hidden">
        <div className="p-5 border-b border-white/10 flex items-center justify-between">
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Settings2 size={16} />
            PARAMETERS
          </h3>
          <button
            type="button"
            onClick={reset}
            className="text-white/50 hover:text-purple-400 transition-colors flex items-center gap-1 text-xs"
            title="Reset to recommended defaults"
          >
            <RefreshCw size={14} />
            Reset
          </button>
        </div>
        {panelBody}
      </div>
    );
  }

  // Floating panel mode (top-right), like your snippet
  if (!show) return null;

  return (
    <div className="absolute top-20 right-6 z-30 bg-black/95 border border-white/10 rounded-2xl shadow-2xl w-80 backdrop-blur-xl overflow-hidden">
      <div className="p-5 border-b border-white/10 flex items-center justify-between">
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <Settings2 size={16} />
          PARAMETERS
        </h3>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={reset}
            className="text-white/50 hover:text-purple-400 transition-colors flex items-center gap-1 text-xs"
            title="Reset to recommended defaults"
          >
            <RefreshCw size={14} />
            Reset
          </button>
          {onRequestClose && (
            <button type="button" onClick={onRequestClose} className="text-white/50 hover:text-white">
              <X size={16} />
            </button>
          )}
        </div>
      </div>
      {panelBody}
    </div>
  );
}

export default CreatorStudioSettings;

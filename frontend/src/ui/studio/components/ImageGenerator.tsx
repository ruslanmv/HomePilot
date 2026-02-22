import React, { useState, useEffect, useCallback } from 'react';
import { PolicyBadge } from './PolicyBadge';
import { resolveFileUrl } from '../../resolveFileUrl';

interface GenerationSettings {
  model: string;
  width: number;
  height: number;
  steps: number;
  cfg: number;
  sampler: string;
  clipSkip: number;
  seed: number | 'random';
}

interface PolicyResult {
  allowed: boolean;
  reason: string;
  flags: string[];
}

interface ImageGeneratorProps {
  contentRating: 'sfw' | 'mature';
  onGenerate: (prompt: string, negPrompt: string, settings: GenerationSettings) => void;
  isGenerating?: boolean;
  generatedImage?: string | null;
  presetSettings?: Partial<GenerationSettings>;
  presetPositivePrefix?: string;
  presetPositiveSuffix?: string;
  presetNegative?: string;
}

const DEFAULT_SETTINGS: GenerationSettings = {
  model: 'abyssOrangeMix3_aom3a1b.safetensors',
  width: 512,
  height: 768,
  steps: 25,
  cfg: 6.0,
  sampler: 'dpm++_2m_karras',
  clipSkip: 2,
  seed: 'random',
};

const MODELS = [
  { id: 'abyssOrangeMix3_aom3a1b.safetensors', label: 'AbyssOrangeMix3 (AOM3)', nsfw: true },
  { id: 'counterfeit_v30.safetensors', label: 'Counterfeit V3.0', nsfw: true },
  { id: 'anything_v5PrtRE.safetensors', label: 'Anything V5', nsfw: true },
  { id: 'sd_xl_base_1.0.safetensors', label: 'SDXL Base 1.0', nsfw: false },
  { id: 'dreamshaper_8.safetensors', label: 'DreamShaper 8', nsfw: true },
];

const SIZES = [
  { width: 512, height: 512, label: 'Square (512x512)' },
  { width: 512, height: 768, label: 'Portrait (512x768)' },
  { width: 768, height: 512, label: 'Landscape (768x512)' },
  { width: 768, height: 1024, label: 'Tall (768x1024)' },
  { width: 1024, height: 768, label: 'Wide (1024x768)' },
];

const SAMPLERS = [
  'dpm++_2m_karras',
  'euler_a',
  'euler',
  'dpm++_sde_karras',
  'ddim',
];

/**
 * Image Generator Interface
 *
 * Main generation UI with prompt input, settings, and preview.
 * Includes real-time policy checking.
 */
export const ImageGenerator: React.FC<ImageGeneratorProps> = ({
  contentRating,
  onGenerate,
  isGenerating = false,
  generatedImage = null,
  presetSettings,
  presetPositivePrefix = '',
  presetPositiveSuffix = '',
  presetNegative = '',
}) => {
  const [prompt, setPrompt] = useState('');
  const [negativePrompt, setNegativePrompt] = useState(presetNegative);
  const [settings, setSettings] = useState<GenerationSettings>({
    ...DEFAULT_SETTINGS,
    ...presetSettings,
  });
  const [policyResult, setPolicyResult] = useState<PolicyResult | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Update negative prompt when preset changes
  useEffect(() => {
    if (presetNegative) {
      setNegativePrompt(presetNegative);
    }
  }, [presetNegative]);

  // Apply preset settings
  useEffect(() => {
    if (presetSettings) {
      setSettings((prev) => ({ ...prev, ...presetSettings }));
    }
  }, [presetSettings]);

  // Real-time policy check with debounce
  useEffect(() => {
    const fullPrompt = `${presetPositivePrefix}${prompt}${presetPositiveSuffix}`;
    if (!fullPrompt.trim()) {
      setPolicyResult(null);
      return;
    }

    const timer = setTimeout(async () => {
      try {
        const res = await fetch(
          `/studio/image/policy-check?prompt=${encodeURIComponent(fullPrompt)}&content_rating=${contentRating}&provider=comfyui`,
          { method: 'POST' }
        );
        const data = await res.json();
        setPolicyResult(data);
      } catch (e) {
        console.error('Policy check failed:', e);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [prompt, contentRating, presetPositivePrefix, presetPositiveSuffix]);

  const handleGenerate = useCallback(() => {
    const fullPrompt = `${presetPositivePrefix}${prompt}${presetPositiveSuffix}`;
    onGenerate(fullPrompt, negativePrompt, settings);
  }, [prompt, negativePrompt, settings, presetPositivePrefix, presetPositiveSuffix, onGenerate]);

  const handleRandomize = () => {
    setSettings((prev) => ({
      ...prev,
      seed: Math.floor(Math.random() * 2147483647),
    }));
  };

  const selectedSize = SIZES.find(
    (s) => s.width === settings.width && s.height === settings.height
  );

  const canGenerate = prompt.trim() && (!policyResult || policyResult.allowed);

  return (
    <div className="image-generator">
      {/* Preview Area */}
      <div className="preview-area">
        {isGenerating ? (
          <div className="generating-state">
            <div className="spinner" />
            <p>Generating...</p>
          </div>
        ) : generatedImage ? (
          <img src={resolveFileUrl(generatedImage)} alt="Generated" className="generated-image" />
        ) : (
          <div className="empty-state">
            <span className="empty-icon">&#127912;</span>
            <p>Enter a prompt to generate</p>
          </div>
        )}
      </div>

      {/* Prompt Section */}
      <div className="prompt-section">
        <div className="prompt-group">
          <label className="prompt-label">
            PROMPT
            {presetPositivePrefix && (
              <span className="preset-indicator" title="Preset prefix applied">
                &#10003; Preset
              </span>
            )}
          </label>
          <textarea
            className="prompt-input"
            placeholder="beautiful anime girl, long hair, cherry blossoms..."
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
          />
          {presetPositivePrefix && (
            <div className="preset-preview">
              <small>
                Full prompt: <code>{presetPositivePrefix}{prompt || '...'}{presetPositiveSuffix}</code>
              </small>
            </div>
          )}
        </div>

        <div className="prompt-group">
          <label className="prompt-label">NEGATIVE PROMPT</label>
          <textarea
            className="prompt-input negative"
            placeholder="lowres, bad anatomy, blurry..."
            value={negativePrompt}
            onChange={(e) => setNegativePrompt(e.target.value)}
            rows={2}
          />
        </div>

        {/* Quick Settings */}
        <div className="quick-settings">
          <div className="setting-group">
            <label>Model</label>
            <select
              value={settings.model}
              onChange={(e) => setSettings({ ...settings, model: e.target.value })}
            >
              {MODELS.filter((m) => !m.nsfw || contentRating === 'mature').map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label} {m.nsfw ? '\uD83D\uDD1E' : ''}
                </option>
              ))}
            </select>
          </div>

          <div className="setting-group">
            <label>Size</label>
            <select
              value={`${settings.width}x${settings.height}`}
              onChange={(e) => {
                const [w, h] = e.target.value.split('x').map(Number);
                setSettings({ ...settings, width: w, height: h });
              }}
            >
              {SIZES.map((s) => (
                <option key={`${s.width}x${s.height}`} value={`${s.width}x${s.height}`}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          <div className="setting-group">
            <label>Seed</label>
            <div className="seed-input">
              <input
                type="text"
                value={settings.seed === 'random' ? 'Random' : settings.seed}
                onChange={(e) => {
                  const val = e.target.value;
                  if (val.toLowerCase() === 'random' || val === '') {
                    setSettings({ ...settings, seed: 'random' });
                  } else {
                    const num = parseInt(val, 10);
                    if (!isNaN(num)) {
                      setSettings({ ...settings, seed: num });
                    }
                  }
                }}
              />
              <button className="dice-btn" onClick={handleRandomize} title="Randomize">
                &#127922;
              </button>
            </div>
          </div>
        </div>

        {/* Advanced Settings */}
        <button
          className="advanced-toggle"
          onClick={() => setShowAdvanced(!showAdvanced)}
        >
          {showAdvanced ? '\u25BC' : '\u25B6'} Advanced Settings
        </button>

        {showAdvanced && (
          <div className="advanced-settings">
            <div className="slider-group">
              <label>Steps: {settings.steps}</label>
              <input
                type="range"
                min={10}
                max={50}
                value={settings.steps}
                onChange={(e) => setSettings({ ...settings, steps: Number(e.target.value) })}
              />
            </div>

            <div className="slider-group">
              <label>CFG: {settings.cfg}</label>
              <input
                type="range"
                min={1}
                max={20}
                step={0.5}
                value={settings.cfg}
                onChange={(e) => setSettings({ ...settings, cfg: Number(e.target.value) })}
              />
            </div>

            <div className="setting-group">
              <label>Sampler</label>
              <select
                value={settings.sampler}
                onChange={(e) => setSettings({ ...settings, sampler: e.target.value })}
              >
                {SAMPLERS.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>

            <div className="slider-group">
              <label>Clip Skip: {settings.clipSkip}</label>
              <input
                type="range"
                min={1}
                max={4}
                value={settings.clipSkip}
                onChange={(e) => setSettings({ ...settings, clipSkip: Number(e.target.value) })}
              />
            </div>
          </div>
        )}

        {/* Action Buttons */}
        <div className="action-row">
          <button
            className="generate-btn"
            onClick={handleGenerate}
            disabled={!canGenerate || isGenerating}
          >
            {isGenerating ? 'Generating...' : '\u2728 Generate'}
          </button>

          <button className="randomize-btn" onClick={handleRandomize}>
            &#127922; Randomize
          </button>
        </div>

        {/* Policy Status */}
        <div className="policy-status">
          {policyResult && <PolicyBadge result={policyResult} />}
        </div>
      </div>

      <style>{`
        .image-generator {
          display: flex;
          flex-direction: column;
          gap: 20px;
          height: 100%;
        }

        .preview-area {
          flex: 1;
          min-height: 300px;
          background: var(--color-background);
          border: 2px dashed var(--color-border);
          border-radius: 12px;
          display: flex;
          align-items: center;
          justify-content: center;
          overflow: hidden;
        }

        .empty-state,
        .generating-state {
          text-align: center;
          color: var(--color-text-muted);
        }

        .empty-icon {
          font-size: 48px;
          display: block;
          margin-bottom: 12px;
        }

        .spinner {
          width: 40px;
          height: 40px;
          border: 3px solid var(--color-border);
          border-top-color: var(--color-primary);
          border-radius: 50%;
          animation: spin 1s linear infinite;
          margin: 0 auto 12px;
        }

        @keyframes spin {
          to { transform: rotate(360deg); }
        }

        .generated-image {
          max-width: 100%;
          max-height: 100%;
          object-fit: contain;
          border-radius: 8px;
        }

        .prompt-section {
          background: var(--color-surface);
          border-radius: 12px;
          padding: 20px;
          border: 1px solid var(--color-border);
        }

        .prompt-group {
          margin-bottom: 16px;
        }

        .prompt-label {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 12px;
          font-weight: 600;
          color: var(--color-text-muted);
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin-bottom: 8px;
        }

        .preset-indicator {
          background: var(--color-primary-light);
          color: var(--color-primary);
          padding: 2px 8px;
          border-radius: 4px;
          font-size: 11px;
        }

        .prompt-input {
          width: 100%;
          padding: 12px;
          border: 1px solid var(--color-border);
          border-radius: 8px;
          background: var(--color-background);
          color: var(--color-text);
          font-size: 14px;
          resize: vertical;
          font-family: inherit;
        }

        .prompt-input:focus {
          outline: none;
          border-color: var(--color-primary);
          box-shadow: 0 0 0 3px var(--color-primary-light);
        }

        .prompt-input.negative {
          font-size: 13px;
          color: var(--color-text-muted);
        }

        .preset-preview {
          margin-top: 8px;
          padding: 8px;
          background: var(--color-background);
          border-radius: 6px;
          font-size: 12px;
          color: var(--color-text-muted);
        }

        .preset-preview code {
          word-break: break-all;
        }

        .quick-settings {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 12px;
          margin-bottom: 16px;
        }

        .setting-group {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .setting-group label {
          font-size: 12px;
          font-weight: 500;
          color: var(--color-text-muted);
        }

        .setting-group select,
        .setting-group input[type="text"] {
          padding: 8px 12px;
          border: 1px solid var(--color-border);
          border-radius: 6px;
          background: var(--color-background);
          color: var(--color-text);
          font-size: 13px;
        }

        .seed-input {
          display: flex;
          gap: 4px;
        }

        .seed-input input {
          flex: 1;
          min-width: 0;
        }

        .dice-btn {
          padding: 8px 10px;
          border: 1px solid var(--color-border);
          border-radius: 6px;
          background: var(--color-surface);
          cursor: pointer;
          font-size: 16px;
        }

        .dice-btn:hover {
          background: var(--color-surface-hover);
        }

        .advanced-toggle {
          background: none;
          border: none;
          color: var(--color-text-muted);
          font-size: 13px;
          cursor: pointer;
          padding: 8px 0;
          margin-bottom: 12px;
        }

        .advanced-toggle:hover {
          color: var(--color-text);
        }

        .advanced-settings {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 16px;
          padding: 16px;
          background: var(--color-background);
          border-radius: 8px;
          margin-bottom: 16px;
        }

        .slider-group {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .slider-group label {
          font-size: 12px;
          font-weight: 500;
          color: var(--color-text-muted);
        }

        .slider-group input[type="range"] {
          width: 100%;
          accent-color: var(--color-primary);
        }

        .action-row {
          display: flex;
          gap: 12px;
          margin-bottom: 12px;
        }

        .generate-btn {
          flex: 1;
          padding: 14px 24px;
          background: var(--color-primary);
          color: white;
          border: none;
          border-radius: 8px;
          font-size: 16px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s;
        }

        .generate-btn:hover:not(:disabled) {
          background: var(--color-primary-hover);
          transform: translateY(-1px);
        }

        .generate-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
          transform: none;
        }

        .randomize-btn {
          padding: 14px 20px;
          background: var(--color-surface);
          color: var(--color-text);
          border: 1px solid var(--color-border);
          border-radius: 8px;
          font-size: 14px;
          cursor: pointer;
        }

        .randomize-btn:hover {
          background: var(--color-surface-hover);
        }

        .policy-status {
          min-height: 24px;
        }
      `}</style>
    </div>
  );
};

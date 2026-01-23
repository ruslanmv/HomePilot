import React from 'react';

interface SamplerSettings {
  sampler: string;
  steps: number;
  cfg_scale: number;
  clip_skip: number;
}

interface Preset {
  id: string;
  label: string;
  description: string;
  content_rating: 'sfw' | 'mature';
  requires_mature_mode: boolean;
  recommended_models: string[];
  sampler_settings: SamplerSettings;
  available?: boolean;
}

interface PresetCardProps {
  preset: Preset;
  selected?: boolean;
  onSelect: (preset: Preset) => void;
  matureEnabled: boolean;
}

/**
 * Preset Card
 *
 * Displays a generation preset with its settings.
 * Shows availability based on mature mode status.
 */
export const PresetCard: React.FC<PresetCardProps> = ({
  preset,
  selected = false,
  onSelect,
  matureEnabled,
}) => {
  const isAvailable = !preset.requires_mature_mode || matureEnabled;

  const getIcon = () => {
    if (preset.id.includes('fan_service')) return '\uD83C\uDFA8'; // Art palette
    if (preset.id.includes('romantic')) return '\uD83D\uDC95'; // Heart
    if (preset.id.includes('sfw')) return '\u2728'; // Sparkles
    return '\uD83D\uDDBC\uFE0F'; // Frame
  };

  return (
    <div
      className={`preset-card ${selected ? 'selected' : ''} ${!isAvailable ? 'locked' : ''}`}
      onClick={() => isAvailable && onSelect(preset)}
    >
      <div className="preset-header">
        <span className="preset-icon">{getIcon()}</span>
        <h3 className="preset-label">{preset.label}</h3>
      </div>

      <p className="preset-description">{preset.description}</p>

      <div className="preset-badge-row">
        {preset.requires_mature_mode ? (
          <span className="badge badge-mature">
            &#128286; Mature
          </span>
        ) : (
          <span className="badge badge-sfw">
            &#10003; SFW
          </span>
        )}

        {!isAvailable && (
          <span className="badge badge-locked">
            &#128274; Enable Mature Mode
          </span>
        )}
      </div>

      <div className="preset-settings">
        <div className="setting">
          <span className="setting-label">Sampler</span>
          <span className="setting-value">{preset.sampler_settings.sampler}</span>
        </div>
        <div className="setting">
          <span className="setting-label">Steps</span>
          <span className="setting-value">{preset.sampler_settings.steps}</span>
        </div>
        <div className="setting">
          <span className="setting-label">CFG</span>
          <span className="setting-value">{preset.sampler_settings.cfg_scale}</span>
        </div>
        <div className="setting">
          <span className="setting-label">Clip Skip</span>
          <span className="setting-value">{preset.sampler_settings.clip_skip}</span>
        </div>
      </div>

      <button
        className="apply-button"
        disabled={!isAvailable}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(preset);
        }}
      >
        {isAvailable ? 'Apply Preset' : 'Locked'}
      </button>

      <style>{`
        .preset-card {
          background: var(--color-surface);
          border: 2px solid var(--color-border);
          border-radius: 12px;
          padding: 16px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .preset-card:hover:not(.locked) {
          border-color: var(--color-primary);
          box-shadow: var(--shadow-md);
        }

        .preset-card.selected {
          border-color: var(--color-primary);
          background: var(--color-primary-light);
        }

        .preset-card.locked {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .preset-header {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-bottom: 8px;
        }

        .preset-icon {
          font-size: 24px;
        }

        .preset-label {
          margin: 0;
          font-size: 16px;
          font-weight: 600;
          color: var(--color-text);
        }

        .preset-description {
          margin: 0 0 12px;
          font-size: 13px;
          color: var(--color-text-muted);
          line-height: 1.4;
        }

        .preset-badge-row {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-bottom: 12px;
        }

        .badge {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 4px 10px;
          border-radius: 6px;
          font-size: 12px;
          font-weight: 500;
        }

        .badge-mature {
          background: linear-gradient(135deg, #8B5CF6, #F59E0B);
          color: white;
        }

        .badge-sfw {
          background: #D1FAE5;
          color: #065F46;
        }

        .badge-locked {
          background: #FEE2E2;
          color: #991B1B;
        }

        .preset-settings {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 8px;
          margin-bottom: 16px;
          padding: 12px;
          background: var(--color-background);
          border-radius: 8px;
        }

        .setting {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .setting-label {
          font-size: 11px;
          color: var(--color-text-muted);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }

        .setting-value {
          font-size: 13px;
          font-weight: 500;
          color: var(--color-text);
        }

        .apply-button {
          width: 100%;
          padding: 10px 16px;
          border: none;
          border-radius: 8px;
          background: var(--color-primary);
          color: white;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s;
        }

        .apply-button:hover:not(:disabled) {
          background: var(--color-primary-hover);
        }

        .apply-button:disabled {
          background: var(--color-border);
          color: var(--color-text-muted);
          cursor: not-allowed;
        }
      `}</style>
    </div>
  );
};

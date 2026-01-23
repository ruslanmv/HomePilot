import React, { useState, useEffect } from "react";
import { useStudioStore } from "../stores/studioStore";
import { useModels } from "../hooks";

interface NSFWInfo {
  nsfw_enabled: boolean;
  env_var: string;
  current_value: string;
  when_enabled: Record<string, string>;
  always_blocked: Record<string, string>;
  recommended_models: string[];
  how_to_enable: string;
}

/**
 * Settings Page
 *
 * Studio configuration and preferences.
 */
export const SettingsPage: React.FC = () => {
  const {
    contentRating,
    setContentRating,
    matureEnabled,
    matureVerified,
    setMatureVerified,
    currentSettings,
    setCurrentSettings,
    selectedModelId,
    setSelectedModelId,
    reset,
  } = useStudioStore();

  const { models, animeModels, nsfwModels } = useModels(contentRating);
  const [nsfwInfo, setNsfwInfo] = useState<NSFWInfo | null>(null);
  const [showResetConfirm, setShowResetConfirm] = useState(false);

  // Fetch NSFW info
  useEffect(() => {
    const fetchInfo = async () => {
      try {
        const res = await fetch("/studio/image/nsfw-info");
        if (res.ok) {
          setNsfwInfo(await res.json());
        }
      } catch (e) {
        console.error("Failed to fetch NSFW info:", e);
      }
    };
    fetchInfo();
  }, []);

  const handleRatingChange = (rating: "sfw" | "mature") => {
    if (rating === "mature" && !matureVerified) {
      // Would show verification modal
      setMatureVerified(true);
    }
    setContentRating(rating);
  };

  return (
    <div className="settings-page">
      <h2>Studio Settings</h2>

      {/* Content Policy Section */}
      <section className="settings-section">
        <h3>Content Policy</h3>

        <div className="setting-row">
          <div className="setting-info">
            <label>Content Rating</label>
            <p>Controls what type of content can be generated</p>
          </div>
          <div className="setting-control">
            <div className="radio-group">
              <label className="radio-option">
                <input
                  type="radio"
                  name="contentRating"
                  checked={contentRating === "sfw"}
                  onChange={() => handleRatingChange("sfw")}
                />
                <span className="radio-label">
                  <span className="radio-title">SFW (Safe for Work)</span>
                  <span className="radio-desc">
                    General audience content only
                  </span>
                </span>
              </label>
              <label className="radio-option">
                <input
                  type="radio"
                  name="contentRating"
                  checked={contentRating === "mature"}
                  onChange={() => handleRatingChange("mature")}
                  disabled={!matureEnabled}
                />
                <span className="radio-label">
                  <span className="radio-title">
                    Mature (Adult Content)
                    {!matureEnabled && " - Disabled"}
                  </span>
                  <span className="radio-desc">
                    Enables NSFW/explicit image generation
                  </span>
                </span>
              </label>
            </div>
          </div>
        </div>

        {/* NSFW Status Box */}
        <div
          className={`status-box ${nsfwInfo?.nsfw_enabled ? "enabled" : "disabled"}`}
        >
          <div className="status-header">
            <span className="status-icon">
              {nsfwInfo?.nsfw_enabled ? "\uD83D\uDD13" : "\uD83D\uDD12"}
            </span>
            <span className="status-title">
              NSFW Mode: {nsfwInfo?.nsfw_enabled ? "ENABLED" : "DISABLED"}
            </span>
          </div>

          {nsfwInfo?.nsfw_enabled ? (
            <div className="status-content">
              <p>Explicit content (porn, nudity) is <strong>ALLOWED</strong></p>
              <p>Only illegal content is blocked (CSAM, non-consent)</p>

              <div className="allowed-list">
                <h4>Allowed when NSFW enabled:</h4>
                <ul>
                  {nsfwInfo.when_enabled &&
                    Object.entries(nsfwInfo.when_enabled).map(([key, value]) => (
                      <li key={key}>
                        <span className="check">\u2713</span> {key}: {value}
                      </li>
                    ))}
                </ul>
              </div>

              <div className="blocked-list">
                <h4>Always blocked:</h4>
                <ul>
                  {nsfwInfo.always_blocked &&
                    Object.entries(nsfwInfo.always_blocked).map(
                      ([key, value]) => (
                        <li key={key}>
                          <span className="block">\u2717</span> {value}
                        </li>
                      )
                    )}
                </ul>
              </div>
            </div>
          ) : (
            <div className="status-content">
              <p>NSFW content generation is currently disabled.</p>
              <p className="enable-hint">
                To enable, set environment variable:{" "}
                <code>{nsfwInfo?.how_to_enable}</code>
              </p>
            </div>
          )}
        </div>
      </section>

      {/* Default Generation Settings */}
      <section className="settings-section">
        <h3>Default Generation Settings</h3>

        <div className="setting-row">
          <div className="setting-info">
            <label>Default Model</label>
            <p>Model used for new generations</p>
          </div>
          <div className="setting-control">
            <select
              value={selectedModelId}
              onChange={(e) => setSelectedModelId(e.target.value)}
            >
              {models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.label}{" "}
                  {model.nsfw ? "\uD83D\uDD1E" : ""}
                  {model.anime ? " \uD83C\uDF38" : ""}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="setting-row">
          <div className="setting-info">
            <label>Default Steps</label>
            <p>Number of diffusion steps</p>
          </div>
          <div className="setting-control">
            <input
              type="number"
              min={10}
              max={50}
              value={currentSettings.steps}
              onChange={(e) =>
                setCurrentSettings({ steps: parseInt(e.target.value) })
              }
            />
          </div>
        </div>

        <div className="setting-row">
          <div className="setting-info">
            <label>Default CFG Scale</label>
            <p>How closely to follow the prompt</p>
          </div>
          <div className="setting-control">
            <input
              type="number"
              min={1}
              max={20}
              step={0.5}
              value={currentSettings.cfg}
              onChange={(e) =>
                setCurrentSettings({ cfg: parseFloat(e.target.value) })
              }
            />
          </div>
        </div>

        <div className="setting-row">
          <div className="setting-info">
            <label>Default Sampler</label>
            <p>Sampling algorithm</p>
          </div>
          <div className="setting-control">
            <select
              value={currentSettings.sampler}
              onChange={(e) => setCurrentSettings({ sampler: e.target.value })}
            >
              <option value="dpm++_2m_karras">DPM++ 2M Karras</option>
              <option value="euler_a">Euler A</option>
              <option value="euler">Euler</option>
              <option value="dpm++_sde_karras">DPM++ SDE Karras</option>
              <option value="ddim">DDIM</option>
            </select>
          </div>
        </div>

        <div className="setting-row">
          <div className="setting-info">
            <label>Default Size</label>
            <p>Output image dimensions</p>
          </div>
          <div className="setting-control">
            <select
              value={`${currentSettings.width}x${currentSettings.height}`}
              onChange={(e) => {
                const [w, h] = e.target.value.split("x").map(Number);
                setCurrentSettings({ width: w, height: h });
              }}
            >
              <option value="512x512">512 x 512 (Square)</option>
              <option value="512x768">512 x 768 (Portrait)</option>
              <option value="768x512">768 x 512 (Landscape)</option>
              <option value="768x1024">768 x 1024 (Tall)</option>
              <option value="1024x768">1024 x 768 (Wide)</option>
              <option value="1024x1024">1024 x 1024 (SDXL Square)</option>
            </select>
          </div>
        </div>
      </section>

      {/* Recommended Models */}
      {nsfwInfo?.nsfw_enabled && nsfwInfo.recommended_models && (
        <section className="settings-section">
          <h3>Recommended NSFW Models</h3>
          <p className="section-desc">
            These models are optimized for mature content generation
          </p>

          <div className="model-chips">
            {nsfwInfo.recommended_models.map((modelId) => {
              const model = models.find((m) => m.id === modelId);
              return (
                <button
                  key={modelId}
                  className={`model-chip ${selectedModelId === modelId ? "selected" : ""}`}
                  onClick={() => setSelectedModelId(modelId)}
                >
                  {model?.label || modelId}
                  {selectedModelId === modelId && " \u2713"}
                </button>
              );
            })}
          </div>
        </section>
      )}

      {/* Reset Section */}
      <section className="settings-section danger-section">
        <h3>Reset</h3>

        <div className="setting-row">
          <div className="setting-info">
            <label>Reset All Settings</label>
            <p>Clear all preferences and gallery</p>
          </div>
          <div className="setting-control">
            <button
              className="danger-btn"
              onClick={() => setShowResetConfirm(true)}
            >
              Reset Everything
            </button>
          </div>
        </div>
      </section>

      {/* Reset Confirmation Modal */}
      {showResetConfirm && (
        <div className="modal-overlay" onClick={() => setShowResetConfirm(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>Reset All Settings?</h3>
            <p>
              This will clear all your preferences, generated images, and return
              to default settings. This action cannot be undone.
            </p>
            <div className="modal-actions">
              <button onClick={() => setShowResetConfirm(false)}>Cancel</button>
              <button
                className="danger-btn"
                onClick={() => {
                  reset();
                  setShowResetConfirm(false);
                }}
              >
                Reset Everything
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        .settings-page {
          padding: 24px;
          max-width: 800px;
          margin: 0 auto;
        }

        .settings-page h2 {
          margin: 0 0 24px;
          font-size: 24px;
          color: var(--color-text);
        }

        .settings-section {
          background: var(--color-surface);
          border: 1px solid var(--color-border);
          border-radius: 12px;
          padding: 20px;
          margin-bottom: 20px;
        }

        .settings-section h3 {
          margin: 0 0 16px;
          font-size: 16px;
          color: var(--color-text);
        }

        .section-desc {
          color: var(--color-text-muted);
          font-size: 14px;
          margin: -8px 0 16px;
        }

        .setting-row {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          padding: 16px 0;
          border-bottom: 1px solid var(--color-border);
        }

        .setting-row:last-child {
          border-bottom: none;
          padding-bottom: 0;
        }

        .setting-info {
          flex: 1;
        }

        .setting-info label {
          display: block;
          font-weight: 500;
          color: var(--color-text);
          margin-bottom: 4px;
        }

        .setting-info p {
          margin: 0;
          font-size: 13px;
          color: var(--color-text-muted);
        }

        .setting-control {
          flex-shrink: 0;
          margin-left: 20px;
        }

        .setting-control select,
        .setting-control input[type="number"] {
          padding: 8px 12px;
          border: 1px solid var(--color-border);
          border-radius: 6px;
          background: var(--color-background);
          color: var(--color-text);
          font-size: 14px;
          min-width: 200px;
        }

        .radio-group {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .radio-option {
          display: flex;
          align-items: flex-start;
          gap: 12px;
          cursor: pointer;
        }

        .radio-option input {
          margin-top: 4px;
        }

        .radio-option input:disabled {
          cursor: not-allowed;
        }

        .radio-label {
          display: flex;
          flex-direction: column;
        }

        .radio-title {
          font-weight: 500;
          color: var(--color-text);
        }

        .radio-desc {
          font-size: 12px;
          color: var(--color-text-muted);
        }

        .status-box {
          border-radius: 8px;
          padding: 16px;
          margin-top: 16px;
        }

        .status-box.enabled {
          background: rgba(139, 92, 246, 0.1);
          border: 1px solid rgba(139, 92, 246, 0.3);
        }

        .status-box.disabled {
          background: var(--color-background);
          border: 1px solid var(--color-border);
        }

        .status-header {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-bottom: 12px;
        }

        .status-icon {
          font-size: 20px;
        }

        .status-title {
          font-weight: 600;
          font-size: 15px;
          color: var(--color-text);
        }

        .status-content p {
          margin: 0 0 8px;
          font-size: 14px;
          color: var(--color-text-muted);
        }

        .status-content strong {
          color: #10B981;
        }

        .allowed-list, .blocked-list {
          margin-top: 16px;
        }

        .allowed-list h4, .blocked-list h4 {
          margin: 0 0 8px;
          font-size: 13px;
          font-weight: 500;
          color: var(--color-text);
        }

        .allowed-list ul, .blocked-list ul {
          margin: 0;
          padding: 0;
          list-style: none;
        }

        .allowed-list li, .blocked-list li {
          font-size: 13px;
          color: var(--color-text-muted);
          padding: 4px 0;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .check {
          color: #10B981;
          font-weight: bold;
        }

        .block {
          color: #EF4444;
          font-weight: bold;
        }

        .enable-hint {
          margin-top: 12px;
        }

        .enable-hint code {
          background: var(--color-background);
          padding: 2px 6px;
          border-radius: 4px;
          font-size: 13px;
        }

        .model-chips {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .model-chip {
          padding: 8px 16px;
          border: 1px solid var(--color-border);
          border-radius: 20px;
          background: var(--color-surface);
          color: var(--color-text);
          font-size: 13px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .model-chip:hover {
          border-color: var(--color-primary);
        }

        .model-chip.selected {
          background: var(--color-primary);
          border-color: var(--color-primary);
          color: white;
        }

        .danger-section {
          border-color: rgba(239, 68, 68, 0.3);
        }

        .danger-btn {
          padding: 10px 20px;
          background: transparent;
          border: 1px solid #EF4444;
          border-radius: 8px;
          color: #EF4444;
          font-size: 14px;
          cursor: pointer;
        }

        .danger-btn:hover {
          background: #EF4444;
          color: white;
        }

        .modal-overlay {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.6);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
        }

        .modal-content {
          background: var(--color-surface);
          border-radius: 12px;
          padding: 24px;
          max-width: 400px;
          margin: 16px;
        }

        .modal-content h3 {
          margin: 0 0 12px;
        }

        .modal-content p {
          margin: 0 0 20px;
          color: var(--color-text-muted);
          font-size: 14px;
        }

        .modal-actions {
          display: flex;
          gap: 12px;
          justify-content: flex-end;
        }

        .modal-actions button {
          padding: 10px 20px;
          border-radius: 8px;
          font-size: 14px;
          cursor: pointer;
        }

        .modal-actions button:first-child {
          background: transparent;
          border: 1px solid var(--color-border);
          color: var(--color-text);
        }
      `}</style>
    </div>
  );
};

export default SettingsPage;

import React from "react";
import { useTVModeStore } from "../../stores/tvModeStore";

interface TVModeSettingsProps {
  onClose: () => void;
}

export const TVModeSettings: React.FC<TVModeSettingsProps> = ({ onClose }) => {
  const { settings, updateSettings, resetSettings } = useTVModeStore();

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  return (
    <div className="settings-overlay" onClick={handleBackdropClick}>
      <div className="settings-panel">
        <div className="settings-header">
          <h3>TV Mode Settings</h3>
          <button className="close-btn" onClick={onClose} aria-label="Close settings">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="settings-content">
          {/* Scene Duration */}
          <div className="setting-group">
            <label className="setting-label">Scene Duration</label>
            <div className="setting-description">How long each scene displays</div>
            <div className="button-group">
              <button
                className={settings.sceneDuration === 0 ? "active" : ""}
                onClick={() => updateSettings({ sceneDuration: 0 })}
              >
                Auto
              </button>
              <button
                className={settings.sceneDuration === 5 ? "active" : ""}
                onClick={() => updateSettings({ sceneDuration: 5 })}
              >
                5s
              </button>
              <button
                className={settings.sceneDuration === 10 ? "active" : ""}
                onClick={() => updateSettings({ sceneDuration: 10 })}
              >
                10s
              </button>
              <button
                className={settings.sceneDuration === 15 ? "active" : ""}
                onClick={() => updateSettings({ sceneDuration: 15 })}
              >
                15s
              </button>
              <button
                className={settings.sceneDuration === 20 ? "active" : ""}
                onClick={() => updateSettings({ sceneDuration: 20 })}
              >
                20s
              </button>
            </div>
          </div>

          {/* Transition Speed */}
          <div className="setting-group">
            <label className="setting-label">Transition Speed</label>
            <div className="setting-description">Speed of scene transitions</div>
            <div className="button-group">
              <button
                className={settings.transitionDuration === 1200 ? "active" : ""}
                onClick={() => updateSettings({ transitionDuration: 1200 })}
              >
                Slow
              </button>
              <button
                className={settings.transitionDuration === 800 ? "active" : ""}
                onClick={() => updateSettings({ transitionDuration: 800 })}
              >
                Normal
              </button>
              <button
                className={settings.transitionDuration === 400 ? "active" : ""}
                onClick={() => updateSettings({ transitionDuration: 400 })}
              >
                Fast
              </button>
            </div>
          </div>

          {/* Narration Position */}
          <div className="setting-group">
            <label className="setting-label">Narration Position</label>
            <div className="setting-description">Where text appears on screen</div>
            <div className="button-group">
              <button
                className={settings.narrationPosition === "bottom" ? "active" : ""}
                onClick={() => updateSettings({ narrationPosition: "bottom" })}
              >
                Bottom
              </button>
              <button
                className={settings.narrationPosition === "top" ? "active" : ""}
                onClick={() => updateSettings({ narrationPosition: "top" })}
              >
                Top
              </button>
            </div>
          </div>

          {/* Text Size */}
          <div className="setting-group">
            <label className="setting-label">Text Size</label>
            <div className="setting-description">Size of narration text</div>
            <div className="button-group">
              <button
                className={settings.narrationSize === "small" ? "active" : ""}
                onClick={() => updateSettings({ narrationSize: "small" })}
              >
                S
              </button>
              <button
                className={settings.narrationSize === "medium" ? "active" : ""}
                onClick={() => updateSettings({ narrationSize: "medium" })}
              >
                M
              </button>
              <button
                className={settings.narrationSize === "large" ? "active" : ""}
                onClick={() => updateSettings({ narrationSize: "large" })}
              >
                L
              </button>
            </div>
          </div>

          {/* Toggle Options */}
          <div className="setting-group">
            <label className="toggle-option">
              <input
                type="checkbox"
                checked={settings.showSceneNumber}
                onChange={(e) => updateSettings({ showSceneNumber: e.target.checked })}
              />
              <span className="toggle-text">Show scene numbers</span>
            </label>
          </div>

          <div className="setting-group">
            <label className="toggle-option">
              <input
                type="checkbox"
                checked={settings.pauseOnEnd}
                onChange={(e) => updateSettings({ pauseOnEnd: e.target.checked })}
              />
              <span className="toggle-text">Pause at end of story</span>
            </label>
          </div>

          {/* Auto-hide Delay */}
          <div className="setting-group">
            <label className="setting-label">Auto-hide Controls</label>
            <div className="setting-description">Hide controls after inactivity</div>
            <div className="button-group">
              <button
                className={settings.autoHideDelay === 2000 ? "active" : ""}
                onClick={() => updateSettings({ autoHideDelay: 2000 })}
              >
                2s
              </button>
              <button
                className={settings.autoHideDelay === 3000 ? "active" : ""}
                onClick={() => updateSettings({ autoHideDelay: 3000 })}
              >
                3s
              </button>
              <button
                className={settings.autoHideDelay === 5000 ? "active" : ""}
                onClick={() => updateSettings({ autoHideDelay: 5000 })}
              >
                5s
              </button>
            </div>
          </div>
        </div>

        <div className="settings-footer">
          <button className="reset-btn" onClick={resetSettings}>
            Reset to Defaults
          </button>
        </div>
      </div>

      <style>{`
        .settings-overlay {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.6);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 10000;
          animation: fadeIn 200ms ease;
        }

        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        .settings-panel {
          background: #1a1a2e;
          border-radius: 16px;
          width: 90%;
          max-width: 400px;
          max-height: 80vh;
          overflow: hidden;
          display: flex;
          flex-direction: column;
          box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
          animation: slideUp 300ms ease;
        }

        @keyframes slideUp {
          from { transform: translateY(20px); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }

        .settings-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 20px 24px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }

        .settings-header h3 {
          margin: 0;
          font-size: 18px;
          font-weight: 600;
          color: #fff;
        }

        .close-btn {
          background: transparent;
          border: none;
          color: rgba(255, 255, 255, 0.6);
          cursor: pointer;
          padding: 4px;
          border-radius: 6px;
          transition: all 0.2s;
        }

        .close-btn:hover {
          color: #fff;
          background: rgba(255, 255, 255, 0.1);
        }

        .settings-content {
          padding: 24px;
          overflow-y: auto;
        }

        .setting-group {
          margin-bottom: 24px;
        }

        .setting-group:last-child {
          margin-bottom: 0;
        }

        .setting-label {
          display: block;
          font-size: 14px;
          font-weight: 500;
          color: #fff;
          margin-bottom: 4px;
        }

        .setting-description {
          font-size: 12px;
          color: rgba(255, 255, 255, 0.5);
          margin-bottom: 12px;
        }

        .button-group {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
        }

        .button-group button {
          padding: 8px 16px;
          border: 1px solid rgba(255, 255, 255, 0.2);
          border-radius: 8px;
          background: transparent;
          color: rgba(255, 255, 255, 0.7);
          font-size: 13px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .button-group button:hover {
          border-color: rgba(139, 92, 246, 0.5);
          color: #fff;
        }

        .button-group button.active {
          background: linear-gradient(135deg, #8B5CF6, #6366F1);
          border-color: transparent;
          color: #fff;
        }

        .toggle-option {
          display: flex;
          align-items: center;
          gap: 12px;
          cursor: pointer;
        }

        .toggle-option input[type="checkbox"] {
          width: 18px;
          height: 18px;
          accent-color: #8B5CF6;
          cursor: pointer;
        }

        .toggle-text {
          font-size: 14px;
          color: rgba(255, 255, 255, 0.8);
        }

        .settings-footer {
          padding: 16px 24px;
          border-top: 1px solid rgba(255, 255, 255, 0.1);
        }

        .reset-btn {
          width: 100%;
          padding: 12px;
          border: 1px solid rgba(255, 255, 255, 0.2);
          border-radius: 8px;
          background: transparent;
          color: rgba(255, 255, 255, 0.6);
          font-size: 14px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .reset-btn:hover {
          border-color: rgba(255, 255, 255, 0.4);
          color: #fff;
        }

        @media (max-width: 768px) {
          .settings-panel {
            width: 95%;
            max-height: 90vh;
          }

          .settings-content {
            padding: 16px;
          }

          .button-group button {
            padding: 6px 12px;
            font-size: 12px;
          }
        }
      `}</style>
    </div>
  );
};

export default TVModeSettings;

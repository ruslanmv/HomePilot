import React from "react";
import { useTVModeStore } from "../../stores/tvModeStore";

interface TVModeEndScreenProps {
  onRestart: () => void;
  onExit: () => void;
  onContinue?: () => void;
}

export const TVModeEndScreen: React.FC<TVModeEndScreenProps> = ({
  onRestart,
  onExit,
  onContinue,
}) => {
  const { storyTitle, scenes, isPrefetching } = useTVModeStore();

  return (
    <div className="end-screen-overlay">
      <div className="end-screen-content">
        <div className="end-icon">
          <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" fill="rgba(139, 92, 246, 0.3)" />
          </svg>
        </div>

        <h2 className="end-title">The End</h2>
        <p className="story-name">{storyTitle}</p>
        <p className="scene-count">{scenes.length} scenes</p>

        <div className="end-actions">
          <button className="action-btn primary" onClick={onRestart}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M1 4v6h6" />
              <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
            </svg>
            Watch Again
          </button>

          {onContinue && (
            <button
              className="action-btn secondary"
              onClick={onContinue}
              disabled={isPrefetching}
            >
              {isPrefetching ? (
                <>
                  <div className="loading-spinner-small" />
                  Generating...
                </>
              ) : (
                <>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="12" y1="5" x2="12" y2="19" />
                    <line x1="5" y1="12" x2="19" y2="12" />
                  </svg>
                  Generate More
                </>
              )}
            </button>
          )}

          <button className="action-btn outline" onClick={onExit}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
            Exit
          </button>
        </div>
      </div>

      <style>{`
        .end-screen-overlay {
          position: absolute;
          inset: 0;
          background: rgba(0, 0, 0, 0.85);
          display: flex;
          align-items: center;
          justify-content: center;
          animation: fadeIn 500ms ease;
          z-index: 100;
        }

        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        .end-screen-content {
          text-align: center;
          padding: 40px;
          animation: scaleIn 500ms ease;
        }

        @keyframes scaleIn {
          from {
            opacity: 0;
            transform: scale(0.9);
          }
          to {
            opacity: 1;
            transform: scale(1);
          }
        }

        .end-icon {
          margin-bottom: 24px;
          color: #8B5CF6;
          animation: starGlow 2s ease-in-out infinite;
        }

        @keyframes starGlow {
          0%, 100% {
            filter: drop-shadow(0 0 8px rgba(139, 92, 246, 0.5));
          }
          50% {
            filter: drop-shadow(0 0 20px rgba(139, 92, 246, 0.8));
          }
        }

        .end-title {
          font-size: 48px;
          font-weight: 300;
          color: #fff;
          margin: 0 0 12px;
          letter-spacing: 4px;
          text-transform: uppercase;
        }

        .story-name {
          font-size: 20px;
          color: rgba(255, 255, 255, 0.9);
          margin: 0 0 8px;
          font-weight: 500;
        }

        .scene-count {
          font-size: 14px;
          color: rgba(255, 255, 255, 0.5);
          margin: 0 0 32px;
        }

        .end-actions {
          display: flex;
          flex-direction: column;
          gap: 12px;
          max-width: 280px;
          margin: 0 auto;
        }

        .action-btn {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          padding: 14px 24px;
          border-radius: 12px;
          font-size: 15px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .action-btn.primary {
          background: linear-gradient(135deg, #8B5CF6, #6366F1);
          border: none;
          color: #fff;
        }

        .action-btn.primary:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 24px rgba(139, 92, 246, 0.4);
        }

        .action-btn.secondary {
          background: rgba(255, 255, 255, 0.1);
          border: 1px solid rgba(255, 255, 255, 0.2);
          color: #fff;
        }

        .action-btn.secondary:hover:not(:disabled) {
          background: rgba(255, 255, 255, 0.15);
          border-color: rgba(255, 255, 255, 0.3);
        }

        .action-btn.secondary:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .action-btn.outline {
          background: transparent;
          border: 1px solid rgba(255, 255, 255, 0.3);
          color: rgba(255, 255, 255, 0.8);
        }

        .action-btn.outline:hover {
          border-color: rgba(255, 255, 255, 0.5);
          color: #fff;
        }

        .loading-spinner-small {
          width: 18px;
          height: 18px;
          border: 2px solid rgba(255, 255, 255, 0.2);
          border-top-color: #fff;
          border-radius: 50%;
          animation: spin 1s linear infinite;
        }

        @keyframes spin {
          to { transform: rotate(360deg); }
        }

        @media (max-width: 768px) {
          .end-screen-content {
            padding: 24px;
          }

          .end-title {
            font-size: 36px;
          }

          .story-name {
            font-size: 16px;
          }

          .end-actions {
            max-width: 100%;
          }
        }
      `}</style>
    </div>
  );
};

export default TVModeEndScreen;

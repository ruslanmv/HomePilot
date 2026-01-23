import React from "react";
import { useTVModeStore } from "../../stores/tvModeStore";

interface TVModeControlsProps {
  visible: boolean;
  isPlaying: boolean;
  currentIndex: number;
  totalScenes: number;
  isPrefetching: boolean;
  onTogglePlay: () => void;
  onPrev: () => void;
  onNext: () => void;
  onExit: () => void;
  onGoToScene: (index: number) => void;
  onShowSettings: () => void;
}

export const TVModeControls: React.FC<TVModeControlsProps> = ({
  visible,
  isPlaying,
  currentIndex,
  totalScenes,
  isPrefetching,
  onTogglePlay,
  onPrev,
  onNext,
  onExit,
  onGoToScene,
  onShowSettings,
}) => {
  const { storyTitle } = useTVModeStore();
  const progress = totalScenes > 0 ? ((currentIndex + 1) / totalScenes) * 100 : 0;

  const handleProgressClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const percentage = clickX / rect.width;
    const sceneIndex = Math.floor(percentage * totalScenes);
    onGoToScene(Math.min(Math.max(sceneIndex, 0), totalScenes - 1));
  };

  return (
    <div className={`tv-controls ${visible ? "visible" : "hidden"}`}>
      {/* Top Bar */}
      <div className="controls-top">
        <button
          className="control-btn exit-btn"
          onClick={onExit}
          aria-label="Exit TV Mode"
        >
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
          <span>Exit</span>
        </button>

        <div className="title-container">
          <h2 className="story-title">{storyTitle}</h2>
        </div>

        <div className="top-right">
          <span className="scene-counter">
            {currentIndex + 1} / {totalScenes}
          </span>
          <button
            className="control-btn settings-btn"
            onClick={onShowSettings}
            aria-label="Settings"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
        </div>
      </div>

      {/* Bottom Bar */}
      <div className="controls-bottom">
        {/* Playback Controls */}
        <div className="playback-controls">
          <button
            className="control-btn nav-btn"
            onClick={onPrev}
            disabled={currentIndex === 0}
            aria-label="Previous scene"
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polygon points="19 20 9 12 19 4 19 20" fill="currentColor" />
              <line x1="5" y1="19" x2="5" y2="5" />
            </svg>
          </button>

          <button
            className="control-btn play-btn"
            onClick={onTogglePlay}
            aria-label={isPlaying ? "Pause" : "Play"}
          >
            {isPlaying ? (
              <svg width="32" height="32" viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="4" width="4" height="16" rx="1" />
                <rect x="14" y="4" width="4" height="16" rx="1" />
              </svg>
            ) : (
              <svg width="32" height="32" viewBox="0 0 24 24" fill="currentColor">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
            )}
          </button>

          <button
            className="control-btn nav-btn"
            onClick={onNext}
            disabled={currentIndex >= totalScenes - 1 && !isPrefetching}
            aria-label="Next scene"
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polygon points="5 4 15 12 5 20 5 4" fill="currentColor" />
              <line x1="19" y1="5" x2="19" y2="19" />
            </svg>
          </button>
        </div>

        {/* Progress Bar */}
        <div className="progress-container" onClick={handleProgressClick}>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${progress}%` }}
            />
            <div
              className="progress-thumb"
              style={{ left: `${progress}%` }}
            />
          </div>

          {/* Scene markers */}
          <div className="scene-markers">
            {Array.from({ length: totalScenes }).map((_, i) => (
              <div
                key={i}
                className={`scene-marker ${i === currentIndex ? "active" : ""} ${i < currentIndex ? "passed" : ""}`}
                style={{ left: `${((i + 0.5) / totalScenes) * 100}%` }}
                onClick={(e) => {
                  e.stopPropagation();
                  onGoToScene(i);
                }}
              />
            ))}
          </div>
        </div>

        {/* Generating indicator */}
        {isPrefetching && (
          <div className="generating-indicator">
            <div className="generating-dot" />
            <span>Generating next...</span>
          </div>
        )}
      </div>

      <style>{`
        .tv-controls {
          position: absolute;
          inset: 0;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          pointer-events: none;
          transition: opacity 300ms ease-in-out;
        }

        .tv-controls.hidden {
          opacity: 0;
        }

        .tv-controls.visible {
          opacity: 1;
        }

        .tv-controls > * {
          pointer-events: auto;
        }

        /* Top Bar */
        .controls-top {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 20px 24px;
          background: linear-gradient(to bottom, rgba(0, 0, 0, 0.7), transparent);
        }

        .title-container {
          flex: 1;
          text-align: center;
        }

        .story-title {
          margin: 0;
          font-size: 18px;
          font-weight: 500;
          color: #fff;
          text-shadow: 0 2px 4px rgba(0, 0, 0, 0.5);
        }

        .top-right {
          display: flex;
          align-items: center;
          gap: 16px;
        }

        .scene-counter {
          font-size: 14px;
          color: rgba(255, 255, 255, 0.8);
          font-variant-numeric: tabular-nums;
        }

        /* Bottom Bar */
        .controls-bottom {
          display: flex;
          flex-direction: column;
          gap: 16px;
          padding: 20px 24px;
          background: linear-gradient(to top, rgba(0, 0, 0, 0.8), transparent);
        }

        /* Playback Controls */
        .playback-controls {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 24px;
        }

        /* Control Buttons */
        .control-btn {
          display: flex;
          align-items: center;
          gap: 8px;
          background: transparent;
          border: none;
          color: #fff;
          cursor: pointer;
          padding: 8px;
          border-radius: 8px;
          transition: all 0.2s ease;
        }

        .control-btn:hover:not(:disabled) {
          background: rgba(255, 255, 255, 0.1);
        }

        .control-btn:disabled {
          opacity: 0.3;
          cursor: not-allowed;
        }

        .exit-btn {
          padding: 8px 16px;
        }

        .exit-btn span {
          font-size: 14px;
        }

        .play-btn {
          width: 64px;
          height: 64px;
          border-radius: 50%;
          background: rgba(255, 255, 255, 0.1);
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .play-btn:hover {
          background: rgba(255, 255, 255, 0.2) !important;
          transform: scale(1.05);
        }

        .nav-btn {
          width: 48px;
          height: 48px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        /* Progress Bar */
        .progress-container {
          position: relative;
          height: 24px;
          cursor: pointer;
          display: flex;
          align-items: center;
        }

        .progress-bar {
          position: relative;
          width: 100%;
          height: 4px;
          background: rgba(255, 255, 255, 0.2);
          border-radius: 2px;
          overflow: visible;
        }

        .progress-fill {
          height: 100%;
          background: linear-gradient(90deg, #8B5CF6, #6366F1);
          border-radius: 2px;
          transition: width 300ms ease;
        }

        .progress-thumb {
          position: absolute;
          top: 50%;
          width: 14px;
          height: 14px;
          background: #fff;
          border-radius: 50%;
          transform: translate(-50%, -50%);
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
          transition: left 300ms ease;
        }

        .progress-container:hover .progress-thumb {
          transform: translate(-50%, -50%) scale(1.2);
        }

        /* Scene Markers */
        .scene-markers {
          position: absolute;
          inset: 0;
          pointer-events: none;
        }

        .scene-marker {
          position: absolute;
          top: 50%;
          width: 8px;
          height: 8px;
          background: rgba(255, 255, 255, 0.3);
          border-radius: 50%;
          transform: translate(-50%, -50%);
          pointer-events: auto;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .scene-marker:hover {
          background: rgba(255, 255, 255, 0.6);
          transform: translate(-50%, -50%) scale(1.3);
        }

        .scene-marker.active {
          background: #fff;
          box-shadow: 0 0 8px rgba(255, 255, 255, 0.5);
        }

        .scene-marker.passed {
          background: rgba(139, 92, 246, 0.8);
        }

        /* Generating Indicator */
        .generating-indicator {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          font-size: 13px;
          color: rgba(255, 255, 255, 0.7);
        }

        .generating-dot {
          width: 8px;
          height: 8px;
          background: #8B5CF6;
          border-radius: 50%;
          animation: pulse 1.5s ease-in-out infinite;
        }

        @keyframes pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(0.8); }
        }

        @media (max-width: 768px) {
          .controls-top {
            padding: 16px;
          }

          .controls-bottom {
            padding: 16px;
          }

          .story-title {
            font-size: 14px;
          }

          .exit-btn span {
            display: none;
          }

          .play-btn {
            width: 56px;
            height: 56px;
          }

          .nav-btn {
            width: 40px;
            height: 40px;
          }

          .playback-controls {
            gap: 16px;
          }
        }
      `}</style>
    </div>
  );
};

export default TVModeControls;

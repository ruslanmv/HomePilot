import React, { useState, useEffect, useCallback } from "react";
import { useTVModeStore } from "../../stores/tvModeStore";

interface TVModeChapterTransitionProps {
  onContinue: () => Promise<void>;
  onCancel: () => void;
  nextChapterTitle?: string;
  countdown?: number; // seconds
}

export const TVModeChapterTransition: React.FC<TVModeChapterTransitionProps> = ({
  onContinue,
  onCancel,
  nextChapterTitle,
  countdown: initialCountdown = 5,
}) => {
  const { storyTitle, chapterNumber, isLoadingNextChapter } = useTVModeStore();
  const [countdown, setCountdown] = useState(initialCountdown);
  const [isPaused, setIsPaused] = useState(false);
  const [isStarting, setIsStarting] = useState(false);

  const handleContinue = useCallback(async () => {
    if (isLoadingNextChapter || isStarting) return;
    setIsStarting(true);
    try {
      await onContinue();
    } catch (error) {
      setIsStarting(false);
    }
  }, [onContinue, isLoadingNextChapter, isStarting]);

  // Countdown timer
  useEffect(() => {
    if (isPaused || isLoadingNextChapter || isStarting) return;

    if (countdown <= 0) {
      handleContinue();
      return;
    }

    const timer = setTimeout(() => {
      setCountdown((prev) => prev - 1);
    }, 1000);

    return () => clearTimeout(timer);
  }, [countdown, isPaused, isLoadingNextChapter, isStarting, handleContinue]);

  const handlePauseToggle = () => {
    setIsPaused((prev) => !prev);
  };

  const handleSkip = () => {
    handleContinue();
  };

  return (
    <div className="chapter-transition-overlay">
      <div className="chapter-transition-content">
        {/* Chapter Complete Badge */}
        <div className="chapter-complete-badge">
          <div className="badge-icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
              <polyline points="22 4 12 14.01 9 11.01" />
            </svg>
          </div>
          <span>Chapter {chapterNumber} Complete</span>
        </div>

        {/* Story Title */}
        <h2 className="story-title">{storyTitle}</h2>

        {/* Divider with decoration */}
        <div className="divider">
          <span className="divider-line"></span>
          <span className="divider-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
            </svg>
          </span>
          <span className="divider-line"></span>
        </div>

        {/* Next Episode Announcement */}
        <div className="next-episode">
          <span className="next-label">Next Episode</span>
          <h3 className="next-title">
            {nextChapterTitle || `Chapter ${chapterNumber + 1}`}
          </h3>
        </div>

        {/* Loading or Countdown */}
        {isLoadingNextChapter || isStarting ? (
          <div className="loading-section">
            <div className="loading-spinner-large" />
            <p className="loading-text">Generating next chapter...</p>
          </div>
        ) : (
          <>
            {/* Countdown Ring */}
            <div className="countdown-container">
              <svg className="countdown-ring" viewBox="0 0 100 100">
                <circle
                  className="countdown-bg"
                  cx="50"
                  cy="50"
                  r="45"
                  fill="none"
                  stroke="rgba(255,255,255,0.1)"
                  strokeWidth="4"
                />
                <circle
                  className="countdown-progress"
                  cx="50"
                  cy="50"
                  r="45"
                  fill="none"
                  stroke="url(#gradient)"
                  strokeWidth="4"
                  strokeLinecap="round"
                  strokeDasharray={`${(countdown / initialCountdown) * 283} 283`}
                  transform="rotate(-90 50 50)"
                  style={{
                    transition: isPaused ? "none" : "stroke-dasharray 1s linear",
                  }}
                />
                <defs>
                  <linearGradient id="gradient" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="#8B5CF6" />
                    <stop offset="100%" stopColor="#6366F1" />
                  </linearGradient>
                </defs>
              </svg>
              <div className="countdown-text">
                <span className="countdown-number">{countdown}</span>
                <span className="countdown-label">
                  {isPaused ? "Paused" : "seconds"}
                </span>
              </div>
            </div>

            {/* Action Buttons */}
            <div className="transition-actions">
              <button
                className="action-btn skip"
                onClick={handleSkip}
                title="Start now"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polygon points="5 4 15 12 5 20 5 4" fill="currentColor" />
                  <line x1="19" y1="5" x2="19" y2="19" />
                </svg>
                Start Now
              </button>

              <button
                className="action-btn pause"
                onClick={handlePauseToggle}
                title={isPaused ? "Resume" : "Pause"}
              >
                {isPaused ? (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <polygon points="5 3 19 12 5 21 5 3" />
                  </svg>
                ) : (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <rect x="6" y="4" width="4" height="16" />
                    <rect x="14" y="4" width="4" height="16" />
                  </svg>
                )}
                {isPaused ? "Resume" : "Pause"}
              </button>

              <button
                className="action-btn cancel"
                onClick={onCancel}
                title="Stop and exit"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="3" width="18" height="18" rx="2" />
                </svg>
                Stop
              </button>
            </div>
          </>
        )}
      </div>

      <style>{`
        .chapter-transition-overlay {
          position: absolute;
          inset: 0;
          background: linear-gradient(135deg, rgba(0, 0, 0, 0.95), rgba(20, 10, 40, 0.95));
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 100;
          animation: fadeIn 500ms ease;
        }

        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        .chapter-transition-content {
          text-align: center;
          padding: 40px;
          max-width: 500px;
          animation: slideUp 600ms ease;
        }

        @keyframes slideUp {
          from {
            opacity: 0;
            transform: translateY(30px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .chapter-complete-badge {
          display: inline-flex;
          align-items: center;
          gap: 12px;
          background: linear-gradient(135deg, rgba(34, 197, 94, 0.2), rgba(34, 197, 94, 0.1));
          border: 1px solid rgba(34, 197, 94, 0.3);
          padding: 12px 24px;
          border-radius: 50px;
          margin-bottom: 24px;
          animation: badgePop 500ms ease 200ms both;
        }

        @keyframes badgePop {
          0% {
            opacity: 0;
            transform: scale(0.8);
          }
          50% {
            transform: scale(1.05);
          }
          100% {
            opacity: 1;
            transform: scale(1);
          }
        }

        .badge-icon {
          color: #22C55E;
          display: flex;
        }

        .chapter-complete-badge span {
          color: #22C55E;
          font-size: 16px;
          font-weight: 600;
          letter-spacing: 0.5px;
        }

        .story-title {
          font-size: 28px;
          font-weight: 300;
          color: rgba(255, 255, 255, 0.7);
          margin: 0 0 24px;
          letter-spacing: 1px;
        }

        .divider {
          display: flex;
          align-items: center;
          gap: 16px;
          margin-bottom: 24px;
        }

        .divider-line {
          flex: 1;
          height: 1px;
          background: linear-gradient(90deg, transparent, rgba(139, 92, 246, 0.5), transparent);
        }

        .divider-icon {
          color: #8B5CF6;
          animation: starPulse 2s ease-in-out infinite;
        }

        @keyframes starPulse {
          0%, 100% {
            transform: scale(1);
            filter: drop-shadow(0 0 4px rgba(139, 92, 246, 0.5));
          }
          50% {
            transform: scale(1.1);
            filter: drop-shadow(0 0 12px rgba(139, 92, 246, 0.8));
          }
        }

        .next-episode {
          margin-bottom: 32px;
        }

        .next-label {
          display: block;
          font-size: 14px;
          text-transform: uppercase;
          letter-spacing: 3px;
          color: rgba(255, 255, 255, 0.5);
          margin-bottom: 8px;
        }

        .next-title {
          font-size: 36px;
          font-weight: 600;
          color: #fff;
          margin: 0;
          text-shadow: 0 2px 20px rgba(139, 92, 246, 0.5);
        }

        .loading-section {
          padding: 40px 0;
        }

        .loading-spinner-large {
          width: 60px;
          height: 60px;
          border: 4px solid rgba(139, 92, 246, 0.2);
          border-top-color: #8B5CF6;
          border-radius: 50%;
          margin: 0 auto 20px;
          animation: spin 1s linear infinite;
        }

        @keyframes spin {
          to { transform: rotate(360deg); }
        }

        .loading-text {
          color: rgba(255, 255, 255, 0.7);
          font-size: 16px;
          margin: 0;
        }

        .countdown-container {
          position: relative;
          width: 120px;
          height: 120px;
          margin: 0 auto 32px;
        }

        .countdown-ring {
          width: 100%;
          height: 100%;
        }

        .countdown-text {
          position: absolute;
          inset: 0;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
        }

        .countdown-number {
          font-size: 42px;
          font-weight: 700;
          color: #fff;
          line-height: 1;
        }

        .countdown-label {
          font-size: 12px;
          color: rgba(255, 255, 255, 0.5);
          text-transform: uppercase;
          letter-spacing: 1px;
        }

        .transition-actions {
          display: flex;
          justify-content: center;
          gap: 12px;
          flex-wrap: wrap;
        }

        .action-btn {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 12px 20px;
          border-radius: 12px;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .action-btn.skip {
          background: linear-gradient(135deg, #8B5CF6, #6366F1);
          border: none;
          color: #fff;
        }

        .action-btn.skip:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 24px rgba(139, 92, 246, 0.4);
        }

        .action-btn.pause {
          background: rgba(255, 255, 255, 0.1);
          border: 1px solid rgba(255, 255, 255, 0.2);
          color: #fff;
        }

        .action-btn.pause:hover {
          background: rgba(255, 255, 255, 0.15);
          border-color: rgba(255, 255, 255, 0.3);
        }

        .action-btn.cancel {
          background: transparent;
          border: 1px solid rgba(255, 255, 255, 0.2);
          color: rgba(255, 255, 255, 0.7);
        }

        .action-btn.cancel:hover {
          border-color: rgba(239, 68, 68, 0.5);
          color: #EF4444;
        }

        @media (max-width: 768px) {
          .chapter-transition-content {
            padding: 24px;
          }

          .story-title {
            font-size: 22px;
          }

          .next-title {
            font-size: 28px;
          }

          .countdown-container {
            width: 100px;
            height: 100px;
          }

          .countdown-number {
            font-size: 36px;
          }

          .transition-actions {
            flex-direction: column;
          }

          .action-btn {
            justify-content: center;
          }
        }
      `}</style>
    </div>
  );
};

export default TVModeChapterTransition;

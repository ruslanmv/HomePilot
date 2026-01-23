import React, { useState } from 'react';
import { AgeVerificationModal } from './AgeVerificationModal';

interface ContentRatingToggleProps {
  contentRating: 'sfw' | 'mature';
  onRatingChange: (rating: 'sfw' | 'mature') => void;
  disabled?: boolean;
}

/**
 * Content Rating Toggle
 *
 * A prominent toggle switch in the header that controls SFW/Mature mode.
 * Switching to Mature requires age verification.
 */
export const ContentRatingToggle: React.FC<ContentRatingToggleProps> = ({
  contentRating,
  onRatingChange,
  disabled = false,
}) => {
  const [showVerification, setShowVerification] = useState(false);
  const isMature = contentRating === 'mature';

  const handleToggle = () => {
    if (disabled) return;

    if (isMature) {
      // Switching back to SFW - no verification needed
      onRatingChange('sfw');
    } else {
      // Switching to Mature - show verification
      setShowVerification(true);
    }
  };

  const handleVerified = () => {
    setShowVerification(false);
    onRatingChange('mature');
  };

  return (
    <>
      <div className="content-rating-toggle">
        <button
          className={`toggle-option ${!isMature ? 'active' : ''}`}
          onClick={() => isMature && handleToggle()}
          disabled={disabled}
        >
          <span className="toggle-icon">&#10003;</span>
          SFW
        </button>
        <button
          className={`toggle-option ${isMature ? 'active mature' : ''}`}
          onClick={() => !isMature && handleToggle()}
          disabled={disabled}
        >
          <span className="toggle-icon">&#128286;</span>
          MATURE
        </button>

        <div
          className={`toggle-slider ${isMature ? 'mature' : 'sfw'}`}
          style={{
            transform: isMature ? 'translateX(100%)' : 'translateX(0)',
          }}
        />
      </div>

      {showVerification && (
        <AgeVerificationModal
          onConfirm={handleVerified}
          onCancel={() => setShowVerification(false)}
        />
      )}

      <style>{`
        .content-rating-toggle {
          display: flex;
          position: relative;
          background: var(--color-surface);
          border: 1px solid var(--color-border);
          border-radius: 8px;
          padding: 4px;
          gap: 0;
        }

        .toggle-option {
          position: relative;
          z-index: 1;
          padding: 8px 16px;
          border: none;
          background: transparent;
          color: var(--color-text-muted);
          font-weight: 500;
          font-size: 14px;
          cursor: pointer;
          transition: color 0.2s;
          display: flex;
          align-items: center;
          gap: 6px;
          min-width: 90px;
          justify-content: center;
        }

        .toggle-option:disabled {
          cursor: not-allowed;
          opacity: 0.5;
        }

        .toggle-option.active {
          color: var(--color-text);
        }

        .toggle-option.active.mature {
          color: #F59E0B;
        }

        .toggle-icon {
          font-size: 12px;
        }

        .toggle-slider {
          position: absolute;
          top: 4px;
          left: 4px;
          width: calc(50% - 4px);
          height: calc(100% - 8px);
          border-radius: 6px;
          transition: transform 0.3s ease, background 0.3s ease;
        }

        .toggle-slider.sfw {
          background: var(--color-success);
        }

        .toggle-slider.mature {
          background: linear-gradient(135deg, #8B5CF6, #F59E0B);
        }
      `}</style>
    </>
  );
};

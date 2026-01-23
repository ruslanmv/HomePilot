import React, { useState } from 'react';

interface AgeVerificationModalProps {
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Age Verification Modal
 *
 * Required when switching to Mature mode.
 * Professional, non-judgmental design.
 */
export const AgeVerificationModal: React.FC<AgeVerificationModalProps> = ({
  onConfirm,
  onCancel,
}) => {
  const [confirmed, setConfirmed] = useState(false);

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-icon">&#128286;</span>
          <h2>Enable Mature Mode?</h2>
        </div>

        <div className="modal-body">
          <p className="modal-description">
            Mature mode unlocks adult content generation capabilities:
          </p>

          <ul className="feature-list">
            <li>
              <span className="check">&#10003;</span>
              NSFW image generation with anime models
            </li>
            <li>
              <span className="check">&#10003;</span>
              Explicit content (nudity, porn) allowed
            </li>
            <li>
              <span className="check">&#10003;</span>
              Fan service &amp; ecchi content
            </li>
            <li>
              <span className="check">&#10003;</span>
              Mature romance/erotica stories
            </li>
          </ul>

          <div className="blocked-notice">
            <span className="notice-icon">&#9888;</span>
            <span>
              <strong>Always blocked:</strong> CSAM, minors, non-consensual content
            </span>
          </div>

          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <span className="checkbox-text">
              I am 18 years or older and consent to viewing adult content
            </span>
          </label>
        </div>

        <div className="modal-footer">
          <button className="btn-cancel" onClick={onCancel}>
            Cancel
          </button>
          <button
            className="btn-confirm"
            onClick={onConfirm}
            disabled={!confirmed}
          >
            Enable Mature Mode
          </button>
        </div>
      </div>

      <style>{`
        .modal-overlay {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.6);
          backdrop-filter: blur(4px);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          animation: fadeIn 0.2s ease;
        }

        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        .modal-content {
          background: var(--color-surface, #fff);
          border-radius: 16px;
          width: 100%;
          max-width: 480px;
          margin: 16px;
          box-shadow: 0 25px 50px rgba(0, 0, 0, 0.25);
          animation: slideUp 0.3s ease;
        }

        @keyframes slideUp {
          from { transform: translateY(20px); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }

        .modal-header {
          padding: 24px 24px 16px;
          display: flex;
          align-items: center;
          gap: 12px;
          border-bottom: 1px solid var(--color-border, #e2e8f0);
        }

        .modal-icon {
          font-size: 28px;
        }

        .modal-header h2 {
          margin: 0;
          font-size: 20px;
          font-weight: 600;
          color: var(--color-text, #1e293b);
        }

        .modal-body {
          padding: 24px;
        }

        .modal-description {
          margin: 0 0 16px;
          color: var(--color-text-muted, #64748b);
          font-size: 15px;
        }

        .feature-list {
          list-style: none;
          margin: 0 0 20px;
          padding: 0;
        }

        .feature-list li {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 8px 0;
          color: var(--color-text, #1e293b);
          font-size: 14px;
        }

        .check {
          color: #10B981;
          font-weight: bold;
        }

        .blocked-notice {
          background: #FEF2F2;
          border: 1px solid #FECACA;
          border-radius: 8px;
          padding: 12px 16px;
          display: flex;
          align-items: flex-start;
          gap: 10px;
          margin-bottom: 20px;
          font-size: 13px;
          color: #991B1B;
        }

        .notice-icon {
          font-size: 16px;
        }

        .checkbox-label {
          display: flex;
          align-items: flex-start;
          gap: 12px;
          cursor: pointer;
          padding: 12px;
          background: var(--color-surface-hover, #f1f5f9);
          border-radius: 8px;
        }

        .checkbox-label input[type="checkbox"] {
          width: 20px;
          height: 20px;
          margin-top: 2px;
          cursor: pointer;
          accent-color: #8B5CF6;
        }

        .checkbox-text {
          font-size: 14px;
          color: var(--color-text, #1e293b);
          line-height: 1.5;
        }

        .modal-footer {
          padding: 16px 24px 24px;
          display: flex;
          gap: 12px;
          justify-content: flex-end;
        }

        .btn-cancel,
        .btn-confirm {
          padding: 10px 20px;
          border-radius: 8px;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s;
        }

        .btn-cancel {
          background: transparent;
          border: 1px solid var(--color-border, #e2e8f0);
          color: var(--color-text-muted, #64748b);
        }

        .btn-cancel:hover {
          background: var(--color-surface-hover, #f1f5f9);
        }

        .btn-confirm {
          background: linear-gradient(135deg, #8B5CF6, #7C3AED);
          border: none;
          color: white;
        }

        .btn-confirm:hover:not(:disabled) {
          transform: translateY(-1px);
          box-shadow: 0 4px 12px rgba(139, 92, 246, 0.4);
        }

        .btn-confirm:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
      `}</style>
    </div>
  );
};

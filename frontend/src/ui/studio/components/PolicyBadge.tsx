import React from 'react';

interface PolicyResult {
  allowed: boolean;
  reason: string;
  flags?: string[];
  explicit_allowed?: boolean;
}

interface PolicyBadgeProps {
  result: PolicyResult;
  showDetails?: boolean;
}

/**
 * Policy Badge
 *
 * Visual indicator showing if content is allowed by policy.
 * Green for allowed, red for blocked.
 */
export const PolicyBadge: React.FC<PolicyBadgeProps> = ({
  result,
  showDetails = true,
}) => {
  const isAllowed = result.allowed;
  const isExplicitAllowed = result.explicit_allowed;

  return (
    <div className={`policy-badge ${isAllowed ? 'allowed' : 'blocked'}`}>
      <span className="badge-icon">
        {isAllowed ? '\u2713' : '\u2717'}
      </span>
      <span className="badge-text">
        {isAllowed ? 'Allowed' : 'Blocked'}
      </span>
      {isExplicitAllowed && (
        <span className="explicit-tag">Explicit OK</span>
      )}
      {showDetails && (
        <span className="badge-reason">{result.reason}</span>
      )}

      <style>{`
        .policy-badge {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 8px 12px;
          border-radius: 8px;
          font-size: 13px;
          flex-wrap: wrap;
        }

        .policy-badge.allowed {
          background: rgba(16, 185, 129, 0.1);
          border: 1px solid rgba(16, 185, 129, 0.3);
          color: #059669;
        }

        .policy-badge.blocked {
          background: rgba(239, 68, 68, 0.1);
          border: 1px solid rgba(239, 68, 68, 0.3);
          color: #DC2626;
        }

        .badge-icon {
          font-weight: bold;
          font-size: 14px;
        }

        .badge-text {
          font-weight: 600;
        }

        .explicit-tag {
          background: linear-gradient(135deg, #8B5CF6, #F59E0B);
          color: white;
          padding: 2px 8px;
          border-radius: 4px;
          font-size: 11px;
          font-weight: 500;
        }

        .badge-reason {
          color: var(--color-text-muted);
          font-size: 12px;
        }
      `}</style>
    </div>
  );
};

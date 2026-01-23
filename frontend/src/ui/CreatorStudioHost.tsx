import React, { useEffect } from "react";
import { MemoryRouter } from "react-router-dom";
import { StudioRoutes } from "./studio/StudioRoutes";
import { useStudioStore } from "./studio/stores/studioStore";

interface CreatorStudioHostProps {
  backendUrl: string;
  apiKey?: string;
  onSwitchToPlay?: () => void;
}

/**
 * CreatorStudioHost wraps the Creator Studio in a MemoryRouter
 * so it works without requiring the whole app to use react-router.
 *
 * It also bootstraps the connection info (backendUrl + apiKey) for
 * Creator Studio API calls.
 */
export function CreatorStudioHost({
  backendUrl,
  apiKey,
  onSwitchToPlay,
}: CreatorStudioHostProps) {
  // Bootstrap connection info for Creator Studio API calls
  useEffect(() => {
    const store = useStudioStore.getState();
    if (store.setConnection) {
      store.setConnection(backendUrl, (apiKey || "").trim());
    }
  }, [backendUrl, apiKey]);

  return (
    <div className="creator-studio-host">
      {/* Header bar with switch button */}
      {onSwitchToPlay && (
        <div className="creator-studio-header">
          <span className="creator-studio-title">Creator Studio</span>
          <button
            className="switch-mode-btn"
            onClick={onSwitchToPlay}
            title="Switch to Play Studio"
          >
            Switch to Play Mode
          </button>
        </div>
      )}

      {/* The actual Creator Studio routes */}
      <div className="creator-studio-content">
        <MemoryRouter initialEntries={["/"]}>
          <StudioRoutes />
        </MemoryRouter>
      </div>

      <style>{`
        .creator-studio-host {
          display: flex;
          flex-direction: column;
          height: 100%;
          width: 100%;
        }

        .creator-studio-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 8px 16px;
          background: var(--color-surface, #1a1a2e);
          border-bottom: 1px solid var(--color-border, #2a2a4a);
        }

        .creator-studio-title {
          font-weight: 600;
          font-size: 14px;
          color: var(--color-text, #fff);
        }

        .switch-mode-btn {
          padding: 6px 12px;
          font-size: 12px;
          background: transparent;
          border: 1px solid var(--color-border, #2a2a4a);
          border-radius: 6px;
          color: var(--color-text-muted, #888);
          cursor: pointer;
          transition: all 0.2s;
        }

        .switch-mode-btn:hover {
          background: var(--color-surface-hover, #2a2a4a);
          color: var(--color-text, #fff);
        }

        .creator-studio-content {
          flex: 1;
          overflow: hidden;
        }
      `}</style>
    </div>
  );
}

export default CreatorStudioHost;

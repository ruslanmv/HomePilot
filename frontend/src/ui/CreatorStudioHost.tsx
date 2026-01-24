import React, { useEffect } from "react";
import { MemoryRouter } from "react-router-dom";
import { StudioRoutes } from "./studio/StudioRoutes";
import { useStudioStore } from "./studio/stores/studioStore";
import { ArrowLeft } from "lucide-react";

interface CreatorStudioHostProps {
  backendUrl: string;
  apiKey?: string;
  onSwitchToPlay?: () => void;
  /** Initial route - defaults to "/new" (wizard) for direct access */
  initialRoute?: string;
  /** Optional project ID to open directly */
  projectId?: string;
}

/**
 * CreatorStudioHost wraps the Creator Studio in a MemoryRouter
 * so it works without requiring the whole app to use react-router.
 *
 * It also bootstraps the connection info (backendUrl + apiKey) for
 * Creator Studio API calls.
 *
 * When selecting Creator Studio from the mode chooser, it goes directly
 * to the New Project wizard (no intermediate library page).
 */
export function CreatorStudioHost({
  backendUrl,
  apiKey,
  onSwitchToPlay,
  initialRoute,
  projectId,
}: CreatorStudioHostProps) {
  // Bootstrap connection info for Creator Studio API calls
  useEffect(() => {
    const store = useStudioStore.getState();
    if (store.setConnection) {
      store.setConnection(backendUrl, (apiKey || "").trim());
    }
  }, [backendUrl, apiKey]);

  // Determine initial route:
  // - If projectId is provided, go to that project
  // - Otherwise use initialRoute or default to /new (wizard)
  const startRoute = projectId
    ? `/videos/${projectId}/overview`
    : initialRoute || "/new";

  return (
    <div className="creator-studio-host">
      {/* Header with Switch to Play Mode button */}
      {onSwitchToPlay && (
        <div className="creator-studio-header">
          <button
            className="switch-mode-btn"
            onClick={onSwitchToPlay}
            title="Switch to Play Mode"
          >
            <ArrowLeft size={16} />
            <span>Switch to Play Mode</span>
          </button>
          <span className="creator-studio-title">Creator Studio</span>
        </div>
      )}

      {/* The actual Creator Studio routes */}
      <div className="creator-studio-content">
        <MemoryRouter initialEntries={[startRoute]}>
          <StudioRoutes />
        </MemoryRouter>
      </div>

      <style>{`
        .creator-studio-host {
          display: flex;
          flex-direction: column;
          height: 100%;
          width: 100%;
          background: #0f0f0f;
        }

        .creator-studio-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 20px;
          background: #1a1a1a;
          border-bottom: 1px solid #2a2a2a;
        }

        .creator-studio-title {
          font-weight: 600;
          font-size: 14px;
          color: #f1f1f1;
        }

        .switch-mode-btn {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 8px 16px;
          font-size: 13px;
          font-weight: 500;
          background: transparent;
          border: 1px solid #3f3f3f;
          border-radius: 8px;
          color: #aaa;
          cursor: pointer;
          transition: all 0.2s;
        }

        .switch-mode-btn:hover {
          background: #2a2a2a;
          border-color: #4f4f4f;
          color: #f1f1f1;
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

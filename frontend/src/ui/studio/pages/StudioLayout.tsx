import React, { useEffect } from "react";
import { Routes, Route, NavLink, Navigate } from "react-router-dom";
import { useStudioStore } from "../stores/studioStore";
import { ContentRatingToggle } from "../components/ContentRatingToggle";
import { getTheme, themeToCSS } from "../styles/themes";

// Pages
import { GeneratePage } from "./GeneratePage";
import { GalleryPage } from "./GalleryPage";
import { StoryPage } from "./StoryPage";
import { SettingsPage } from "./SettingsPage";

/**
 * Studio Layout
 *
 * Main layout with sidebar navigation for:
 * - Image Generation
 * - Gallery
 * - Story Generation
 * - Settings
 */
export const StudioLayout: React.FC = () => {
  const {
    contentRating,
    setContentRating,
    matureEnabled,
    setMatureEnabled,
    matureVerified,
    setMatureVerified,
    activeTab,
    setActiveTab,
    sidebarCollapsed,
    setSidebarCollapsed,
  } = useStudioStore();

  const theme = getTheme(contentRating);

  // Fetch NSFW status on mount
  useEffect(() => {
    const fetchNSFWStatus = async () => {
      try {
        const res = await fetch("/studio/image/nsfw-info");
        if (res.ok) {
          const data = await res.json();
          setMatureEnabled(data.nsfw_enabled || false);
        }
      } catch (e) {
        console.error("Failed to fetch NSFW status:", e);
      }
    };
    fetchNSFWStatus();
  }, [setMatureEnabled]);

  const handleRatingChange = (rating: "sfw" | "mature") => {
    if (rating === "mature") {
      setMatureVerified(true);
    }
    setContentRating(rating);
  };

  const navItems = [
    { path: "/studio/generate", label: "Generate", icon: "\u2728", tab: "generate" as const },
    { path: "/studio/gallery", label: "Gallery", icon: "\uD83D\uDDBC\uFE0F", tab: "gallery" as const },
    { path: "/studio/story", label: "Story", icon: "\uD83D\uDCDD", tab: "story" as const },
    { path: "/studio/settings", label: "Settings", icon: "\u2699\uFE0F", tab: "settings" as const },
  ];

  return (
    <div className="studio-layout" style={{ "--theme": themeToCSS(theme) } as React.CSSProperties}>
      <style>{`
        .studio-layout {
          ${themeToCSS(theme)}
          min-height: 100vh;
          display: flex;
          flex-direction: column;
          background: var(--color-background);
          color: var(--color-text);
          transition: background 0.3s, color 0.3s;
        }

        .studio-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 20px;
          background: var(--color-surface);
          border-bottom: 1px solid var(--color-border);
          position: sticky;
          top: 0;
          z-index: 100;
        }

        .header-left {
          display: flex;
          align-items: center;
          gap: 16px;
        }

        .logo {
          display: flex;
          align-items: center;
          gap: 10px;
          font-size: 18px;
          font-weight: 700;
          color: var(--color-primary);
          text-decoration: none;
        }

        .logo-icon {
          font-size: 24px;
        }

        .studio-main {
          flex: 1;
          display: flex;
          overflow: hidden;
        }

        .studio-sidebar {
          width: ${sidebarCollapsed ? "60px" : "200px"};
          background: var(--color-surface);
          border-right: 1px solid var(--color-border);
          padding: 16px 8px;
          display: flex;
          flex-direction: column;
          gap: 8px;
          transition: width 0.2s;
        }

        .sidebar-toggle {
          align-self: flex-end;
          background: none;
          border: none;
          color: var(--color-text-muted);
          padding: 8px;
          cursor: pointer;
          border-radius: 6px;
        }

        .sidebar-toggle:hover {
          background: var(--color-surface-hover);
        }

        .nav-item {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px 14px;
          border-radius: 8px;
          text-decoration: none;
          color: var(--color-text-muted);
          font-size: 14px;
          font-weight: 500;
          transition: all 0.2s;
        }

        .nav-item:hover {
          background: var(--color-surface-hover);
          color: var(--color-text);
        }

        .nav-item.active {
          background: var(--color-primary-light);
          color: var(--color-primary);
        }

        .nav-icon {
          font-size: 18px;
          flex-shrink: 0;
        }

        .nav-label {
          white-space: nowrap;
          overflow: hidden;
          opacity: ${sidebarCollapsed ? 0 : 1};
          transition: opacity 0.2s;
        }

        .studio-content {
          flex: 1;
          overflow: auto;
        }

        .studio-footer {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 8px 20px;
          background: var(--color-surface);
          border-top: 1px solid var(--color-border);
          font-size: 12px;
          color: var(--color-text-muted);
        }

        .status-indicator {
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .status-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
        }

        .status-dot.sfw {
          background: #10B981;
        }

        .status-dot.mature {
          background: linear-gradient(135deg, #8B5CF6, #F59E0B);
        }

        .mature-indicator {
          color: #F59E0B;
          font-weight: 500;
        }

        @media (max-width: 768px) {
          .studio-sidebar {
            position: fixed;
            left: 0;
            top: 56px;
            bottom: 32px;
            z-index: 99;
            transform: ${sidebarCollapsed ? "translateX(-100%)" : "translateX(0)"};
            box-shadow: var(--shadow-lg);
          }

          .nav-label {
            opacity: 1;
          }
        }
      `}</style>

      {/* Header */}
      <header className="studio-header">
        <div className="header-left">
          <a href="/studio" className="logo">
            <span className="logo-icon">\uD83C\uDFAC</span>
            <span>Studio</span>
          </a>
        </div>

        <ContentRatingToggle
          contentRating={contentRating}
          onRatingChange={handleRatingChange}
          disabled={!matureEnabled}
        />
      </header>

      {/* Main */}
      <div className="studio-main">
        {/* Sidebar */}
        <nav className="studio-sidebar">
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
          >
            {sidebarCollapsed ? "\u25B6" : "\u25C0"}
          </button>

          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }: { isActive: boolean }) =>
                `nav-item ${isActive ? "active" : ""}`
              }
              onClick={() => setActiveTab(item.tab)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        {/* Content */}
        <main className="studio-content">
          <Routes>
            <Route path="generate" element={<GeneratePage />} />
            <Route path="gallery" element={<GalleryPage />} />
            <Route path="story" element={<StoryPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="generate" replace />} />
          </Routes>
        </main>
      </div>

      {/* Footer */}
      <footer className="studio-footer">
        <div className="status-indicator">
          <span className={`status-dot ${contentRating}`} />
          <span>
            Policy: {contentRating === "mature" ? "Mature" : "SFW"}
          </span>
        </div>

        <span>Provider: ComfyUI (Local)</span>

        {matureEnabled && contentRating === "mature" && (
          <span className="mature-indicator">
            \uD83D\uDD1E Explicit content allowed
          </span>
        )}
      </footer>
    </div>
  );
};

export default StudioLayout;

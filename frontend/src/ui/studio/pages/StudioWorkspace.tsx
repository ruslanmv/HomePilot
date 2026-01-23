import React, { useEffect, useState } from "react";
import { useParams, Routes, Route, Navigate, NavLink } from "react-router-dom";
import { StudioShell } from "../StudioShell";
import { PolicyBanner } from "../components/PolicyBanner";

// Tab components (stubs for now)
import { OverviewTab } from "../tabs/OverviewTab";
import { BibleTab } from "../tabs/BibleTab";
import { TimelineTab } from "../tabs/TimelineTab";
import { PlayerTab } from "../tabs/PlayerTab";
import { ExportTab } from "../tabs/ExportTab";
import { ActivityTab } from "../tabs/ActivityTab";

type Video = {
  id: string;
  title: string;
  logline: string;
  status: "draft" | "in_review" | "approved" | "archived";
  platformPreset: "youtube_16_9" | "shorts_9_16" | "slides_16_9";
  contentRating: "sfw" | "mature";
};

function TabBar({ id }: { id: string }) {
  const tabs = [
    { to: `/studio/videos/${id}/overview`, label: "Overview" },
    { to: `/studio/videos/${id}/bible`, label: "Channel Bible" },
    { to: `/studio/videos/${id}/timeline`, label: "Timeline" },
    { to: `/studio/videos/${id}/player`, label: "Player" },
    { to: `/studio/videos/${id}/export`, label: "Export" },
    { to: `/studio/videos/${id}/activity`, label: "Activity" },
  ];

  return (
    <div className="flex gap-1">
      {tabs.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          className={({ isActive }: { isActive: boolean }) =>
            `text-sm px-3 py-1 rounded border transition-colors ${
              isActive
                ? "bg-primary text-primary-foreground"
                : "hover:bg-muted/30"
            }`
          }
        >
          {t.label}
        </NavLink>
      ))}
    </div>
  );
}

/**
 * Video workspace with tabs.
 *
 * Tabs:
 * - Overview: KPIs, policy warnings
 * - Channel Bible: Brand guidelines, policy controls
 * - Timeline: Clip/scene editing (NSFW-aware generation)
 * - Player: Playback preview
 * - Export: Export packs (policy enforced)
 * - Activity: Audit log
 */
export function StudioWorkspace() {
  const { id } = useParams<{ id: string }>();
  const [video, setVideo] = useState<Video | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  useEffect(() => {
    if (!id) return;

    setLoading(true);
    setError(null);

    fetch(`/studio/videos/${id}`)
      .then((r) => r.json())
      .then((j) => {
        if (j.video) {
          setVideo(j.video);
        } else {
          setError(j.detail || j.error || "Video not found");
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  if (!id) {
    return <Navigate to="/studio" replace />;
  }

  if (loading) {
    return (
      <div className="h-full w-full flex items-center justify-center">
        <div className="text-sm opacity-70">Loading...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full w-full flex items-center justify-center">
        <div className="text-center">
          <div className="text-sm text-red-500">{error}</div>
          <a href="/studio" className="text-sm underline mt-2 inline-block">
            Back to Library
          </a>
        </div>
      </div>
    );
  }

  return (
    <StudioShell
      title={video?.title || "Untitled"}
      status={video?.status}
      platformPreset={video?.platformPreset}
      contentRating={video?.contentRating || "sfw"}
      rightActions={<TabBar id={id} />}
    >
      {/* Policy warning banner for mature content */}
      {!bannerDismissed && video?.contentRating === "mature" && (
        <PolicyBanner
          contentRating={video.contentRating}
          restrictions={[
            "Exports may require compliance confirmation",
            "Public sharing may be restricted",
          ]}
          onDismiss={() => setBannerDismissed(true)}
        />
      )}

      {/* Tab content */}
      <div className="h-full">
        <Routes>
          <Route path="overview" element={<OverviewTab video={video} />} />
          <Route path="bible" element={<BibleTab video={video} />} />
          <Route path="timeline" element={<TimelineTab video={video} />} />
          <Route path="player" element={<PlayerTab video={video} />} />
          <Route path="export" element={<ExportTab video={video} />} />
          <Route path="activity" element={<ActivityTab video={video} />} />
          <Route path="*" element={<Navigate to="overview" replace />} />
        </Routes>
      </div>
    </StudioShell>
  );
}

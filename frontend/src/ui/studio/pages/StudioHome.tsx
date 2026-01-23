import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { StudioLibraryRail, LibraryFilter } from "../StudioLibraryRail";
import { ContentRatingBadge } from "../components/ContentRatingBadge";

type Video = {
  id: string;
  title: string;
  logline: string;
  status: "draft" | "in_review" | "approved" | "archived";
  updatedAt: number;
  platformPreset: "youtube_16_9" | "shorts_9_16" | "slides_16_9";
  contentRating: "sfw" | "mature";
};

/**
 * Studio library home page.
 * Lists all video projects with search and filter.
 */
export function StudioHome() {
  const [filter, setFilter] = useState<LibraryFilter>({ q: "" });
  const [videos, setVideos] = useState<Video[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadVideos() {
    setLoading(true);
    setError(null);

    const params = new URLSearchParams();
    if (filter.q) params.set("q", filter.q);
    if (filter.status) params.set("status", filter.status);
    if (filter.preset) params.set("preset", filter.preset);
    if (filter.contentRating) params.set("contentRating", filter.contentRating);

    try {
      const r = await fetch(`/studio/videos?${params.toString()}`);
      const j = await r.json();
      if (!r.ok) throw new Error(j?.detail || j?.error || `HTTP ${r.status}`);
      setVideos(j.videos || []);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadVideos();
  }, [filter.q, filter.status, filter.preset, filter.contentRating]);

  return (
    <div className="h-full w-full flex">
      <StudioLibraryRail filter={filter} onChange={setFilter}>
        <div className="p-3 flex items-center justify-between border-b">
          <div className="text-sm opacity-70">Projects</div>
          <Link
            to="/studio/new"
            className="text-sm px-3 py-1 rounded border hover:bg-muted/30"
          >
            + New
          </Link>
        </div>

        {error && (
          <div className="mx-3 my-2 text-sm p-2 border rounded bg-red-500/10 border-red-500/30">
            {error}
          </div>
        )}

        {loading && (
          <div className="p-3 text-sm opacity-70">Loading...</div>
        )}

        <div className="px-3 pb-6 grid gap-2">
          {videos.map((v) => (
            <Link
              key={v.id}
              to={`/studio/videos/${v.id}/overview`}
              className="border rounded p-3 hover:bg-muted/30 transition-colors"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="font-semibold truncate flex-1">{v.title}</div>
                <ContentRatingBadge value={v.contentRating} showLabel={false} />
              </div>
              {v.logline && (
                <div className="text-xs opacity-70 mt-1 line-clamp-2">
                  {v.logline}
                </div>
              )}
              <div className="text-xs opacity-50 mt-2 flex gap-2">
                <span className="capitalize">{v.status.replace("_", " ")}</span>
                <span>•</span>
                <span>{v.platformPreset.replace(/_/g, " ")}</span>
              </div>
            </Link>
          ))}

          {!loading && !videos.length && !error && (
            <div className="text-sm opacity-70 p-4 border rounded text-center">
              No projects yet.
              <br />
              <Link to="/studio/new" className="underline">
                Create your first project
              </Link>
            </div>
          )}
        </div>
      </StudioLibraryRail>

      <div className="flex-1 flex items-center justify-center bg-muted/10">
        <div className="text-center">
          <div className="text-lg font-semibold mb-2">Studio</div>
          <div className="text-sm opacity-70">
            Select a project or create a new one.
          </div>
        </div>
      </div>
    </div>
  );
}

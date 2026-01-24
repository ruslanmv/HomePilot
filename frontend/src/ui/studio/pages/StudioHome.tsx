import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { StudioLibraryRail, LibraryFilter } from "../StudioLibraryRail";
import { ContentRatingBadge } from "../components/ContentRatingBadge";
import { studioGet } from "../lib/api";
import { studioPaths } from "../lib/studioPaths";

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
    if (filter.platformPreset) params.set("platformPreset", filter.platformPreset);
    if (filter.contentRating) params.set("contentRating", filter.contentRating);

    try {
      const j = await studioGet<{ videos: Video[] }>(`/studio/videos?${params.toString()}`);
      setVideos(j.videos || []);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadVideos();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter.q, filter.platformPreset, filter.contentRating]);

  return (
    <div className="h-full w-full flex">
      <StudioLibraryRail filter={filter} onChange={setFilter} />

      <div className="flex-1 p-4">
        <div className="flex items-center justify-between gap-2">
          <div>
            <div className="text-lg font-semibold">Creator Studio</div>
            <div className="text-sm opacity-70">Projects</div>
          </div>
          <Link
            to={studioPaths.newProject()}
            className="text-sm px-3 py-1 rounded border hover:bg-muted/30"
          >
            + New
          </Link>
        </div>

        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {loading && (
            <div className="text-sm opacity-70 p-4 border rounded">Loading...</div>
          )}

          {error && (
            <div className="text-sm text-red-500 p-4 border rounded">
              {error}
            </div>
          )}

          {videos.map((v) => (
            <Link
              key={v.id}
              to={studioPaths.videoTab(v.id, "overview")}
              className="border rounded p-3 hover:bg-muted/30 transition-colors"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-medium truncate">{v.title}</div>
                  {v.logline && (
                    <div className="text-xs opacity-70 mt-1 line-clamp-2">
                      {v.logline}
                    </div>
                  )}
                </div>
                <ContentRatingBadge value={v.contentRating} />
              </div>
            </Link>
          ))}

          {!loading && !videos.length && !error && (
            <div className="text-sm opacity-70 p-4 border rounded text-center">
              No projects yet.
              <br />
              <Link to={studioPaths.newProject()} className="underline">
                Create your first project
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

import React from "react";
import { ContentRatingBadge } from "../components/ContentRatingBadge";

type Video = {
  id: string;
  title: string;
  contentRating: "sfw" | "mature";
};

export function PlayerTab({ video }: { video: Video | null }) {
  if (!video) return null;

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b flex items-center gap-3">
        <div className="font-semibold">Player</div>
        <ContentRatingBadge value={video.contentRating} />
        {video.contentRating === "mature" && (
          <span className="text-xs opacity-70">
            (thumbnails may be blurred for enterprise settings)
          </span>
        )}
      </div>

      <div className="flex-1 flex items-center justify-center bg-black/90">
        <div className="text-white/70 text-center">
          <div className="text-lg">▶</div>
          <div className="text-sm mt-2">{video.title}</div>
          <div className="text-xs mt-1 opacity-50">
            Video player coming soon
          </div>
        </div>
      </div>
    </div>
  );
}

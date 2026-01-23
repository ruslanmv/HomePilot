import React, { useEffect, useState } from "react";

type Video = {
  id: string;
  title: string;
  logline: string;
  contentRating: "sfw" | "mature";
};

export function OverviewTab({ video }: { video: Video | null }) {
  const [policyViolations, setPolicyViolations] = useState<number>(0);

  useEffect(() => {
    if (!video?.id) return;

    fetch(`/studio/videos/${video.id}/policy-violations`)
      .then((r) => r.json())
      .then((j) => {
        setPolicyViolations(j.violations?.length || 0);
      })
      .catch(() => {});
  }, [video?.id]);

  if (!video) return null;

  return (
    <div className="p-6">
      <div className="text-lg font-semibold">Overview</div>
      <div className="text-sm opacity-70 mt-1">{video.logline || "No description"}</div>

      <div className="grid grid-cols-3 gap-4 mt-6">
        <div className="border rounded p-4">
          <div className="text-xs opacity-70">Status</div>
          <div className="text-lg font-semibold mt-1 capitalize">Draft</div>
        </div>

        <div className="border rounded p-4">
          <div className="text-xs opacity-70">Content Rating</div>
          <div className="text-lg font-semibold mt-1 capitalize">{video.contentRating}</div>
        </div>

        <div className="border rounded p-4">
          <div className="text-xs opacity-70">Policy Warnings</div>
          <div className={`text-lg font-semibold mt-1 ${policyViolations > 0 ? "text-yellow-600" : ""}`}>
            {policyViolations}
          </div>
        </div>
      </div>

      {video.contentRating === "mature" && (
        <div className="mt-6 p-4 border rounded bg-yellow-500/10 border-yellow-500/30">
          <div className="font-semibold text-sm">Mature Content Enabled</div>
          <div className="text-xs opacity-80 mt-1">
            This project allows mature themes. Generation requires provider approval.
            Exports may have restrictions.
          </div>
        </div>
      )}
    </div>
  );
}

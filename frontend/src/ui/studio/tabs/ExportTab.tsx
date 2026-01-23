import React, { useEffect, useState } from "react";

type Video = {
  id: string;
  contentRating: "sfw" | "mature";
};

type ExportOption = {
  kind: string;
  label: string;
  available: boolean;
};

export function ExportTab({ video }: { video: Video | null }) {
  const [exports, setExports] = useState<ExportOption[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!video?.id) return;

    fetch(`/studio/videos/${video.id}/exports`)
      .then((r) => r.json())
      .then((j) => setExports(j.exports || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [video?.id]);

  if (!video) return null;

  return (
    <div className="p-6">
      <div className="text-lg font-semibold">Export</div>
      <div className="text-sm opacity-70 mt-1">
        Download your project in various formats.
      </div>

      {video.contentRating === "mature" && (
        <div className="mt-4 p-3 border rounded bg-yellow-500/10 border-yellow-500/30 text-sm">
          ⚠️ <strong>Mature content restrictions:</strong>
          <ul className="list-disc list-inside mt-1 text-xs opacity-80">
            <li>Public sharing may be disabled</li>
            <li>YouTube preset may require compliance confirmation</li>
            <li>No exports to restricted platforms</li>
          </ul>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 mt-6 max-w-xl">
        {loading ? (
          <div className="col-span-2 text-sm opacity-70">Loading exports...</div>
        ) : (
          exports.map((exp) => (
            <div
              key={exp.kind}
              className={`border rounded p-4 ${
                exp.available ? "hover:bg-muted/30 cursor-pointer" : "opacity-50"
              }`}
            >
              <div className="font-semibold text-sm">{exp.label}</div>
              <div className="text-xs opacity-70 mt-1">
                {exp.available ? "Available" : "Not available for this preset"}
              </div>
              {exp.available && (
                <button className="mt-3 text-xs px-3 py-1 rounded border">
                  Export
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

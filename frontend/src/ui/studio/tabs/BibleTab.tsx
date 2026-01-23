import React, { useState, useEffect } from "react";

type Video = {
  id: string;
  contentRating: "sfw" | "mature";
};

type PolicySummary = {
  contentRating: string;
  orgAllowsMature: boolean;
  projectAllowsMature: boolean;
  allowedProviders: string[];
  localOnly: boolean;
  restrictions: string[];
};

export function BibleTab({ video }: { video: Video | null }) {
  const [policy, setPolicy] = useState<PolicySummary | null>(null);

  useEffect(() => {
    if (!video?.id) return;

    fetch(`/studio/videos/${video.id}/policy`)
      .then((r) => r.json())
      .then((j) => setPolicy(j.policy))
      .catch(() => {});
  }, [video?.id]);

  if (!video) return null;

  return (
    <div className="p-6">
      <div className="text-lg font-semibold">Channel Bible</div>
      <div className="text-sm opacity-70 mt-1">
        Brand guidelines, tone, and policy controls.
      </div>

      <div className="grid grid-cols-2 gap-6 mt-6">
        {/* Left: Brand guidelines (stub) */}
        <div className="border rounded p-4">
          <div className="font-semibold text-sm">Brand Guidelines</div>
          <div className="text-xs opacity-70 mt-2">
            Coming soon: tone of voice, visual style, brand colors.
          </div>
        </div>

        {/* Right: Policy controls */}
        <div className="border rounded p-4">
          <div className="font-semibold text-sm">Policy Controls</div>

          {policy && (
            <div className="mt-3 grid gap-2 text-sm">
              <div className="flex justify-between">
                <span className="opacity-70">Content Rating:</span>
                <span className="capitalize">{policy.contentRating}</span>
              </div>

              <div className="flex justify-between">
                <span className="opacity-70">Org Allows Mature:</span>
                <span>{policy.orgAllowsMature ? "Yes" : "No"}</span>
              </div>

              <div className="flex justify-between">
                <span className="opacity-70">Project Allows Mature:</span>
                <span>{policy.projectAllowsMature ? "Yes" : "No"}</span>
              </div>

              <div className="flex justify-between">
                <span className="opacity-70">Local Only:</span>
                <span>{policy.localOnly ? "Yes" : "No"}</span>
              </div>

              <div className="flex justify-between">
                <span className="opacity-70">Allowed Providers:</span>
                <span>{policy.allowedProviders.join(", ") || "None"}</span>
              </div>

              <div className="mt-2 pt-2 border-t">
                <div className="text-xs opacity-70 font-medium">Restrictions:</div>
                <ul className="text-xs opacity-60 mt-1 list-disc list-inside">
                  {policy.restrictions.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

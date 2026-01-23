import React, { useState } from "react";
import { useNavigate } from "react-router-dom";

type PlatformPreset = "youtube_16_9" | "shorts_9_16" | "slides_16_9";
type ContentRating = "sfw" | "mature";

/**
 * New project creation wizard.
 *
 * Steps:
 * 1. Basic info (title, logline)
 * 2. Format (platform preset)
 * 3. Policy & Safety (content rating, provider policy)
 */
export function StudioNewWizard() {
  const nav = useNavigate();

  // Form state
  const [title, setTitle] = useState("");
  const [logline, setLogline] = useState("");
  const [platformPreset, setPlatformPreset] = useState<PlatformPreset>("youtube_16_9");
  const [contentRating, setContentRating] = useState<ContentRating>("sfw");
  const [allowMature, setAllowMature] = useState(false);
  const [localOnly, setLocalOnly] = useState(true);

  // UI state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate() {
    if (!title.trim()) {
      setError("Title is required");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const r = await fetch("/studio/videos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: title.trim(),
          logline: logline.trim(),
          platformPreset,
          contentRating,
          policyMode: contentRating === "mature" ? "restricted" : "youtube_safe",
          providerPolicy: {
            allowMature: contentRating === "mature" ? allowMature : false,
            allowedProviders: ["ollama"],
            localOnly,
          },
        }),
      });

      const j = await r.json();
      if (!r.ok) throw new Error(j?.detail || j?.error || `HTTP ${r.status}`);

      nav(`/studio/videos/${j.video.id}/overview`);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  const matureDisabled = contentRating !== "mature";

  return (
    <div className="h-full w-full flex items-center justify-center p-6">
      <div className="w-full max-w-xl border rounded p-6 bg-background">
        <div className="text-xl font-semibold">New Studio Project</div>
        <div className="text-sm opacity-70 mt-1">
          YouTube-first workflow with optional mature content governance.
        </div>

        <div className="mt-6 grid gap-4">
          {/* Title */}
          <div>
            <label className="text-sm font-medium mb-1 block">Title *</label>
            <input
              className="w-full border rounded px-3 py-2"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g., Product Launch Teaser"
            />
          </div>

          {/* Logline */}
          <div>
            <label className="text-sm font-medium mb-1 block">Logline</label>
            <textarea
              className="w-full border rounded px-3 py-2 resize-none"
              rows={2}
              value={logline}
              onChange={(e) => setLogline(e.target.value)}
              placeholder="Brief description of your video..."
            />
          </div>

          {/* Platform preset */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-1 block">Platform</label>
              <select
                className="w-full border rounded px-3 py-2"
                value={platformPreset}
                onChange={(e) => setPlatformPreset(e.target.value as PlatformPreset)}
              >
                <option value="youtube_16_9">YouTube 16:9</option>
                <option value="shorts_9_16">Shorts 9:16</option>
                <option value="slides_16_9">Slides 16:9</option>
              </select>
            </div>

            {/* Content rating */}
            <div>
              <label className="text-sm font-medium mb-1 block">
                Content Rating
              </label>
              <select
                className="w-full border rounded px-3 py-2"
                value={contentRating}
                onChange={(e) => setContentRating(e.target.value as ContentRating)}
              >
                <option value="sfw">SFW (Safe for Work)</option>
                <option value="mature">Mature</option>
              </select>
            </div>
          </div>

          {/* Policy & Safety section */}
          <div className="border rounded p-4 mt-2">
            <div className="font-semibold text-sm">Policy & Safety</div>
            <div className="text-xs opacity-70 mt-1">
              Mature content is intended for permitted artistic/educational
              contexts (horror, medical, fashion, etc.). Organization must enable
              it server-side via <code>STUDIO_ALLOW_MATURE=1</code>.
            </div>

            <div className="mt-3 grid gap-2">
              <label
                className={`flex items-center gap-2 text-sm ${
                  matureDisabled ? "opacity-50 cursor-not-allowed" : ""
                }`}
              >
                <input
                  type="checkbox"
                  disabled={matureDisabled}
                  checked={allowMature}
                  onChange={(e) => setAllowMature(e.target.checked)}
                />
                Allow mature generation (project-level)
              </label>

              <label
                className={`flex items-center gap-2 text-sm ${
                  matureDisabled ? "opacity-50 cursor-not-allowed" : ""
                }`}
              >
                <input
                  type="checkbox"
                  disabled={matureDisabled}
                  checked={localOnly}
                  onChange={(e) => setLocalOnly(e.target.checked)}
                />
                Local-only mode (recommended for mature content)
              </label>

              <div className="text-xs opacity-60 mt-1">
                Default allowed providers: <code>ollama</code> (local)
              </div>
            </div>

            {contentRating === "mature" && (
              <div className="mt-3 p-2 bg-yellow-500/10 border border-yellow-500/30 rounded text-xs">
                ⚠️ This project may generate sensitive imagery. Use only for
                permitted artistic/educational contexts.
              </div>
            )}
          </div>

          {/* Error */}
          {error && (
            <div className="text-sm p-3 border rounded bg-red-500/10 border-red-500/30">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2 justify-end mt-2">
            <button
              className="px-4 py-2 rounded border hover:bg-muted/30"
              onClick={() => nav("/studio")}
              disabled={loading}
            >
              Cancel
            </button>
            <button
              className="px-4 py-2 rounded border bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
              onClick={handleCreate}
              disabled={!title.trim() || loading}
            >
              {loading ? "Creating..." : "Create Project"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

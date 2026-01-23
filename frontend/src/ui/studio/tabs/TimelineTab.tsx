import React, { useState } from "react";
import { ContentRatingBadge } from "../components/ContentRatingBadge";

type Video = {
  id: string;
  contentRating: "sfw" | "mature";
};

/**
 * Timeline tab for clip/scene editing.
 * NSFW-aware generation with policy enforcement.
 */
export function TimelineTab({ video }: { video: Video | null }) {
  const [prompt, setPrompt] = useState("");
  const [provider, setProvider] = useState("ollama");
  const [result, setResult] = useState<{ ok: boolean; error?: string; flags?: string[] } | null>(null);
  const [loading, setLoading] = useState(false);

  async function checkPolicy() {
    if (!video?.id || !prompt.trim()) return;

    setLoading(true);
    setResult(null);

    try {
      const r = await fetch(`/studio/videos/${video.id}/policy/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt.trim(), provider }),
      });
      const j = await r.json();
      setResult(j);
    } catch (e: any) {
      setResult({ ok: false, error: e.message });
    } finally {
      setLoading(false);
    }
  }

  if (!video) return null;

  return (
    <div className="p-6">
      <div className="flex items-center gap-3">
        <div className="text-lg font-semibold">Timeline</div>
        <ContentRatingBadge value={video.contentRating} />
      </div>
      <div className="text-sm opacity-70 mt-1">
        Clip and scene editor with policy-enforced generation.
      </div>

      {/* Policy check demo */}
      <div className="mt-6 border rounded p-4 max-w-xl">
        <div className="font-semibold text-sm">Generation Policy Check</div>
        <div className="text-xs opacity-70 mt-1">
          Test if a prompt would be allowed by current policy.
        </div>

        <div className="mt-3 grid gap-3">
          <div>
            <label className="text-xs mb-1 block">Prompt</label>
            <textarea
              className="w-full border rounded px-2 py-1 text-sm resize-none"
              rows={3}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe what you want to generate..."
            />
          </div>

          <div>
            <label className="text-xs mb-1 block">Provider</label>
            <select
              className="border rounded px-2 py-1 text-sm"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
            >
              <option value="ollama">Ollama (local)</option>
              <option value="openai">OpenAI</option>
              <option value="comfyui">ComfyUI</option>
            </select>
          </div>

          <button
            className="px-3 py-1 rounded border text-sm hover:bg-muted/30 disabled:opacity-50"
            onClick={checkPolicy}
            disabled={!prompt.trim() || loading}
          >
            {loading ? "Checking..." : "Check Policy"}
          </button>

          {result && (
            <div
              className={`p-2 rounded border text-sm ${
                result.ok
                  ? "bg-green-500/10 border-green-500/30"
                  : "bg-red-500/10 border-red-500/30"
              }`}
            >
              {result.ok ? (
                <div>✅ Allowed</div>
              ) : (
                <div>❌ Blocked: {result.error}</div>
              )}
              {result.flags && result.flags.length > 0 && (
                <div className="text-xs opacity-70 mt-1">
                  Flags: {result.flags.join(", ")}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Placeholder for actual timeline UI */}
      <div className="mt-6 border rounded p-8 text-center opacity-70">
        <div className="text-sm">Timeline editor coming soon.</div>
        <div className="text-xs mt-1">
          Clips, scenes, and NSFW-aware generation controls.
        </div>
      </div>
    </div>
  );
}

import React from "react";

type Preset = "youtube_16_9" | "shorts_9_16" | "slides_16_9";

const PRESET_CONFIG: Record<Preset, { label: string; icon: string }> = {
  youtube_16_9: { label: "YouTube 16:9", icon: "▶" },
  shorts_9_16: { label: "Shorts 9:16", icon: "📱" },
  slides_16_9: { label: "Slides 16:9", icon: "📊" },
};

export function PlatformBadge({ preset }: { preset: Preset }) {
  const config = PRESET_CONFIG[preset] || PRESET_CONFIG.youtube_16_9;

  return (
    <span className="text-xs px-2 py-1 rounded-full border opacity-80">
      {config.icon} {config.label}
    </span>
  );
}

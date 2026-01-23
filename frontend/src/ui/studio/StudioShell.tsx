import React from "react";
import { ContentRatingBadge } from "./components/ContentRatingBadge";
import { StatusBadge } from "./components/StatusBadge";
import { PlatformBadge } from "./components/PlatformBadge";

type Props = {
  title: string;
  status?: "draft" | "in_review" | "approved" | "archived";
  platformPreset?: "youtube_16_9" | "shorts_9_16" | "slides_16_9";
  contentRating?: "sfw" | "mature";
  rightActions?: React.ReactNode;
  children: React.ReactNode;
};

/**
 * Studio shell layout with header and content area.
 *
 * Header shows:
 * - Breadcrumb (Studio / {title})
 * - Status badge
 * - Platform preset badge
 * - Content rating badge (NSFW indicator)
 * - Right-side actions slot
 */
export function StudioShell(props: Props) {
  const {
    title,
    status = "draft",
    platformPreset = "youtube_16_9",
    contentRating = "sfw",
  } = props;

  return (
    <div className="h-full w-full grid" style={{ gridTemplateRows: "56px 1fr" }}>
      {/* Header bar */}
      <header className="flex items-center justify-between px-4 border-b bg-background">
        <div className="flex items-center gap-3 min-w-0">
          <div className="text-sm opacity-70">Studio</div>
          <div className="text-sm opacity-40">/</div>
          <div className="font-semibold truncate">{title}</div>
          <StatusBadge status={status} />
          <PlatformBadge preset={platformPreset} />
          <ContentRatingBadge value={contentRating} />
        </div>
        <div className="flex items-center gap-2">{props.rightActions}</div>
      </header>

      {/* Main content */}
      <main className="h-full w-full overflow-auto">{props.children}</main>
    </div>
  );
}

import React from "react";

type Props = {
  value: "sfw" | "mature";
  showLabel?: boolean;
};

/**
 * Badge showing content rating (SFW or Mature).
 *
 * Mature badge has warning styling (yellow/amber).
 */
export function ContentRatingBadge({ value, showLabel = true }: Props) {
  if (value === "mature") {
    return (
      <span
        className="text-xs px-2 py-1 rounded-full border border-yellow-500/50 bg-yellow-500/10 text-yellow-600 dark:text-yellow-400"
        title="Mature content enabled - exports may have restrictions"
      >
        {showLabel ? "Mature" : "M"}
      </span>
    );
  }

  return (
    <span
      className="text-xs px-2 py-1 rounded-full border opacity-80"
      title="Safe for work content"
    >
      {showLabel ? "SFW" : "S"}
    </span>
  );
}

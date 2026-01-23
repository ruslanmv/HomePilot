import React from "react";

type Status = "draft" | "in_review" | "approved" | "archived";

const STATUS_CONFIG: Record<Status, { label: string; className: string }> = {
  draft: {
    label: "Draft",
    className: "border-gray-500/50 bg-gray-500/10",
  },
  in_review: {
    label: "In Review",
    className: "border-blue-500/50 bg-blue-500/10 text-blue-600 dark:text-blue-400",
  },
  approved: {
    label: "Approved",
    className: "border-green-500/50 bg-green-500/10 text-green-600 dark:text-green-400",
  },
  archived: {
    label: "Archived",
    className: "border-gray-500/50 bg-gray-500/10 opacity-60",
  },
};

export function StatusBadge({ status }: { status: Status }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.draft;

  return (
    <span className={`text-xs px-2 py-1 rounded-full border ${config.className}`}>
      {config.label}
    </span>
  );
}

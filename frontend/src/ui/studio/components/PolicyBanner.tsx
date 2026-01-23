import React from "react";

type Props = {
  contentRating: "sfw" | "mature";
  restrictions?: string[];
  onDismiss?: () => void;
};

/**
 * Banner showing policy status and restrictions.
 * Shows warning when Mature content is enabled.
 */
export function PolicyBanner({ contentRating, restrictions = [], onDismiss }: Props) {
  if (contentRating !== "mature") {
    return null;
  }

  return (
    <div className="mx-4 my-2 p-3 border rounded bg-yellow-500/10 border-yellow-500/30">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold text-sm text-yellow-600 dark:text-yellow-400">
            ⚠️ Mature content enabled
          </div>
          <div className="text-xs opacity-80 mt-1">
            This project may generate sensitive imagery. Use only for permitted
            artistic/educational contexts. Exports may have restrictions.
          </div>
          {restrictions.length > 0 && (
            <ul className="text-xs opacity-70 mt-2 list-disc list-inside">
              {restrictions.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
        </div>
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="text-xs opacity-50 hover:opacity-100"
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

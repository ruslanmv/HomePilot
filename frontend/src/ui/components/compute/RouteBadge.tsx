/**
 * RouteBadge — a small "ran on <device>" chip under an assistant reply.
 *
 * Makes routing legible (design acceptance #7): the user can see which device
 * served the response, and — when the primary target was offline — that it fell
 * back, and why. Deliberately quiet: it stays hidden for plain local replies so
 * it's signal, not chrome.
 *
 * Consumes the raw /chat `compute` block (snake_case; that endpoint isn't
 * routed through the camelizing compute-client).
 */
import React from "react";
import { Cpu, CornerDownRight } from "lucide-react";

export interface RouteInfo {
  target: string;
  device_id?: string | null;
  label: string;
  fell_back: boolean;
  reason?: string | null;
}

export default function RouteBadge({ compute }: { compute?: RouteInfo | null }) {
  // Hide for the common local case — only surface remote or fallback routing.
  if (!compute || (compute.target === "local" && !compute.fell_back)) return null;

  if (compute.fell_back) {
    return (
      <span
        title={compute.reason || undefined}
        className="inline-flex items-center gap-1 text-[11px] text-amber-300/90 bg-amber-500/10 border border-amber-500/20 rounded-full px-2 py-0.5"
      >
        <CornerDownRight size={11} />
        Fell back to {compute.label}
        {compute.reason ? <span className="text-amber-300/50"> · {compute.reason}</span> : null}
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-white/45 bg-white/[0.04] border border-white/10 rounded-full px-2 py-0.5">
      <Cpu size={11} />
      Ran on {compute.label}
    </span>
  );
}

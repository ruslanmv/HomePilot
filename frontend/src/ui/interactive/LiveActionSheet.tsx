/**
 * LiveActionSheet — catalog of unlockable actions during live play.
 *
 * Mirrors the "Live Action Beta v2" screenshot: a scrollable list
 * of action rows, each with a pink play affordance on the right
 * (unlocked) or a padlock + level gate chip (locked). Tapping an
 * unlocked row fires POST /play/sessions/{sid}/resolve with the
 * action_id and notifies the parent so it can append the
 * character's reply bubble + update mood just like a chat turn.
 *
 * Loading / empty / error all have dedicated renderings so the
 * player never shows a silent blank sheet.
 */

import React, { useCallback, useMemo, useState } from "react";
import { Lock, Play, Sparkles } from "lucide-react";
import type { InteractiveApi } from "./api";
import type { CatalogItemView, ResolveResult } from "./types";
import { InteractiveApiError } from "./types";
import { BottomSheet } from "./BottomSheet";
import {
  EmptyState,
  ErrorBanner,
  SkeletonRow,
  useAsyncResource,
  useToast,
} from "./ui";

export interface LiveActionSheetProps {
  open: boolean;
  onClose: () => void;
  api: InteractiveApi;
  sessionId: string;
  currentLevel: number;
  /** Called with the resolved turn after a successful action. */
  onResolved: (resolved: ResolveResult, action: CatalogItemView) => void;
}

export function LiveActionSheet({
  open, onClose, api, sessionId, currentLevel, onResolved,
}: LiveActionSheetProps) {
  const toast = useToast();
  const [firing, setFiring] = useState<string | null>(null);

  const catalog = useAsyncResource<CatalogItemView[]>(
    (signal) => (open ? api.getCatalog(sessionId, signal) : Promise.resolve([])),
    [api, sessionId, open],
  );

  const items = useMemo(
    () =>
      [...(catalog.data || [])].sort((a, b) => {
        if (a.unlocked !== b.unlocked) return a.unlocked ? -1 : 1;
        return (a.ordinal || 0) - (b.ordinal || 0);
      }),
    [catalog.data],
  );

  const fire = useCallback(
    async (action: CatalogItemView) => {
      if (!action.unlocked || firing) return;
      setFiring(action.id);
      try {
        const resolved = await api.resolveTurn(sessionId, { action_id: action.id });
        if (resolved.decision.decision !== "allow") {
          toast.toast({
            variant: "warning",
            title: "Action blocked",
            message: resolved.decision.message || resolved.decision.reason_code,
          });
        } else {
          onResolved(resolved, action);
        }
      } catch (err) {
        const e = err as InteractiveApiError;
        toast.toast({
          variant: "error",
          title: "Couldn't run that action",
          message: e.message || "Try again in a moment.",
        });
      } finally {
        setFiring(null);
      }
    },
    [api, firing, onResolved, sessionId, toast],
  );

  return (
    <BottomSheet
      open={open}
      onClose={onClose}
      title={
        <span className="inline-flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-[#3ea6ff]" aria-hidden />
          Live Action
          <span className="text-[10px] uppercase tracking-wide text-[#aaa] bg-white/10 rounded-full px-2 py-0.5">
            Beta
          </span>
        </span>
      }
      subtitle={`Level ${currentLevel} · unlock more by chatting and earning XP.`}
    >
      {catalog.error ? (
        <ErrorBanner
          title="Couldn't load the action catalog"
          message={catalog.error}
          onRetry={catalog.reload}
        />
      ) : catalog.loading && !catalog.data ? (
        <div className="flex flex-col gap-2" aria-busy="true">
          {Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} />)}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Sparkles className="w-10 h-10" aria-hidden />}
          title="No actions yet"
          description="The author hasn't added any actions to this project's catalog."
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((action) => (
            <li key={action.id}>
              <ActionRow
                action={action}
                firing={firing === action.id}
                onFire={() => fire(action)}
              />
            </li>
          ))}
        </ul>
      )}
    </BottomSheet>
  );
}

function ActionRow({
  action, firing, onFire,
}: {
  action: CatalogItemView;
  firing: boolean;
  onFire: () => void;
}) {
  const unlocked = action.unlocked;
  return (
    <button
      type="button"
      onClick={onFire}
      disabled={!unlocked || firing}
      aria-label={
        unlocked
          ? `Play action: ${action.label}`
          : `Locked: ${action.label}. Requires level ${action.required_level}.`
      }
      className={[
        "w-full text-left bg-[#121212] border rounded-xl px-4 py-3",
        "flex items-center gap-3",
        "transition-colors focus:outline-none",
        unlocked
          ? "border-[#3f3f3f] hover:bg-[#1f1f1f] hover:border-[#555] focus-visible:ring-2 focus-visible:ring-[#3ea6ff]"
          : "border-[#2a2a2a] opacity-70 cursor-not-allowed",
      ].join(" ")}
    >
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-[#f1f1f1] truncate">{action.label}</div>
        <div className="text-[11px] text-[#777] mt-0.5 flex gap-3">
          {action.intent_code && <span>intent: {action.intent_code}</span>}
          {action.xp_award > 0 && <span>+{action.xp_award} XP</span>}
          {action.cooldown_sec > 0 && <span>{action.cooldown_sec}s cooldown</span>}
        </div>
      </div>
      {unlocked ? (
        <span
          className={[
            "inline-flex items-center justify-center w-9 h-9 rounded-full shrink-0",
            firing ? "bg-[#62b6ff]" : "bg-[#ec4899] hover:bg-[#f472b6]",
            "text-black",
          ].join(" ")}
          aria-hidden
        >
          <Play className="w-4 h-4 fill-current" />
        </span>
      ) : (
        <span className="inline-flex items-center gap-1.5 rounded-full bg-[#3730a3]/80 text-white text-[11px] px-3 py-1 shrink-0">
          <Lock className="w-3 h-3" aria-hidden />
          Level {action.required_level || 2}
        </span>
      )}
    </button>
  );
}

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
import { Gamepad2, Lock, Play, Sparkles, Star } from "lucide-react";
import { BottomSheet } from "./BottomSheet";
import { EmptyState, ErrorBanner, SkeletonRow, useAsyncResource, useToast, } from "./ui";
export function LiveActionSheet({ open, onClose, api, sessionId, currentLevel, onResolved, skipLevelCost, onSkipLevel, }) {
    const toast = useToast();
    const [firing, setFiring] = useState(null);
    const catalog = useAsyncResource((signal) => (open ? api.getCatalog(sessionId, signal) : Promise.resolve([])), [api, sessionId, open]);
    const items = useMemo(() => [...(catalog.data || [])].sort((a, b) => {
        if (a.unlocked !== b.unlocked)
            return a.unlocked ? -1 : 1;
        return (a.ordinal || 0) - (b.ordinal || 0);
    }), [catalog.data]);
    const fire = useCallback(async (action) => {
        if (!action.unlocked || firing)
            return;
        setFiring(action.id);
        try {
            const resolved = await api.resolveTurn(sessionId, { action_id: action.id });
            if (resolved.decision.decision !== "allow") {
                toast.toast({
                    variant: "warning",
                    title: "Action blocked",
                    message: resolved.decision.message || resolved.decision.reason_code,
                });
            }
            else {
                onResolved(resolved, action);
            }
        }
        catch (err) {
            const e = err;
            toast.toast({
                variant: "error",
                title: "Couldn't run that action",
                message: e.message || "Try again in a moment.",
            });
        }
        finally {
            setFiring(null);
        }
    }, [api, firing, onResolved, sessionId, toast]);
    return (<BottomSheet open={open} onClose={onClose} title={<span className="inline-flex items-center gap-2">
          <Gamepad2 className="w-4 h-4 text-[#3ea6ff]" aria-hidden/>
          Live Action
          <span className="text-[10px] uppercase tracking-wide text-[#aaa] bg-white/10 rounded-full px-2 py-0.5">
            Beta v2
          </span>
        </span>} subtitle={`Level ${currentLevel} · unlock more by chatting and earning XP.`}>
      {typeof skipLevelCost === "number" && skipLevelCost > 0 && onSkipLevel && (<SkipLevelCard currentLevel={currentLevel} cost={skipLevelCost} onSkip={onSkipLevel}/>)}
      {catalog.error ? (<ErrorBanner title="Couldn't load the action catalog" message={catalog.error} onRetry={catalog.reload}/>) : catalog.loading && !catalog.data ? (<div className="flex flex-col gap-2" aria-busy="true">
          {Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i}/>)}
        </div>) : items.length === 0 ? (<EmptyState icon={<Sparkles className="w-10 h-10" aria-hidden/>} title="No actions yet" description="The author hasn't added any actions to this project's catalog."/>) : (<ul className="flex flex-col gap-2">
          {items.map((action) => (<li key={action.id}>
              <ActionRow action={action} firing={firing === action.id} onFire={() => fire(action)}/>
            </li>))}
        </ul>)}
    </BottomSheet>);
}
function ActionRow({ action, firing, onFire, }) {
    const unlocked = action.unlocked;
    return (<button type="button" onClick={onFire} disabled={!unlocked || firing} aria-label={unlocked
            ? `Play action: ${action.label}`
            : `Locked: ${action.label}. Requires level ${action.required_level}.`} className={[
            "w-full text-left bg-[#121212] border rounded-xl px-4 py-3",
            "flex items-center gap-3",
            "transition-colors focus:outline-none",
            unlocked
                ? "border-[#3f3f3f] hover:bg-[#1f1f1f] hover:border-[#555] focus-visible:ring-2 focus-visible:ring-[#3ea6ff]"
                : "border-[#2a2a2a] opacity-70 cursor-not-allowed",
        ].join(" ")}>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-[#f1f1f1] truncate">{action.label}</div>
        <div className="text-[11px] text-[#777] mt-0.5 flex gap-3">
          {action.intent_code && <span>intent: {action.intent_code}</span>}
          {action.xp_award > 0 && <span>+{action.xp_award} XP</span>}
          {action.cooldown_sec > 0 && <span>{action.cooldown_sec}s cooldown</span>}
        </div>
      </div>
      {unlocked ? (<span className={[
                "inline-flex items-center justify-center w-9 h-9 rounded-full shrink-0",
                firing ? "bg-[#62b6ff]" : "bg-[#ec4899] hover:bg-[#f472b6]",
                "text-black",
            ].join(" ")} aria-hidden>
          <Play className="w-4 h-4 fill-current"/>
        </span>) : (
        // Locked pill — bright indigo to match the candy.ai
        // reference screenshot; prior `/80` opacity looked washed
        // out against the dark row background.
        <span className="inline-flex items-center gap-1.5 rounded-full bg-[#4f46e5] text-white text-[11px] px-3 py-1 shrink-0 font-medium">
          <Lock className="w-3 h-3" aria-hidden/>
          Level {action.required_level || 2}
        </span>)}
    </button>);
}
function SkipLevelCard({ currentLevel, cost, onSkip, }) {
    // Summary card pinned above the action list. Mirrors the
    // candy.ai screenshot: large level badge on the left, blue
    // outlined pill on the right showing the skip cost. Tapping
    // the pill asks the host to consume the cost.
    const nextLevel = currentLevel + 1;
    return (<div className="mb-3 rounded-xl bg-[#121212] border border-[#3f3f3f] px-4 py-3 flex items-center justify-between gap-3">
      <div className="flex items-center gap-3 min-w-0">
        <span className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-black border border-[#4f46e5]/70 text-sm font-semibold text-[#f1f1f1] shrink-0">
          {currentLevel}
        </span>
        <div className="text-sm font-medium text-[#f1f1f1]">
          Level {currentLevel}
        </div>
      </div>
      <button type="button" onClick={onSkip} aria-label={`Skip to level ${nextLevel} for ${cost} coins`} className={[
            "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium",
            "border border-[#6366f1] text-white bg-transparent hover:bg-[#6366f1]/10",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#6366f1] focus-visible:ring-offset-2 focus-visible:ring-offset-black",
            "transition-colors",
        ].join(" ")}>
        Skip to Level {nextLevel}
        <Star className="w-3.5 h-3.5 fill-yellow-400 text-yellow-400" aria-hidden/>
        <span className="tabular-nums">{cost}</span>
      </button>
    </div>);
}

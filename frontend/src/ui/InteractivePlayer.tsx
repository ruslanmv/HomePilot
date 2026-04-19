/**
 * InteractivePlayer — full-bleed live-play surface.
 *
 * Mirrors the candy.ai-style layout from the screenshots:
 *
 *   ┌──────────────────────────────────────────┐
 *   │ VideoStage  (scene video, or idle)       │
 *   │                                          │
 *   │ ┌TopBar─────────────────────────────┐    │
 *   │ │ ◀ avatar · name · lvl · 🔊 ⋯ ✕    │    │
 *   │ └────────────────────────────────────┘    │
 *   │                                          │
 *   │        ┌ChatOverlay (last N turns)┐      │
 *   │        │ viewer: Hi                │      │
 *   │        │ char:   Hey trouble…      │      │
 *   │        └───────────────────────────┘      │
 *   │                                          │
 *   │ ┌Input──────────────────────── ▶ ┐       │
 *   │ │ Ask Anything…                  │       │
 *   │ └─────────────────────────────────┘       │
 *   └──────────────────────────────────────────┘
 *
 * The video stage stays full-bleed behind chat — when the player
 * mounts we render a placeholder backdrop with the experience
 * gradient; as scene jobs complete via /pending, the most recent
 * ``status === 'ready'`` job becomes the current scene. Phase-1
 * asset ids are stubs so we show a small debug label; phase-2
 * replaces the placeholder with a <video> element sourced from
 * the real Animate asset URL.
 *
 * Mutations are additive-only: the component never touches the
 * editor DB state or the authoring routes. Every write goes
 * through POST /play/.../chat which the backend already proved
 * in PLAY-4 keeps the policy gate in front of the render job.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft, Eye, EyeOff, MoreHorizontal, Send,
  Volume2, VolumeX, Workflow, X,
} from "lucide-react";
import { createInteractiveApi, type InteractiveApi } from "./interactive/api";
import type {
  ChatResult, Experience, SceneJobView,
} from "./interactive/types";
import { InteractiveApiError } from "./interactive/types";
import {
  ErrorBanner, PrimaryButton, SecondaryButton, StatusBadge,
  ToastProvider, useAsyncResource, useToast,
} from "./interactive/ui";

const POLL_INTERVAL_MS = 1500;
const MAX_VISIBLE_TURNS = 6;

type ChatRole = "user" | "assistant" | "system";

interface ChatBubble {
  id: string;
  role: ChatRole;
  text: string;
  ts: number;
  intent?: string;
  blocked?: boolean;
  blockedReason?: string;
}

export interface InteractivePlayerProps {
  backendUrl: string;
  apiKey?: string;
  projectId: string;
  onExit: () => void;
}

export default function InteractivePlayer(props: InteractivePlayerProps) {
  return (
    <ToastProvider>
      <InteractivePlayerBody {...props} />
    </ToastProvider>
  );
}

function InteractivePlayerBody({
  backendUrl, apiKey, projectId, onExit,
}: InteractivePlayerProps) {
  const api = useMemo(() => createInteractiveApi(backendUrl, apiKey), [backendUrl, apiKey]);
  const toast = useToast();

  // ── Session bootstrap ───────────────────────────────────────
  const exp = useAsyncResource<Experience>(
    (signal) => api.getExperience(projectId, signal),
    [api, projectId],
  );
  const session = useAsyncResource<{ id: string }>(
    async () => {
      const body = await api.createExperience as unknown; // just to satisfy TS unused
      void body;
      // Start a new anonymous session dedicated to this player mount.
      // Sessions are cheap; the editor + live-play are intentionally
      // decoupled so the player can run without stepping on editor
      // state like current_node_id for an authoring preview.
      const resp = await fetch(
        `${backendUrl.replace(/\/+$/, "")}/v1/interactive/play/sessions`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(apiKey ? { "x-api-key": apiKey } : {}),
          },
          body: JSON.stringify({
            experience_id: projectId,
            viewer_ref: `player_${Date.now()}`,
          }),
        },
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const body2 = await resp.json();
      return { id: String(body2?.session?.id || "") };
    },
    [api, backendUrl, apiKey, projectId],
  );

  const sessionId = session.data?.id || "";

  // ── Player state ────────────────────────────────────────────
  const [bubbles, setBubbles] = useState<ChatBubble[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [mood, setMood] = useState("neutral");
  const [affinity, setAffinity] = useState(0.5);
  const [muted, setMuted] = useState(true);
  const [hideChat, setHideChat] = useState(false);
  const [currentScene, setCurrentScene] = useState<SceneJobView | null>(null);
  const [pendingScene, setPendingScene] = useState<SceneJobView | null>(null);
  const [cursor, setCursor] = useState<string>("");

  // Refs for state read by the polling effect without re-binding.
  const cursorRef = useRef<string>("");
  useEffect(() => { cursorRef.current = cursor; }, [cursor]);

  // ── Polling loop ────────────────────────────────────────────
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    let timer: number | undefined;

    async function tick() {
      if (cancelled) return;
      try {
        const res = await api.pending(sessionId, { since_id: cursorRef.current || undefined });
        if (cancelled) return;
        if (res.items.length > 0) {
          // Find the newest ready job; promote it to current scene.
          const latestReady = [...res.items].reverse().find((j) => j.status === "ready");
          if (latestReady) setCurrentScene(latestReady);
          // Any still-rendering job lives in pendingScene so the UI
          // can show a subtle "generating…" indicator without
          // blocking input.
          const stillPending = res.items.find(
            (j) => j.status === "pending" || j.status === "rendering",
          );
          setPendingScene(stillPending || null);
          setCursor(res.cursor || cursorRef.current);
        }
      } catch {
        // Swallow transient polling errors; next tick retries.
      } finally {
        if (!cancelled) timer = window.setTimeout(tick, POLL_INTERVAL_MS);
      }
    }
    timer = window.setTimeout(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [api, sessionId]);

  // ── Send handler ────────────────────────────────────────────
  const onSend = useCallback(async () => {
    const text = input.trim();
    if (!text || !sessionId || sending) return;
    setSending(true);
    const optimisticId = `u_${Date.now()}`;
    setBubbles((prev) => [
      ...prev,
      { id: optimisticId, role: "user", text, ts: Date.now() },
    ]);
    setInput("");

    try {
      const result: ChatResult = await api.chat(sessionId, { text });
      if (result.status === "blocked") {
        setBubbles((prev) => [
          ...prev,
          {
            id: `sys_${Date.now()}`,
            role: "system",
            text: policyMessage(result.decision.reason_code, result.decision.message),
            ts: Date.now(),
            blocked: true,
            blockedReason: result.decision.reason_code,
          },
        ]);
        toast.toast({
          variant: "warning",
          title: "That message was blocked by policy",
          message: result.decision.reason_code || "Try rephrasing.",
        });
        return;
      }
      if (result.reply_text) {
        setBubbles((prev) => [
          ...prev,
          {
            id: `a_${Date.now()}`,
            role: "assistant",
            text: result.reply_text,
            ts: Date.now(),
            intent: result.intent_code,
          },
        ]);
      }
      if (typeof result.mood === "string" && result.mood) setMood(result.mood);
      if (typeof result.affinity_score === "number") setAffinity(result.affinity_score);
      // Phase-1 render_now lands the job as already-ready, but we
      // keep the pending marker for the gap in phase-2. When
      // status is 'ready' immediately we update the current scene
      // without waiting for the next poll tick.
      if (result.video_asset_id && result.video_job_status === "ready") {
        setCurrentScene({
          id: result.video_job_id,
          session_id: sessionId,
          turn_id: result.character_turn_id || "",
          status: "ready",
          job_id: "",
          asset_id: result.video_asset_id,
          prompt: result.scene_prompt || "",
          duration_sec: result.duration_sec || 5,
          error: "",
          created_at: "",
          updated_at: "",
        });
      }
    } catch (err) {
      const e = err as InteractiveApiError;
      toast.toast({
        variant: "error",
        title: "Message failed",
        message: e.message || "Try again.",
      });
    } finally {
      setSending(false);
    }
  }, [api, input, sending, sessionId, toast]);

  // ── Keyboard: Enter submits, Shift+Enter newline ────────────
  const onInputKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        onSend();
      }
    },
    [onSend],
  );

  // ── Derived ──────────────────────────────────────────────────
  const visibleBubbles = useMemo(
    () => bubbles.slice(-MAX_VISIBLE_TURNS),
    [bubbles],
  );

  // ── Render ───────────────────────────────────────────────────
  if (exp.error || session.error) {
    return (
      <div className="min-h-full bg-[#0f0f0f] text-[#f1f1f1] p-6">
        <SecondaryButton
          onClick={onExit}
          size="sm"
          icon={<ArrowLeft className="w-3.5 h-3.5" aria-hidden />}
        >
          Back
        </SecondaryButton>
        <div className="mt-6 max-w-xl mx-auto">
          <ErrorBanner
            title="Couldn't start the live session"
            message={(exp.error || session.error) || "Unknown error"}
            onRetry={() => {
              exp.reload();
              session.reload();
            }}
          />
        </div>
      </div>
    );
  }

  if (exp.loading || session.loading || !exp.data || !sessionId) {
    return (
      <div className="min-h-full bg-[#0f0f0f] text-[#f1f1f1] flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Workflow className="w-10 h-10 text-[#3ea6ff] animate-pulse" aria-hidden />
          <div className="text-sm text-[#aaa]">Warming up the stage…</div>
        </div>
      </div>
    );
  }

  const experience = exp.data;
  const level = Math.max(1, Math.round(affinity * 5) + 1);

  return (
    <div className="relative min-h-screen bg-black text-[#f1f1f1] overflow-hidden select-none">
      <VideoStage scene={currentScene} mood={mood} />

      <TopBar
        title={experience.title || "Interactive"}
        subtitle={moodDescriptor(mood, affinity)}
        level={level}
        muted={muted}
        onToggleMute={() => setMuted((m) => !m)}
        hideChat={hideChat}
        onToggleHideChat={() => setHideChat((h) => !h)}
        onExit={onExit}
      />

      {pendingScene && (
        <GeneratingHint prompt={pendingScene.prompt} />
      )}

      {!hideChat && (
        <ChatOverlay bubbles={visibleBubbles} />
      )}

      {!hideChat && (
        <ChatInput
          value={input}
          onChange={setInput}
          onKeyDown={onInputKeyDown}
          onSend={onSend}
          sending={sending}
        />
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Subcomponents
// ────────────────────────────────────────────────────────────────

function VideoStage({ scene, mood }: { scene: SceneJobView | null; mood: string }) {
  // Phase-1: scene.asset_id is a stub (ixa_stub_*); no real file
  // to play. Render a mood-tinted backdrop + a translucent label
  // so authors can verify the scene landed. Phase-2 swaps this
  // for a looping <video src={resolveAssetUrl(asset_id)} /> once
  // the Animate pipeline writes real files.
  const tint = moodTint(mood);
  return (
    <div
      className="absolute inset-0 -z-10"
      style={{
        background: `radial-gradient(1200px 800px at 50% 40%, ${tint.mid} 0%, #0a0a0a 70%, #000 100%)`,
      }}
      aria-hidden
    >
      {scene && scene.status === "ready" && (
        <div className="absolute bottom-28 left-1/2 -translate-x-1/2 text-[10px] uppercase tracking-widest text-white/40 backdrop-blur-sm bg-black/30 rounded px-2 py-1">
          scene · {scene.id.slice(-6)} · {scene.duration_sec}s
        </div>
      )}
    </div>
  );
}

function TopBar({
  title, subtitle, level, muted, onToggleMute,
  hideChat, onToggleHideChat, onExit,
}: {
  title: string;
  subtitle: string;
  level: number;
  muted: boolean;
  onToggleMute: () => void;
  hideChat: boolean;
  onToggleHideChat: () => void;
  onExit: () => void;
}) {
  return (
    <div className="absolute top-0 inset-x-0 z-20 px-4 py-3 flex items-center justify-between gap-3 bg-gradient-to-b from-black/70 to-transparent">
      <div className="flex items-center gap-2.5 min-w-0">
        <button
          type="button"
          onClick={onExit}
          aria-label="Back to projects"
          className="w-9 h-9 rounded-full bg-white/10 hover:bg-white/15 flex items-center justify-center transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]"
        >
          <ArrowLeft className="w-4 h-4" aria-hidden />
        </button>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold truncate max-w-[200px]">{title}</span>
            <LevelPill level={level} />
          </div>
          <div className="text-[11px] text-white/60 truncate">{subtitle}</div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <RoundIconBtn onClick={onToggleMute} label={muted ? "Unmute" : "Mute"}>
          {muted ? <VolumeX className="w-4 h-4" aria-hidden /> : <Volume2 className="w-4 h-4" aria-hidden />}
        </RoundIconBtn>
        <RoundIconBtn onClick={onToggleHideChat} label={hideChat ? "Show chat" : "Hide chat"}>
          {hideChat ? <EyeOff className="w-4 h-4" aria-hidden /> : <Eye className="w-4 h-4" aria-hidden />}
        </RoundIconBtn>
        <RoundIconBtn onClick={() => {}} label="More options">
          <MoreHorizontal className="w-4 h-4" aria-hidden />
        </RoundIconBtn>
        <RoundIconBtn onClick={onExit} label="Close">
          <X className="w-4 h-4" aria-hidden />
        </RoundIconBtn>
      </div>
    </div>
  );
}

function RoundIconBtn({
  children, onClick, label,
}: { children: React.ReactNode; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="w-9 h-9 rounded-full bg-white/10 hover:bg-white/15 flex items-center justify-center transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]"
    >
      {children}
    </button>
  );
}

function LevelPill({ level }: { level: number }) {
  return (
    <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-black/60 border border-white/20 text-[11px] font-semibold">
      {level}
    </span>
  );
}

function ChatOverlay({ bubbles }: { bubbles: ChatBubble[] }) {
  if (bubbles.length === 0) return null;
  return (
    <div className="absolute inset-x-0 bottom-24 z-10 px-4 pb-4 pointer-events-none">
      <ol className="max-w-xl mx-auto flex flex-col gap-2">
        {bubbles.map((b) => (
          <li key={b.id} className={b.role === "user" ? "self-start" : "self-start w-full"}>
            <ChatBubbleView bubble={b} />
          </li>
        ))}
      </ol>
    </div>
  );
}

function ChatBubbleView({ bubble }: { bubble: ChatBubble }) {
  if (bubble.role === "user") {
    return (
      <div className="inline-block rounded-2xl px-3 py-1.5 bg-[#3ea6ff]/80 text-black text-sm font-medium shadow-md">
        {bubble.text}
      </div>
    );
  }
  if (bubble.role === "system") {
    return (
      <div className="inline-block rounded-2xl px-3 py-2 bg-amber-500/15 border border-amber-400/40 text-amber-200 text-xs">
        {bubble.text}
      </div>
    );
  }
  return (
    <div className="rounded-2xl px-4 py-3 bg-black/55 backdrop-blur-sm text-white text-sm leading-snug shadow-xl border border-white/10 max-w-[540px]">
      {bubble.text}
    </div>
  );
}

function GeneratingHint({ prompt }: { prompt: string }) {
  return (
    <div
      role="status"
      className="absolute top-20 left-1/2 -translate-x-1/2 z-10 bg-black/60 backdrop-blur-sm border border-white/15 rounded-full px-3 py-1.5 text-[11px] text-white/80 flex items-center gap-2 pointer-events-none"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-[#3ea6ff] animate-pulse" aria-hidden />
      Generating next scene · <span className="max-w-[160px] truncate">{prompt}</span>
    </div>
  );
}

function ChatInput({
  value, onChange, onKeyDown, onSend, sending,
}: {
  value: string;
  onChange: (v: string) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onSend: () => void;
  sending: boolean;
}) {
  return (
    <div className="absolute inset-x-0 bottom-0 z-20 px-4 pb-5 pt-3 bg-gradient-to-t from-black/85 to-transparent">
      <div className="max-w-xl mx-auto flex gap-2">
        <div className="relative flex-1">
          <textarea
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask anything…"
            rows={1}
            className="w-full bg-black/60 backdrop-blur-sm border border-white/15 rounded-full px-5 py-3 text-sm outline-none focus:border-[#3ea6ff] resize-none leading-tight"
            disabled={sending}
          />
        </div>
        <PrimaryButton
          onClick={onSend}
          disabled={!value.trim()}
          loading={sending}
          aria-label="Send message"
          icon={!sending ? <Send className="w-4 h-4" aria-hidden /> : undefined}
        >
          Send
        </PrimaryButton>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Helpers
// ────────────────────────────────────────────────────────────────

function moodDescriptor(mood: string, affinity: number): string {
  const tier =
    affinity >= 0.75 ? "close"
    : affinity >= 0.5 ? "warm"
    : affinity >= 0.2 ? "friendly"
    : "stranger";
  return `${tier} · mood ${mood}`;
}

function moodTint(mood: string): { mid: string } {
  const map: Record<string, string> = {
    neutral: "#162030",
    shy:     "#2a1c30",
    flirty:  "#3a1626",
    playful: "#1e2a3a",
    warm:    "#3a2a1a",
    cold:    "#12202f",
  };
  return { mid: map[mood] || map.neutral };
}

function policyMessage(code: string, fallback: string): string {
  if (code === "policy_blocked") {
    return "That message can't be sent — try rephrasing.";
  }
  if (code === "consent_required") {
    return "Mature content requires a consent check first.";
  }
  if (code === "region_blocked") {
    return "This experience isn't available in your region.";
  }
  return fallback || "Message blocked by policy.";
}

// Re-export the badge so callers can use a consistent status chip.
export { StatusBadge };

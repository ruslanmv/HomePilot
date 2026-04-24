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
 *
 * Production fixes in this version:
 *  - Persona idle portrait is centered and never face-cropped.
 *  - Portrait-oriented scene stills are auto-detected and rendered
 *    with a contain/center foreground plus blurred cinematic fill.
 *  - Avatar chip uses object-top so faces crop more naturally.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Eye,
  EyeOff,
  Gamepad2,
  MoreHorizontal,
  Send,
  Volume2,
  VolumeX,
  Workflow,
  X,
} from "lucide-react";
import { createInteractiveApi, type InteractiveApi } from "./interactive/api";
import { LiveActionSheet } from "./interactive/LiveActionSheet";
import { PersonaLiveRuntimeShell } from "./interactive/personaLiveRuntime";
import { StandardPlayer } from "./interactive/StandardPlayer";
import { XPRewardsSheet } from "./interactive/XPRewardsSheet";
import type {
  AudienceProfile,
  CatalogItemView,
  ChatResult,
  Experience,
  InteractionType,
  ResolveResult,
  SceneJobView,
} from "./interactive/types";
import { InteractiveApiError, resolveInteractionType } from "./interactive/types";
import {
  ErrorBanner,
  PrimaryButton,
  SecondaryButton,
  StatusBadge,
  ToastProvider,
  useAsyncResource,
  useToast,
} from "./interactive/ui";

// Adaptive polling. The previous fixed 1.5s interval flooded backend
// access logs with GET /v1/interactive/play/sessions/*/pending entries
// (~40/min per open session). We now poll fast only while there's
// actual work in flight and back off when the server has nothing new.
const POLL_INTERVAL_ACTIVE_MS = 1500;  // something pending → stay responsive
const POLL_INTERVAL_IDLE_MS   = 5000;  // nothing pending → cool off
const POLL_INTERVAL_MAX_MS    = 15000; // ceiling for error backoff
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
  backendUrl,
  apiKey,
  projectId,
  onExit,
}: InteractivePlayerProps) {
  const api = useMemo(() => createInteractiveApi(backendUrl, apiKey), [backendUrl, apiKey]);
  const toast = useToast();

  // ── Session bootstrap ───────────────────────────────────────
  const exp = useAsyncResource<Experience>(
    (signal) => api.getExperience(projectId, signal),
    [api, projectId],
  );
  const session = useAsyncResource<{
    id: string;
    initial_scene?: {
      node_id: string;
      asset_id: string;
      asset_url: string;
      media_kind: "image" | "video" | "unknown" | string;
      duration_sec: number;
      title: string;
      status?: "pending" | "rendering" | "ready" | "failed" | string;
    } | null;
    opening_turn?: { reply_text: string; scene_prompt: string; character_turn_id: string };
    persona_portrait_url?: string;
    render_media_type?: "image" | "video";
  }>(
    async () => {
      const sess = await api.startSession({
        experience_id: projectId,
        viewer_ref: `player_${Date.now()}`,
      });
      return {
        id: sess.id,
        initial_scene: sess.initial_scene || null,
        opening_turn: sess.opening_turn,
        persona_portrait_url: sess.persona_portrait_url,
        render_media_type: sess.render_media_type,
      };
    },
    [api, projectId],
  );

  const sessionId = session.data?.id || "";
  const openingTurn = session.data?.opening_turn;
  const personaPortraitUrl = session.data?.persona_portrait_url || "";

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
  const [liveActionOpen, setLiveActionOpen] = useState(false);
  const [xpRewardsOpen, setXpRewardsOpen] = useState(false);
  const [pollFailures, setPollFailures] = useState(0);

  useEffect(() => {
    const initial = session.data?.initial_scene;
    if (!initial) return;
    // Debug: dump what the backend delivered so the next "Play shows
    // empty" bug tells us whether the miss is in the payload
    // (backend) or in how we mount it (frontend). Remove once the
    // player's bootstrap is proven stable end-to-end.
    // eslint-disable-next-line no-console
    console.log("[InteractivePlayer] initial_scene from backend:", {
      node_id: initial.node_id,
      status: initial.status,
      asset_id: initial.asset_id,
      asset_url: initial.asset_url,
      media_kind: initial.media_kind,
      duration_sec: initial.duration_sec,
    });
    setCurrentScene({
      id: `initial_${initial.node_id || "scene"}`,
      session_id: sessionId,
      turn_id: "",
      status: (String(initial.status || "").toLowerCase() as SceneJobView["status"]) || "pending",
      job_id: "",
      asset_id: initial.asset_id || "",
      media_kind: initial.media_kind || "unknown",
      asset_url: initial.asset_url || "",
      prompt: initial.title || "",
      duration_sec: Number(initial.duration_sec || 5),
      error: "",
      created_at: "",
      updated_at: "",
    });
  }, [session.data?.initial_scene, sessionId]);

  const cursorRef = useRef<string>("");
  useEffect(() => {
    cursorRef.current = cursor;
  }, [cursor]);

  const seededOpeningForRef = useRef<string>("");
  useEffect(() => {
    if (!sessionId || !openingTurn?.reply_text) return;
    if (seededOpeningForRef.current === sessionId) return;
    seededOpeningForRef.current = sessionId;
    setBubbles((prev) => [
      ...prev,
      {
        id: `a_open_${sessionId}`,
        role: "assistant",
        text: openingTurn.reply_text,
        ts: Date.now(),
      },
    ]);
  }, [sessionId, openingTurn]);

  // ── Polling loop ────────────────────────────────────────────
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    let timer: number | undefined;
    let failures = 0;

    async function tick() {
      if (cancelled) return;
      // Default delay for next tick — reassigned based on activity/errors.
      let nextDelay = POLL_INTERVAL_IDLE_MS;
      try {
        const res = await api.pending(sessionId, { since_id: cursorRef.current || undefined });
        if (cancelled) return;
        const hasItems = res.items.length > 0;
        let stillPending: typeof res.items[number] | null = null;
        if (hasItems) {
          const latestReady = [...res.items].reverse().find((j) => j.status === "ready");
          if (latestReady) setCurrentScene(latestReady);
          stillPending = res.items.find(
            (j) => j.status === "pending" || j.status === "rendering",
          ) || null;
          setPendingScene(stillPending);
          setCursor(res.cursor || cursorRef.current);
        }
        // Poll fast while there's work in flight; otherwise cool off.
        nextDelay = stillPending ? POLL_INTERVAL_ACTIVE_MS : POLL_INTERVAL_IDLE_MS;
        failures = 0;
        setPollFailures(0);
      } catch {
        failures = Math.min(failures + 1, 6);
        setPollFailures((n) => Math.min(n + 1, 99));
        // Exponential backoff on transient failures: 1.5s → 3s → 6s → 12s → cap.
        nextDelay = Math.min(POLL_INTERVAL_ACTIVE_MS * 2 ** failures, POLL_INTERVAL_MAX_MS);
      } finally {
        if (!cancelled) timer = window.setTimeout(tick, nextDelay);
      }
    }

    timer = window.setTimeout(tick, POLL_INTERVAL_ACTIVE_MS);
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

      if (result.video_asset_id && result.video_job_status === "ready") {
        const resolvedUrl = result.video_asset_url || "";
        setCurrentScene({
          id: result.video_job_id,
          session_id: sessionId,
          turn_id: result.character_turn_id || "",
          status: "ready",
          job_id: "",
          asset_id: result.video_asset_id,
          media_kind: String(result.video_media_kind || inferMediaKind(resolvedUrl)),
          asset_url: resolvedUrl,
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

  // ── Action catalog resolution (Live Action sheet) ───────────
  const onActionResolved = useCallback(
    (resolved: ResolveResult, action: CatalogItemView) => {
      const ts = Date.now();
      setBubbles((prev) => [
        ...prev,
        { id: `a_user_${ts}`, role: "user", text: `▶ ${action.label}`, ts },
        {
          id: `a_ast_${ts}`,
          role: "assistant",
          text: resolved.level_description?.display
            ? `${action.label} · ${resolved.level_description.display}`
            : action.label,
          ts,
          intent: resolved.intent_code,
        },
      ]);
      if (typeof resolved.mood === "string" && resolved.mood) setMood(resolved.mood);
      if (typeof resolved.affinity_score === "number") setAffinity(resolved.affinity_score);
      setLiveActionOpen(false);
    },
    [],
  );

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
  const visibleBubbles = useMemo(() => bubbles.slice(-MAX_VISIBLE_TURNS), [bubbles]);

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
  const audience = (experience.audience_profile || {}) as AudienceProfile;
  const interactionType: InteractionType = resolveInteractionType(experience);
  const displayName =
    (interactionType === "persona_live_play" && audience.persona_label) ||
    experience.title ||
    "Interactive";
  const avatarUrl = audience.persona_avatar_url || "";

  if (interactionType === "standard_project") {
    return (
      <div className="relative min-h-screen bg-black text-[#f1f1f1] overflow-hidden select-none">
        <StandardPlayer
          api={api}
          sessionId={sessionId}
          scene={currentScene}
          onExit={onExit}
          onResolved={onActionResolved}
        />
      </div>
    );
  }

  if ((experience.project_type || "") === "persona_live") {
    return (
      <div className="relative min-h-screen bg-black text-[#f1f1f1] overflow-hidden select-none">
        <PersonaLiveRuntimeShell api={api} experience={experience} onExit={onExit} />
      </div>
    );
  }

  const effectiveAvatarUrl = avatarUrl || personaPortraitUrl;

  return (
    <div className="relative min-h-screen bg-black text-[#f1f1f1] overflow-hidden select-none">
      <VideoStage
        scene={currentScene}
        mood={mood}
        muted={muted}
        portraitUrl={personaPortraitUrl}
      />

      <TopBar
        title={displayName}
        subtitle={moodDescriptor(mood, affinity)}
        avatarUrl={effectiveAvatarUrl}
        level={level}
        onOpenXp={() => setXpRewardsOpen(true)}
        muted={muted}
        onToggleMute={() => setMuted((m) => !m)}
        hideChat={hideChat}
        onToggleHideChat={() => setHideChat((h) => !h)}
        onExit={onExit}
      />

      {pendingScene && <GeneratingHint prompt={pendingScene.prompt} />}

      {pollFailures >= 3 && <ReconnectChip />}

      {!hideChat && <ChatOverlay bubbles={visibleBubbles} />}

      {!hideChat && (
        <>
          <LiveActionFab onClick={() => setLiveActionOpen(true)} />
          <ChatInput
            value={input}
            onChange={setInput}
            onKeyDown={onInputKeyDown}
            onSend={onSend}
            sending={sending}
          />
        </>
      )}

      <LiveActionSheet
        open={liveActionOpen}
        onClose={() => setLiveActionOpen(false)}
        api={api}
        sessionId={sessionId}
        currentLevel={level}
        onResolved={onActionResolved}
      />

      <XPRewardsSheet
        open={xpRewardsOpen}
        onClose={() => setXpRewardsOpen(false)}
        api={api}
        sessionId={sessionId}
      />
    </div>
  );
}

function inferMediaKind(url: string): "image" | "video" | "unknown" {
  const u = (url || "").toLowerCase();
  if ([".mp4", ".webm", ".mov", ".mkv", ".m4v"].some((ext) => u.endsWith(ext) || u.includes(`${ext}?`))) {
    return "video";
  }
  if ([".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"].some((ext) => u.endsWith(ext) || u.includes(`${ext}?`))) {
    return "image";
  }
  return "unknown";
}

function LiveActionFab({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Open Live Action catalog"
      className={[
        "absolute bottom-[92px] right-4 z-20",
        "w-12 h-12 rounded-full",
        "bg-gradient-to-br from-[#6366f1] to-[#3ea6ff]",
        "shadow-lg flex items-center justify-center",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] focus-visible:ring-offset-2 focus-visible:ring-offset-black",
        "hover:scale-105 active:scale-95 transition-transform",
      ].join(" ")}
    >
      <Gamepad2 className="w-5 h-5 text-white" aria-hidden />
    </button>
  );
}

// ────────────────────────────────────────────────────────────────
// Subcomponents
// ────────────────────────────────────────────────────────────────

function VideoStage({
  scene,
  mood,
  muted,
  portraitUrl,
}: {
  scene: SceneJobView | null;
  mood: string;
  muted: boolean;
  portraitUrl?: string;
}) {
  const tint = moodTint(mood);
  const url = scene?.status === "ready" ? (scene.asset_url || "") : "";
  const isVideo = url && /\.(mp4|webm|mov|mkv|m4v)(\?|$)/i.test(url);
  const isImage = url && !isVideo;

  if (isVideo) {
    return (
      <div
        key={scene!.id}
        className="absolute inset-0 -z-10 bg-black animate-scene-fade"
        aria-hidden
      >
        <video
          src={url}
          autoPlay
          loop
          muted={muted}
          playsInline
          preload="auto"
          className="absolute inset-0 w-full h-full object-cover"
          // Face-safe focal point: persona faces sit in the upper third of the
          // frame. Default ``object-position: center`` chops them when the
          // container is wider than the asset's aspect. 50% 18% keeps the
          // face visible without changing full-bleed composition.
          style={{ objectPosition: '50% 18%' }}
        />
        <SceneStamp scene={scene!} />
      </div>
    );
  }

  if (isImage) {
    return (
      <div
        key={scene!.id}
        className="absolute inset-0 -z-10 bg-black animate-scene-fade"
        aria-hidden
      >
        <ResponsiveStageImage
          src={url}
          alt=""
          forcePortraitContain={false}
          overlay={
            <div
              className="absolute inset-0 pointer-events-none"
              style={{
                background:
                  "linear-gradient(to bottom, rgba(0,0,0,0.10), rgba(0,0,0,0.22))",
              }}
            />
          }
        />
        <SceneStamp scene={scene!} />
      </div>
    );
  }

  if (portraitUrl) {
    return (
      <div
        key={`portrait-${portraitUrl}`}
        className="absolute inset-0 -z-10 bg-black animate-scene-fade"
        aria-hidden
      >
        <ResponsiveStageImage
          src={portraitUrl}
          alt=""
          forcePortraitContain
          overlay={
            <>
              <div
                className="absolute inset-0 pointer-events-none animate-mood-breathe"
                style={{
                  background: `radial-gradient(1200px 800px at 50% 40%, ${tint.mid}22 0%, transparent 55%, #0006 100%)`,
                }}
              />
              <div
                className="absolute inset-0 pointer-events-none"
                style={{
                  background:
                    "linear-gradient(to bottom, rgba(0,0,0,0.14), rgba(0,0,0,0.26))",
                }}
              />
            </>
          }
        />
      </div>
    );
  }

  return (
    <div
      key={scene?.id || `idle-${mood}`}
      className="absolute inset-0 -z-10 animate-scene-fade animate-mood-breathe"
      style={{
        background: `radial-gradient(1200px 800px at 50% 40%, ${tint.mid} 0%, #0a0a0a 70%, #000 100%)`,
      }}
      aria-hidden
    >
      {scene && scene.status === "ready" && <SceneStamp scene={scene} />}
    </div>
  );
}

/**
 * ResponsiveStageImage
 *
 * Production behavior:
 * - Landscape images stay full-bleed with object-cover.
 * - Portrait images switch to a blurred background fill plus a
 *   centered object-contain foreground, so faces are not cropped.
 * - `forcePortraitContain` is used for Persona Live idle portraits
 *   where we always want a safe, centered composition.
 */
function ResponsiveStageImage({
  src,
  alt,
  forcePortraitContain = false,
  overlay,
}: {
  src: string;
  alt: string;
  forcePortraitContain?: boolean;
  overlay?: React.ReactNode;
}) {
  const [broken, setBroken] = useState(false);
  const [isPortrait, setIsPortrait] = useState(forcePortraitContain);

  if (!src || broken) return null;

  const useContain = forcePortraitContain || isPortrait;

  return (
    <div className="absolute inset-0 overflow-hidden bg-black">
      {/* cinematic fill */}
      <img
        src={src}
        alt=""
        className="absolute inset-0 w-full h-full object-cover scale-105 blur-xl opacity-35"
        onError={() => setBroken(true)}
        onLoad={(e) => {
          const img = e.currentTarget;
          if (!forcePortraitContain && img.naturalHeight > img.naturalWidth * 1.05) {
            setIsPortrait(true);
          }
        }}
      />

      {/* main visible asset */}
      <img
        src={src}
        alt={alt}
        className={[
          "absolute inset-0 w-full h-full transition-[transform,opacity] duration-300 ease-out",
          // Landscape cover: bias the focal point toward the upper third so
          // persona faces aren't cropped by default center-cover. Portrait
          // path uses object-contain so the whole image is always visible.
          useContain ? "object-contain object-center" : "object-cover",
        ].join(" ")}
        style={!useContain ? { objectPosition: '50% 18%' } : undefined}
        onError={() => setBroken(true)}
        onLoad={(e) => {
          const img = e.currentTarget;
          if (!forcePortraitContain && img.naturalHeight > img.naturalWidth * 1.05) {
            setIsPortrait(true);
          }
        }}
      />

      {overlay}
    </div>
  );
}

function SceneStamp({ scene }: { scene: SceneJobView }) {
  return (
    <div className="absolute bottom-28 left-1/2 -translate-x-1/2 text-[10px] uppercase tracking-widest text-white/40 backdrop-blur-sm bg-black/30 rounded px-2 py-1 pointer-events-none">
      scene · {scene.id.slice(-6)} · {scene.duration_sec}s
    </div>
  );
}

function ReconnectChip() {
  return (
    <div
      role="status"
      className="absolute top-20 right-4 z-10 bg-amber-500/90 text-black rounded-full px-3 py-1.5 text-[11px] font-medium flex items-center gap-2 shadow-lg"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-black animate-live-dot" aria-hidden />
      Reconnecting…
    </div>
  );
}

function TopBar({
  title,
  subtitle,
  avatarUrl,
  level,
  onOpenXp,
  muted,
  onToggleMute,
  hideChat,
  onToggleHideChat,
  onExit,
}: {
  title: string;
  subtitle: string;
  avatarUrl?: string;
  level: number;
  onOpenXp: () => void;
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
        <Avatar url={avatarUrl} label={title} />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold truncate max-w-[200px]">{title}</span>
            <button
              type="button"
              onClick={onOpenXp}
              aria-label={`View XP rewards — level ${level}`}
              className="focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] rounded-full"
            >
              <LevelPill level={level} />
            </button>
          </div>
          <div className="text-[11px] text-white/60 truncate">{subtitle}</div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <RoundIconBtn onClick={onToggleMute} label={muted ? "Unmute" : "Mute"}>
          {muted ? (
            <VolumeX className="w-4 h-4" aria-hidden />
          ) : (
            <Volume2 className="w-4 h-4" aria-hidden />
          )}
        </RoundIconBtn>
        <RoundIconBtn onClick={onToggleHideChat} label={hideChat ? "Show chat" : "Hide chat"}>
          {hideChat ? (
            <EyeOff className="w-4 h-4" aria-hidden />
          ) : (
            <Eye className="w-4 h-4" aria-hidden />
          )}
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
  children,
  onClick,
  label,
}: {
  children: React.ReactNode;
  onClick: () => void;
  label: string;
}) {
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

function Avatar({ url, label }: { url?: string; label: string }) {
  const initial = (label || "?").trim().charAt(0).toUpperCase();

  return (
    <div
      className="w-8 h-8 rounded-full overflow-hidden border border-white/20 bg-gradient-to-br from-[#6366f1]/70 to-[#3ea6ff]/70 shrink-0 flex items-center justify-center text-[11px] font-semibold text-white"
      aria-hidden
    >
      {url ? (
        <img
          src={url}
          alt=""
          className="w-full h-full object-cover object-top"
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = "none";
          }}
        />
      ) : (
        <span>{initial}</span>
      )}
    </div>
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
  value,
  onChange,
  onKeyDown,
  onSend,
  sending,
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
    affinity >= 0.75
      ? "close"
      : affinity >= 0.5
        ? "warm"
        : affinity >= 0.2
          ? "friendly"
          : "stranger";
  return `${tier} · mood ${mood}`;
}

function moodTint(mood: string): { mid: string } {
  const map: Record<string, string> = {
    neutral: "#162030",
    shy: "#2a1c30",
    flirty: "#3a1626",
    playful: "#1e2a3a",
    warm: "#3a2a1a",
    cold: "#12202f",
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

export { StatusBadge };
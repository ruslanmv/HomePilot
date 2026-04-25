/**
 * StandardPlayer — YouTube-style surface for `interaction_type =
 * "standard_project"` experiences.
 *
 * Layout (matching the user's reference screenshots):
 *
 *   ┌──────────────────────────────────────────────────────┐
 *   │ ⟲              <video playback>                →     │  ← top row
 *   │                                                       │
 *   │            ⟲10     ▶/⏸     10⟳                       │  ← center
 *   │                                                       │
 *   │  ─────[seek bar]──────────────────       [thumbs]    │
 *   │  ▶  🔊  00:23 / 01:30                        ⛶       │  ← bottom
 *   └──────────────────────────────────────────────────────┘
 *
 * When the current scene finishes (or the user taps Next), a
 * centered "What to do next?" modal appears with image-card choices
 * sourced from the action catalog. Tapping one calls resolveTurn
 * — same endpoint the persona Live Action sheet uses, so no
 * backend changes.
 *
 * Everything is additive: ``InteractivePlayer`` routes to this
 * component only when ``resolveInteractionType(exp)`` returns
 * "standard_project". Persona mode is unaffected.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft, ArrowRight, Maximize, Minimize,
  Pause, Play, RotateCcw, SkipBack, SkipForward,
  Volume2, VolumeX,
} from "lucide-react";
import type { InteractiveApi } from "./api";
import type { CatalogItemView, ResolveResult, SceneJobView } from "./types";
import { InteractiveApiError } from "./types";
import { useAsyncResource, useToast } from "./ui";
import {
  fadeKey,
  useFadeOnSceneChange,
  useScenePreload,
} from "./scenePreload";


const SKIP_SECONDS = 10;


export interface StandardPlayerProps {
  api: InteractiveApi;
  sessionId: string;
  /** Experience id (a.k.a. project id). Threaded in so the player
   *  can preload upcoming scene assets via ``useScenePreload`` —
   *  optional only because some legacy callers may not have it. */
  experienceId?: string;
  scene: SceneJobView | null;
  onExit: () => void;
  onResolved: (resolved: ResolveResult, action: CatalogItemView) => void;
}


export function StandardPlayer({
  api, sessionId, experienceId, scene, onExit, onResolved,
}: StandardPlayerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const toast = useToast();

  const [playing, setPlaying] = useState(true);
  const [muted, setMuted] = useState(true);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [decisionOpen, setDecisionOpen] = useState(false);
  const [firing, setFiring] = useState<string | null>(null);
  // ``mediaError`` covers BOTH <img> and <video> failures. Was
  // ``imageError`` for images only — the <video> element used to fall
  // through to a silent black stage, which was indistinguishable from
  // a still-loading clip and produced the "Play screen is empty"
  // reports we kept getting. Renamed + a forced retry-counter that
  // appends a cache-bust ?t=N to the src so the browser actually
  // re-fetches when the user clicks Retry.
  const [mediaError, setMediaError] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);

  const baseUrl = (() => {
    if (!scene?.asset_url) return "";
    // Trust the URL whenever it's present. The previous gate
    // (status === "ready") was redundant — _build_initial_scene
    // only stamps asset_url after asset registry resolution
    // succeeds — and it caused a black stage for any backend that
    // omitted the explicit "ready" stamp (legacy sessions, the
    // pending-then-resolve race, single-tap retries, etc).
    return scene.asset_url;
  })();
  const url = retryNonce > 0 && baseUrl
    ? `${baseUrl}${baseUrl.includes("?") ? "&" : "?"}_t=${retryNonce}`
    : baseUrl;

  // ── Preload + transitions (cinematic engine spec §5–7) ─────────
  // Walk the experience graph from the current scene and preload
  // every reachable next-scene's image so navigation feels instant
  // — the spec called out "Avoid lag when switching scenes" as
  // critical for premium UX. depth=2 covers the immediate Continue
  // hop plus the first step of every choice branch.
  //
  // ``scene.id`` is shaped ``initial_<node_id>`` for the entry
  // payload and ``<node_id>`` for subsequent turns; strip the
  // prefix so the graph lookup matches the actual node row.
  const currentNodeId = String(scene?.id || "")
    .replace(/^initial_/, "")
    .trim();
  useScenePreload(api, experienceId || "", currentNodeId);

  // Cross-fade the media wrapper on scene change. The fade key
  // changes when EITHER the scene id OR the asset url changes,
  // so a regenerate-scene also fades the new image in.
  const fade = useFadeOnSceneChange(fadeKey(scene?.id, url));
  const mediaHint = String(scene?.media_kind || "").toLowerCase();
  // Media-kind detection is the union of three signals — any one is
  // enough. The boundary character set covers ``.png?…``, ``.png&…``
  // (ComfyUI /view URLs), ``.png#…``, and end-of-string. The previous
  // ``(\?|$)`` form matched only the first and last, so a URL like
  //   http://comfy:8188/view?filename=foo.png&subfolder=&type=output
  // was misclassified as "unknown" and the Standard player rendered
  // a black stage with the "Scene not available yet." placeholder.
  const _IMG_RE = /\.(png|jpe?g|webp|gif|avif)([?&#]|$)/i;
  const _VID_RE = /\.(mp4|webm|mov|mkv|m4v)([?&#]|$)/i;
  const isImage =
    mediaHint === "image" || (!!url && _IMG_RE.test(url));
  const isVideo =
    mediaHint === "video" || (!!url && _VID_RE.test(url));
  const defaultDuration = Math.max(1, Number(scene?.duration_sec || 5));

  // Load catalog as the pool of decision cards. For standard
  // projects it's the author's branch choices (mapped onto the
  // shared catalog table by the backend); for a graph without
  // decisions it will be empty and the modal just won't open.
  const catalog = useAsyncResource<CatalogItemView[]>(
    (signal) => api.getCatalog(sessionId, signal),
    [api, sessionId],
  );

  // Top-2 unlocked options for the modal — a standard branching
  // video usually only has two-to-four choices per decision.
  const choices = (catalog.data || [])
    .filter((c) => c.unlocked)
    .sort((a, b) => (a.ordinal || 0) - (b.ordinal || 0));

  useEffect(() => {
    setDecisionOpen(false);
    setMediaError(false);
    setRetryNonce(0);
    setCurrentTime(0);
    setDuration(defaultDuration);
    setPlaying(true);
  }, [scene?.id, defaultDuration]);

  // ── Video element wiring ─────────────────────────────────────
  useEffect(() => {
    if (!isVideo) return undefined;
    const v = videoRef.current;
    if (!v) return;
    const onTime = () => setCurrentTime(v.currentTime || 0);
    const onDur = () => setDuration(v.duration || 0);
    const onEnd = () => {
      setPlaying(false);
      // Open the decision modal at end-of-scene so authors know the
      // beat has landed. If there are no choices, stay quiet — a
      // linear scene just pauses on its last frame.
      if (choices.length > 0) setDecisionOpen(true);
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("loadedmetadata", onDur);
    v.addEventListener("ended", onEnd);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    return () => {
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("loadedmetadata", onDur);
      v.removeEventListener("ended", onEnd);
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
    };
  }, [choices.length, isVideo]);

  // Timed still-image playback: treat images like fixed-duration
  // scenes. When the timer completes, open the decision modal.
  useEffect(() => {
    if (!isImage || !url || mediaError) return undefined;
    const maxSec = Math.max(1, Number(scene?.duration_sec || 5));
    setDuration(maxSec);
    if (!playing || decisionOpen) return undefined;
    const t = window.setInterval(() => {
      setCurrentTime((prev) => {
        const next = Math.min(maxSec, prev + 0.1);
        if (next >= maxSec) {
          setPlaying(false);
          if (choices.length > 0) setDecisionOpen(true);
        }
        return next;
      });
    }, 100);
    return () => window.clearInterval(t);
  }, [choices.length, decisionOpen, mediaError, isImage, playing, scene?.duration_sec, url]);

  // Keep the <video> element's mute state in sync with the control.
  useEffect(() => {
    if (videoRef.current) videoRef.current.muted = muted;
  }, [muted]);

  // Track fullscreen state from the browser so our icon stays honest.
  useEffect(() => {
    const onChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  // ── Controls ────────────────────────────────────────────────
  const togglePlay = useCallback(() => {
    if (isImage) {
      setPlaying((p) => !p);
      return;
    }
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) v.play().catch(() => { /* autoplay policy */ });
    else v.pause();
  }, [isImage]);

  const skipBy = useCallback((delta: number) => {
    if (isImage) {
      setCurrentTime((prev) => {
        const target = Math.max(0, Math.min(duration, prev + delta));
        if (target >= duration && choices.length > 0) setDecisionOpen(true);
        return target;
      });
      return;
    }
    const v = videoRef.current;
    if (!v) return;
    const target = Math.max(
      0,
      Math.min((v.duration || 0) - 0.1, (v.currentTime || 0) + delta),
    );
    v.currentTime = target;
  }, [choices.length, duration, isImage]);

  const restart = useCallback(() => {
    if (isImage) {
      setCurrentTime(0);
      setPlaying(true);
      setDecisionOpen(false);
      return;
    }
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = 0;
    v.play().catch(() => { /* autoplay policy */ });
    setDecisionOpen(false);
  }, [isImage]);

  const toggleFullscreen = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    if (!document.fullscreenElement) {
      el.requestFullscreen?.().catch(() => undefined);
    } else {
      document.exitFullscreen?.().catch(() => undefined);
    }
  }, []);

  const onSeek = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (isImage) {
      const pctVal = Number(e.target.value);
      setCurrentTime(duration * (pctVal / 100));
      return;
    }
    const v = videoRef.current;
    if (!v) return;
    const pct = Number(e.target.value);
    v.currentTime = (v.duration || 0) * (pct / 100);
  }, [duration, isImage]);

  const fireChoice = useCallback(async (action: CatalogItemView) => {
    if (!action.unlocked || firing) return;
    setFiring(action.id);
    try {
      const resolved = await api.resolveTurn(sessionId, { action_id: action.id });
      if (resolved.decision.decision !== "allow") {
        toast.toast({
          variant: "warning",
          title: "Choice blocked",
          message: resolved.decision.message || resolved.decision.reason_code,
        });
      } else {
        onResolved(resolved, action);
        setDecisionOpen(false);
      }
    } catch (err) {
      const e = err as InteractiveApiError;
      toast.toast({
        variant: "error",
        title: "Couldn't pick that path",
        message: e.message || "Try again.",
      });
    } finally {
      setFiring(null);
    }
  }, [api, firing, onResolved, sessionId, toast]);

  const pct = duration > 0 ? Math.min(100, (currentTime / duration) * 100) : 0;

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full bg-black text-white flex items-center justify-center"
    >
      {/*
       * Fade-transition wrapper. Wraps every media element + the
       * error / pending fallback so the whole stage cross-fades
       * on scene change. CSS transition matches the JS-side
       * duration via ``transitionMs`` to keep them in sync.
       */}
      <div
        className="absolute inset-0 flex items-center justify-center"
        style={{
          opacity: fade.opacity,
          transition: `opacity ${fade.transitionMs}ms ease-out`,
          willChange: "opacity",
        }}
      >
      {mediaError ? (
        // Shared error UI for both <img> and <video> failures. The
        // Retry button bumps ``retryNonce`` which appends a
        // cache-busting ``?_t=N`` query string to the asset URL —
        // resetting just the ``mediaError`` flag wasn't enough
        // because the browser would happily re-use the cached 404.
        <div className="w-full h-full flex flex-col items-center justify-center text-white/75 text-sm gap-3 px-6 text-center">
          <div className="text-base font-medium">
            {isVideo ? "Couldn't play this video scene." : "Couldn't load this scene's image."}
          </div>
          <div className="text-xs text-white/50 max-w-md">
            The asset host may be unreachable. If you're running
            ComfyUI locally, make sure it's still running. If you
            switched between machines, your operator may need to
            enable ``INTERACTIVE_PROXY_ASSETS`` so the backend
            streams assets through itself.
          </div>
          <button
            type="button"
            onClick={() => {
              setMediaError(false);
              setRetryNonce((n) => n + 1);
              setCurrentTime(0);
            }}
            className="px-3 py-1.5 rounded-md border border-white/30 bg-black/30 hover:bg-black/50"
          >
            Retry
          </button>
        </div>
      ) : isVideo ? (
        <video
          ref={videoRef}
          src={url}
          autoPlay
          muted={muted}
          playsInline
          className="w-full h-full object-contain"
          onClick={togglePlay}
          onError={() => setMediaError(true)}
        />
      ) : isImage ? (
        <img
          src={url}
          className="w-full h-full object-contain animate-[pulse_12s_ease-in-out_infinite]"
          alt={scene?.prompt || "Scene"}
          onError={() => setMediaError(true)}
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-white/60 text-sm">
          {scene?.status === "rendering" || scene?.status === "pending"
            ? "Generating scene…"
            : "Scene not available yet."}
        </div>
      )}
      </div>{/* end fade wrapper */}

      {/*
       * Visual-novel caption overlay. Reads scene.subtitles first
       * (author override) then scene.narration (planner) — falls
       * silent if neither is present. Lives below the controls and
       * above the seek bar so a viewer's eyes don't have to leave
       * the bottom of the frame to read along. The "Standard" player
       * is YouTube-scope entertainment + visual-novel reading; the
       * caption is what makes it feel like a manga/visual novel.
       *
       * Visibility persists in localStorage so the user's preference
       * (captions on / off) survives reloads.
       */}
      <CaptionOverlay scene={scene} />

      <TopBar onRestart={restart} onNext={() => setDecisionOpen(true)} onExit={onExit} />
      <CenterControls
        playing={playing}
        onPlay={togglePlay}
        onBack={() => skipBy(-SKIP_SECONDS)}
        onForward={() => skipBy(SKIP_SECONDS)}
      />
      <BottomBar
        playing={playing}
        muted={muted}
        onTogglePlay={togglePlay}
        onToggleMute={() => setMuted((m) => !m)}
        pct={pct}
        currentTime={currentTime}
        duration={duration}
        onSeek={onSeek}
        isFullscreen={isFullscreen}
        onToggleFullscreen={toggleFullscreen}
      />

      {decisionOpen && choices.length > 0 && (
        <DecisionModal
          choices={choices}
          firing={firing}
          onPick={fireChoice}
          onClose={() => setDecisionOpen(false)}
        />
      )}
    </div>
  );
}


// ── Controls ────────────────────────────────────────────────────

function TopBar({
  onRestart, onNext, onExit,
}: {
  onRestart: () => void;
  onNext: () => void;
  onExit: () => void;
}) {
  return (
    <div className="absolute top-0 inset-x-0 z-20 px-4 py-3 flex items-center justify-between pointer-events-none">
      <div className="flex items-center gap-2 pointer-events-auto">
        <IconBtn onClick={onExit} label="Back to projects">
          <ArrowLeft className="w-4 h-4" />
        </IconBtn>
        <IconBtn onClick={onRestart} label="Restart scene">
          <RotateCcw className="w-4 h-4" />
        </IconBtn>
      </div>
      <div className="pointer-events-auto">
        <IconBtn onClick={onNext} label="Go to next decision">
          <ArrowRight className="w-4 h-4" />
        </IconBtn>
      </div>
    </div>
  );
}


function CenterControls({
  playing, onPlay, onBack, onForward,
}: {
  playing: boolean;
  onPlay: () => void;
  onBack: () => void;
  onForward: () => void;
}) {
  // Center playback + scrubbing overlay. Mirrors the reference
  // screenshot's three-icon cluster: back-10, play/pause, fwd-10.
  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center gap-8 pointer-events-none">
      <button
        type="button"
        onClick={onBack}
        aria-label={`Back ${SKIP_SECONDS} seconds`}
        className="pointer-events-auto w-14 h-14 rounded-full bg-black/40 hover:bg-black/60 border border-white/30 flex items-center justify-center backdrop-blur-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
      >
        <span className="relative inline-flex items-center justify-center">
          <SkipBack className="w-6 h-6" />
          <span className="absolute text-[10px] font-bold pointer-events-none">10</span>
        </span>
      </button>
      <button
        type="button"
        onClick={onPlay}
        aria-label={playing ? "Pause" : "Play"}
        className="pointer-events-auto w-20 h-20 rounded-full bg-black/40 hover:bg-black/60 border border-white/30 flex items-center justify-center backdrop-blur-sm transition-transform hover:scale-105 focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
      >
        {playing
          ? <Pause className="w-9 h-9 fill-current" />
          : <Play className="w-9 h-9 fill-current ml-1" />}
      </button>
      <button
        type="button"
        onClick={onForward}
        aria-label={`Forward ${SKIP_SECONDS} seconds`}
        className="pointer-events-auto w-14 h-14 rounded-full bg-black/40 hover:bg-black/60 border border-white/30 flex items-center justify-center backdrop-blur-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
      >
        <span className="relative inline-flex items-center justify-center">
          <SkipForward className="w-6 h-6" />
          <span className="absolute text-[10px] font-bold pointer-events-none">10</span>
        </span>
      </button>
    </div>
  );
}


function BottomBar({
  playing, muted, onTogglePlay, onToggleMute, pct, currentTime, duration,
  onSeek, isFullscreen, onToggleFullscreen,
}: {
  playing: boolean;
  muted: boolean;
  onTogglePlay: () => void;
  onToggleMute: () => void;
  pct: number;
  currentTime: number;
  duration: number;
  onSeek: (e: React.ChangeEvent<HTMLInputElement>) => void;
  isFullscreen: boolean;
  onToggleFullscreen: () => void;
}) {
  return (
    <div className="absolute bottom-0 inset-x-0 z-20 px-4 py-3 bg-gradient-to-t from-black/80 to-transparent">
      <input
        type="range"
        min={0}
        max={100}
        step={0.1}
        value={pct}
        onChange={onSeek}
        aria-label="Seek"
        className="w-full h-1.5 accent-[#ec4899] cursor-pointer"
        style={{
          background: `linear-gradient(to right, #ec4899 ${pct}%, rgba(255,255,255,0.25) ${pct}%)`,
        }}
      />
      <div className="mt-2 flex items-center gap-3 text-[12px] text-white/85">
        <IconBtn onClick={onTogglePlay} label={playing ? "Pause" : "Play"}>
          {playing
            ? <Pause className="w-4 h-4 fill-current" />
            : <Play className="w-4 h-4 fill-current" />}
        </IconBtn>
        <IconBtn onClick={onToggleMute} label={muted ? "Unmute" : "Mute"}>
          {muted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
        </IconBtn>
        <span className="tabular-nums">
          {fmtTime(currentTime)} / {fmtTime(duration)}
        </span>
        <span className="flex-1" />
        <IconBtn onClick={onToggleFullscreen} label={isFullscreen ? "Exit fullscreen" : "Fullscreen"}>
          {isFullscreen ? <Minimize className="w-4 h-4" /> : <Maximize className="w-4 h-4" />}
        </IconBtn>
      </div>
    </div>
  );
}


function IconBtn({
  children, onClick, label,
}: { children: React.ReactNode; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="w-9 h-9 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
    >
      {children}
    </button>
  );
}


// ── Decision modal ─────────────────────────────────────────────

function DecisionModal({
  choices, firing, onPick, onClose,
}: {
  choices: CatalogItemView[];
  firing: string | null;
  onPick: (c: CatalogItemView) => void;
  onClose: () => void;
}) {
  // Centered card with "WHAT TO DO NEXT?" header + 2–4 image-card
  // choices. The backdrop dims + blurs the video so the decision
  // point has the visual weight the reference screenshot shows.
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="What to do next?"
      className="absolute inset-0 z-30 flex items-center justify-center p-6 bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl rounded-3xl bg-black/60 border border-white/15 backdrop-blur-md px-6 py-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="text-[11px] uppercase tracking-[0.18em] text-white/60 text-center mb-4">
          What to do next?
        </div>
        <div
          className={[
            "grid gap-4",
            choices.length >= 3 ? "sm:grid-cols-3 grid-cols-2" : "grid-cols-2",
          ].join(" ")}
        >
          {choices.slice(0, 4).map((c) => (
            <ChoiceCard
              key={c.id}
              choice={c}
              firing={firing === c.id}
              onClick={() => onPick(c)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}


// ── Caption overlay (visual-novel surface) ────────────────────────
//
// Visual-novel / manga-style caption that sits ABOVE the bottom
// controls and renders the scene's narration. Reads scene.subtitles
// first (author override) then scene.narration (planner). Hidden
// when both are empty.
//
// The toggle (eye icon) lives at the right edge so the user can hide
// captions for a clean view; the choice persists in localStorage
// (key: ``homepilot_captions``) so a user who hides them once stays
// hidden across reloads.

const CAPTIONS_STORAGE_KEY = "homepilot_captions";

function _readCaptionsEnabled(): boolean {
  try {
    const raw = globalThis.localStorage?.getItem(CAPTIONS_STORAGE_KEY);
    // Default ON — captions are the visual-novel feature; only honor
    // an explicit "off" preference written by the toggle below.
    return raw !== "0";
  } catch {
    return true;
  }
}

function _writeCaptionsEnabled(next: boolean): void {
  try {
    globalThis.localStorage?.setItem(CAPTIONS_STORAGE_KEY, next ? "1" : "0");
  } catch {
    /* private browsing / quota — non-fatal */
  }
}

function CaptionOverlay({ scene }: { scene: SceneJobView | null }) {
  const [enabled, setEnabled] = useState<boolean>(() => _readCaptionsEnabled());

  // Re-read from localStorage on mount so a different tab that
  // toggled the preference takes effect here on next render.
  useEffect(() => {
    const sync = () => setEnabled(_readCaptionsEnabled());
    globalThis.addEventListener?.("storage", sync);
    return () => globalThis.removeEventListener?.("storage", sync);
  }, []);

  const text = String(scene?.subtitles || scene?.narration || "").trim();
  // Hide when nothing to show OR the user toggled captions off. The
  // toggle button stays mounted (small dot at the right edge) so the
  // user can re-enable without leaving the player.
  const hasText = text.length > 0;

  const onToggle = useCallback(() => {
    setEnabled((prev) => {
      const next = !prev;
      _writeCaptionsEnabled(next);
      return next;
    });
  }, []);

  return (
    <div
      className={[
        "absolute left-0 right-0 z-10 px-4 pointer-events-none",
        // Sit ABOVE the bottom bar. BottomBar lives at bottom-0 with
        // ~3rem of internal padding + the seek slider — 5.5rem keeps
        // the caption clear of the slider and safely above controls.
        "bottom-[5.5rem] sm:bottom-[6rem]",
      ].join(" ")}
      aria-hidden={!hasText || !enabled}
    >
      <div className="max-w-3xl mx-auto flex items-end gap-2">
        {hasText && enabled ? (
          <div
            className={[
              "pointer-events-auto flex-1 min-w-0",
              "rounded-xl border border-white/15 bg-black/65 backdrop-blur-md",
              "px-4 py-3 text-white/95 text-[15px] leading-relaxed",
              "shadow-[0_8px_32px_-12px_rgba(0,0,0,0.6)]",
              // Visual-novel tone: serif feels storybook-y; system
              // font-stack falls through cleanly when serif unavailable.
              "font-serif",
            ].join(" ")}
            role="region"
            aria-label="Scene caption"
            aria-live="polite"
          >
            {text}
          </div>
        ) : (
          <span className="flex-1" aria-hidden />
        )}
        <button
          type="button"
          onClick={onToggle}
          aria-label={enabled ? "Hide captions" : "Show captions"}
          aria-pressed={enabled}
          className={[
            "pointer-events-auto shrink-0",
            "w-9 h-9 rounded-full bg-black/55 hover:bg-black/75",
            "border border-white/20 text-white/85",
            "flex items-center justify-center backdrop-blur-sm",
            "transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-white",
          ].join(" ")}
        >
          {/* Use a tiny inline glyph so we don't pull another lucide
              import this far down the file. ``Aa`` reads as captions
              universally (YouTube convention). */}
          <span
            className={[
              "text-[12px] font-semibold leading-none tracking-tight",
              enabled ? "" : "line-through opacity-60",
            ].join(" ")}
          >
            Aa
          </span>
        </button>
      </div>
    </div>
  );
}


function ChoiceCard({
  choice, firing, onClick,
}: {
  choice: CatalogItemView;
  firing: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={firing}
      aria-label={`Pick: ${choice.label}`}
      className={[
        "group relative aspect-[4/3] rounded-2xl overflow-hidden",
        "bg-gradient-to-br from-[#1f1f1f] to-[#0a0a0a]",
        "border border-white/15 hover:border-[#3ea6ff]/80",
        "transition-all duration-150 hover:scale-[1.02]",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]",
        firing ? "opacity-60 cursor-wait" : "",
      ].join(" ")}
    >
      <div
        className="absolute inset-0 opacity-80 group-hover:opacity-100 transition-opacity"
        style={{
          // Placeholder tint based on intent code → derive a
          // deterministic hue so authors can eyeball "this choice
          // goes to path X" even before real thumbnails exist.
          background: hueFromString(choice.intent_code || choice.label),
        }}
        aria-hidden
      />
      <div className="absolute inset-x-0 bottom-0 p-3 bg-gradient-to-t from-black/85 to-transparent">
        <div className="text-sm font-semibold text-white truncate">
          {choice.label}
        </div>
        {choice.intent_code && (
          <div className="text-[10px] text-white/60 truncate mt-0.5">
            {choice.intent_code}
          </div>
        )}
      </div>
    </button>
  );
}


// ── Helpers ─────────────────────────────────────────────────────

function fmtTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}


function hueFromString(s: string): string {
  // FNV-1a-ish hash → hue. Deterministic + cheap; no dependency.
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = (h * 0x01000193) >>> 0;
  }
  const hue = h % 360;
  return `linear-gradient(135deg, hsl(${hue}, 55%, 35%), hsl(${(hue + 40) % 360}, 45%, 20%))`;
}

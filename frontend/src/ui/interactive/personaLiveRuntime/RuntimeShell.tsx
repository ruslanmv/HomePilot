import React, { useEffect, useMemo, useState } from "react";
import {
  Eye,
  EyeOff,
  Loader2,
  Lock,
  Menu,
  Send,
  Volume2,
  VolumeX,
  X,
  Zap,
} from "lucide-react";
import type { InteractiveApi } from "../api";
import type { Experience } from "../types";
// Polished chat bubbles + typewriter reveal for persona live chat.
// Pure presentation layer — no state, no API assumptions.
import { AnimatedBubble, RichDialogueText, TypingDots } from "./LiveChatPolish";
import { usePersonaSpeech } from "./usePersonaSpeech";

type RuntimeAction = {
  id: string;
  label: string;
  category?: "expression" | "pose" | "scene" | "outfit" | string;
  unlock_level?: number;
};
type VersionThumb = { id: string; thumb_url?: string; active?: boolean };

type SceneContext = {
  id: string;
  label: string;
  icon?: string;
  prompt?: string;
  category?: "indoor" | "outdoor" | "public" | "private" | string;
};

type SceneMemory = {
  current_scene: string;
  previous_scenes: string[];
  last_actions: string[];
  emotional_state: { mood: string; intensity: number };
};

type EmotionalState = {
  trust: number;
  intensity: number;
  mood: string;
};

type CharacterState = {
  emotion: "neutral" | "happy" | "playful" | "flirty" | "shy" | "guarded" | "warm";
  expression: "idle" | "smile" | "smirk" | "blush";
  camera: "full" | "medium" | "close";
  gaze: "center" | "left" | "right";
  speaking: boolean;
};

type ChatMessage = {
  // Stable id — used as the React key in ConversationOverlay. Without it,
  // the previous implementation keyed on ``${sender}-${index}-${text.slice(0,12)}``
  // and ``prev.slice(-7)`` re-indexed every surviving bubble on every new
  // turn, which made React unmount + remount each one → the slide-in /
  // typewriter animations replayed on every send, producing the "all the
  // bubbles auto-populate again" behaviour the user reported.
  id: string;
  sender: "user" | "ai";
  text: string;
  emotion?: string;
};

function _newMessageId(): string {
  // crypto.randomUUID() is available in every modern browser + jsdom; fall
  // back to a timestamp + random suffix so the unit test harness never
  // fails on environments without it.
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
  } catch {
    /* fallthrough */
  }
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

type PersonaRuntimeState = {
  persona: {
    id: string;
    name: string;
    avatarUrl: string;
    archetype: string;
    mode: "image" | "video";
  };
  session: {
    id: string;
    level: number;
    xp: number;
    xpToNext: number;
    currentVersionId: string;
  };
  currentMedia: {
    type: "image" | "video";
    url: string;
    status: "idle" | "rendering" | "ready" | "error";
  };
  dialogue: { text: string };
  sceneContext: SceneContext;
  sceneMemory: SceneMemory;
  emotionalState: EmotionalState;
  actions: { available: RuntimeAction[]; locked: RuntimeAction[] };
  versions: VersionThumb[];
};

const CAMERA_PRESETS: Record<CharacterState["camera"], { zoom: number; yOffset: number }> = {
  close: { zoom: 1.15, yOffset: 8 },
  medium: { zoom: 1.0, yOffset: 0 },
  full: { zoom: 0.9, yOffset: -8 },
};

function mapEmotionToExpression(emotion: string): CharacterState["expression"] {
  const e = String(emotion || "").toLowerCase();
  if (e.includes("play") || e.includes("flirt")) return "smirk";
  if (e.includes("warm") || e.includes("happy")) return "smile";
  if (e.includes("shy")) return "blush";
  return "idle";
}

function SceneBadge({ scene }: { scene: SceneContext }) {
  return (
    <div className="absolute top-3 left-3 px-3 py-1 bg-black/50 rounded-full text-xs border border-white/10">
      {scene.icon || "📍"} {scene.label || "Unknown scene"}
    </div>
  );
}

function ConversationOverlay({ messages, pending }: { messages: ChatMessage[]; pending?: boolean }) {
  if (!messages.length && !pending) return null;
  // Index of the most-recent AI message — that's the one we typewriter-reveal.
  // Older AI replies render in full so scrolling through history doesn't
  // re-animate every bubble.
  let lastAiIdx = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].sender === "ai") { lastAiIdx = i; break; }
  }
  return (
    <div className="space-y-2">
      {messages.map((message, index) => {
        const role: "user" | "assistant" = message.sender === "user" ? "user" : "assistant";
        // Stable id lets React keep the same DOM node across list shifts
        // (prev.slice(-7) re-indexes entries on every send). Without this
        // every bubble unmounted + remounted each turn and the slide-in
        // animation replayed on all of them — the "auto-populate again"
        // behaviour. Index is kept as a fallback only for historic dev
        // data that predates the id field.
        const key = message.id || `${message.sender}-${index}-${message.text.slice(0, 12)}`;
        // ``lastAiIdx`` is computed by the caller and used to be
        // referenced as ``isLatestAi`` to gate the typewriter
        // animation. RichDialogueText handles all AI bubbles now;
        // the index-tracking flag is intentionally dropped — kept
        // commented so future "highlight the latest line" features
        // know where the cheapest hook is.
        // const isLatestAi = role === "assistant" && index === lastAiIdx;
        void lastAiIdx;
        return (
          <AnimatedBubble key={key} role={role}>
            {/*
             * Visual-novel rendering for the AI persona's bubbles:
             * narration / action description ("Lina blushed playfully
             * and said") renders italic + muted, the quoted speech
             * ("I'm so glad you found my surprise") renders bright
             * + normal weight. Makes the "she does X, then says Y"
             * pattern read at a glance.
             *
             * User bubbles stay plain — what the player typed isn't
             * narrated. ``isLatestAi`` is preserved as a flag for
             * future "highlight latest" treatment without affecting
             * the parser today.
             */}
            {role === "assistant" ? (
              <RichDialogueText text={message.text} />
            ) : (
              <span>{message.text}</span>
            )}
          </AnimatedBubble>
        );
      })}
      {pending ? (
        <AnimatedBubble role="assistant">
          <TypingDots />
        </AnimatedBubble>
      ) : null}
    </div>
  );
}

function useSceneTransition(type: "soft" | "scene" | "hard") {
  if (type === "scene") return "duration-300 ease-out scale-[1.01] saturate-105";
  if (type === "hard") return "duration-300 ease-in opacity-95";
  return "duration-150 ease-linear";
}

export function RuntimeShell({ api, experience, onExit }: { api: InteractiveApi; experience: Experience; onExit: () => void }) {
  const personaId = String(experience.audience_profile?.persona_project_id || "");
  const [state, setState] = useState<PersonaRuntimeState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [pendingJobId, setPendingJobId] = useState("");
  const [chat, setChat] = useState("");
  const [sending, setSending] = useState(false);
  const [transitionType, setTransitionType] = useState<"soft" | "scene" | "hard">("soft");
  const [showMobileDrawer, setShowMobileDrawer] = useState(false);
  const [mobileTab, setMobileTab] = useState<"actions" | "history">("actions");
  const [overlaysHidden, setOverlaysHidden] = useState(false);
  const [muted, setMuted] = useState(true);

  // One mute button, two side-effects: hush the <video> background
  // AND silence the AI's voice. The frontend wants a single tap to
  // shut everything up — the user may want to keep watching without
  // listening (commute / shared room) and conflating the two
  // reduces UI clutter. ``toggleMute`` is the canonical handler;
  // both mobile + desktop volume buttons call it.
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [characterState, setCharacterState] = useState<CharacterState>({
    emotion: "neutral",
    expression: "idle",
    camera: "medium",
    gaze: "center",
    speaking: false,
  });

  const sessionId = state?.session.id || "";
  const transitionClass = useSceneTransition(transitionType);
  const overlayMessages = useMemo((): ChatMessage[] => {
    const recent = messages.slice(-3);
    if (recent.length > 0) return recent;
    const dialogueText = state?.dialogue.text?.trim();
    // Memoize the synthesized id on the dialogue text so the bubble
    // doesn't remount every time overlayMessages recomputes — avoids
    // the repeated slide-in animation when the user types.
    return dialogueText
      ? [{ id: `dlg-${dialogueText.length}-${dialogueText.slice(0, 24)}`, sender: "ai" as const, text: dialogueText }]
      : [];
  }, [messages, state?.dialogue.text]);

  useEffect(() => {
    let alive = true;
    async function boot() {
      if (!personaId) {
        setError("Persona not linked to this project.");
        setLoading(false);
        return;
      }
      try {
        const sess = await api.personaLiveStart({
          persona_id: personaId,
          mode: String(experience.audience_profile?.render_media_type || "image") === "video" ? "video" : "image",
        });
        const payload = await api.personaLiveSession(sess.id);
        if (!alive) return;
        setState(_mapRuntime(payload));
      } catch (e) {
        if (!alive) return;
        setError((e as Error).message || "Failed to start session");
      } finally {
        if (alive) setLoading(false);
      }
    }
    boot();
    return () => { alive = false; };
  }, [api, personaId, experience.audience_profile?.render_media_type]);

  useEffect(() => {
    if (!pendingJobId || !sessionId) return;
    const t = window.setInterval(async () => {
      try {
        const job = await api.personaLiveJob(pendingJobId);
        // Backend stamps "completed" for live-render jobs and "ready"
        // for library-hit pseudo-jobs (id prefixed lib_…). Accept both
        // — without this, a library-cached lib_xxxxx job would never
        // resolve and the "Rendering…" overlay stayed up indefinitely.
        const s = String(job.status || "").toLowerCase();
        if (s !== "completed" && s !== "ready") return;
        setPendingJobId("");
        const latest = await api.personaLiveSession(sessionId);
        setTransitionType("soft");
        setState(_mapRuntime(latest));
      } catch {
        // keep polling
      }
    }, 1200);
    return () => window.clearInterval(t);
  }, [api, pendingJobId, sessionId]);

  const xpPct = useMemo(() => {
    if (!state) return 0;
    const progressCap = Math.max(1, state.session.xpToNext + state.session.xp);
    return Math.max(0, Math.min(100, Math.round((state.session.xp / progressCap) * 100)));
  }, [state]);
  // Keep desktop/mobile stage framing stable to avoid perceived
  // "jumping" while typing/chatting. Interaction updates still
  // change emotion/expression state, but camera stays fixed.
  const cameraPreset = CAMERA_PRESETS.medium;

  // Companion voice — Web Speech API. Hook is a silent no-op when
  // the browser doesn't support synthesis, so wiring it
  // unconditionally is safe. The ``speaking`` flag from this hook
  // drives the existing portrait-animation state below so the lips
  // move while audio plays. Additive only: no backend deps, swap-
  // friendly when a server-side TTS lands later.
  const speech = usePersonaSpeech();

  // Initial sync: persona-live boots ``muted=true`` (autoplay
  // policies disallow background audio without a user gesture
  // anyway), so disable speech up front and let the user flip both
  // on with the mute button. This prevents a silent <audio> token
  // from queueing under a muted video.
  useEffect(() => {
    if (muted && speech.enabled) speech.setEnabled(false);
    // Run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleMute = React.useCallback(() => {
    setMuted((prev) => {
      const nextMuted = !prev;
      // When the user UN-mutes, turn speech ON; when MUTES, turn
      // speech OFF. Single source of truth: the mute button.
      speech.setEnabled(!nextMuted);
      return nextMuted;
    });
  }, [speech]);

  useEffect(() => {
    const text = state?.dialogue.text;
    if (!text) return;
    // Speak the latest dialogue line. usePersonaSpeech.cancel() is
    // called internally before each utterance so back-to-back
    // actions don't stack into garbled overlap.
    speech.speak(text);
    setCharacterState((prev) => ({
      ...prev,
      speaking: true,
      expression: mapEmotionToExpression(state.emotionalState.mood),
      emotion: (state.emotionalState.mood as CharacterState["emotion"]) || "neutral",
    }));
    const t = window.setTimeout(() => {
      setCharacterState((prev) => ({ ...prev, speaking: false }));
    }, 1800);
    return () => window.clearTimeout(t);
    // speech.speak intentionally excluded — the hook returns a stable
    // callback whose closure already reads the latest enabled / voice
    // / supported state via refs + setState; including it here would
    // re-fire the effect on every voiceschanged event.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state?.dialogue.text, state?.emotionalState.mood]);

  function applyCharacterTurn(opts: { userText?: string; aiText: string; emotion?: string }) {
    const userText = opts.userText?.trim() || "";
    if (userText) {
      setMessages((prev) => [...prev.slice(-7), { id: _newMessageId(), sender: "user", text: userText }]);
    }
    setMessages((prev) => [...prev.slice(-7), { id: _newMessageId(), sender: "ai", text: opts.aiText, emotion: opts.emotion }]);
    setCharacterState((prev) => ({
      ...prev,
      emotion: (opts.emotion as CharacterState["emotion"]) || prev.emotion,
      expression: mapEmotionToExpression(opts.emotion || prev.emotion),
      speaking: true,
    }));
  }

  if (loading) {
    return <div className="h-full flex items-center justify-center"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  }
  if (error || !state) {
    return (
      <div className="h-full p-6">
        <button type="button" onClick={onExit} className="text-xs text-[#aaa] hover:text-white">← Back</button>
        <p className="mt-3 text-red-400 text-sm">{error || "Unable to load runtime."}</p>
      </div>
    );
  }

  async function fireAction(actionId: string) {
    if (!sessionId || sending) return;
    setSending(true);
    setState((prev) => (prev ? { ...prev, currentMedia: { ...prev.currentMedia, status: "rendering" } } : prev));
    try {
      const res = await api.personaLiveAction(sessionId, { action_id: actionId, message: chat.trim() || undefined });
      setTransitionType((res.scene_context ? "scene" : "soft") as "soft" | "scene");
      const dialogueText = typeof res.dialogue === "string" ? res.dialogue : (res.dialogue?.text || state?.dialogue.text || "");
      applyCharacterTurn({
        userText: actionId.replaceAll("_", " "),
        aiText: dialogueText,
        emotion: ((res.emotional_state as EmotionalState | undefined)?.mood || state?.emotionalState.mood || "neutral"),
      });
      // Library-first hit: the backend's persona-asset-library fast
      // path returns ``media.status === "ready"`` with the URL of a
      // pre-rendered photo (e.g. expression_00013_.png&subfolder=avatar)
      // — there's nothing to poll. Without this short-circuit the
      // frontend used to fall through to ``setPendingJobId`` and the
      // poll loop waited for a status that never arrived, leaving the
      // "Rendering…" overlay stuck on a perfectly-cached image.
      const media = (res.media || {}) as Record<string, unknown>;
      const mediaUrl = String(media.url || "");
      const mediaStatus = String(media.status || "").toLowerCase();
      const mediaType = String(media.type || "image") === "video" ? "video" : "image";
      const libraryHit = mediaStatus === "ready" && !!mediaUrl;
      // XP / level surfaced inline in the action response so the
      // progress bar advances without waiting on the polling path.
      // Library-hit responses bypass the live-render polling that
      // previously refreshed XP via personaLiveSession() — without
      // this read, taps on a warm library left "0 / 35 XP" forever.
      const nextXp = typeof res.xp === "number" ? res.xp : null;
      const nextLevel = typeof res.level === "number" ? res.level : null;
      const nextXpToNext = typeof res.xp_to_next === "number" ? res.xp_to_next : null;
      setState((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          dialogue: { text: dialogueText },
          sceneContext: (res.scene_context as SceneContext) || prev.sceneContext,
          sceneMemory: (res.scene_memory as SceneMemory) || prev.sceneMemory,
          emotionalState: (res.emotional_state as EmotionalState) || prev.emotionalState,
          currentMedia: libraryHit
            ? { type: mediaType, url: mediaUrl, status: "ready" }
            : prev.currentMedia,
          session: {
            ...prev.session,
            xp: nextXp ?? prev.session.xp,
            level: nextLevel ?? prev.session.level,
            xpToNext: nextXpToNext ?? prev.session.xpToNext,
          },
        };
      });
      if (libraryHit || res.render_skipped) {
        setState((prev) => (prev ? { ...prev, currentMedia: { ...prev.currentMedia, status: "ready" } } : prev));
      } else {
        setPendingJobId(res.job_id || "");
      }
      setChat("");
    } catch (err) {
      // Don't leave the overlay stuck on "Rendering…" when the
      // backend fails (e.g. the recent 500 from the
      // current_version_id kwarg mismatch). Surface a brief error
      // hint and unblock the action panel so the user can retry.
      // eslint-disable-next-line no-console
      console.error("[PersonaLive] action failed:", err);
      setState((prev) => (prev ? { ...prev, currentMedia: { ...prev.currentMedia, status: "error" } } : prev));
    } finally {
      setSending(false);
    }
  }

  async function sendChat() {
    if (!chat.trim() || !sessionId || sending) return;
    const userText = chat.trim();
    // Optimistic: push the user bubble immediately and clear the input so
    // there's no "dead input" gap while we wait for the AI reply.
    setMessages((prev) => [...prev.slice(-7), { id: _newMessageId(), sender: "user", text: userText }]);
    setChat("");
    setSending(true);
    try {
      const res = await api.personaLiveChat(sessionId, userText);
      const maybeScene = (res.scene_context as SceneContext | undefined) || undefined;
      // Only push the AI bubble here — user bubble was already added above,
      // so we sidestep applyCharacterTurn's user-text push to avoid a
      // duplicate. Reapply emotion + speaking-state side effects inline.
      const aiText = String(res.dialogue?.text || "");
      const emotion = ((res.emotional_state as EmotionalState | undefined)?.mood
        || state?.emotionalState.mood
        || "neutral");
      setMessages((prev) => [...prev.slice(-7), { id: _newMessageId(), sender: "ai", text: aiText, emotion }]);
      setCharacterState((prev) => ({
        ...prev,
        emotion: emotion as CharacterState["emotion"],
        expression: mapEmotionToExpression(emotion),
        speaking: true,
      }));
      // Chat earns 2 XP per turn server-side. Read the new totals
      // out of the response so the progress bar moves while the
      // user is talking — without this, free-form conversation felt
      // unrewarded and the bar only nudged when a Live Action was
      // tapped.
      const chatNextXp = typeof res.xp === "number" ? res.xp : null;
      const chatNextLevel = typeof res.level === "number" ? res.level : null;
      const chatNextXpToNext = typeof res.xp_to_next === "number" ? res.xp_to_next : null;
      setState((prev) => {
        if (!prev) return prev;
        setTransitionType(maybeScene && maybeScene.id !== prev.sceneContext.id ? "scene" : "soft");
        return {
          ...prev,
          dialogue: res.dialogue,
          sceneContext: maybeScene || prev.sceneContext,
          sceneMemory: (res.scene_memory as SceneMemory) || prev.sceneMemory,
          emotionalState: (res.emotional_state as EmotionalState) || prev.emotionalState,
          session: {
            ...prev.session,
            xp: chatNextXp ?? prev.session.xp,
            level: chatNextLevel ?? prev.session.level,
            xpToNext: chatNextXpToNext ?? prev.session.xpToNext,
          },
        };
      });
      // Don't auto-fill the input with action suggestions anymore — the
      // suggestion is surfaced in the Live Action panel; keeping input
      // empty after Enter matches industry chat UX.
    } catch (err) {
      // Mark the last user message as errored so the UI can surface a
      // retry affordance (AnimatedBubble renders a red ring on error).
      setMessages((prev) => {
        if (!prev.length) return prev;
        const copy = [...prev];
        const last = copy[copy.length - 1];
        if (last.sender === "user") {
          copy[copy.length - 1] = { ...last, text: last.text + "  ⚠︎" };
        }
        return copy;
      });
    } finally {
      setSending(false);
    }
  }

  async function restore(versionId: string) {
    if (!sessionId) return;
    await api.personaLiveRestore(sessionId, versionId);
    const latest = await api.personaLiveSession(sessionId);
    setTransitionType("hard");
    setState(_mapRuntime(latest));
  }

  return (
    <div className="h-full min-h-0 flex flex-col bg-black">
      <div className="hidden lg:block px-4 py-2 border-b border-[#2a2a2a] text-xs text-[#aaa]">Persona Live • {state.persona.name}</div>

      {/* Mobile immersive runtime */}
      <div className="lg:hidden relative flex-1 min-h-0 overflow-hidden">
        <div className={`absolute inset-0 transition-all ${transitionClass}`} style={{ transform: `scale(${cameraPreset.zoom}) translateY(${cameraPreset.yOffset}%)` }}>
          {/*
           * ``object-cover`` fills the viewport (no letterbox bars on
           * mobile — phone players want immersive) but anchored
           * ``object-top`` so the face stays visible when the source
           * is squarer than the phone's aspect. Without ``object-top``
           * the default center-crop chopped the eyes off on tall
           * phones.
           */}
          {state.currentMedia.url ? (
            state.currentMedia.type === "video" ? (
              <video src={state.currentMedia.url} className="absolute inset-0 w-full h-full object-cover object-top" autoPlay loop muted={muted} playsInline />
            ) : (
              <img src={state.currentMedia.url} alt={state.persona.name} className="absolute inset-0 w-full h-full object-cover object-top" />
            )
          ) : (
            <div className="absolute inset-0 grid place-items-center text-[#888] text-sm">No render yet</div>
          )}
        </div>
        <div className="absolute inset-0 bg-gradient-to-b from-black/35 via-transparent to-black/60 pointer-events-none" />

        {!overlaysHidden && (
          <>
            <div className="absolute top-4 left-3 z-20">
              <div className="inline-flex items-center gap-2 px-2.5 py-1.5 rounded-full bg-black/50 border border-white/15 backdrop-blur">
                {state.persona.avatarUrl ? <img src={state.persona.avatarUrl} alt={state.persona.name} className="w-6 h-6 rounded-full object-cover" /> : <div className="w-6 h-6 rounded-full bg-[#333]" />}
                <span className="text-xs font-medium">{state.persona.name}</span>
              </div>
              <div className="mt-2">
                <SceneBadge scene={state.sceneContext} />
              </div>
            </div>

            <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20">
              <div className="px-3 py-1 rounded-full bg-black/55 border border-white/15 text-[11px] backdrop-blur">
                L{state.session.level} · {state.session.xp} XP
              </div>
            </div>

            <div className="absolute top-4 right-3 z-20 flex flex-col gap-2">
              <button
                type="button"
                onClick={toggleMute}
                aria-label={muted ? "Unmute (turn on AI voice)" : "Mute"}
                aria-pressed={muted}
                title={muted ? "Unmute" : "Mute"}
                className="w-9 h-9 rounded-full bg-black/55 border border-white/15 grid place-items-center focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
              >
                {muted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
              </button>
              <button type="button" onClick={() => setOverlaysHidden((v) => !v)} className="w-9 h-9 rounded-full bg-black/55 border border-white/15 grid place-items-center">
                {overlaysHidden ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
              </button>
              <button type="button" onClick={() => setShowMobileDrawer((v) => !v)} className="w-9 h-9 rounded-full bg-black/55 border border-white/15 grid place-items-center">
                <Menu className="w-4 h-4" />
              </button>
              <button type="button" onClick={onExit} className="w-9 h-9 rounded-full bg-black/55 border border-white/15 grid place-items-center">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="absolute left-3 right-3 bottom-28 z-20">
              <ConversationOverlay messages={overlayMessages} pending={sending} />
            </div>
          </>
        )}

        <button
          type="button"
          onClick={() => setShowMobileDrawer(true)}
          className="absolute right-3 bottom-24 z-20 inline-flex items-center gap-1.5 px-3 py-2 rounded-full bg-[#8b5cf6]/90 text-white text-xs shadow-lg"
        >
          <Zap className="w-3.5 h-3.5" /> Live Action
        </button>

        <div className="absolute left-0 right-0 bottom-0 z-20 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <div className="flex items-center gap-2 rounded-2xl bg-black/55 backdrop-blur border border-white/15 px-2 py-2">
            <input
              value={chat}
              onChange={(e) => setChat(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void sendChat();
                }
              }}
              placeholder="Message her..."
              disabled={sending}
              maxLength={500}
              className="flex-1 bg-transparent text-sm outline-none px-2 disabled:opacity-60"
            />
            <button
              type="button"
              onClick={sendChat}
              disabled={!chat.trim() || sending}
              aria-label="Send"
              className="w-9 h-9 rounded-full bg-[#ffffff1a] border border-white/20 grid place-items-center disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </div>
        </div>

        {showMobileDrawer && (
          <div className="absolute inset-0 z-30">
            <button type="button" className="absolute inset-0 bg-black/45" onClick={() => setShowMobileDrawer(false)} />
            <div className="absolute left-0 right-0 bottom-0 rounded-t-2xl border-t border-white/10 bg-[#101010] p-4 max-h-[65vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-3">
                <div className="text-sm font-medium">Live Action</div>
                <button type="button" onClick={() => setShowMobileDrawer(false)} className="w-7 h-7 rounded-full border border-white/15 grid place-items-center"><X className="w-3.5 h-3.5" /></button>
              </div>
              <div className="flex gap-2 mb-3">
                <button type="button" onClick={() => setMobileTab("actions")} className={`px-3 py-1.5 rounded-full text-xs ${mobileTab === "actions" ? "bg-[#8b5cf6] text-white" : "bg-[#1c1c1c] text-[#bbb]"}`}>Actions</button>
                <button type="button" onClick={() => setMobileTab("history")} className={`px-3 py-1.5 rounded-full text-xs ${mobileTab === "history" ? "bg-[#8b5cf6] text-white" : "bg-[#1c1c1c] text-[#bbb]"}`}>History</button>
              </div>
              {mobileTab === "actions" ? (
                <>
                  <div className="text-[11px] text-[#aaa] mb-2">Level {state.session.level} · {state.session.xp} XP ({state.session.xpToNext} to next)</div>
                  <div className="h-2 rounded-full bg-[#222] overflow-hidden mb-3"><div className="h-full bg-gradient-to-r from-[#8b5cf6] to-[#3ea6ff]" style={{ width: `${xpPct}%` }} /></div>
                  <div className="text-xs text-[#aaa] mb-2">Available</div>
                  <div className="grid grid-cols-1 gap-2">
                    {state.actions.available.map((a) => (
                      <button key={a.id} type="button" onClick={() => { void fireAction(a.id); setShowMobileDrawer(false); }} disabled={sending || !!pendingJobId} className="text-left rounded-md border border-[#3a3a3a] bg-[#1a1a1a] px-3 py-2 text-sm disabled:opacity-50">{a.label}</button>
                    ))}
                  </div>
                  <div className="text-xs text-[#aaa] mt-4 mb-2">Locked</div>
                  <div className="grid grid-cols-1 gap-2">
                    {state.actions.locked.map((a) => (
                      <div key={a.id} className="rounded-md border border-[#2d2d2d] bg-[#151515] px-3 py-2 text-sm text-[#7c7c7c] flex items-center justify-between">
                        <span>{a.label}</span>
                        <span className="inline-flex items-center gap-1 text-[10px]"><Lock className="w-3 h-3" /> L{a.unlock_level}</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  <div className="text-xs text-[#aaa] mb-2">Version history</div>
                  <div className="grid grid-cols-4 gap-2">
                    {state.versions.slice(0, 8).map((v) => (
                      <button
                        key={v.id}
                        type="button"
                        onClick={() => { void restore(v.id); setShowMobileDrawer(false); }}
                        className={["relative w-full aspect-square rounded border overflow-hidden", v.active ? "border-[#8b5cf6]" : "border-[#3a3a3a]"].join(" ")}
                      >
                        {v.thumb_url ? <img src={v.thumb_url} alt={v.id} className="w-full h-full object-cover" /> : <div className="w-full h-full bg-[#222]" />}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Desktop runtime */}
      <div className="hidden lg:grid flex-1 min-h-0 lg:grid-cols-[minmax(0,1.35fr)_minmax(340px,0.65fr)] gap-4 p-4">
        <div className="min-h-0 flex flex-col gap-3">
          <div className="relative flex-1 min-h-[320px] rounded-2xl border border-[#343434] overflow-hidden bg-[#101010]">
            <div className={`absolute inset-0 transition-all ${transitionClass}`} style={{ transform: `scale(${cameraPreset.zoom}) translateY(${cameraPreset.yOffset}%)` }}>
              {/*
               * Desktop fits the WHOLE image inside the panel
               * (``object-contain``) so the face is never trimmed —
               * the portrait is the focus of Persona Live, and
               * cropping the head off the top is the worst possible
               * default. Letterboxing the rounded panel with a dark
               * background reads as intentional matting; the user
               * sees Lina end-to-end. Mobile keeps ``object-cover``
               * for the immersive full-screen takeover.
               */}
              {state.currentMedia.url ? (
                state.currentMedia.type === "video" ? (
                  <video src={state.currentMedia.url} className="absolute inset-0 w-full h-full object-contain" autoPlay loop muted playsInline />
                ) : (
                  <img src={state.currentMedia.url} alt={state.persona.name} className="absolute inset-0 w-full h-full object-contain" />
                )
              ) : (
                <div className="absolute inset-0 grid place-items-center text-[#666] text-sm">No render yet</div>
              )}
            </div>
            <div className="absolute inset-0 bg-gradient-to-b from-black/35 via-transparent to-black/65 pointer-events-none" />

            <div className="absolute top-3 left-3 z-20 inline-flex items-center gap-2 px-2.5 py-1.5 rounded-full bg-black/50 border border-white/15 backdrop-blur">
              {state.persona.avatarUrl ? <img src={state.persona.avatarUrl} alt={state.persona.name} className="w-7 h-7 rounded-full object-cover" /> : <div className="w-7 h-7 rounded-full bg-[#333]" />}
              <span className="text-sm font-medium">{state.persona.name}</span>
            </div>
            <div className="absolute top-3 left-[220px] z-20 px-3 py-1 rounded-full bg-black/55 border border-white/15 text-xs backdrop-blur">
              Level {state.session.level}
            </div>
            <div className="absolute top-3 right-3 z-20 flex flex-col gap-2">
              <button type="button" onClick={onExit} className="w-10 h-10 rounded-full bg-black/55 border border-white/15 grid place-items-center"><X className="w-4 h-4" /></button>
              <button
                type="button"
                onClick={toggleMute}
                aria-label={muted ? "Unmute (turn on AI voice)" : "Mute"}
                aria-pressed={muted}
                title={muted ? "Unmute" : "Mute"}
                className="w-10 h-10 rounded-full bg-black/55 border border-white/15 grid place-items-center focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
              >
                {muted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
              </button>
              <button type="button" onClick={() => setOverlaysHidden((v) => !v)} className="w-10 h-10 rounded-full bg-black/55 border border-white/15 grid place-items-center">{overlaysHidden ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}</button>
              <button type="button" className="w-10 h-10 rounded-full bg-black/55 border border-white/15 grid place-items-center"><Menu className="w-4 h-4" /></button>
            </div>

            {!overlaysHidden && (
              <>
                <SceneBadge scene={state.sceneContext} />
                <div className="absolute left-4 right-4 bottom-24">
                  <ConversationOverlay messages={overlayMessages} pending={sending} />
                </div>
              </>
            )}
            <div className="absolute left-4 right-4 bottom-4 flex items-center gap-2 rounded-full bg-black/55 border border-white/15 backdrop-blur px-2 py-2">
              <input
                value={chat}
                onChange={(e) => setChat(e.target.value)}
                onKeyDown={(e) => {
                  // Enter sends; Shift+Enter is a no-op on single-line <input>
                  // but we still block it so a future upgrade to <textarea>
                  // Just Works.
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void sendChat();
                  }
                }}
                placeholder="Ask anything"
                disabled={sending}
                maxLength={500}
                className="flex-1 bg-transparent text-sm outline-none px-2 disabled:opacity-60"
              />
              <button
                type="button"
                onClick={sendChat}
                disabled={!chat.trim() || sending}
                aria-label="Send"
                className="w-9 h-9 rounded-full bg-[#ffffff1a] border border-white/20 grid place-items-center disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </button>
            </div>
            {state.currentMedia.status === "rendering" && (
              <div className="absolute inset-0 bg-black/35 grid place-items-center pointer-events-none">
                <div className="inline-flex items-center gap-2 text-xs bg-[#111] border border-[#3a3a3a] rounded-full px-3 py-1.5">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" /> Rendering…
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="min-h-0 overflow-y-auto rounded-2xl border border-[#2f2f2f] bg-[#121212] p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-[#262626] pb-3">
            <div className="text-[30px] font-semibold">Live Action</div>
            <span className="text-xs border border-white/20 rounded-full px-2 py-1 text-[#d0d0d0]">Beta v2</span>
          </div>

          <div className="rounded-xl bg-[#1d1d1d] border border-[#2e2e2e] p-4">
            <div className="flex items-center justify-between text-sm">
              <div className="inline-flex items-center gap-2"><span className="w-7 h-7 rounded-full bg-black/60 border border-white/20 grid place-items-center text-xs">{state.session.level}</span>Level {state.session.level}</div>
              <div className="text-xs text-[#bbb]">{state.session.xpToNext} to next</div>
            </div>
            <div className="mt-3 h-2 rounded-full bg-[#313131] overflow-hidden"><div className="h-full bg-gradient-to-r from-[#8b5cf6] to-[#3ea6ff]" style={{ width: `${xpPct}%` }} /></div>
            <div className="mt-2 text-xs text-[#cacaca]">{state.session.xp} / {state.session.xp + state.session.xpToNext} XP</div>
          </div>

          <div className="space-y-2">
            {state.actions.available.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => fireAction(a.id)}
                disabled={sending || !!pendingJobId}
                className="w-full text-left rounded-xl border border-[#2f2f2f] bg-[#1a1a1a] hover:border-[#8b5cf6] px-4 py-3 text-sm disabled:opacity-50 flex items-center justify-between"
              >
                <span>{a.label}</span>
                <span className="w-8 h-8 rounded-full bg-[#ec4899] text-white grid place-items-center">▶</span>
              </button>
            ))}
            {state.actions.locked.map((a) => (
              <div key={a.id} className="w-full rounded-xl border border-[#2a2a2a] bg-[#171717] px-4 py-3 text-sm text-[#8d8d8d] flex items-center justify-between">
                <span>{a.label}</span>
                <span className="inline-flex items-center gap-2 text-xs"><span className="w-7 h-7 rounded-full bg-[#4338ca] text-white grid place-items-center"><Lock className="w-3 h-3" /></span>Level {a.unlock_level}</span>
              </div>
            ))}
          </div>

          <div className="pt-2">
            <div className="text-xs text-[#aaa] mb-2">History</div>
            <div className="grid grid-cols-4 gap-2">
              {state.versions.slice(0, 8).map((v) => (
                <button
                  key={v.id}
                  type="button"
                  onClick={() => restore(v.id)}
                  className={["relative w-full aspect-square rounded border overflow-hidden", v.active ? "border-[#8b5cf6]" : "border-[#3a3a3a]"].join(" ")}
                >
                  {v.thumb_url ? <img src={v.thumb_url} alt={v.id} className="w-full h-full object-cover" /> : <div className="w-full h-full bg-[#222]" />}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function _mapRuntime(payload: Record<string, unknown>): PersonaRuntimeState {
  const persona = (payload.persona || {}) as Record<string, unknown>;
  const session = (payload.session || {}) as Record<string, unknown>;
  const currentMedia = (payload.current_media || {}) as Record<string, unknown>;
  const actions = (payload.actions || {}) as Record<string, unknown>;
  const dialogue = (payload.dialogue || {}) as Record<string, unknown>;
  const versions = Array.isArray(payload.versions) ? payload.versions : [];
  const sceneContext = (payload.scene_context || {}) as Record<string, unknown>;
  const sceneMemory = (payload.scene_memory || {}) as Record<string, unknown>;
  const emotionalState = (payload.emotional_state || {}) as Record<string, unknown>;

  return {
    persona: {
      id: String(persona.id || ""),
      name: String(persona.name || "Persona"),
      avatarUrl: String(persona.avatar_url || ""),
      archetype: String(persona.archetype || ""),
      mode: String(persona.mode || "image") === "video" ? "video" : "image",
    },
    session: {
      id: String(session.id || ""),
      level: Number(session.level || 1),
      xp: Number(session.xp || 0),
      xpToNext: Number(session.xp_to_next || 35),
      currentVersionId: String(session.current_version_id || ""),
    },
    currentMedia: {
      type: String(currentMedia.type || "image") === "video" ? "video" : "image",
      url: String(currentMedia.url || ""),
      status: String(currentMedia.status || "idle") as "idle" | "rendering" | "ready" | "error",
    },
    dialogue: { text: String(dialogue.text || "") },
    sceneContext: {
      id: String(sceneContext.id || "apartment"),
      label: String(sceneContext.label || "Her apartment"),
      icon: String(sceneContext.icon || "🏠"),
      prompt: String(sceneContext.prompt || ""),
      category: String(sceneContext.category || "private"),
    },
    sceneMemory: {
      current_scene: String(sceneMemory.current_scene || "apartment"),
      previous_scenes: (Array.isArray(sceneMemory.previous_scenes) ? sceneMemory.previous_scenes : []).map(String),
      last_actions: (Array.isArray(sceneMemory.last_actions) ? sceneMemory.last_actions : []).map(String),
      emotional_state: {
        mood: String((sceneMemory.emotional_state as Record<string, unknown> | undefined)?.mood || "guarded"),
        intensity: Number((sceneMemory.emotional_state as Record<string, unknown> | undefined)?.intensity || 25),
      },
    },
    emotionalState: {
      trust: Number(emotionalState.trust || 35),
      intensity: Number(emotionalState.intensity || 25),
      mood: String(emotionalState.mood || "guarded"),
    },
    actions: {
      available: (Array.isArray(actions.available) ? actions.available : []) as RuntimeAction[],
      locked: (Array.isArray(actions.locked) ? actions.locked : []) as RuntimeAction[],
    },
    versions: versions as VersionThumb[],
  };
}

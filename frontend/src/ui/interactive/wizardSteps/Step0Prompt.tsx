/**
 * Step 0 — Prompt + mode selection.
 *
 * Two required inputs (title, prompt) and one mode picker. Mode
 * options are static here to avoid a network roundtrip on first
 * paint; the planner backend tolerates any of the six known mode
 * strings and falls back to sfw_general otherwise.
 */

import React, { useEffect, useMemo, useState } from "react";
import { GitBranch, Image as ImageIcon, Users, Video } from "lucide-react";
import type { ExperienceMode } from "../types";
import type { RenderMediaType, WizardForm } from "../wizardState";
import { LS_PERSONA_CACHE } from "../../voice/personalityGating";
import { resolveBackendUrl } from "../../lib/backendUrl";

export interface Step0Props {
  form: WizardForm;
  setForm: (patch: Partial<WizardForm>) => void;
}

const MODE_OPTIONS: Array<{ value: ExperienceMode; label: string; hint: string; matureOnly?: boolean }> = [
  { value: "sfw_general",         label: "General (SFW)",        hint: "Safe-for-work default — broad audiences." },
  { value: "sfw_education",       label: "Education",            hint: "Lessons, tutorials, explanations." },
  { value: "language_learning",   label: "Language learning",    hint: "CEFR-aware exercises and conversation." },
  { value: "enterprise_training", label: "Enterprise training",  hint: "Onboarding, compliance, certification." },
  { value: "social_romantic",     label: "Social / Romantic",    hint: "Casual social play, mood-aware companions." },
  { value: "mature_gated",        label: "Mature (gated)",       hint: "Requires explicit viewer consent + region check.", matureOnly: true },
];

// The "Mature (gated)" tier is only surfaced when Spicy Mode (NSFW) is
// enabled under Settings → Advanced. This hook reads the same
// localStorage key App.tsx writes (`homepilot_nsfw_mode`) and reacts to
// cross-tab toggles via the native `storage` event, so flipping the
// switch reflects here without a page reload.
const NSFW_MODE_STORAGE_KEY = "homepilot_nsfw_mode";

function useNsfwMode(): boolean {
  const [enabled, setEnabled] = useState<boolean>(() => {
    try { return localStorage.getItem(NSFW_MODE_STORAGE_KEY) === "true"; }
    catch { return false; }
  });
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === NSFW_MODE_STORAGE_KEY) {
        setEnabled(e.newValue === "true");
      }
    };
    // Same-tab toggles don't fire `storage`, so poll briefly on focus.
    const onFocus = () => {
      try { setEnabled(localStorage.getItem(NSFW_MODE_STORAGE_KEY) === "true"); }
      catch { /* ignore */ }
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener("focus", onFocus);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("focus", onFocus);
    };
  }, []);
  return enabled;
}

export function Step0Prompt({ form, setForm }: Step0Props) {
  const spicyModeEnabled = useNsfwMode();

  // When Spicy Mode is disabled, the gated-mature tier is hidden from
  // the picker entirely. If the form already carries `mature_gated`
  // (e.g. Spicy was flipped off mid-wizard), coerce it back to the
  // SFW default so the payload stays consistent with the visible UI.
  useEffect(() => {
    if (!spicyModeEnabled && form.experience_mode === "mature_gated") {
      setForm({ experience_mode: "sfw_general", policy_profile_id: "sfw_general" });
    }
  }, [spicyModeEnabled, form.experience_mode, setForm]);

  const visibleModeOptions = useMemo(
    () => MODE_OPTIONS.filter((m) => !m.matureOnly || spicyModeEnabled),
    [spicyModeEnabled],
  );

  const personaOptions = useMemo(() => {
    try {
      const raw = localStorage.getItem(LS_PERSONA_CACHE);
      if (!raw) return [];
      const parsed = JSON.parse(raw) as Array<{
        id?: unknown; label?: unknown; avatar_url?: unknown; archetype?: unknown;
      }>;
      return parsed
        .map((item) => ({
          id: typeof item.id === "string" ? item.id : "",
          label: typeof item.label === "string" ? item.label : "",
          avatar_url: typeof item.avatar_url === "string" ? item.avatar_url : "",
          archetype: typeof item.archetype === "string" ? item.archetype : "",
        }))
        .filter((item) => item.id && item.label);
    } catch {
      return [];
    }
  }, []);

  // The LS_PERSONA_CACHE writers in App.tsx persist label / persona_class
  // but do NOT include avatar_url or archetype — historical oversight.
  // That's why the wizard's persona preview card used to render an empty
  // grey swatch next to the selected persona name. Rather than touch every
  // cache writer, we resolve the missing fields from the backend at
  // selection time and keep them in component state. Cheap: one GET per
  // wizard session per selected persona.
  const [resolvedDetails, setResolvedDetails] = useState<
    Record<string, { avatar_url: string; archetype: string }>
  >({});

  useEffect(() => {
    const pid = form.persona_project_id;
    if (!pid) return;
    const cached = personaOptions.find((p) => p.id === pid);
    const needsAvatar = !(cached && cached.avatar_url);
    const needsArchetype = !(cached && cached.archetype);
    if (!needsAvatar && !needsArchetype) return;
    if (resolvedDetails[pid]) return;

    const ctrl = new AbortController();
    const backend = resolveBackendUrl();
    fetch(`${backend}/projects/${encodeURIComponent(pid)}`, {
      signal: ctrl.signal,
      credentials: "include",
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => {
        if (!body || !body.ok || !body.project) return;
        const project = body.project as {
          persona_appearance?: { selected_filename?: unknown };
          persona_agent?: {
            persona_class?: unknown;
            response_style?: { tone?: unknown };
          };
        };
        const filename = String(
          project.persona_appearance?.selected_filename || "",
        ).trim();
        const avatarUrl = filename ? `${backend}/files/${filename}` : "";
        const archetype =
          String(project.persona_agent?.persona_class || "").trim() ||
          String(project.persona_agent?.response_style?.tone || "").trim();
        setResolvedDetails((prev) => ({
          ...prev,
          [pid]: { avatar_url: avatarUrl, archetype },
        }));
      })
      .catch(() => { /* swallow — preview falls back to placeholder */ });
    return () => ctrl.abort();
  }, [form.persona_project_id, personaOptions, resolvedDetails]);

  return (
    <div className="flex flex-col gap-5">
      {/* Interaction type picker — mirrors the Animate/Voice dual-card
          pattern so Interactive inherits the same visual rhythm. */}
      <FieldLabel label="Interaction type" hint="Choose what kind of interactive video to build.">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => setForm({
              interaction_type: "standard_project",
              persona_project_id: "",
              persona_label: "",
            })}
            aria-pressed={form.interaction_type === "standard_project"}
            className={[
              "text-left bg-[#121212] border rounded-md p-3 transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]",
              form.interaction_type === "standard_project"
                ? "border-[#3ea6ff] bg-[rgba(62,166,255,0.08)] ring-1 ring-[#3ea6ff]"
                : "border-[#3f3f3f] hover:border-[#555] hover:bg-[#1a1a1a]",
            ].join(" ")}
          >
            <div className="text-sm font-medium text-[#f1f1f1] inline-flex items-center gap-1.5">
              <GitBranch className="w-3.5 h-3.5 text-[#7dd3fc]" aria-hidden />
              Standard interactive project
            </div>
            <div className="text-xs text-[#aaa] mt-0.5">
              Branching AI video with scenes, choices, and endings.
            </div>
          </button>

          <button
            type="button"
            onClick={() => setForm({ interaction_type: "persona_live_play" })}
            aria-pressed={form.interaction_type === "persona_live_play"}
            className={[
              "text-left bg-[#121212] border rounded-md p-3 transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]",
              form.interaction_type === "persona_live_play"
                ? "border-[#8b5cf6] bg-[rgba(139,92,246,0.08)] ring-1 ring-[#8b5cf6]"
                : "border-[#3f3f3f] hover:border-[#555] hover:bg-[#1a1a1a]",
            ].join(" ")}
          >
            <div className="text-sm font-medium text-[#f1f1f1] inline-flex items-center gap-1.5">
              <Users className="w-3.5 h-3.5 text-[#c4b5fd]" aria-hidden />
              Persona live play
            </div>
            <div className="text-xs text-[#aaa] mt-0.5">
              Pick one of your personas — chat + video revolve around them.
            </div>
          </button>
        </div>
      </FieldLabel>

      {form.interaction_type === "persona_live_play" && (
        <FieldLabel
          htmlFor="ix_persona_pick"
          label="Persona"
          required
          hint="Select the persona that should drive live-play animation and conversation."
        >
          <select
            id="ix_persona_pick"
            value={form.persona_project_id}
            onChange={(e) => {
              const selected = personaOptions.find((p) => p.id === e.target.value);
              setForm({
                persona_project_id: e.target.value,
                persona_label: selected?.label || "",
              });
            }}
            className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2.5 text-sm outline-none focus:border-[#8b5cf6] focus:ring-1 focus:ring-[#8b5cf6]/50"
          >
            <option value="">Select persona…</option>
            {personaOptions.map((persona) => (
              <option key={persona.id} value={persona.id}>{persona.label}</option>
            ))}
          </select>
          {personaOptions.length === 0 && (
            <p className="text-[11px] text-amber-300 mt-1">
              No personas yet. Create one under the Persona workspace, then come back.
            </p>
          )}
          {form.persona_project_id && (() => {
            const selected = personaOptions.find((p) => p.id === form.persona_project_id);
            if (!selected) return null;
            const resolved = resolvedDetails[form.persona_project_id];
            const avatarUrl = selected.avatar_url || resolved?.avatar_url || "";
            const archetype = selected.archetype || resolved?.archetype || "";
            return (
              <div className="mt-2.5 flex items-center gap-2.5 rounded-md border border-[#3a2a58] bg-[#130f1f] p-2.5">
                {avatarUrl ? (
                  <img src={avatarUrl} alt={selected.label} className="w-12 h-12 rounded-md object-cover border border-[#51347f]" />
                ) : (
                  <div className="w-12 h-12 rounded-md bg-[#24173a] border border-[#51347f]" />
                )}
                <div className="min-w-0">
                  <div className="text-xs font-medium text-[#f1f1f1] truncate">{selected.label}</div>
                  <div className="text-[11px] text-[#b59ed9] truncate">{archetype || "Persona companion"}</div>
                </div>
              </div>
            );
          })()}
        </FieldLabel>
      )}

      <FieldLabel htmlFor="ix_title" label="Project title" required>
        <input
          id="ix_title"
          type="text"
          value={form.title}
          onChange={(e) => setForm({ title: e.target.value })}
          placeholder="e.g. Onboard new sales reps to our pricing tiers"
          maxLength={120}
          className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2.5 text-sm outline-none focus:border-[#3ea6ff] focus:ring-1 focus:ring-[#3ea6ff]/50"
        />
      </FieldLabel>

      <FieldLabel
        htmlFor="ix_prompt"
        label={form.interaction_type === "persona_live_play" ? "Session vibe" : "Prompt"}
        required
        hint={form.interaction_type === "persona_live_play"
          ? "Describe the live-play vibe in plain language (e.g., playful tease, romantic late-night, dominant banter)."
          : "Describe the experience in plain language. The planner uses this to design branches and pick scene topics."}
      >
        <textarea
          id="ix_prompt"
          rows={5}
          value={form.prompt}
          onChange={(e) => setForm({ prompt: e.target.value })}
          placeholder={form.interaction_type === "persona_live_play"
            ? "e.g. teasing and flirt with progressive unlocks, playful dominant tone"
            : "e.g. Walk a new hire through our 3 pricing tiers in 4 branches; each branch ends with a quiz question."}
          className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2.5 text-sm outline-none focus:border-[#3ea6ff] focus:ring-1 focus:ring-[#3ea6ff]/50 resize-y"
        />
        <PromptCounter value={form.prompt} />
      </FieldLabel>

      <FieldLabel
        label="Render media"
        hint="Image = fast still-frame scenes (low GPU, good for feasibility tests). Video = full Animate/SVD clips."
      >
        <RenderMediaSelect
          value={form.render_media_type}
          onChange={(v) => setForm({ render_media_type: v })}
        />
      </FieldLabel>

      <FieldLabel label="Experience mode" hint="Selects the policy profile + scene templates downstream.">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {visibleModeOptions.map((m) => {
            const selected = form.experience_mode === m.value;
            return (
              <button
                key={m.value}
                type="button"
                onClick={() => setForm({ experience_mode: m.value, policy_profile_id: m.value })}
                aria-pressed={selected}
                className={[
                  "text-left bg-[#121212] border rounded-md p-3 transition-colors",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]",
                  selected
                    ? "border-[#3ea6ff] bg-[rgba(62,166,255,0.08)] ring-1 ring-[#3ea6ff]"
                    : "border-[#3f3f3f] hover:border-[#555] hover:bg-[#1a1a1a]",
                ].join(" ")}
              >
                <div className="text-sm font-medium text-[#f1f1f1]">{m.label}</div>
                <div className="text-xs text-[#aaa] mt-0.5">{m.hint}</div>
              </button>
            );
          })}
        </div>
      </FieldLabel>
    </div>
  );
}

function FieldLabel({
  label, hint, required, htmlFor, children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium text-[#cfd8dc]">
        {label}
        {required && <span className="text-[#3ea6ff] ml-0.5" aria-label="required">*</span>}
      </label>
      {hint && <p className="text-xs text-[#777] -mt-0.5">{hint}</p>}
      {children}
    </div>
  );
}

function PromptCounter({ value }: { value: string }) {
  const len = value.trim().length;
  const ok = len >= 1;
  return (
    <div className="mt-0.5" aria-live="polite">
      <div className={["text-[11px]", ok ? "text-[#777]" : "text-amber-400"].join(" ")}>
        {len} characters{ok ? " ✓" : ""}
      </div>
      {!ok && (
        <div className="text-[11px] text-[#777] mt-1">
          Type at least one character to enable the Next button.
        </div>
      )}
    </div>
  );
}

function RenderMediaSelect({
  value, onChange,
}: {
  value: RenderMediaType;
  onChange: (v: RenderMediaType) => void;
}) {
  // Compact two-option picker styled like the existing interaction-
  // type cards so the wizard stays visually consistent. Keeping the
  // control small matches the user's request ("add a new small
  // dropdown") — a full-width two-card picker would steal focus from
  // the more important interaction-type + mode decisions above.
  const options: Array<{
    value: RenderMediaType;
    label: string;
    sub: string;
    icon: React.ReactNode;
  }> = [
    {
      value: "video",
      label: "Video (full pipeline)",
      sub: "Uses the Animate / SVD workflow. Needs a capable GPU.",
      icon: <Video className="w-4 h-4" aria-hidden />,
    },
    {
      value: "image",
      label: "Image (feasibility mode)",
      sub: "Still frames via txt2img. Fast, low-VRAM; same UX everywhere else.",
      icon: <ImageIcon className="w-4 h-4" aria-hidden />,
    },
  ];
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
      {options.map((opt) => {
        const selected = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            aria-pressed={selected}
            className={[
              "text-left bg-[#121212] border rounded-md p-3 transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]",
              selected
                ? "border-[#3ea6ff] bg-[rgba(62,166,255,0.08)] ring-1 ring-[#3ea6ff]"
                : "border-[#3f3f3f] hover:border-[#555] hover:bg-[#1a1a1a]",
            ].join(" ")}
          >
            <div className="flex items-center gap-2 text-sm font-medium text-[#f1f1f1]">
              <span className="text-[#3ea6ff]">{opt.icon}</span>
              {opt.label}
            </div>
            <div className="text-xs text-[#aaa] mt-0.5">{opt.sub}</div>
          </button>
        );
      })}
    </div>
  );
}


/** Validation hook used by the parent Wizard to enable Next. */
export function step0Valid(f: WizardForm): boolean {
  // Persona live play additionally requires a persona selection so
  // the live-play engine has a character to animate + chat as.
  if (f.interaction_type === "persona_live_play" && !f.persona_project_id.trim()) {
    return false;
  }
  return f.title.trim().length >= 3 && f.prompt.trim().length >= 1;
}

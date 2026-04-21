/**
 * Step 4 — Review summary + planner preview.
 *
 * Renders a tidy summary of every prior step and asks the planner
 * to "preview" the resolved Intent so authors can sanity-check
 * topic / objective / scheme choices before they hit Create.
 *
 * The preview call is a non-mutating GET-equivalent (POST /plan
 * has no DB side-effects) so it's safe to re-run on retry.
 */

import React, { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import type { InteractiveApi } from "../api";
import { InteractiveApiError } from "../types";
import type { PlanIntent } from "../types";
import type { WizardForm } from "../wizardState";
import { toPlanPayload } from "../wizardState";

export interface Step4Props {
  form: WizardForm;
  api: InteractiveApi;
}

export function Step4Review({ form, api }: Step4Props) {
  const [preview, setPreview] = useState<PlanIntent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const payload = useMemo(() => toPlanPayload(form), [form]);

  useEffect(() => {
    if (form.interaction_type === "persona_live_play") {
      setLoading(false);
      setError(null);
      setPreview({
        prompt: form.prompt,
        mode: form.experience_mode,
        objective: "",
        topic: "",
        branch_count: 0,
        depth: 0,
        scenes_per_branch: 0,
        success_metric: "",
        seed_intents: ["tease", "dance", "outfit_change"],
        scheme: "affinity_tier",
        audience: {
          role: form.audience_role,
          level: form.audience_level,
          language: form.audience_language,
          locale_hint: form.audience_locale_hint,
          interests: [],
        },
        raw_hints: {},
      });
      return;
    }
    const ctrl = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.plan(payload)
      .then((intent) => { if (!cancelled) setPreview(intent); })
      .catch((err: Error) => {
        if (cancelled || err.name === "AbortError") return;
        const apiErr = err as InteractiveApiError;
        setError(apiErr.message || "Couldn't preview plan.");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; ctrl.abort(); };
  }, [api, payload]);

  return (
    <div className="flex flex-col gap-5">
      <SummaryCard form={form} />
      <PreviewCard
        loading={loading}
        error={error}
        intent={preview}
        personaLive={form.interaction_type === "persona_live_play"}
      />
    </div>
  );
}

function SummaryCard({ form }: { form: WizardForm }) {
  const personaLive = form.interaction_type === "persona_live_play";
  return (
    <section className="rounded-md border border-[#3f3f3f] bg-[#121212] divide-y divide-[#2a2a2a]">
      <Row
        label={personaLive ? "Session type" : "Interaction"}
        value={
          personaLive
            ? `Persona live play${form.persona_label ? ` · ${form.persona_label}` : ""}`
            : "Standard interactive project"
        }
      />
      <Row label="Mode" value={form.experience_mode} />
      <Row label="Policy profile" value={form.policy_profile_id} />
      {!personaLive && <Row label="Title" value={form.title} />}
      {!personaLive && <Row label="Audience" value={`${form.audience_role} · ${form.audience_level} · ${form.audience_language}${form.audience_locale_hint ? ` · ${form.audience_locale_hint}` : ""}`} />}
      {!personaLive && <Row label="Branches" value={`${form.branch_count} branches × depth ${form.depth} × ${form.scenes_per_branch} scenes`} />}
      <Row label={personaLive ? "Session vibe" : "Prompt"} value={form.prompt} multiline />
    </section>
  );
}

function PreviewCard({
  loading, error, intent, personaLive,
}: {
  loading: boolean;
  error: string | null;
  intent: PlanIntent | null;
  personaLive?: boolean;
}) {
  const persona = !!personaLive;
  return (
    <section className="rounded-md border border-[#3f3f3f] bg-[#121212] p-4">
      <header className="text-xs font-medium text-[#cfd8dc] mb-3">
        {persona ? "Live session preview" : "Planner preview"}
      </header>
      {loading && (
        <div className="flex items-center gap-2 text-sm text-[#aaa]">
          <Loader2 className="w-4 h-4 animate-spin text-[#3ea6ff]" aria-hidden />
          {persona ? "Preparing persona progression preview…" : "Asking the planner to resolve your prompt…"}
        </div>
      )}
      {error && (
        <div role="alert" className="text-sm text-red-400">
          {error}
        </div>
      )}
      {!loading && !error && intent && (
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-xs">
          {!persona && <DLRow term="Objective" value={intent.objective} />}
          {!persona && <DLRow term="Topic" value={intent.topic || "(auto)"} />}
          <DLRow term={persona ? "Progression scheme" : "Scheme"} value={intent.scheme} />
          {!persona && <DLRow term="Success metric" value={intent.success_metric || "(none)"} />}
          {!persona && <DLRow term="Branches" value={`${intent.branch_count} × depth ${intent.depth}`} />}
          {!persona && <DLRow term="Scenes / branch" value={String(intent.scenes_per_branch)} />}
          <DLRow term="Seed intents" value={intent.seed_intents.join(", ") || "(none)"} />
          {!persona && <DLRow term="Audience" value={`${intent.audience.role} · ${intent.audience.level} · ${intent.audience.language}`} />}
        </dl>
      )}
    </section>
  );
}

function Row({ label, value, multiline }: { label: string; value: string; multiline?: boolean }) {
  return (
    <div className="flex gap-4 px-4 py-2.5">
      <div className="text-xs text-[#777] w-32 shrink-0 mt-0.5">{label}</div>
      <div
        className={[
          "text-sm text-[#f1f1f1] flex-1 min-w-0 break-words",
          multiline ? "whitespace-pre-wrap" : "truncate",
        ].join(" ")}
      >
        {value || <span className="text-[#777] italic">(empty)</span>}
      </div>
    </div>
  );
}

function DLRow({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex gap-3 min-w-0">
      <dt className="text-[#777] shrink-0 w-28">{term}</dt>
      <dd className="text-[#f1f1f1] truncate" title={value}>{value}</dd>
    </div>
  );
}

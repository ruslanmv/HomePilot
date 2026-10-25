/**
 * ModelBadge — "which model wrote this" under an assistant reply.
 *
 * Reads the /chat `answered_by` block (backend/app/llm.py ``_answered_by``): the provider and
 * model that actually answered, and — when Hugging Face could not answer and the local model
 * stood in — that it fell back, and why, with the way to fix it. So a reply from the built-in
 * model is never mistaken for one from the Hugging Face account.
 */
import React from "react";
import { CornerDownRight } from "lucide-react";

export interface AnsweredBy {
  provider: string;
  model: string;
  fell_back?: boolean;
  reason?: string | null;
}

const PROVIDER_LABEL: Record<string, string> = {
  huggingface: "Hugging Face",
  ollama: "local",
  openai: "OpenAI",
  claude: "Anthropic",
  watsonx: "watsonx",
  openai_compat: "local server",
};

/** "meta-llama/Llama-3.1-8B-Instruct" → "Llama-3.1-8B-Instruct"; Ollama tags stay as they are. */
function shortModel(model: string): string {
  const name = (model || "").replace(/^hf:/, "");
  return name.includes("/") ? name.split("/").slice(1).join("/") : name;
}

export default function ModelBadge({ answeredBy }: { answeredBy?: AnsweredBy | null }) {
  if (!answeredBy || !answeredBy.model) return null;
  const where = PROVIDER_LABEL[answeredBy.provider] || answeredBy.provider;
  const isHf = answeredBy.provider === "huggingface";

  if (answeredBy.fell_back) {
    return (
      <span className="inline-flex flex-wrap items-center gap-x-1.5 gap-y-0.5 rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-200/90">
        <CornerDownRight size={11} aria-hidden />
        <span title={answeredBy.model}>{shortModel(answeredBy.model)} · {where}</span>
        {answeredBy.reason ? <span className="text-amber-200/55">— {answeredBy.reason}</span> : null}
        {/connected/i.test(answeredBy.reason || "") ? (
          <button
            type="button"
            onClick={() => window.dispatchEvent(new CustomEvent("homepilot:open-settings", { detail: { tab: "connectors" } }))}
            className="font-semibold text-amber-100 underline-offset-2 hover:underline"
          >
            Connect
          </button>
        ) : null}
      </span>
    );
  }

  return (
    <span
      title={`${answeredBy.model} · ${where}`}
      className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] text-white/45"
    >
      {isHf ? <span aria-hidden>🤗</span> : null}
      {shortModel(answeredBy.model)} · {where}
    </span>
  );
}

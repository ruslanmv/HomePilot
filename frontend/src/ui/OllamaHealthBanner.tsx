import React from "react";

export default function OllamaHealthBanner({
  show,
  onSwitchToVllm,
  onFetchModels,
  onDismiss,
}: {
  show: boolean;
  onSwitchToVllm: () => void;
  onFetchModels: () => void;
  onDismiss: () => void;
}) {
  if (!show) return null;

  return (
    <div className="mb-3 rounded-2xl border border-yellow-500/30 bg-yellow-500/10 p-3 text-xs text-yellow-100">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-bold text-yellow-100">Ollama unavailable</div>
          <div className="mt-1 text-yellow-100/80 leading-snug">
            Ollama is selected, but it isn&apos;t reachable from the backend. You can switch to the
            OpenAI-compatible vLLM provider and fetch available models.
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={onSwitchToVllm}
              className="px-3 py-1.5 rounded-xl bg-yellow-400/20 hover:bg-yellow-400/30 border border-yellow-400/30 text-yellow-100 font-semibold"
            >
              Switch to vLLM
            </button>
            <button
              type="button"
              onClick={onFetchModels}
              className="px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-white font-semibold"
            >
              Fetch models
            </button>
          </div>
        </div>

        <button
          type="button"
          onClick={onDismiss}
          className="p-1 rounded-lg hover:bg-white/5 text-yellow-100/60 hover:text-yellow-100"
          aria-label="Dismiss"
        >
          ✕
        </button>
      </div>
    </div>
  );
}

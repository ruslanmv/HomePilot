import React from "react";
import type { Remedy } from "./lib/modelResolution";

/**
 * Shown in Settings when the local LLM runtime cannot serve chat. The text and
 * the buttons follow the backend's remedy (docs/design/LOCAL_MODEL_RESOLUTION.md):
 *
 *   wsl_bridge  Ollama runs on the Windows host but WSL cannot reach it
 *   start       no runtime answered anywhere
 *   pull        a runtime answered but holds no usable model → offer a download
 *
 * "Switch to vLLM" is offered only when an OpenAI-compatible server actually
 * answered the health check; suggesting it blindly sent people down a dead end.
 */
export default function OllamaHealthBanner({
  show,
  remedy,
  vllmAvailable = false,
  onSwitchToVllm,
  onFetchModels,
  onDownloadModel,
  onRetry,
  onDismiss,
}: {
  show: boolean;
  remedy?: Remedy | null;
  vllmAvailable?: boolean;
  onSwitchToVllm: () => void;
  onFetchModels: () => void;
  onDownloadModel?: () => void;
  onRetry?: () => void;
  onDismiss: () => void;
}) {
  if (!show) return null;

  const kind = remedy?.kind;
  const title =
    kind === "pull"
      ? "No chat model installed"
      : kind === "wsl_bridge"
        ? "Ollama is on Windows, but WSL cannot reach it"
        : "Ollama unavailable";
  const body =
    remedy?.message ||
    "Ollama is selected, but it isn't reachable from the backend. Start it with `ollama serve`, or set the Chat Base URL to where it runs.";

  return (
    <div
      className="mb-3 rounded-2xl border border-yellow-500/30 bg-yellow-500/10 p-3 text-xs text-yellow-100"
      role="status"
      data-testid="ollama-health-banner"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-bold text-yellow-100">{title}</div>
          <div className="mt-1 text-yellow-100/80 leading-snug whitespace-pre-line">{body}</div>
          {remedy?.command && kind !== "pull" ? (
            <code className="mt-2 block w-fit rounded bg-black/30 px-2 py-1 text-[11px] text-yellow-50/90">
              {remedy.command}
            </code>
          ) : null}
          {remedy?.probed && remedy.probed.length ? (
            <div className="mt-1 text-[10px] text-yellow-100/50">Tried: {remedy.probed.join(", ")}</div>
          ) : null}

          <div className="mt-3 flex flex-wrap gap-2">
            {kind === "pull" && onDownloadModel ? (
              <button
                type="button"
                onClick={onDownloadModel}
                className="px-3 py-1.5 rounded-xl bg-yellow-400/20 hover:bg-yellow-400/30 border border-yellow-400/30 text-yellow-100 font-semibold"
              >
                Download a model
              </button>
            ) : null}
            {onRetry ? (
              <button
                type="button"
                onClick={onRetry}
                className="px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-white font-semibold"
              >
                Check again
              </button>
            ) : null}
            <button
              type="button"
              onClick={onFetchModels}
              className="px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-white font-semibold"
            >
              Fetch models
            </button>
            {vllmAvailable ? (
              <button
                type="button"
                onClick={onSwitchToVllm}
                className="px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-white font-semibold"
              >
                Switch to vLLM
              </button>
            ) : null}
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

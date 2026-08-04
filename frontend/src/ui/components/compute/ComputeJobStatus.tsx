/**
 * ComputeJobStatus — live status for an async image/video job.
 *
 * Given a jobId it polls /v1/jobs/{id} and renders queue → routing → running →
 * done, the selected device and GPU seconds (so the user sees *where* it ran),
 * and the resulting artifacts or an actionable error. Polling stops on a
 * terminal state. Polling is used rather than SSE so the component has no
 * transport dependency; the compute-client also exposes event subscription for
 * apps that inject one.
 */
import React, { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import type { Job } from "@homepilot/types";
import { computeClient } from "../../api";

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);

export default function ComputeJobStatus({
  jobId,
  pollMs = 1500,
}: {
  jobId: string;
  pollMs?: number;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      try {
        const j = await computeClient.getJobStatus(jobId);
        if (cancelled) return;
        setJob(j);
        setError(null);
        if (!TERMINAL.has(j.status)) {
          timer.current = setTimeout(tick, pollMs);
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Failed to fetch job");
        timer.current = setTimeout(tick, pollMs * 2);
      }
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [jobId, pollMs]);

  if (error && !job) {
    return (
      <div className="px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/20 text-red-300 text-xs">
        {error}
      </div>
    );
  }
  if (!job) {
    return (
      <div className="text-xs text-white/50 inline-flex items-center gap-2">
        <Loader2 size={14} className="animate-spin" /> Starting…
      </div>
    );
  }

  const pct = Math.max(0, Math.min(100, Math.round(job.progress || 0)));
  const running = !TERMINAL.has(job.status);

  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4 space-y-3">
      <div className="flex items-center justify-between text-sm">
        <span className="flex items-center gap-2 text-white/80">
          {job.status === "succeeded" ? (
            <CheckCircle2 size={16} className="text-emerald-400" />
          ) : job.status === "failed" || job.status === "canceled" ? (
            <AlertTriangle size={16} className="text-red-400" />
          ) : (
            <Loader2 size={16} className="animate-spin text-cyan-300" />
          )}
          <span className="capitalize">{job.status}</span>
          {job.model && <span className="text-white/40">· {job.model}</span>}
        </span>
        <span className="text-xs text-white/40">
          {job.selectedDeviceId ? `on ${job.selectedDeviceId}` : ""}
          {job.gpuSeconds != null ? ` · ${job.gpuSeconds.toFixed(1)}s GPU` : ""}
        </span>
      </div>

      {running && (
        <div className="h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
          <div
            className="h-full bg-cyan-400/70 transition-[width] duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}

      {job.error && (
        <div className="px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/20 text-red-300 text-xs">
          {job.error.message}
          <span className="text-red-300/60"> ({job.error.code})</span>
        </div>
      )}

      {job.output?.artifacts?.length ? (
        <div className="flex flex-wrap gap-2">
          {job.output.artifacts.map((a, i) =>
            a.contentType.startsWith("image/") ? (
              <img
                key={i}
                src={a.url}
                alt={`artifact ${i + 1}`}
                className="h-24 w-24 object-cover rounded-lg border border-white/10"
              />
            ) : (
              <a
                key={i}
                href={a.url}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-cyan-300 underline"
              >
                Artifact {i + 1}
              </a>
            ),
          )}
        </div>
      ) : null}
    </div>
  );
}

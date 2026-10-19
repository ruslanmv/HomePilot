import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Download, RefreshCw, CheckCircle2, AlertTriangle } from 'lucide-react'
import {
  describeResolution,
  fetchModelResolution,
  formatGb,
  getModelPull,
  startModelPull,
  type ModelResolutionSnapshot,
  type PullJob,
  type RoleResolution,
  type SuggestedModel,
} from '../lib/modelResolution'

/**
 * Shows which local model a role will actually use, and when nothing can
 * serve it, lets the user download one with progress — instead of printing
 * "run ollama pull …" in an error message.
 *
 * Rendered under the Chat Model / Multimodal Model rows in Settings.
 */
export default function ModelDownloadCard({
  backendUrl,
  role,
  configured,
  baseUrl,
  onInstalled,
}: {
  backendUrl: string
  role: 'chat' | 'vision'
  configured: string
  baseUrl?: string
  /** Called with the model name once a download completes. */
  onInstalled?: (name: string) => void
}) {
  const [snap, setSnap] = useState<ModelResolutionSnapshot | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [jobs, setJobs] = useState<Record<string, PullJob>>({})
  const [showAll, setShowAll] = useState(false)
  const timers = useRef<Record<string, number>>({})

  const load = useCallback(
    async (refresh = false) => {
      setLoading(true)
      setError(null)
      try {
        const data = await fetchModelResolution(backendUrl, {
          configured: role === 'chat' ? configured : undefined,
          vision: role === 'vision' ? configured : undefined,
          baseUrl,
          refresh,
        })
        setSnap(data)
        const active: Record<string, PullJob> = {}
        for (const j of data.pulls || []) active[j.name] = j
        setJobs((prev) => ({ ...prev, ...active }))
      } catch (e: any) {
        setError(e?.message || String(e))
      } finally {
        setLoading(false)
      }
    },
    [backendUrl, role, configured, baseUrl],
  )

  useEffect(() => {
    void load(false)
  }, [load])

  useEffect(() => {
    const t = timers.current
    return () => {
      Object.values(t).forEach((id) => window.clearTimeout(id))
    }
  }, [])

  const poll = useCallback(
    (name: string) => {
      const tick = async () => {
        try {
          const job = await getModelPull(backendUrl, name)
          if (job) setJobs((prev) => ({ ...prev, [name]: job }))
          if (job && (job.status === 'completed' || job.status === 'error')) {
            if (job.status === 'completed') {
              onInstalled?.(name)
              void load(true)
            }
            return
          }
        } catch {
          /* keep polling; a transient error must not stop progress updates */
        }
        timers.current[name] = window.setTimeout(tick, 1000)
      }
      timers.current[name] = window.setTimeout(tick, 800)
    },
    [backendUrl, onInstalled, load],
  )

  const download = useCallback(
    async (name: string) => {
      setError(null)
      try {
        const job = await startModelPull(backendUrl, name, baseUrl)
        setJobs((prev) => ({ ...prev, [name]: job }))
        poll(name)
      } catch (e: any) {
        setError(e?.message || String(e))
      }
    },
    [backendUrl, baseUrl, poll],
  )

  const res: RoleResolution | null = snap ? (role === 'chat' ? snap.chat : snap.vision) : null
  const remedy = res?.remedy || null
  const reachable = !!res?.runtime_url
  const suggested: SuggestedModel[] = (remedy?.suggested && remedy.suggested.length
    ? remedy.suggested
    : (snap?.suggested || []).filter((s) => s.roles.includes(role))) as SuggestedModel[]
  const needsModel = !!res && res.source === 'none'
  const listVisible = needsModel || showAll

  return (
    <div
      className="mt-2 rounded-xl border border-white/[0.08] bg-white/[0.03] p-3 text-[11px] text-white/70"
      data-testid={`model-download-card-${role}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {res && res.model ? (
            <div className="flex items-center gap-1.5 text-white/85">
              <CheckCircle2 size={13} className="shrink-0 text-emerald-400" />
              <span className="truncate">
                {role === 'chat' ? 'Chat will use ' : 'Images will use '}
                <span className="font-semibold text-white">{describeResolution(res)}</span>
              </span>
            </div>
          ) : res ? (
            <div className="flex items-start gap-1.5 text-amber-200">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              <span>{remedy?.message || res.reason}</span>
            </div>
          ) : (
            <span>{loading ? 'Checking local models…' : error ? `Could not check models: ${error}` : ''}</span>
          )}
          {res && res.source === 'fallback' && res.configured ? (
            <div className="mt-1 text-white/50">{res.reason}</div>
          ) : null}
          {remedy?.command && remedy.kind !== 'pull' ? (
            <code className="mt-1 block rounded bg-black/30 px-2 py-1 text-[10px] text-white/70">{remedy.command}</code>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {reachable && !needsModel ? (
            <button
              type="button"
              onClick={() => setShowAll((v) => !v)}
              className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] font-semibold text-white hover:bg-white/10"
            >
              {showAll ? 'Hide downloads' : 'Download another model'}
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => void load(true)}
            disabled={loading}
            className="rounded-lg border border-white/10 bg-white/5 p-1.5 text-white hover:bg-white/10 disabled:opacity-50"
            aria-label="Check again"
            title="Check again"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {reachable && listVisible && suggested.length ? (
        <ul className="mt-3 space-y-2" aria-label="Models you can download">
          {suggested.map((s) => {
            const job = jobs[s.name]
            const running = job && (job.status === 'queued' || job.status === 'running')
            const done = (job && job.status === 'completed') || s.installed
            return (
              <li key={s.name} className="rounded-lg border border-white/[0.06] bg-black/20 p-2.5">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-semibold text-white">
                      {s.name} <span className="font-normal text-white/50">· {formatGb(s.size_gb)}</span>
                    </div>
                    <div className="text-white/55">{s.why}</div>
                  </div>
                  {done ? (
                    <span className="flex items-center gap-1 text-emerald-300">
                      <CheckCircle2 size={13} /> Installed
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void download(s.name)}
                      disabled={!!running}
                      className="flex shrink-0 items-center gap-1 rounded-lg bg-indigo-500/80 px-2.5 py-1.5 font-semibold text-white hover:bg-indigo-500 disabled:opacity-60"
                    >
                      <Download size={12} />
                      {running ? 'Downloading…' : 'Download'}
                    </button>
                  )}
                </div>
                {job && job.status !== 'completed' ? (
                  <div className="mt-2">
                    <div className="h-1.5 w-full overflow-hidden rounded bg-white/10">
                      <div
                        className={`h-full ${job.status === 'error' ? 'bg-red-400' : 'bg-indigo-400'} transition-all`}
                        style={{ width: `${Math.max(2, Math.min(100, job.pct || 0))}%` }}
                      />
                    </div>
                    <div className="mt-1 flex justify-between text-[10px] text-white/50">
                      <span>{job.status === 'error' ? `Failed: ${job.error}` : job.message || job.status}</span>
                      <span>{job.pct ? `${job.pct.toFixed(0)}%` : ''}</span>
                    </div>
                  </div>
                ) : null}
              </li>
            )
          })}
        </ul>
      ) : null}

      {error && res ? <div className="mt-2 text-red-300">{error}</div> : null}
    </div>
  )
}

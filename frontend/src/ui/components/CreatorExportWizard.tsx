/**
 * CreatorExportWizard — 2-step modal for exporting a Creator Studio video.
 *
 * Flow:
 *   1. Choose target — "MP4 (edit/share)" or "MP4 for YouTube".
 *   2. Render + download — POST /studio/videos/{id}/export/mp4, poll the
 *      job, then trigger a same-tab download via <a href download>.
 *
 * Race protection:
 *   The poller captures the wizard's mount-instance id at submit time and
 *   discards any response that returns after the wizard has been closed
 *   or after the user submitted a different render. This mirrors the
 *   session-epoch pattern used in App.tsx for account-switch races.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Download, Film, Youtube, X, CheckCircle2, AlertTriangle, Loader2 } from 'lucide-react'

export type ExportKind = 'mp4_plain' | 'mp4_youtube'

interface Props {
  open: boolean
  onClose: () => void
  backendUrl: string
  videoId: string
  /** Display name shown in the modal header (project / video title). */
  videoTitle?: string
  /** Disable submit when there are no scenes or scenes are still generating. */
  disabledReason?: string | null
}

type JobStatus = 'queued' | 'running' | 'done' | 'error'

interface JobView {
  id: string
  status: JobStatus
  progress: number
  error?: string | null
  kind?: ExportKind
}

const POLL_INTERVAL_MS = 1000
const POLL_TIMEOUT_MS = 10 * 60 * 1000 // 10 minutes

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('homepilot_auth_token') || ''
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function trimBackend(u: string): string {
  return u.replace(/\/+$/, '')
}

export default function CreatorExportWizard({
  open,
  onClose,
  backendUrl,
  videoId,
  videoTitle,
  disabledReason,
}: Props) {
  const [step, setStep] = useState<1 | 2>(1)
  const [kind, setKind] = useState<ExportKind>('mp4_youtube')
  const [job, setJob] = useState<JobView | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // Race protection: a monotonically-increasing token; every submit captures
  // the current value, and the poller drops responses whose epoch < current.
  const epochRef = useRef(0)

  // Reset modal whenever it opens.
  useEffect(() => {
    if (open) {
      setStep(1)
      setJob(null)
      setSubmitError(null)
    } else {
      // Closing the modal invalidates any in-flight poll.
      epochRef.current += 1
    }
  }, [open])

  const downloadUrl = useMemo(() => {
    if (!job || job.status !== 'done') return ''
    const tok = localStorage.getItem('homepilot_auth_token') || ''
    const qp = tok ? `?token=${encodeURIComponent(tok)}` : ''
    return `${trimBackend(backendUrl)}/studio/videos/${videoId}/export/jobs/${job.id}/download${qp}`
  }, [job, backendUrl, videoId])

  const pollJob = useCallback(
    async (jobId: string, myEpoch: number) => {
      const url = `${trimBackend(backendUrl)}/studio/videos/${videoId}/export/jobs/${jobId}`
      const start = Date.now()
      // Polling loop with a hard upper bound.
      // We bail on epoch mismatch so closing the modal cancels the loop.
      while (Date.now() - start < POLL_TIMEOUT_MS) {
        if (epochRef.current !== myEpoch) return
        try {
          const r = await fetch(url, { headers: { ...authHeaders() } })
          if (epochRef.current !== myEpoch) return
          if (!r.ok) {
            setJob((prev) =>
              prev ? { ...prev, status: 'error', error: `HTTP ${r.status}` } : prev,
            )
            return
          }
          const j = await r.json()
          if (epochRef.current !== myEpoch) return
          setJob({
            id: j.id,
            status: j.status,
            progress: typeof j.progress === 'number' ? j.progress : 0,
            error: j.error || null,
            kind: j.kind,
          })
          if (j.status === 'done' || j.status === 'error') return
        } catch (err: any) {
          if (epochRef.current !== myEpoch) return
          setJob((prev) =>
            prev
              ? { ...prev, status: 'error', error: String(err?.message || err) }
              : prev,
          )
          return
        }
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
      }
      // Timed out: surface to the user, leave the job alone so they can
      // re-open the wizard later if it does eventually finish.
      if (epochRef.current === myEpoch) {
        setJob((prev) =>
          prev ? { ...prev, status: 'error', error: 'Render timed out' } : prev,
        )
      }
    },
    [backendUrl, videoId],
  )

  const handleStart = useCallback(async () => {
    setSubmitError(null)
    epochRef.current += 1
    const myEpoch = epochRef.current
    setStep(2)
    setJob({ id: '', status: 'queued', progress: 0, kind })
    try {
      const r = await fetch(
        `${trimBackend(backendUrl)}/studio/videos/${videoId}/export/mp4`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify({ kind }),
        },
      )
      if (epochRef.current !== myEpoch) return
      if (!r.ok) {
        const text = await r.text().catch(() => '')
        const detail = text || `HTTP ${r.status}`
        setSubmitError(detail)
        setJob({ id: '', status: 'error', progress: 0, error: detail, kind })
        return
      }
      const j = await r.json()
      if (epochRef.current !== myEpoch) return
      setJob({
        id: j.id,
        status: j.status,
        progress: typeof j.progress === 'number' ? j.progress : 0,
        kind: j.kind,
      })
      void pollJob(j.id, myEpoch)
    } catch (err: any) {
      if (epochRef.current !== myEpoch) return
      const msg = String(err?.message || err)
      setSubmitError(msg)
      setJob({ id: '', status: 'error', progress: 0, error: msg, kind })
    }
  }, [backendUrl, videoId, kind, pollJob])

  if (!open) return null

  const submitDisabled = Boolean(disabledReason)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Export video"
    >
      <div
        className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#0b0b0c] text-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <div>
            <div className="text-sm font-semibold">Export video</div>
            {videoTitle ? (
              <div className="text-xs text-white/50 truncate max-w-[28rem]">{videoTitle}</div>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/10 text-white/60 hover:text-white"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-5 space-y-4">
          {step === 1 && (
            <>
              <div className="text-xs text-white/60">
                Choose the encode profile. Both produce an .mp4 file you can
                download.
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setKind('mp4_plain')}
                  className={[
                    'text-left rounded-xl border p-4 transition-all',
                    kind === 'mp4_plain'
                      ? 'border-cyan-400/60 bg-cyan-400/5'
                      : 'border-white/10 hover:border-white/30 bg-white/5',
                  ].join(' ')}
                  aria-pressed={kind === 'mp4_plain'}
                >
                  <div className="flex items-center gap-2 font-medium">
                    <Film size={16} className="text-cyan-300" />
                    MP4 (edit / share)
                  </div>
                  <div className="mt-2 text-[11px] leading-relaxed text-white/60">
                    Balanced size and quality. Plays on any device. Good for
                    re-editing later in another tool.
                  </div>
                  <div className="mt-2 text-[10px] text-white/40">
                    H.264 · CRF 20 · AAC 128 kbps
                  </div>
                </button>

                <button
                  type="button"
                  onClick={() => setKind('mp4_youtube')}
                  className={[
                    'text-left rounded-xl border p-4 transition-all',
                    kind === 'mp4_youtube'
                      ? 'border-red-400/60 bg-red-400/5'
                      : 'border-white/10 hover:border-white/30 bg-white/5',
                  ].join(' ')}
                  aria-pressed={kind === 'mp4_youtube'}
                >
                  <div className="flex items-center gap-2 font-medium">
                    <Youtube size={16} className="text-red-400" />
                    MP4 for YouTube
                  </div>
                  <div className="mt-2 text-[11px] leading-relaxed text-white/60">
                    Matches YouTube's recommended upload spec. Faststart layout
                    means YouTube ingests without re-mux.
                  </div>
                  <div className="mt-2 text-[10px] text-white/40">
                    H.264 high · CRF 18 · AAC 192 kbps · +faststart
                  </div>
                </button>
              </div>

              {disabledReason ? (
                <div className="flex items-start gap-2 rounded-lg border border-amber-400/30 bg-amber-400/10 p-3 text-[12px] text-amber-200">
                  <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
                  <span>{disabledReason}</span>
                </div>
              ) : null}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-3 py-1.5 rounded-lg text-sm text-white/70 hover:bg-white/10"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleStart}
                  disabled={submitDisabled}
                  className={[
                    'px-3 py-1.5 rounded-lg text-sm font-medium',
                    submitDisabled
                      ? 'bg-white/10 text-white/40 cursor-not-allowed'
                      : 'bg-white text-black hover:bg-white/90',
                  ].join(' ')}
                >
                  Render
                </button>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              {job?.status === 'done' ? (
                <div className="space-y-4">
                  <div className="flex items-center gap-2 text-emerald-300">
                    <CheckCircle2 size={18} />
                    <span className="font-medium">Render complete</span>
                  </div>
                  <a
                    href={downloadUrl}
                    download
                    className="flex items-center justify-center gap-2 w-full px-4 py-2.5 rounded-xl bg-white text-black font-medium hover:bg-white/90"
                  >
                    <Download size={16} />
                    Download .mp4
                  </a>
                  <div className="text-[11px] text-white/40 text-center">
                    {job.kind === 'mp4_youtube' ? 'YouTube-optimized' : 'Plain MP4'}
                  </div>
                </div>
              ) : job?.status === 'error' ? (
                <div className="space-y-3">
                  <div className="flex items-start gap-2 rounded-lg border border-red-400/30 bg-red-400/10 p-3 text-[12px] text-red-200">
                    <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
                    <div>
                      <div className="font-medium mb-0.5">Render failed</div>
                      <div className="text-red-300/80 break-words">
                        {job.error || submitError || 'Unknown error'}
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setStep(1)}
                    className="w-full px-3 py-1.5 rounded-lg text-sm bg-white/10 hover:bg-white/15"
                  >
                    Try again
                  </button>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-white/80">
                    <Loader2 size={16} className="animate-spin" />
                    <span className="text-sm">
                      {job?.status === 'queued' ? 'Queued…' : 'Rendering…'}
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-white/10 overflow-hidden">
                    <div
                      className="h-full bg-cyan-400 transition-all"
                      style={{ width: `${Math.max(2, Math.min(100, job?.progress || 0))}%` }}
                    />
                  </div>
                  <div className="text-[11px] text-white/40 text-center">
                    {Math.round(job?.progress || 0)}% — this can take a minute or two
                  </div>
                </div>
              )}

              <div className="flex justify-end pt-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-3 py-1.5 rounded-lg text-sm text-white/70 hover:bg-white/10"
                >
                  Close
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

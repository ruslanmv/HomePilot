/**
 * CreatorExportWizard — 4-step modal for exporting a Creator Studio video
 * with in-browser Piper TTS narration.
 *
 * Flow:
 *   1. Target    — MP4 (edit/share) vs MP4 for YouTube.
 *   2. Voiceover — Piper voice + rate + pitch + subtitle burn-in toggle,
 *                  with a Preview button.
 *   3. Generate  — synthesize narration for every scene that has text
 *                  (or re-synthesize all if the user checks "regenerate")
 *                  and upload each WAV to the backend.
 *   4. Render    — POST /studio/videos/{id}/export/mp4, poll, download.
 *
 * Race protection:
 *   Every async op captures a per-mount epoch; closing the modal or
 *   starting a new render bumps the epoch and stale responses are
 *   dropped. Same pattern as App.tsx's account-switch guard.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  Film,
  Loader2,
  Mic,
  Play,
  Square,
  X,
  Youtube,
} from 'lucide-react'

import {
  listVoices,
  synthesizeToBlob,
  speak as piperSpeak,
  stop as piperStop,
  isSupported as piperSupported,
  getSelectedVoiceId,
  setSelectedVoiceId,
} from '../tts/piperTts'
import { DEFAULT_PIPER_VOICE_ID } from '../tts/piperVoices'

export type ExportKind = 'mp4_plain' | 'mp4_youtube'

/** Minimum scene info the wizard needs. Matches the flat shape used
 *  inside CreatorStudioEditor. */
export interface WizardScene {
  id: string
  idx: number
  narration: string
  audioUrl: string | null
}

interface Props {
  open: boolean
  onClose: () => void
  backendUrl: string
  videoId: string
  /** Ordered scenes the render will concatenate. */
  scenes: WizardScene[]
  /** Display name shown in the modal header. */
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
const PREVIEW_TEXT = 'Hello, this is a preview of your selected voice.'

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('homepilot_auth_token') || ''
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function trimBackend(u: string): string {
  return u.replace(/\/+$/, '')
}

type Step = 1 | 2 | 3 | 4

export default function CreatorExportWizard({
  open,
  onClose,
  backendUrl,
  videoId,
  scenes,
  videoTitle,
  disabledReason,
}: Props) {
  // ── Step ─────────────────────────────────────────────────────────────────
  const [step, setStep] = useState<Step>(1)

  // ── Step 1 state ─────────────────────────────────────────────────────────
  const [kind, setKind] = useState<ExportKind>('mp4_youtube')

  // ── Step 2 state ─────────────────────────────────────────────────────────
  const voices = useMemo(() => listVoices(), [])
  const [voiceId, setVoiceId] = useState<string>(() =>
    piperSupported() ? getSelectedVoiceId() : DEFAULT_PIPER_VOICE_ID,
  )
  const [rate, setRate] = useState<number>(0.9)
  const [pitch, setPitch] = useState<number>(1.0)
  const [subtitlesBurnIn, setSubtitlesBurnIn] = useState<boolean>(true)
  const [regenerateAll, setRegenerateAll] = useState<boolean>(false)
  const [previewing, setPreviewing] = useState<boolean>(false)
  const [previewError, setPreviewError] = useState<string | null>(null)

  // ── Step 3 state ─────────────────────────────────────────────────────────
  const [genIdx, setGenIdx] = useState<number>(0)
  const [genTotal, setGenTotal] = useState<number>(0)
  const [genError, setGenError] = useState<string | null>(null)

  // ── Step 4 state ─────────────────────────────────────────────────────────
  const [job, setJob] = useState<JobView | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // Race protection.
  const epochRef = useRef(0)

  // Reset when modal opens or closes.
  useEffect(() => {
    if (open) {
      setStep(1)
      setJob(null)
      setSubmitError(null)
      setGenIdx(0)
      setGenTotal(0)
      setGenError(null)
      setPreviewing(false)
      setPreviewError(null)
    } else {
      epochRef.current += 1
      try { piperStop() } catch { /* ignore */ }
    }
  }, [open])

  // Persist voice selection so subsequent renders remember the pick.
  useEffect(() => {
    if (voiceId) setSelectedVoiceId(voiceId)
  }, [voiceId])

  const downloadUrl = useMemo(() => {
    if (!job || job.status !== 'done') return ''
    const tok = localStorage.getItem('homepilot_auth_token') || ''
    const qp = tok ? `?token=${encodeURIComponent(tok)}` : ''
    return `${trimBackend(backendUrl)}/studio/videos/${videoId}/export/jobs/${job.id}/download${qp}`
  }, [job, backendUrl, videoId])

  // ── Step 2 — Preview ─────────────────────────────────────────────────────

  const handlePreview = useCallback(async () => {
    setPreviewError(null)
    if (previewing) {
      try { piperStop() } catch { /* ignore */ }
      setPreviewing(false)
      return
    }
    if (!piperSupported()) {
      setPreviewError('Piper requires a secure context (https) with Web Audio + OPFS support.')
      return
    }
    setPreviewing(true)
    try {
      await piperSpeak(PREVIEW_TEXT, {
        voiceId,
        rate,
        onEnd: () => setPreviewing(false),
        onError: (err) => {
          setPreviewError(String(err?.message || err))
          setPreviewing(false)
        },
      })
    } catch (err: any) {
      setPreviewError(String(err?.message || err))
      setPreviewing(false)
    }
  }, [previewing, voiceId, rate])

  // ── Step 3 — Generate all scene narrations ───────────────────────────────

  /** Scenes that need synthesis under the current toggle state. */
  const scenesToSynthesize = useMemo(
    () =>
      scenes.filter((s) => {
        const hasText = (s.narration || '').trim().length > 0
        if (!hasText) return false
        if (regenerateAll) return true
        return !s.audioUrl
      }),
    [scenes, regenerateAll],
  )

  const handleGenerate = useCallback(async () => {
    if (!piperSupported()) {
      setGenError('Piper is not supported in this browser. Use a Chromium-based browser on https.')
      return
    }
    epochRef.current += 1
    const myEpoch = epochRef.current
    setStep(3)
    setGenError(null)
    setGenIdx(0)
    setGenTotal(scenesToSynthesize.length)

    if (scenesToSynthesize.length === 0) {
      // Nothing to synthesize — jump straight to render.
      setStep(4)
      void startRender(myEpoch)
      return
    }

    for (let i = 0; i < scenesToSynthesize.length; i++) {
      if (epochRef.current !== myEpoch) return
      const scene = scenesToSynthesize[i]
      try {
        const blob = await synthesizeToBlob(scene.narration, { voiceId })
        if (epochRef.current !== myEpoch) return

        // Upload to the backend so render_mp4 can mix it in.
        const fd = new FormData()
        fd.append('file', blob, `${scene.id}.wav`)
        const url = `${trimBackend(backendUrl)}/studio/videos/${videoId}/scenes/${scene.id}/narration`
        const r = await fetch(url, {
          method: 'POST',
          headers: { ...authHeaders() },
          body: fd,
        })
        if (epochRef.current !== myEpoch) return
        if (!r.ok) {
          const text = await r.text().catch(() => '')
          throw new Error(text || `Upload failed (HTTP ${r.status})`)
        }
      } catch (err: any) {
        if (epochRef.current !== myEpoch) return
        setGenError(
          `Scene ${scene.idx + 1}: ${String(err?.message || err)}`,
        )
        return
      }
      setGenIdx(i + 1)
    }

    if (epochRef.current !== myEpoch) return
    // All done — kick off the render.
    setStep(4)
    void startRender(myEpoch)
  }, [scenesToSynthesize, voiceId, backendUrl, videoId])

  // ── Step 4 — Render + poll ───────────────────────────────────────────────

  const pollJob = useCallback(
    async (jobId: string, myEpoch: number) => {
      const url = `${trimBackend(backendUrl)}/studio/videos/${videoId}/export/jobs/${jobId}`
      const start = Date.now()
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
      if (epochRef.current === myEpoch) {
        setJob((prev) =>
          prev ? { ...prev, status: 'error', error: 'Render timed out' } : prev,
        )
      }
    },
    [backendUrl, videoId],
  )

  const startRender = useCallback(
    async (myEpoch: number) => {
      setSubmitError(null)
      setJob({ id: '', status: 'queued', progress: 0, kind })
      try {
        const r = await fetch(
          `${trimBackend(backendUrl)}/studio/videos/${videoId}/export/mp4`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify({
              kind,
              audio_rate: rate,
              audio_pitch: pitch,
              subtitles: subtitlesBurnIn ? 'burn_in' : 'none',
            }),
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
    },
    [backendUrl, videoId, kind, rate, pitch, subtitlesBurnIn, pollJob],
  )

  if (!open) return null

  const submitDisabled = Boolean(disabledReason)

  // ── UI ───────────────────────────────────────────────────────────────────

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Export video"
    >
      <div
        className="w-full max-w-xl rounded-2xl border border-white/10 bg-[#0b0b0c] text-white shadow-2xl max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3 flex-shrink-0">
          <div>
            <div className="text-sm font-semibold">Export video</div>
            {videoTitle ? (
              <div className="text-xs text-white/50 truncate max-w-[28rem]">{videoTitle}</div>
            ) : null}
          </div>
          <div className="flex items-center gap-3 text-[11px] text-white/40">
            <span className={step >= 1 ? 'text-white/80' : ''}>1 · Target</span>
            <span>›</span>
            <span className={step >= 2 ? 'text-white/80' : ''}>2 · Voiceover</span>
            <span>›</span>
            <span className={step >= 3 ? 'text-white/80' : ''}>3 · Narration</span>
            <span>›</span>
            <span className={step >= 4 ? 'text-white/80' : ''}>4 · Render</span>
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

        {/* Body */}
        <div className="px-5 py-5 space-y-4 overflow-y-auto">
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
                  onClick={() => setStep(2)}
                  disabled={submitDisabled}
                  className={[
                    'px-3 py-1.5 rounded-lg text-sm font-medium',
                    submitDisabled
                      ? 'bg-white/10 text-white/40 cursor-not-allowed'
                      : 'bg-white text-black hover:bg-white/90',
                  ].join(' ')}
                >
                  Next: Voiceover
                </button>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <div className="flex items-center gap-2 text-xs text-white/60">
                <Mic size={14} className="text-cyan-300" />
                Piper runs fully in-browser via WebAssembly. First use
                downloads a voice model (~20 MB, cached).
              </div>

              <div className="space-y-3">
                <label className="block text-[11px] uppercase tracking-wide text-white/50">
                  Piper voice
                </label>
                <select
                  value={voiceId}
                  onChange={(e) => setVoiceId(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-white/90 focus:outline-none focus:border-white/30"
                >
                  {voices.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name} — {v.lang} · {v.gender} · {v.quality}
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="flex items-center justify-between text-[11px] uppercase tracking-wide text-white/50">
                    <span>Rate</span>
                    <span className="font-mono text-white/70">{rate.toFixed(2)}</span>
                  </div>
                  <input
                    type="range"
                    min={0.5}
                    max={2.0}
                    step={0.05}
                    value={rate}
                    onChange={(e) => setRate(Number(e.target.value))}
                    className="w-full accent-cyan-400"
                  />
                </div>
                <div>
                  <div className="flex items-center justify-between text-[11px] uppercase tracking-wide text-white/50">
                    <span>Pitch</span>
                    <span className="font-mono text-white/70">{pitch.toFixed(2)}</span>
                  </div>
                  <input
                    type="range"
                    min={0.5}
                    max={2.0}
                    step={0.05}
                    value={pitch}
                    onChange={(e) => setPitch(Number(e.target.value))}
                    className="w-full accent-cyan-400"
                  />
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handlePreview}
                  className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm bg-white/10 hover:bg-white/15 border border-white/10"
                >
                  {previewing ? <Square size={14} /> : <Play size={14} />}
                  {previewing ? 'Stop preview' : 'Preview voice'}
                </button>
                <span className="text-[11px] text-white/40 truncate">{PREVIEW_TEXT}</span>
              </div>

              {previewError ? (
                <div className="text-[11px] text-red-300/80">{previewError}</div>
              ) : null}

              <label className="flex items-center gap-2 text-sm text-white/80 cursor-pointer">
                <input
                  type="checkbox"
                  checked={subtitlesBurnIn}
                  onChange={(e) => setSubtitlesBurnIn(e.target.checked)}
                  className="accent-cyan-400"
                />
                Burn subtitles into the video (from scene narration text)
              </label>

              <label className="flex items-center gap-2 text-sm text-white/80 cursor-pointer">
                <input
                  type="checkbox"
                  checked={regenerateAll}
                  onChange={(e) => setRegenerateAll(e.target.checked)}
                  className="accent-cyan-400"
                />
                Regenerate narration for all scenes (otherwise keep existing audio)
              </label>

              <div className="text-[11px] text-white/40">
                {scenesToSynthesize.length === 0
                  ? 'All scenes already have narration audio — nothing to synthesize.'
                  : `${scenesToSynthesize.length} scene${scenesToSynthesize.length === 1 ? '' : 's'} will be synthesized with the selected voice.`}
              </div>

              <div className="flex justify-between gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setStep(1)}
                  className="px-3 py-1.5 rounded-lg text-sm text-white/70 hover:bg-white/10"
                >
                  Back
                </button>
                <button
                  type="button"
                  onClick={handleGenerate}
                  className="px-3 py-1.5 rounded-lg text-sm font-medium bg-white text-black hover:bg-white/90"
                >
                  {scenesToSynthesize.length === 0 ? 'Skip & render' : 'Generate narration'}
                </button>
              </div>
            </>
          )}

          {step === 3 && (
            <>
              <div className="flex items-center gap-2 text-white/80">
                <Loader2 size={16} className="animate-spin" />
                <span className="text-sm">Synthesizing narration…</span>
              </div>
              <div className="h-2 rounded-full bg-white/10 overflow-hidden">
                <div
                  className="h-full bg-cyan-400 transition-all"
                  style={{
                    width: `${genTotal === 0 ? 0 : Math.round((genIdx / genTotal) * 100)}%`,
                  }}
                />
              </div>
              <div className="text-[11px] text-white/40 text-center">
                {genIdx} of {genTotal} scenes
              </div>

              {genError ? (
                <div className="space-y-3">
                  <div className="flex items-start gap-2 rounded-lg border border-red-400/30 bg-red-400/10 p-3 text-[12px] text-red-200">
                    <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
                    <div>
                      <div className="font-medium mb-0.5">Narration synthesis failed</div>
                      <div className="text-red-300/80 break-words">{genError}</div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setStep(2)}
                    className="w-full px-3 py-1.5 rounded-lg text-sm bg-white/10 hover:bg-white/15"
                  >
                    Back to voiceover
                  </button>
                </div>
              ) : null}
            </>
          )}

          {step === 4 && (
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
                    {subtitlesBurnIn ? ' · subtitles burned in' : ''}
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
                    onClick={() => setStep(2)}
                    className="w-full px-3 py-1.5 rounded-lg text-sm bg-white/10 hover:bg-white/15"
                  >
                    Back to voiceover
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
                      style={{
                        width: `${Math.max(2, Math.min(100, job?.progress || 0))}%`,
                      }}
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

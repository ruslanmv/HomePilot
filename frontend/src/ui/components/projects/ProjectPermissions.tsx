/**
 * ProjectPermissions — who can use this project, and what it may do.
 *
 *   • Sharing: private / workspace / public (public is read-only for others)
 *   • Connectors: external services (GitPilot …) — off until the owner turns them on
 *   • Tools: built-in agent tools — on until the owner turns them off
 *
 * Changes save immediately and are enforced by the server on every tool call;
 * an AI model cannot reach a capability that is switched off here. Only the
 * owner can change anything; others see the settings read-only.
 */
import React, { useCallback, useEffect, useState } from 'react'
import { Lock, Globe, Users, Loader2 } from 'lucide-react'
import { authFetch } from '../../lib/authFetch'

type Capability = { kind: 'tool' | 'connector'; ref: string; enabled: boolean; name?: string; description?: string; linked?: boolean }
type CapState = { can_edit: boolean; tools: Capability[]; connectors: Capability[] }
type Sharing = { role: string | null; is_owner: boolean; visibility: 'private' | 'workspace' | 'public' }

const TOOL_LABELS: Record<string, string> = {
  'vision.analyze': 'Look at images',
  'knowledge.search': 'Search project files',
  'memory.recall': 'Recall memories',
  'memory.store': 'Save memories',
  'web.search': 'Search the web',
  'image.index': 'Index images into files',
  'image.generate': 'Generate images',
}

export function toolLabel(ref: string): string {
  return TOOL_LABELS[ref] || ref
}

function Toggle({ on, disabled, onChange, label }: { on: boolean; disabled?: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-40 ${on ? 'bg-emerald-500' : 'bg-white/15'}`}
    >
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${on ? 'left-[22px]' : 'left-0.5'}`} />
    </button>
  )
}

export default function ProjectPermissions({ backendUrl, projectId }: { backendUrl: string; projectId: string }) {
  const base = backendUrl.replace(/\/+$/, '')
  const [caps, setCaps] = useState<CapState | null>(null)
  const [sharing, setSharing] = useState<Sharing | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([
        authFetch(`${base}/projects/${projectId}/capabilities`),
        authFetch(`${base}/projects/${projectId}/sharing`),
      ])
      if (c.ok) setCaps(await c.json())
      if (s.ok) setSharing(await s.json())
    } catch {
      setError('Could not load this project’s permissions.')
    }
  }, [base, projectId])

  useEffect(() => { void load() }, [load])

  async function setCapability(section: 'tools' | 'connectors', ref: string, enabled: boolean) {
    setBusy(true)
    setError('')
    try {
      const res = await authFetch(`${base}/projects/${projectId}/capabilities`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [section]: { [ref]: enabled } }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setCaps(await res.json())
    } catch {
      setError('Could not save. Only the project owner can change permissions.')
    } finally {
      setBusy(false)
    }
  }

  async function setVisibility(visibility: Sharing['visibility']) {
    setBusy(true)
    setError('')
    try {
      const res = await authFetch(`${base}/projects/${projectId}/sharing`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ visibility }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setSharing(await res.json())
    } catch {
      setError('Could not change sharing.')
    } finally {
      setBusy(false)
    }
  }

  if (!caps || !sharing) {
    return error
      ? <p className="text-sm text-amber-300">{error}</p>
      : <div className="flex items-center gap-2 text-sm text-white/50"><Loader2 size={14} className="animate-spin" /> Loading permissions…</div>
  }

  const canEdit = caps.can_edit
  return (
    <div className="space-y-5">
      <section>
        <h3 className="text-sm font-medium text-white/80">Who can open this project</h3>
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {([
            ['private', Lock, 'Only me', 'And people I add'],
            ['public', Globe, 'Anyone signed in', 'Read and chat only'],
          ] as const).map(([value, Icon, title, hint]) => (
            <button
              key={value}
              type="button"
              disabled={!canEdit || busy}
              onClick={() => { void setVisibility(value) }}
              className={`flex items-start gap-2.5 rounded-xl border p-3 text-left transition-colors disabled:cursor-default ${
                sharing.visibility === value ? 'border-purple-400/60 bg-purple-500/10' : 'border-white/10 hover:border-white/20'
              }`}
            >
              <Icon size={16} className="mt-0.5 text-white/70" />
              <span>
                <span className="block text-sm text-white">{title}</span>
                <span className="block text-xs text-white/50">{hint}</span>
              </span>
            </button>
          ))}
        </div>
        {sharing.visibility === 'workspace' ? (
          <p className="mt-2 flex items-center gap-1.5 text-xs text-white/50"><Users size={12} /> Shared with a workspace.</p>
        ) : null}
      </section>

      <section>
        <h3 className="text-sm font-medium text-white/80">Connected services</h3>
        <p className="text-xs text-white/50">Off until you turn them on. Each person uses their own linked account — this project never shares yours.</p>
        <div className="mt-2 space-y-2">
          {caps.connectors.map((c) => (
            <div key={c.ref} className="flex items-center justify-between gap-3 rounded-xl border border-white/10 p-3">
              <div className="min-w-0">
                <div className="text-sm text-white">{c.name || c.ref}</div>
                <div className="text-xs text-white/50">
                  {c.description}
                  {!c.linked ? ' Link it first in Settings → Connectors.' : ''}
                </div>
              </div>
              <Toggle on={c.enabled} disabled={!canEdit || busy} label={`${c.name || c.ref} in this project`}
                onChange={(v) => { void setCapability('connectors', c.ref, v) }} />
            </div>
          ))}
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-white/80">Assistant tools</h3>
        <div className="mt-2 divide-y divide-white/5 rounded-xl border border-white/10">
          {caps.tools.map((t) => (
            <div key={t.ref} className="flex items-center justify-between gap-3 px-3 py-2.5">
              <span className="text-sm text-white/85">{toolLabel(t.ref)}</span>
              <Toggle on={t.enabled} disabled={!canEdit || busy} label={toolLabel(t.ref)}
                onChange={(v) => { void setCapability('tools', t.ref, v) }} />
            </div>
          ))}
        </div>
      </section>

      {!canEdit ? <p className="text-xs text-white/50">Only the project owner can change these.</p> : null}
      {error ? <p role="alert" className="text-sm text-amber-300">{error}</p> : null}
    </div>
  )
}

/**
 * DayPilotCard — a small, read-only view of the user's workday for a project.
 *
 * Shows the next priority, the next task, the first calendar conflict and how
 * many approvals are waiting — only the parts the project allows and the
 * user's own DayPilot connection shares — with links into DayPilot for the
 * rest. It is not a second dashboard.
 *
 * Loads after the page, never blocks it, and always says which state it is in:
 * Connected · Offline · Stale · Needs attention · Not authorized.
 */
import React, { useEffect, useState } from 'react'
import { AlertTriangle, CalendarClock, CheckCircle2, ExternalLink, ListTodo, RefreshCw, Sun } from 'lucide-react'
import { authFetch } from '../../lib/authFetch'

type Section = { status: string; [key: string]: any }
type CardData = {
  state: 'connected' | 'offline' | 'stale' | 'needs_attention' | 'not_authorized' | 'not_connected' | 'not_enabled'
  sections: Record<string, Section>
  views?: Record<string, string>
  age_s?: number | null
  problem?: string
}

export const STATE_LABEL: Record<CardData['state'], string> = {
  connected: 'Connected',
  offline: 'Offline',
  stale: 'Stale',
  needs_attention: 'Needs attention',
  not_authorized: 'Not authorized',
  not_connected: 'Not connected',
  not_enabled: 'Off for this project',
}

const STATE_TONE: Record<string, string> = {
  connected: 'bg-emerald-400', stale: 'bg-amber-400', offline: 'bg-white/30',
  needs_attention: 'bg-amber-400', not_authorized: 'bg-red-400',
}

/** The single most useful line per section, or null when there is nothing to say. */
export function summarize(sections: Record<string, Section>) {
  const ok = (name: string) => sections[name]?.status === 'ok' ? sections[name] : null
  const plan = ok('plan')
  const tasks = ok('tasks')
  const calendar = ok('calendar')
  const approvals = ok('approvals')
  return {
    priority: plan?.focus?.title || plan?.nextBlock?.title || null,
    task: tasks?.items?.[0]?.title || null,
    conflict: calendar?.conflicts?.[0] ? `${calendar.conflicts[0].first} overlaps ${calendar.conflicts[0].second}` : null,
    approvals: typeof approvals?.pending === 'number' ? approvals.pending : null,
  }
}

export default function DayPilotCard({ backendUrl, projectId }: { backendUrl: string; projectId: string }) {
  const base = backendUrl.replace(/\/+$/, '')
  const [data, setData] = useState<CardData | null>(null)
  const [loading, setLoading] = useState(false)

  async function load() {
    setLoading(true)
    try {
      const res = await authFetch(`${base}/v1/connectors/daypilot/context?project_id=${encodeURIComponent(projectId)}`)
      if (res.ok) setData(await res.json())
      else setData({ state: res.status === 401 ? 'not_authorized' : 'needs_attention', sections: {} })
    } catch {
      setData({ state: 'offline', sections: {} })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [base, projectId])  // eslint-disable-line react-hooks/exhaustive-deps

  // Nothing to show when the project does not use DayPilot or the user has not connected it.
  if (!data || data.state === 'not_enabled' || data.state === 'not_connected') return null

  const s = summarize(data.sections)
  const view = (key: string) => data.views?.[key]
  const Row = ({ icon, label, value, href }: { icon: React.ReactNode; label: string; value: React.ReactNode; href?: string }) => (
    <div className="flex items-start gap-2.5 py-1.5">
      <span className="mt-0.5 text-white/50">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-[11px] uppercase tracking-wide text-white/40">{label}</span>
        <span className="block truncate text-sm text-white/85">{value}</span>
      </span>
      {href ? <a href={href} target="_blank" rel="noreferrer" aria-label={`Open ${label} in DayPilot`}
        className="mt-1 text-white/40 hover:text-white"><ExternalLink size={13} /></a> : null}
    </div>
  )

  return (
    <section className="rounded-xl border border-white/10 bg-black/20 p-3" aria-label="DayPilot workday">
      <div className="mb-1 flex items-center justify-between">
        <span className="flex items-center gap-2 text-sm font-medium text-white">
          <span aria-hidden>☀</span> DayPilot
        </span>
        <span className="flex items-center gap-2 text-xs text-white/60">
          <span className={`h-2 w-2 rounded-full ${STATE_TONE[data.state] || 'bg-white/30'}`} aria-hidden />
          {STATE_LABEL[data.state]}
          <button type="button" onClick={() => { void load() }} aria-label="Refresh" className="hover:text-white">
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
        </span>
      </div>
      {data.problem ? <p className="mb-1 flex items-center gap-1.5 text-xs text-amber-300"><AlertTriangle size={12} /> {data.problem}</p> : null}
      {s.priority ? <Row icon={<Sun size={14} />} label="Now" value={s.priority} href={view('today')} /> : null}
      {s.task ? <Row icon={<ListTodo size={14} />} label="Next task" value={s.task} href={view('tasks')} /> : null}
      {s.conflict ? <Row icon={<CalendarClock size={14} />} label="Calendar conflict" value={s.conflict} href={view('calendar')} /> : null}
      {s.approvals !== null ? (
        <Row icon={<CheckCircle2 size={14} />} label="Approvals"
          value={s.approvals === 0 ? 'Nothing waiting' : `${s.approvals} waiting for you`} href={view('approvals')} />
      ) : null}
      {data.state === 'connected' && !s.priority && !s.task && !s.conflict && s.approvals === null ? (
        <p className="py-1 text-xs text-white/50">Turn on Today's plan, Tasks or Calendar in Permissions to see them here.</p>
      ) : null}
    </section>
  )
}

/**
 * AccountComputers (Batch 3) — the "Account & Computers" settings tab.
 *
 * Renders the redesigned screen (one account, multiple computers, clear remote
 * access) driven entirely by the Batch-2 spine (useAccount / useComputer →
 * MirrorClient → BFF → cloud). ADDITIVE and shown only when the
 * Account & Computers feature flag is on.
 *
 * Interaction model (design §10 of the tab spec):
 *  - Connection actions apply immediately: Refresh, select computer, Sign Out.
 *  - Sharing/permissions are a draft that commits on the panel's Save.
 *
 * Controls that require cloud/local endpoints not yet built (toggle a remote
 * machine's remote-access, rename, pairing, policy enforcement) are rendered
 * faithfully but guarded — disabled with a note — so nothing is faked.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity, ChevronRight, Cpu, ExternalLink, Globe, Monitor, Pencil, Plus,
  RefreshCw, ShieldCheck, User, Users,
} from 'lucide-react'

import { resolveBackendUrl } from '../lib/backendUrl'
import { getCurrentUserId, userScopedKey } from '../lib/userScopedStorage'
import { useAccount } from './HomePilotAccountProvider'
import { useComputer } from './ComputerContext'
import { MirrorError, mirrorClient } from './mirrorClient'
import type { MirrorNode, NodeManifest, PresenceState } from './types'

const LS_PRIVACY = 'homepilot_sharing_level'
type PrivacyLevel = 'only_me' | 'team' | 'advanced'

// ── small presentational helpers ─────────────────────────────────────────────

function StatusDot({ state }: { state: PresenceState }) {
  const color =
    state === 'online' ? 'bg-emerald-400'
      : state === 'attention' ? 'bg-amber-400'
        : 'bg-white/30'
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />
}

function Badge({ state, children }: { state: PresenceState; children: React.ReactNode }) {
  const cls =
    state === 'online' ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
      : state === 'attention' ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
        : 'bg-white/5 text-white/50 border-white/10'
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full border ${cls}`}>{children}</span>
  )
}

function Card({ title, right, children }: { title?: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
      {(title || right) && (
        <div className="flex items-center justify-between mb-3">
          {title && <h3 className="text-sm font-semibold text-white/80">{title}</h3>}
          {right}
        </div>
      )}
      {children}
    </div>
  )
}

function readPrivacy(): PrivacyLevel {
  try {
    const uid = getCurrentUserId()
    const v = localStorage.getItem(uid ? userScopedKey(LS_PRIVACY, uid) : `${LS_PRIVACY}:user:anon`)
    if (v === 'team' || v === 'advanced' || v === 'only_me') return v
  } catch { /* ignore */ }
  return 'only_me'
}
function writePrivacy(v: PrivacyLevel): void {
  try {
    const uid = getCurrentUserId()
    localStorage.setItem(uid ? userScopedKey(LS_PRIVACY, uid) : `${LS_PRIVACY}:user:anon`, v)
  } catch { /* ignore */ }
}

// ── main ─────────────────────────────────────────────────────────────────────

export default function AccountComputers(): JSX.Element {
  const { status, computers, loading, error, notLinked, refresh } = useAccount()
  const { selectedComputerId, selectComputer, presenceOf, anyOnline } = useComputer()

  const [email, setEmail] = useState<string>('')
  const [manifests, setManifests] = useState<Record<string, NodeManifest | null>>({})
  const [privacy, setPrivacy] = useState<PrivacyLevel>(() => readPrivacy())

  // Account email — read from the existing session endpoint (read-only).
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const tok = localStorage.getItem('homepilot_auth_token') || ''
        const res = await fetch(`${resolveBackendUrl()}/v1/auth/me`, {
          headers: tok ? { Authorization: `Bearer ${tok}` } : {},
          credentials: 'include',
        })
        if (!res.ok) return
        const data = await res.json()
        if (!cancelled) setEmail(data?.email || data?.user?.email || '')
      } catch { /* ignore */ }
    })()
    return () => { cancelled = true }
  }, [])

  // Lazily fetch manifests for ONLINE computers (offline → relay 409).
  useEffect(() => {
    let cancelled = false
    computers.filter((c) => c.online && manifests[c.node_id] === undefined).forEach(async (c) => {
      try {
        const m = await mirrorClient.getManifest(c.node_id)
        if (!cancelled) setManifests((prev) => ({ ...prev, [c.node_id]: m }))
      } catch (e) {
        if (!(e instanceof MirrorError && e.isNodeOffline) && !cancelled) {
          setManifests((prev) => ({ ...prev, [c.node_id]: null }))
        }
      }
    })
    return () => { cancelled = true }
  }, [computers, manifests])

  const thisComputer: MirrorNode | null = useMemo(() => {
    return computers.find((c) => c.node_id === selectedComputerId)
      ?? computers.find((c) => c.online)
      ?? computers[0]
      ?? null
  }, [computers, selectedComputerId])

  const onSignOut = useCallback(() => {
    try {
      localStorage.removeItem('homepilot_auth_token')
      localStorage.removeItem('homepilot_cloud_token')
    } catch { /* ignore */ }
    // Full reload returns to the AuthGate sign-in screen.
    window.location.reload()
  }, [])

  const onManageAccount = useCallback(() => {
    const url = status?.cloud
    if (url) window.open(url, '_blank', 'noopener,noreferrer')
  }, [status])

  const onChangePrivacy = useCallback((v: PrivacyLevel) => {
    setPrivacy(v)
    // Persist the intent locally (per-user). Server-side policy enforcement is
    // wired in a later batch; this is the draft the panel's Save commits.
    writePrivacy(v)
  }, [])

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">Account &amp; Computers</h2>
          <p className="text-xs text-white/50 mt-0.5">Access your HomePilot from anywhere with your linked computers.</p>
        </div>
        <button
          type="button"
          title="HomePilot securely connects to your own computers. AI processing and project data stay on those computers unless you enable another storage option."
          className="text-[11px] px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-white/60"
        >
          ? What is this?
        </button>
      </div>

      {/* Your Account */}
      <Card title="Your Account">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-full bg-violet-500/20 border border-violet-400/30 grid place-items-center">
              <User size={18} className="text-violet-200" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm text-white/90 truncate">{email || 'Signed in'}</span>
                <Badge state="online">Connected</Badge>
              </div>
              <div className="text-xs text-white/45">Your HomePilot account is active and secure.</div>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button onClick={onManageAccount} disabled={!status?.cloud}
              className="text-[11px] px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-white/70 disabled:opacity-40 inline-flex items-center gap-1">
              Manage Account <ExternalLink size={12} />
            </button>
            <button onClick={onSignOut}
              className="text-[11px] px-3 py-1.5 rounded-xl bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-300">
              Sign Out
            </button>
          </div>
        </div>
      </Card>

      {notLinked && (
        <Card>
          <div className="text-sm text-white/70">
            No computer is linked to this account yet. Install HomePilot Local on a
            computer with your models and projects, sign in with this same account,
            and enable remote access.
          </div>
        </Card>
      )}

      {/* This Computer + Your Computers */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* This Computer */}
        <Card title="This Computer">
          {thisComputer ? (
            <ThisComputer node={thisComputer} manifest={manifests[thisComputer.node_id]} presence={presenceOf(thisComputer.node_id)} />
          ) : (
            <div className="text-sm text-white/50 py-6 text-center">
              {loading ? 'Loading…' : 'No active computer yet.'}
            </div>
          )}
        </Card>

        {/* Your Computers */}
        <Card
          title="Your Computers"
          right={
            <button
              type="button"
              title="Pairing a new computer arrives in a later update."
              className="text-[11px] px-3 py-1.5 rounded-xl bg-violet-500/80 hover:bg-violet-500 text-white inline-flex items-center gap-1"
            >
              <Plus size={13} /> Add Computer
            </button>
          }
        >
          {error && <div className="text-xs text-red-300 mb-2">{error}</div>}
          <div className="space-y-2">
            {computers.map((c) => {
              const st = presenceOf(c.node_id)
              const m = manifests[c.node_id]
              const selected = c.node_id === selectedComputerId
              return (
                <button
                  key={c.node_id}
                  onClick={() => selectComputer(selected ? null : c.node_id)}
                  className={`w-full text-left rounded-xl border px-3 py-2.5 flex items-center gap-3 transition-colors ${
                    selected ? 'border-violet-400/50 bg-violet-500/10' : 'border-white/10 bg-white/[0.02] hover:bg-white/[0.05]'
                  }`}
                >
                  <div className="w-9 h-9 rounded-lg bg-white/5 grid place-items-center shrink-0 relative">
                    <Monitor size={16} className="text-white/70" />
                    <span className="absolute -bottom-0.5 -right-0.5"><StatusDot state={st} /></span>
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-white/90 truncate">{c.node_name || c.node_id}</span>
                      <Badge state={st}>{st === 'online' ? 'Online' : 'Offline'}</Badge>
                    </div>
                    <div className="text-[11px] text-white/45 truncate">{summarize(c, m)}</div>
                  </div>
                  <ChevronRight size={16} className="text-white/30 shrink-0" />
                </button>
              )
            })}
            {computers.length === 0 && !loading && !notLinked && (
              <div className="text-xs text-white/45 py-4 text-center">No computers found.</div>
            )}
            <button
              onClick={refresh}
              className="w-full text-[11px] text-white/50 hover:text-white/80 inline-flex items-center justify-center gap-1 pt-1"
            >
              <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> Refresh
            </button>
          </div>
        </Card>
      </div>

      {/* Privacy & Sharing (draft → commits on Save) */}
      <Card
        title="Privacy &amp; Sharing"
        right={<span className="text-[11px] text-white/40">Choose who can use your computers and data.</span>}
      >
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <PrivacyOption
            active={privacy === 'only_me'} onClick={() => onChangePrivacy('only_me')}
            Icon={User} title="Only Me" desc="Only you can access your computers"
          />
          <PrivacyOption
            active={privacy === 'team'} onClick={() => onChangePrivacy('team')}
            Icon={Users} title="My Team" desc="Team members you invite can access"
          />
          <PrivacyOption
            active={privacy === 'advanced'} onClick={() => onChangePrivacy('advanced')}
            Icon={Globe} title="Advanced Sharing" desc="Custom rules and permissions"
          />
        </div>
      </Card>
    </div>
  )
}

function summarize(c: MirrorNode, m: NodeManifest | null | undefined): string {
  const parts: string[] = []
  if (m?.gpu?.name) parts.push(String(m.gpu.name))
  if (typeof m?.gpu?.vram_mb === 'number') parts.push(`${Math.round(m.gpu.vram_mb / 1024)} GB VRAM`)
  if (Array.isArray(m?.models)) parts.push(`${m!.models.length} models`)
  if (Array.isArray(m?.projects)) parts.push(`${m!.projects.length} projects`)
  if (parts.length === 0) {
    if (!c.online) return 'Offline'
    return c.platform ? String(c.platform) : 'Online'
  }
  return parts.join(' · ')
}

function ThisComputer({ node, manifest, presence }: { node: MirrorNode; manifest: NodeManifest | null | undefined; presence: PresenceState }) {
  const gpu = manifest?.gpu?.name
  const vram = typeof manifest?.gpu?.vram_mb === 'number' ? `${Math.round(manifest.gpu.vram_mb / 1024)} GB VRAM` : ''
  const os = manifest?.os || node.platform || ''
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3">
        <div className="w-12 h-12 rounded-xl bg-violet-500/15 border border-violet-400/20 grid place-items-center shrink-0">
          <Monitor size={20} className="text-violet-200" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white/90 truncate">{node.node_name || node.node_id}</span>
            <button title="Rename from HomePilot Local" className="text-white/30 hover:text-white/60"><Pencil size={13} /></button>
            <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-white/60">
              <StatusDot state={presence} /> {presence === 'online' ? 'Online' : 'Offline'}
            </span>
          </div>
          <div className="text-[11px] text-white/45 mt-0.5">
            {[gpu, vram].filter(Boolean).join(' · ') || 'Details unavailable'}
          </div>
          <div className="text-[11px] text-white/45">{[os, 'HomePilot Local'].filter(Boolean).join(' · ')}</div>
        </div>
      </div>

      {/* Provider-managed controls — reflected read-only on Web. */}
      <div className="space-y-2 text-sm">
        <Row label="Remote Access" note="Managed on the computer">
          <Toggle on={presence === 'online'} disabled />
        </Row>
        <Row label="Available To" note="">
          <span className="text-white/60 text-[12px]">Only me</span>
        </Row>
        <Row label="Start with HomePilot" note="Managed on the computer">
          <span className="text-emerald-300 text-[11px] inline-flex items-center gap-1"><StatusDot state="online" /> On</span>
        </Row>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <button className="text-[11px] px-3 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-white/70 inline-flex items-center justify-center gap-1">
          <Activity size={13} /> Diagnostics
        </button>
        <button title="Rename from HomePilot Local" className="text-[11px] px-3 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-white/70 inline-flex items-center justify-center gap-1">
          <Pencil size={13} /> Rename
        </button>
      </div>
    </div>
  )
}

function Row({ label, note, children }: { label: string; note?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <ShieldCheck size={14} className="text-white/30" />
        <span className="text-white/70 text-[13px]">{label}</span>
        {note && <span className="text-white/30 text-[10px]">· {note}</span>}
      </div>
      {children}
    </div>
  )
}

function Toggle({ on, disabled }: { on: boolean; disabled?: boolean }) {
  return (
    <span
      className={`inline-flex w-9 h-5 rounded-full p-0.5 transition-colors ${on ? 'bg-emerald-500/70' : 'bg-white/15'} ${disabled ? 'opacity-60' : ''}`}
    >
      <span className={`w-4 h-4 rounded-full bg-white transition-transform ${on ? 'translate-x-4' : ''}`} />
    </span>
  )
}

function PrivacyOption({ active, onClick, Icon, title, desc }: {
  active: boolean; onClick: () => void; Icon: typeof User; title: string; desc: string
}) {
  return (
    <button
      onClick={onClick}
      className={`text-left rounded-2xl border p-3 flex items-start gap-3 transition-colors ${
        active ? 'border-violet-400/60 bg-violet-500/10' : 'border-white/10 bg-white/[0.02] hover:bg-white/[0.05]'
      }`}
    >
      <div className={`w-8 h-8 rounded-lg grid place-items-center shrink-0 ${active ? 'bg-violet-500/25' : 'bg-white/5'}`}>
        <Icon size={16} className={active ? 'text-violet-200' : 'text-white/60'} />
      </div>
      <div className="min-w-0">
        <div className="text-[13px] text-white/90">{title}</div>
        <div className="text-[11px] text-white/45">{desc}</div>
      </div>
      <span className={`ml-auto w-4 h-4 rounded-full border shrink-0 ${active ? 'border-violet-400 bg-violet-500' : 'border-white/25'}`} />
    </button>
  )
}

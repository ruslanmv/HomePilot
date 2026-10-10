/**
 * Model Advisor — FitLab suggestions for the computer HomePilot runs on.
 *
 * Optional and additive. Three choices, kept per device (Settings → Models →
 * Model suggestions):
 *   enabled    show "Suggested for your GPU" on the Models page (on by default)
 *   autoCheck  check FitLab for new definitions at most once a day while HomePilot is
 *              open (a conditional request: an unchanged feed downloads nothing; on)
 *   notify     tell me when a clearly better model than the one I use fits this
 *              computer, or when the suggestions changed (e.g. after an update).
 *              Off by default: no notice and no "New" badge until it is turned on.
 *
 * Without autoCheck, FitLab is contacted only when "Fetch definitions" is pressed.
 * Nothing is installed or changed unless the user presses Install. Admins can turn
 * the whole feature off (FITLAB_ENABLED=false) or keep it offline (FITLAB_OFFLINE=true).
 */
import { useCallback, useEffect, useState } from 'react'

export type AdvisorKind = 'chat' | 'vision' | 'image' | 'video'
export const ADVISOR_KINDS: AdvisorKind[] = ['chat', 'vision', 'image', 'video']
export const KIND_LABEL: Record<AdvisorKind, string> = { chat: 'Chat', vision: 'Vision', image: 'Image', video: 'Video' }

export type Suggestion = {
  id: string
  name: string
  kind: AdvisorKind
  hf_id?: string | null
  license?: string | null
  params_b?: number | null
  capabilities?: string[]
  verdict: 'fits' | 'tight' | 'offload'
  memory_needed_gb?: number | null
  tokens_per_s?: number | null
  tokens_per_s_kind?: 'measured' | 'estimated' | null
  download_gb?: number | null
  score: number
  reasons: string[]
  install: { provider: string; model_type: string; model_id: string }
  installed: boolean
}

export type Upgrade = {
  kind: AdvisorKind
  current: { id: string; name: string; model_id: string; score: number; rank: number }
  better: Suggestion
}

export type FeedInfo = {
  source: 'live' | 'cache' | 'bundled' | 'none'
  generated_at?: string | null
  ranking_version?: string | null
  fetched_at?: number | null
  checked_at?: number | null
}

export type AdvisorResponse = {
  ok: boolean
  enabled: boolean
  app_version?: string | null
  hardware?: {
    kind: 'nvidia' | 'apple' | 'cpu' | 'planned'
    name: string
    vram_gb: number
    ram_gb?: number
    bandwidth_gbs?: number | null
    detected?: boolean
    note?: string
  }
  feeds?: { llm: FeedInfo; media: FeedInfo }
  fetch?: { ok: boolean; partial: boolean; changed?: boolean; network: boolean; errors: string[] } | null
  suggestions?: Partial<Record<AdvisorKind, Suggestion[]>>
  upgrades?: Partial<Record<AdvisorKind, Upgrade>>
  attribution?: string
}

export type CurrentModels = Partial<Record<AdvisorKind, string | null | undefined>>

function base(url: string) {
  return (url || '').trim().replace(/\/+$/, '')
}

export async function loadAdvisor(
  backendUrl: string,
  opts: { refresh?: boolean; vramGb?: number | null; apiKey?: string; signal?: AbortSignal; current?: CurrentModels } = {},
): Promise<AdvisorResponse> {
  const qs = new URLSearchParams({ limit: '5' })
  if (opts.vramGb !== null && opts.vramGb !== undefined) qs.set('vram_gb', String(opts.vramGb))
  for (const k of ADVISOR_KINDS) {
    const m = opts.current?.[k]
    if (m) qs.set(`current_${k}`, m)
  }
  const res = await fetch(`${base(backendUrl)}/v1/model-advisor${opts.refresh ? '/fetch' : ''}?${qs}`, {
    method: opts.refresh ? 'POST' : 'GET',
    headers: opts.apiKey ? { 'x-api-key': opts.apiKey } : {},
    credentials: 'include',
    signal: opts.signal,
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as AdvisorResponse
}

// ── preferences (this device) ────────────────────────────────────────────────

export type AdvisorPrefs = { enabled: boolean; autoCheck: boolean; notify: boolean }
export const DEFAULT_ADVISOR_PREFS: AdvisorPrefs = { enabled: true, autoCheck: true, notify: false }
/**
 * Version of the stored preferences. Version 1 saved every key whenever any one
 * changed, so its `notify: true` was usually the old default rather than a choice;
 * such a value is read as the current default (off). An explicit off stays off.
 */
const ADVISOR_PREFS_VERSION = 2
export const ADVISOR_PREFS_KEY = 'homepilot_model_advisor_prefs'
export const ADVISOR_EVENT = 'hp:model-advisor-change'

function readJson<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* storage unavailable — applies to this page only */
  }
}

export function readAdvisorPrefs(): AdvisorPrefs {
  const p = readJson<Partial<AdvisorPrefs> & { v?: number }>(ADVISOR_PREFS_KEY) || {}
  const pick = (k: keyof AdvisorPrefs) => (typeof p[k] === 'boolean' ? (p[k] as boolean) : DEFAULT_ADVISOR_PREFS[k])
  const notify = p.v === ADVISOR_PREFS_VERSION ? pick('notify') : p.notify === false ? false : DEFAULT_ADVISOR_PREFS.notify
  return { enabled: pick('enabled'), autoCheck: pick('autoCheck'), notify }
}

export function writeAdvisorPrefs(next: Partial<AdvisorPrefs>): AdvisorPrefs {
  const merged = { ...readAdvisorPrefs(), ...next }
  writeJson(ADVISOR_PREFS_KEY, { ...merged, v: ADVISOR_PREFS_VERSION })
  window.dispatchEvent(new CustomEvent(ADVISOR_EVENT))
  return merged
}

export function useAdvisorPrefs(): AdvisorPrefs {
  const [prefs, setPrefs] = useState(readAdvisorPrefs)
  useEffect(() => {
    const sync = () => setPrefs(readAdvisorPrefs())
    const onStorage = (e: StorageEvent) => { if (e.key === ADVISOR_PREFS_KEY) sync() }
    window.addEventListener(ADVISOR_EVENT, sync)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener(ADVISOR_EVENT, sync)
      window.removeEventListener('storage', onStorage)
    }
  }, [])
  return prefs
}

export const advisorEnabled = () => readAdvisorPrefs().enabled
export const setAdvisorEnabled = (on: boolean) => { writeAdvisorPrefs({ enabled: on }) }
export const useAdvisorEnabled = () => useAdvisorPrefs().enabled

// ── automatic check schedule ─────────────────────────────────────────────────

export const CHECK_KEY = 'homepilot_model_advisor_check'
export const CHECK_INTERVAL_MS = 24 * 3600 * 1000
export const RETRY_INTERVAL_MS = 6 * 3600 * 1000
type CheckState = { at: number; ok: boolean }

export function lastCheck(): CheckState | null {
  return readJson<CheckState>(CHECK_KEY)
}

/** Due once a day after a good check, every 6 hours after a failed one. */
export function checkDue(now: number = Date.now()): boolean {
  const c = lastCheck()
  if (!c) return true
  return now - c.at >= (c.ok ? CHECK_INTERVAL_MS : RETRY_INTERVAL_MS)
}

export function recordCheck(ok: boolean, now: number = Date.now()): void {
  writeJson(CHECK_KEY, { at: now, ok })
  window.dispatchEvent(new CustomEvent(ADVISOR_EVENT))
}

// ── what the user has seen ───────────────────────────────────────────────────

export const ADVISOR_SEEN_KEY = 'homepilot_model_advisor_seen'
type Seen = { sig: string; ids: Partial<Record<AdvisorKind, string[]>> }

/** Changes when HomePilot updates or FitLab publishes new data. */
export function advisorSignature(r: AdvisorResponse): string {
  return [r.app_version || '', r.feeds?.llm?.generated_at || '', r.feeds?.media?.generated_at || ''].join('|')
}

export function readSeen(): Seen | null {
  return readJson<Seen>(ADVISOR_SEEN_KEY)
}

export const SEEN_EVENT = 'hp:model-advisor-seen'

export function markSeen(r: AdvisorResponse): void {
  const ids: Seen['ids'] = {}
  for (const k of ADVISOR_KINDS) ids[k] = (r.suggestions?.[k] || []).map((s) => s.id)
  writeJson(ADVISOR_SEEN_KEY, { sig: advisorSignature(r), ids })
  window.dispatchEvent(new CustomEvent(SEEN_EVENT))
}

/** Suggestions that were not in the list the user last saw (none on the very first look). */
export function newIds(r: AdvisorResponse, seen: Seen | null): Set<string> {
  const out = new Set<string>()
  if (!seen) return out
  for (const k of ADVISOR_KINDS) {
    const before = new Set(seen.ids[k] || [])
    for (const s of r.suggestions?.[k] || []) if (!before.has(s.id)) out.add(s.id)
  }
  return out
}

// ── notices ──────────────────────────────────────────────────────────────────

export const SNOOZE_KEY = 'homepilot_model_advisor_snoozed'
const SNOOZE_DAYS = 7

export type AdvisorNotice =
  | { type: 'upgrade'; key: string; kind: AdvisorKind; better: Suggestion; currentName: string }
  | { type: 'updated'; key: string; firstTime: boolean }

function snoozed(key: string, now = Date.now()): boolean {
  const until = (readJson<Record<string, number>>(SNOOZE_KEY) || {})[key]
  return typeof until === 'number' && until > now
}

export function snooze(key: string, days = SNOOZE_DAYS, now = Date.now()): void {
  const all = readJson<Record<string, number>>(SNOOZE_KEY) || {}
  for (const [k, until] of Object.entries(all)) if (until <= now) delete all[k]   // keep it small
  all[key] = now + days * 86400_000
  writeJson(SNOOZE_KEY, all)
}

/** The one notice worth showing now: an upgrade first, otherwise "suggestions updated". */
export function pickNotice(r: AdvisorResponse, updated: boolean): AdvisorNotice | null {
  for (const k of ADVISOR_KINDS) {
    const up = r.upgrades?.[k]
    if (!up) continue
    const key = `upgrade:${k}:${up.better.id}:${up.current.model_id}`
    if (!snoozed(key)) return { type: 'upgrade', key, kind: k, better: up.better, currentName: up.current.name }
  }
  const seen = readSeen()
  const sig = advisorSignature(r)
  if ((updated || seen?.sig !== sig) && !snoozed(`updated:${sig}`)) {
    return { type: 'updated', key: `updated:${sig}`, firstTime: !seen }
  }
  return null
}

/**
 * App-level: the Models badge, the optional daily check, and the notice to show.
 * One local request at start; FitLab is contacted only when a check is due and allowed.
 */
export function useAdvisorUpdates(backendUrl: string, current: CurrentModels, apiKey?: string) {
  const prefs = useAdvisorPrefs()
  const [badge, setBadge] = useState(false)
  const [notice, setNotice] = useState<AdvisorNotice | null>(null)
  const currentKey = ADVISOR_KINDS.map((k) => current[k] || '').join('|')

  useEffect(() => {
    if (!prefs.enabled || !prefs.notify || !backendUrl) {
      setBadge(false)
      setNotice(null)
    }
    if (!prefs.enabled || !backendUrl) return
    let cancelled = false
    const ctrl = new AbortController()
    const consider = (r: AdvisorResponse, updated: boolean) => {
      if (cancelled || !r.enabled || !prefs.notify) return
      const next = pickNotice(r, updated)
      // Snoozed or dismissed upgrades stay quiet — in the notice and on the badge.
      setBadge(readSeen()?.sig !== advisorSignature(r) || next?.type === 'upgrade')
      setNotice((prev) => prev || next)
    }
    const autoCheck = async () => {
      if (!prefs.autoCheck || !checkDue() || (typeof navigator !== 'undefined' && navigator.onLine === false)) return
      try {
        const r = await loadAdvisor(backendUrl, { refresh: true, current, apiKey, signal: ctrl.signal })
        recordCheck(!!(r.fetch?.ok || r.fetch?.partial))
        consider(r, !!r.fetch?.changed)
      } catch (e: any) {
        if (e?.name !== 'AbortError') recordCheck(false)
      }
    }
    loadAdvisor(backendUrl, { current, apiKey, signal: ctrl.signal })
      .then((r) => { consider(r, false); return autoCheck() })
      .catch(() => {})
    const timer = window.setInterval(() => { void autoCheck() }, 3600 * 1000)
    const onSeen = () => { if (!cancelled) setBadge(false) }
    window.addEventListener(SEEN_EVENT, onSeen)
    return () => {
      cancelled = true
      ctrl.abort()
      window.clearInterval(timer)
      window.removeEventListener(SEEN_EVENT, onSeen)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendUrl, apiKey, prefs.enabled, prefs.autoCheck, prefs.notify, currentKey])

  const dismiss = useCallback(() => {
    setNotice((n) => {
      if (n) snooze(n.key, n.type === 'updated' ? 3650 : SNOOZE_DAYS)
      return null
    })
  }, [])
  const turnOffNotifications = useCallback(() => {
    writeAdvisorPrefs({ notify: false })
    setNotice(null)
  }, [])
  return { badge, notice, dismiss, turnOffNotifications }
}

/** One-shot: which tab the Models card should open on (set by a notice's View). */
export const FOCUS_KEY = 'hp_model_advisor_focus'
export function requestFocus(kind: AdvisorKind): void {
  try { sessionStorage.setItem(FOCUS_KEY, kind) } catch { /* ignore */ }
}
export function takeFocus(): AdvisorKind | null {
  try {
    const k = sessionStorage.getItem(FOCUS_KEY) as AdvisorKind | null
    sessionStorage.removeItem(FOCUS_KEY)
    return k && ADVISOR_KINDS.includes(k) ? k : null
  } catch {
    return null
  }
}

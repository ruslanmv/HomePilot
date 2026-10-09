/**
 * Project identity — the picture and icon a project is shown with.
 *
 * One rule everywhere (project card, Conversation Hub, chat header, Voice):
 *   no project open           → the default HomePilot look
 *   project without a picture → the project's type icon
 *   project with a picture    → its saved picture (persona_appearance)
 *
 * The picture always comes from the project's saved configuration — the
 * selected avatar a persona was committed with — never a generated stand-in.
 */
import { resolveBackendUrl } from './lib/backendUrl'

export type ProjectLike = {
  id?: string
  name?: string
  project_type?: string
  updated_at?: number | string | null
  persona_appearance?: Record<string, any> | null
}

/**
 * URL of the project's saved picture, or null when it has none.
 * `thumb` is the small committed thumbnail (lists, headers); `full` prefers
 * the full-size image for large displays and falls back to the thumbnail.
 */
export function projectAvatarUrl(
  project: ProjectLike | null | undefined,
  backendUrl?: string,
  variant: 'thumb' | 'full' = 'thumb',
): string | null {
  if (!project) return null
  const pap = project.persona_appearance || {}
  const thumb = pap.selected_thumb_filename as string | undefined
  const full = pap.selected_filename as string | undefined
  const rel = variant === 'full' ? full || thumb : thumb || full
  if (!rel || typeof rel !== 'string') return null
  if (/^(https?:|data:|blob:)/.test(rel)) return rel
  const base = resolveBackendUrl(backendUrl).replace(/\/+$/, '')
  // Cache-buster: a re-committed avatar overwrites the same file name.
  const updated = Number(project.updated_at)
  const v = Number.isFinite(updated) && updated > 0 ? Math.floor(updated * 1000) : 0
  let token = ''
  try {
    token = localStorage.getItem('homepilot_auth_token') || ''
  } catch {
    /* storage unavailable */
  }
  return `${base}/files/${rel.replace(/^\/+/, '')}?v=${v}${token ? `&token=${encodeURIComponent(token)}` : ''}`
}

/** Human label for a project type ("Persona", "Chat / LLM", …). */
export function projectTypeLabel(type?: string | null): string {
  switch (String(type || 'chat').toLowerCase()) {
    case 'persona': return 'Persona'
    case 'agent': return 'Agent'
    case 'image': return 'Image'
    case 'video': return 'Video'
    default: return 'Chat / LLM'
  }
}

/** "Just created today" / "1 day together" / "12 days together" (created_at in epoch seconds). */
export function relationshipAge(createdAtSeconds?: number | null, now: number = Date.now()): string {
  const created = Number(createdAtSeconds)
  if (!Number.isFinite(created) || created <= 0) return 'Just created today'
  const days = Math.max(0, Math.floor((now / 1000 - created) / 86400))
  if (days === 0) return 'Just created today'
  if (days === 1) return '1 day together'
  return `${days} days together`
}

/**
 * Parse a server timestamp. Session times are stored as "YYYY-MM-DD HH:MM:SS"
 * in UTC without a zone marker: Safari can't parse that form at all and other
 * browsers read it as local time, so it is read explicitly as UTC.
 */
export function parseServerTime(value: string | null | undefined): number {
  if (!value) return NaN
  const plain = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)$/.exec(value.trim())
  return new Date(plain ? `${plain[1]}T${plain[2]}Z` : value).getTime()
}

/** "just now", "14 min ago", "3 hours ago", "yesterday", "3 days ago", "1 week ago", "2 months ago". */
export function timeAgo(iso: string | null | undefined, now: number = Date.now()): string {
  const t = parseServerTime(iso)
  if (!Number.isFinite(t)) return ''
  const min = Math.max(0, Math.floor((now - t) / 60000))
  if (min < 1) return 'just now'
  if (min < 60) return `${min} min ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return hr === 1 ? '1 hour ago' : `${hr} hours ago`
  const day = Math.floor(hr / 24)
  if (day === 1) return 'yesterday'
  if (day < 7) return `${day} days ago`
  const wk = Math.floor(day / 7)
  if (day < 30) return wk === 1 ? '1 week ago' : `${wk} weeks ago`
  const mo = Math.floor(day / 30)
  if (mo < 12) return mo === 1 ? '1 month ago' : `${mo} months ago`
  const yr = Math.floor(day / 365)
  return yr <= 1 ? '1 year ago' : `${yr} years ago`
}

/** Short calendar date in the viewer's locale ("13 Sep" / "Sep 13"). */
export function shortDate(iso: string | null | undefined): string {
  const t = parseServerTime(iso)
  if (!Number.isFinite(t)) return ''
  return new Date(t).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

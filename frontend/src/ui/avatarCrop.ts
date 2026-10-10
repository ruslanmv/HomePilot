/**
 * Edit profile picture — the persona's own framing of its picture.
 *
 * The backend cuts a square from the original picture at full resolution and
 * makes it the persona's thumbnail (POST /projects/{id}/persona/avatar/crop),
 * so every round avatar — chat, Conversation Hub, Voice, project cards — shows
 * it. The original is never changed; the framing (area in percent, zoom) is
 * kept in persona_appearance.avatar_crop so the editor reopens where the user
 * left it. DELETE on the same route goes back to the automatic thumbnail.
 */
import type { CSSProperties } from 'react'

export type CropArea = { x: number; y: number; width: number; height: number }

export type AvatarCrop = {
  source: string
  area: CropArea
  zoom?: number | null
  output: string
  size?: number
  auto_thumb?: string | null
  updated_at?: string
}

type WithAppearance = { persona_appearance?: Record<string, any> | null } | null | undefined

/** The saved crop, if it is still what the persona shows (a new picture chosen
 *  elsewhere replaces the thumbnail, and with it the crop). */
export function activeAvatarCrop(project: WithAppearance): AvatarCrop | null {
  const pap = project?.persona_appearance || {}
  const crop = pap.avatar_crop as AvatarCrop | undefined
  if (!crop || typeof crop !== 'object' || !crop.output) return null
  if (crop.output !== pap.selected_thumb_filename) return null
  const a = crop.area
  if (!a || ![a.x, a.y, a.width, a.height].every((n) => typeof n === 'number' && Number.isFinite(n))) return null
  return crop
}

/** Accepted replacement photos — what the backend can read. */
export const PHOTO_TYPES = ['image/png', 'image/jpeg', 'image/webp'] as const
export const MAX_PHOTO_MB = 25

/** Why a chosen file can't be used, or null when it can. */
export function photoProblem(file: { type: string; size: number }): string | null {
  if (!(PHOTO_TYPES as readonly string[]).includes(file.type)) return 'Choose a PNG, JPEG or WebP picture.'
  if (file.size > MAX_PHOTO_MB * 1024 * 1024) return `That picture is larger than ${MAX_PHOTO_MB} MB.`
  if (file.size === 0) return 'That file is empty.'
  return null
}

const pct = (n: number) => `${Math.round(n * 10000) / 10000}%`

/** Where a background of `span`% (the area's size, in % of the picture) must
 *  sit so that `start`% of the picture lands on the box's edge. CSS places a
 *  p% background so that p% of it meets p% of the box. */
function offset(start: number, span: number): string {
  return span >= 100 ? '0%' : pct((100 * start) / (100 - span))
}

/**
 * Background rules that draw `area` of the picture into a square box of any
 * size — the live preview, exactly what the saved thumbnail will contain. In
 * percent, so the same rules are right at every size the preview is shown.
 */
export function previewStyle(src: string, area: CropArea | null): CSSProperties {
  if (!area || area.width <= 0 || area.height <= 0) {
    return { backgroundImage: `url("${src}")`, backgroundSize: 'cover', backgroundPosition: 'center' }
  }
  return {
    backgroundImage: `url("${src}")`,
    backgroundRepeat: 'no-repeat',
    backgroundSize: `${pct((100 / area.width) * 100)} ${pct((100 / area.height) * 100)}`,
    backgroundPosition: `${offset(area.x, area.width)} ${offset(area.y, area.height)}`,
  }
}

/** Two views are the same framing (within rounding). */
export function sameView(a: { crop: { x: number; y: number }; zoom: number }, b: { crop: { x: number; y: number }; zoom: number }): boolean {
  return Math.abs(a.zoom - b.zoom) < 0.005 && Math.abs(a.crop.x - b.crop.x) < 0.5 && Math.abs(a.crop.y - b.crop.y) < 0.5
}

export type SaveResult =
  | { ok: true; project: Record<string, any> | null; persona_appearance: Record<string, any> }
  | { ok: false; error: string }

function errorText(status: number, body: any): string {
  const detail = body && typeof body.detail === 'string' ? body.detail : ''
  if (detail) return detail
  if (status === 413) return 'That picture is too large to upload.'
  if (status === 401 || status === 403) return 'You are not allowed to change this picture.'
  return `Saving failed (HTTP ${status}).`
}

async function send(url: string, init: RequestInit): Promise<SaveResult> {
  let res: Response
  try {
    res = await fetch(url, init)
  } catch {
    return { ok: false, error: 'HomePilot could not be reached. Check the connection and try again.' }
  }
  let body: any = null
  try { body = await res.json() } catch { /* non-JSON error page */ }
  if (!res.ok || !body?.ok) return { ok: false, error: errorText(res.status, body) }
  return { ok: true, project: body.project || null, persona_appearance: body.persona_appearance || {} }
}

/** Save the framing (and, optionally, a replacement photo) for a persona. */
export function saveAvatarCrop(opts: {
  backendUrl: string
  projectId: string
  area: CropArea
  zoom: number
  file?: File | null
  headers?: Record<string, string>
}): Promise<SaveResult> {
  const fd = new FormData()
  fd.append('area', JSON.stringify(opts.area))
  fd.append('zoom', String(Math.round(opts.zoom * 1000) / 1000))
  if (opts.file) fd.append('file', opts.file, opts.file.name)
  const base = opts.backendUrl.replace(/\/+$/, '')
  return send(`${base}/projects/${encodeURIComponent(opts.projectId)}/persona/avatar/crop`, {
    method: 'POST',
    headers: opts.headers, // no Content-Type: the browser sets the multipart boundary
    body: fd,
  })
}

/** Go back to the automatic thumbnail; the saved framing is kept for later. */
export function resetAvatarCrop(opts: { backendUrl: string; projectId: string; headers?: Record<string, string> }): Promise<SaveResult> {
  const base = opts.backendUrl.replace(/\/+$/, '')
  return send(`${base}/projects/${encodeURIComponent(opts.projectId)}/persona/avatar/crop`, {
    method: 'DELETE',
    headers: opts.headers,
  })
}

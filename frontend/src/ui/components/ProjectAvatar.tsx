/**
 * ProjectAvatar — a project's picture in a circular frame, or its type icon.
 *
 * - With a picture: the saved image, a thin ring and a soft glow tinted with
 *   the picture's own colour (sampled once; violet when it can't be read).
 * - Without one (or if it fails to load): the project's type icon.
 * - `level` (0..1, optional) makes the ring respond to audio — used by Voice
 *   for a static picture. The face itself is never animated.
 */
import React, { useEffect, useState } from 'react'
import { Bot, Film, Image as ImageIcon, MessageSquare, User } from 'lucide-react'

const FALLBACK_ACCENT = '139, 92, 246' // violet-500

function iconFor(type?: string | null) {
  switch (String(type || '').toLowerCase()) {
    case 'persona': return { Icon: User, tint: 'text-pink-300', bg: 'bg-pink-500/15 border-pink-400/30' }
    case 'agent': return { Icon: Bot, tint: 'text-amber-300', bg: 'bg-amber-500/15 border-amber-400/30' }
    case 'image': return { Icon: ImageIcon, tint: 'text-fuchsia-300', bg: 'bg-fuchsia-500/15 border-fuchsia-400/30' }
    case 'video': return { Icon: Film, tint: 'text-emerald-300', bg: 'bg-emerald-500/15 border-emerald-400/30' }
    default: return { Icon: MessageSquare, tint: 'text-blue-300', bg: 'bg-blue-500/15 border-blue-400/30' }
  }
}

/**
 * The picture's average colour as "r, g, b", lifted so a dark photo still
 * gives a visible glow. Falls back silently when the image can't be read
 * (cross-origin, not loaded, no canvas).
 */
export function useImageAccent(url: string | null | undefined): string {
  const [accent, setAccent] = useState(FALLBACK_ACCENT)
  useEffect(() => {
    if (!url || typeof document === 'undefined' || /jsdom/i.test(navigator.userAgent || '')) {
      setAccent(FALLBACK_ACCENT)
      return
    }
    let cancelled = false
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => {
      try {
        const c = document.createElement('canvas')
        c.width = 16
        c.height = 16
        const ctx = c.getContext('2d')
        if (!ctx) return
        ctx.drawImage(img, 0, 0, 16, 16)
        const px = ctx.getImageData(0, 0, 16, 16).data
        let r = 0, g = 0, b = 0, n = 0
        for (let i = 0; i < px.length; i += 4) {
          // Skip near-black and near-white pixels: backgrounds, not the subject.
          const sum = px[i] + px[i + 1] + px[i + 2]
          if (sum < 60 || sum > 720) continue
          r += px[i]; g += px[i + 1]; b += px[i + 2]; n++
        }
        if (!n || cancelled) return
        r /= n; g /= n; b /= n
        const max = Math.max(r, g, b, 1)
        const lift = Math.min(2.2, 210 / max) // bring the brightest channel to ~210
        setAccent(`${Math.round(r * lift)}, ${Math.round(g * lift)}, ${Math.round(b * lift)}`)
      } catch {
        /* tainted canvas or decode failure — keep the fallback */
      }
    }
    img.src = url
    return () => {
      cancelled = true
    }
  }, [url])
  return accent
}

export function ProjectAvatar({
  url,
  name,
  projectType,
  size = 112,
  level,
  className = '',
}: {
  url: string | null | undefined
  name: string
  projectType?: string | null
  size?: number
  /** 0..1 audio level; makes the ring respond (Voice). */
  level?: number
  className?: string
}) {
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [url])
  const showPicture = !!url && !failed
  const accent = useImageAccent(showPicture ? url : null)
  const lvl = typeof level === 'number' && Number.isFinite(level) ? Math.max(0, Math.min(1, level)) : null
  const { Icon, tint, bg } = iconFor(projectType)

  return (
    <div
      className={`hp-project-avatar ${lvl !== null ? 'hp-project-avatar--live' : ''} ${className}`}
      style={{
        width: size,
        height: size,
        ['--hp-accent' as string]: accent,
        ['--hp-level' as string]: lvl ?? 0,
      }}
      data-kind={showPicture ? 'picture' : 'icon'}
    >
      {lvl !== null ? (
        <>
          <span className="hp-project-avatar__wave hp-project-avatar__wave--1" aria-hidden="true" />
          <span className="hp-project-avatar__wave hp-project-avatar__wave--2" aria-hidden="true" />
        </>
      ) : null}
      {showPicture ? (
        <img
          src={url as string}
          alt={name}
          className="hp-project-avatar__img"
          draggable={false}
          onError={() => setFailed(true)}
        />
      ) : (
        <div className={`hp-project-avatar__icon border ${bg}`} role="img" aria-label={name}>
          <Icon className={tint} style={{ width: size * 0.4, height: size * 0.4 }} strokeWidth={1.6} />
        </div>
      )}
    </div>
  )
}

export default ProjectAvatar

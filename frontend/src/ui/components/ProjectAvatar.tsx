/**
 * ProjectAvatar — a project's picture in a circular frame, or its type icon.
 *
 * - With a picture: the saved image, a thin ring and a soft glow tinted with
 *   the picture's own colour (sampled once; violet when it can't be read).
 *   `fallbackUrl` is tried when `url` fails (the face crop → the thumbnail).
 * - Without one (or if every URL fails to load): the project's type icon.
 * - `level` (0..1, optional) makes the ring respond to audio — used by Voice
 *   for a static picture. The face itself is never animated.
 * - While a picture is on its way (a full-size original can take a moment), a
 *   soft shimmer fills the circle and the picture fades in once it has arrived —
 *   never an empty black disc. A picture already in the cache shows at once.
 */
import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
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
 * The average colour of a loaded picture as "r, g, b", lifted so a dark photo
 * still gives a visible glow; null when it can't be read.
 *
 * Reads the <img> already on screen — no second download. A picture from
 * another origin (the dev server on another port) can't be read back from a
 * canvas; that throws here, quietly, and the glow stays violet.
 */
export function imageAccent(img: HTMLImageElement): string | null {
  if (/jsdom/i.test(navigator.userAgent || '')) return null // no canvas in tests
  try {
    const c = document.createElement('canvas')
    c.width = 16
    c.height = 16
    const ctx = c.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(img, 0, 0, 16, 16)
    const px = ctx.getImageData(0, 0, 16, 16).data
    let r = 0, g = 0, b = 0, n = 0
    for (let i = 0; i < px.length; i += 4) {
      // Skip near-black and near-white pixels: backgrounds, not the subject.
      const sum = px[i] + px[i + 1] + px[i + 2]
      if (sum < 60 || sum > 720) continue
      r += px[i]; g += px[i + 1]; b += px[i + 2]; n++
    }
    if (!n) return null
    r /= n; g /= n; b /= n
    const max = Math.max(r, g, b, 1)
    const lift = Math.min(2.2, 210 / max) // bring the brightest channel to ~210
    return `${Math.round(r * lift)}, ${Math.round(g * lift)}, ${Math.round(b * lift)}`
  } catch {
    return null // cross-origin (tainted canvas), no canvas, or not decoded
  }
}

/**
 * A picture with fallbacks: shows the first URL, moves to the next when one
 * fails to load, and reports when none is left.
 */
export function useImageFallback(urls: Array<string | null | undefined>) {
  const list = urls.filter((u): u is string => !!u)
  const key = list.join('\n')
  const [index, setIndex] = useState(0)
  useEffect(() => setIndex(0), [key])
  return {
    src: index < list.length ? list[index] : null,
    onError: () => setIndex((i) => i + 1),
  }
}

/**
 * Whether the <img> showing `src` has finished loading. A cached picture can be
 * complete before React listens for "load", so that is checked right away.
 */
export function useImageReady(src: string | null) {
  const ref = useRef<HTMLImageElement>(null)
  const [readySrc, setReadySrc] = useState<string | null>(null)
  useLayoutEffect(() => {
    const img = ref.current
    if (src && img && img.complete && img.naturalWidth > 0) setReadySrc(src)
  }, [src])
  return { ref, ready: !!src && readySrc === src, onLoad: () => setReadySrc(src) }
}

/** A decorative <img> that tries each URL in turn; `fallback` when none loads. */
export function AvatarImage({
  urls,
  className,
  style,
  fallback = null,
}: {
  urls: Array<string | null | undefined>
  className?: string
  style?: React.CSSProperties
  fallback?: React.ReactNode
}) {
  const { src, onError } = useImageFallback(urls)
  const { ref, ready, onLoad } = useImageReady(src)
  if (!src) return <>{fallback}</>
  return (
    <img
      ref={ref}
      src={src}
      alt=""
      aria-hidden
      className={ready ? className : `${className || ''} hp-avatar-loading`}
      style={style}
      draggable={false}
      decoding="async"
      onLoad={onLoad}
      onError={onError}
    />
  )
}

export function ProjectAvatar({
  url,
  fallbackUrl,
  name,
  projectType,
  size = 112,
  level,
  className = '',
}: {
  url: string | null | undefined
  /** Shown when `url` fails to load (e.g. the face crop → the thumbnail). */
  fallbackUrl?: string | null
  name: string
  projectType?: string | null
  size?: number
  /** 0..1 audio level; makes the ring respond (Voice). */
  level?: number
  className?: string
}) {
  const { src, onError } = useImageFallback([url, fallbackUrl])
  const { ref: imgRef, ready, onLoad } = useImageReady(src)
  const showPicture = !!src
  const loading = showPicture && !ready
  const [accent, setAccent] = useState(FALLBACK_ACCENT)
  useEffect(() => setAccent(FALLBACK_ACCENT), [src])
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
      aria-busy={loading || undefined}
    >
      {lvl !== null ? (
        <>
          <span className="hp-project-avatar__wave hp-project-avatar__wave--1" aria-hidden="true" />
          <span className="hp-project-avatar__wave hp-project-avatar__wave--2" aria-hidden="true" />
        </>
      ) : null}
      {loading ? <span className="hp-project-avatar__skeleton" aria-hidden="true" /> : null}
      {showPicture ? (
        <img
          ref={imgRef}
          src={src as string}
          alt={name}
          className="hp-project-avatar__img"
          data-ready={ready ? 'true' : 'false'}
          draggable={false}
          decoding="async"
          onLoad={(e) => {
            onLoad()
            const tint = imageAccent(e.currentTarget)
            if (tint) setAccent(tint)
          }}
          onError={onError}
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

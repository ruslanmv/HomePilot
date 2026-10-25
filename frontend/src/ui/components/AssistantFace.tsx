/**
 * AssistantFace — HomePilot's face: a gradient orb with two eyes that react to what the app
 * is doing (the prototype is the "HomePilot Face Lab").
 *
 *   idle       blinks now and then, glances around
 *   attentive  reading: the user is typing, eyes scan the composer
 *   thinking   eyes drift up and to the side
 *   speaking   eyes bob while the reply plays in
 *   happy      "^ ^"
 *
 * One small engine updates the SVG directly on each animation frame, so React does not
 * re-render 60 times a second. With ``animated`` false (Settings → Chat → "Animate
 * HomePilot", Motion off, or the OS reduce-motion setting) it draws one still frame.
 */
import React, { useEffect, useRef } from 'react'

export type FaceState = 'idle' | 'attentive' | 'thinking' | 'speaking' | 'happy'

const TARGETS: Record<FaceState, { open: number; scale: number; happy: number }> = {
  idle: { open: 1, scale: 1, happy: 0 },
  attentive: { open: 1.08, scale: 1.04, happy: 0 },
  thinking: { open: 0.82, scale: 0.98, happy: 0 },
  speaking: { open: 1, scale: 1, happy: 0 },
  happy: { open: 1, scale: 1.02, happy: 1 },
}

// Sized for an orb that fills the frame (r = 96 of 200).
const EYE = { width: 17, height: 42, spacing: 40, tilt: 8 }
const rand = (a: number, b: number) => a + Math.random() * (b - a)
const approach = (from: number, to: number, dt: number, speed: number) => from + (to - from) * (1 - Math.exp(-dt * speed))

export default function AssistantFace({
  size = 64,
  state = 'idle',
  animated = true,
  className = '',
}: {
  size?: number
  state?: FaceState
  animated?: boolean
  className?: string
}) {
  const eyeRefs = useRef<Array<{ open: SVGRectElement | null; arc: SVGPathElement | null; g: SVGGElement | null }>>([
    { open: null, arc: null, g: null }, { open: null, arc: null, g: null },
  ])
  const stateRef = useRef<FaceState>(state)
  stateRef.current = state
  const gid = useRef(`hpface${Math.random().toString(36).slice(2, 8)}`).current

  useEffect(() => {
    // Live values and where they are heading.
    const s = { gx: 0, gy: 0, open: 1, scale: 1, happy: 0, blink: 0, bob: 0 }
    const target = { gx: 0, gy: 0 }
    let clock = 0, nextBlink = rand(1.2, 3.5), blinkT = -1, nextGlance = rand(1, 2.5)

    function draw() {
      const cx = 100 + s.gx * 22, cy = 95 + s.gy * 18 - s.bob * 8
      const open = Math.max(0.06, s.open * (1 - s.blink))
      eyeRefs.current.forEach((e, i) => {
        if (!e.open || !e.arc || !e.g) return
        const side = i === 0 ? -1 : 1
        const x = cx + (side * EYE.spacing / 2) * s.scale
        const w = EYE.width * s.scale, h = Math.max(1.2, EYE.height * s.scale * open)
        e.g.setAttribute('transform', `rotate(${EYE.tilt} ${x} ${cy})`)
        e.open.setAttribute('x', String(x - w / 2)); e.open.setAttribute('y', String(cy - h / 2))
        e.open.setAttribute('width', String(w)); e.open.setAttribute('height', String(h))
        e.open.setAttribute('rx', String(Math.min(w / 2, h / 2)))
        e.open.setAttribute('opacity', (1 - s.happy).toFixed(3))
        const aw = EYE.width * 0.9 * s.scale + 8, ah = 12 * s.scale
        e.arc.setAttribute('d', `M ${x - aw / 2} ${cy + ah / 2} Q ${x} ${cy - ah * 1.2} ${x + aw / 2} ${cy + ah / 2}`)
        e.arc.setAttribute('opacity', s.happy.toFixed(3))
      })
    }

    if (!animated) {
      const t = TARGETS[stateRef.current]
      Object.assign(s, { open: t.open, scale: t.scale, happy: t.happy })
      draw()
      return
    }

    let raf = 0, last = performance.now()
    function frame(now: number) {
      const dt = Math.min(0.05, (now - last) / 1000)
      last = now
      clock += dt
      const st = stateRef.current
      const t = TARGETS[st]
      // Blink every few seconds, sometimes twice.
      if (clock >= nextBlink && blinkT < 0) {
        blinkT = 0
        nextBlink = clock + (Math.random() < 0.18 ? 0.3 : rand(2.8, 6))
      }
      if (blinkT >= 0) {
        blinkT += dt
        const p = blinkT / 0.16
        s.blink = p < 0.5 ? p * 2 : Math.max(0, 2 - p * 2)
        if (p >= 1) { blinkT = -1; s.blink = 0 }
      }
      // Where the eyes look.
      if (st === 'thinking') {
        target.gx = 0.4 + Math.sin(clock * 0.9) * 0.15; target.gy = -0.45 + Math.cos(clock * 0.7) * 0.1
      } else if (st === 'attentive') {
        target.gx = Math.sin(clock * 2.4) * 0.25; target.gy = 0.35
      } else if (clock >= nextGlance) {
        nextGlance = clock + rand(1.4, 3.8)
        const far = st === 'idle' ? 1 : 0.3
        target.gx = rand(-0.45, 0.45) * far; target.gy = rand(-0.25, 0.2) * far
      }
      const bob = st === 'speaking' ? Math.max(0, Math.sin(clock * 9)) * 0.7 : 0
      s.gx = approach(s.gx, target.gx, dt, 14); s.gy = approach(s.gy, target.gy, dt, 14)
      s.open = approach(s.open, t.open, dt, 10); s.scale = approach(s.scale, t.scale, dt, 9)
      s.happy = approach(s.happy, t.happy, dt, 9); s.bob = approach(s.bob, bob, dt, 16)
      draw()
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    // A hidden tab gets no frames from the browser anyway; nothing else to pause.
    return () => cancelAnimationFrame(raf)
    // The live loop reads the state from a ref, so a new state is a new target, not a restart;
    // the still frame is redrawn for each state.
  }, [animated, animated ? null : state])  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <svg
      viewBox="0 0 200 200"
      width={size}
      height={size}
      aria-hidden
      className={className}
      style={{ filter: 'drop-shadow(0 0 22px rgba(129,140,248,0.45))' }}
    >
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#a78bfa" />
          <stop offset="0.55" stopColor="#6366f1" />
          <stop offset="1" stopColor="#38bdf8" />
        </linearGradient>
        <radialGradient id={`${gid}s`} cx="35%" cy="28%" r="80%">
          <stop offset="0" stopColor="#fff" stopOpacity="0.5" />
          <stop offset="0.45" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="100" cy="100" r="96" fill={`url(#${gid})`} />
      <circle cx="100" cy="100" r="96" fill={`url(#${gid}s)`} />
      {[0, 1].map((i) => (
        <g key={i} ref={(el) => { eyeRefs.current[i].g = el }}>
          <rect ref={(el) => { eyeRefs.current[i].open = el }} fill="#fff" />
          <path ref={(el) => { eyeRefs.current[i].arc = el }} fill="none" stroke="#fff" strokeWidth="10" strokeLinecap="round" opacity="0" />
        </g>
      ))}
    </svg>
  )
}

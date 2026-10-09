/**
 * Settings → Motion: choose how much HomePilot animates, and see every
 * animation in the motion system running live.
 *
 * Applies immediately and is remembered on this device; it does not touch the
 * Save/Reset draft of the settings around it.
 */
import React, { useEffect, useState } from 'react'
import { MotionLevel, RevealStyle, prefersReducedMotion, useMotionPrefs, writeMotionPrefs } from './prefs'
import {
  AudioWaveform,
  Collapsible,
  LoadingDots,
  PulseText,
  ProgressBar,
  ShimmerText,
  Skeleton,
  Spinner,
  StatusText,
  TypingCursor,
  VoiceOrb,
  type OrbState,
} from './Motion'
import { StreamReveal } from './StreamReveal'

const LEVELS: { id: MotionLevel; label: string; note: string }[] = [
  { id: 'enterprise', label: 'Enterprise', note: 'Every animation, quick and restrained.' },
  { id: 'minimal', label: 'Minimal', note: 'Fades and pulses only — no sweeps or slides.' },
  { id: 'off', label: 'Off', note: 'Nothing moves.' },
]
const REVEALS: { id: RevealStyle; label: string; note: string }[] = [
  { id: 'stream', label: 'Stream', note: 'New answers appear word by word with a cursor. Tap to show all.' },
  { id: 'fade', label: 'Fade in', note: 'New answers fade in whole.' },
  { id: 'instant', label: 'Instant', note: 'New answers appear at once.' },
]

const SAMPLE = 'HomePilot reveals a new answer **progressively**, so you can start reading while the rest settles in.'
const TOOL_STEPS = ['Searching the web', 'Reading 3 sources', 'Comparing results', 'Writing the answer']
const ORB_STATES: OrbState[] = ['idle', 'listening', 'thinking', 'speaking']

/** Just enough Markdown for the sample: **bold** runs (an unclosed run is bold too). */
function renderBold(text: string): React.ReactNode {
  return text.split('**').map((part, i) => (i % 2 ? <strong key={i}>{part}</strong> : <React.Fragment key={i}>{part}</React.Fragment>))
}

function useTicker(ms: number) {
  const [n, setN] = useState(0)
  useEffect(() => {
    const t = window.setInterval(() => setN((v) => v + 1), ms)
    return () => window.clearInterval(t)
  }, [ms])
  return n
}

function Choice<T extends string>({
  name,
  value,
  options,
  onChange,
}: {
  name: string
  value: T
  options: { id: T; label: string; note: string }[]
  onChange: (v: T) => void
}) {
  return (
    <div role="radiogroup" aria-label={name} className="grid gap-2 sm:grid-cols-3">
      {options.map((o) => {
        const on = o.id === value
        return (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.id)}
            className={[
              'min-h-[44px] rounded-xl border px-3 py-2.5 text-left',
              on ? 'border-white/40 bg-white/[0.08] text-white' : 'border-white/10 bg-white/[0.02] text-white/70 hover:bg-white/[0.05]',
            ].join(' ')}
          >
            <span className="block text-sm font-semibold">{o.label}</span>
            <span className="block text-xs text-white/55 mt-0.5 leading-snug">{o.note}</span>
          </button>
        )
      })}
    </div>
  )
}

function Demo({ n, name, where, children }: { n: number; name: string; where: string; children: React.ReactNode }) {
  return (
    <li data-motion-demo={n} className="flex items-center gap-3 py-3 border-t border-white/[0.06] first:border-t-0 min-w-0">
      <span className="w-6 shrink-0 text-right text-xs tabular-nums text-white/45">{n}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm text-white/90">{name}</span>
        <span className="block text-xs text-white/50 leading-snug">{where}</span>
      </span>
      <span className="shrink-0 flex items-center justify-end w-[42%] max-w-[13rem] min-h-[28px] text-sm text-white/80">{children}</span>
    </li>
  )
}

export function MotionGallery() {
  const prefs = useMotionPrefs()
  const tick = useTicker(1600)
  const [replay, setReplay] = useState(0)
  const [open, setOpen] = useState(true)
  const [shown, setShown] = useState(true)
  const reduced = prefersReducedMotion()

  // Cycle the stateful demos.
  const step = TOOL_STEPS[tick % TOOL_STEPS.length]
  const orb = ORB_STATES[Math.floor(tick / 2) % ORB_STATES.length]
  const level = orb === 'listening' || orb === 'speaking' ? 0.25 + 0.5 * Math.abs(Math.sin(tick * 1.7)) : 0
  const progress = ((tick % 6) + 1) / 6

  return (
    <div className="space-y-5">
      {reduced ? (
        <p className="text-xs text-amber-200/90 bg-amber-500/10 border border-amber-500/25 rounded-lg px-3 py-2">
          Your device asks for reduced motion, so animations stay off whatever you choose here.
        </p>
      ) : null}

      <div className="space-y-2">
        <div className="text-xs font-semibold uppercase tracking-wider text-white/55">Animation level</div>
        <Choice name="Animation level" value={prefs.level} options={LEVELS} onChange={(level) => writeMotionPrefs({ level })} />
      </div>

      <div className="space-y-2">
        <div className="text-xs font-semibold uppercase tracking-wider text-white/55">New answers</div>
        <Choice name="How new answers appear" value={prefs.reveal} options={REVEALS} onChange={(reveal) => writeMotionPrefs({ reveal })} />
      </div>

      <div className="rounded-xl border border-white/10 bg-black/30 p-4 space-y-2">
        <div className="flex items-center justify-between gap-3">
          <div className="text-xs font-semibold uppercase tracking-wider text-white/55">Preview</div>
          <button
            type="button"
            onClick={() => setReplay((r) => r + 1)}
            className="min-h-[36px] px-3 rounded-lg border border-white/10 bg-white/[0.04] text-xs text-white/80 hover:bg-white/[0.08]"
          >
            Replay
          </button>
        </div>
        <div className="text-[15px] leading-relaxed text-white/90" key={`${replay}-${prefs.reveal}-${prefs.level}`}>
          <div className={prefs.reveal === 'fade' ? 'hp-msg-in' : undefined}>
            <StreamReveal
              text={SAMPLE}
              active={prefs.reveal === 'stream' && prefs.level !== 'off' && !reduced}
              render={renderBold}
            />
          </div>
        </div>
      </div>

      <div>
        <div className="text-xs font-semibold uppercase tracking-wider text-white/55 mb-1">All animations</div>
        <ol className="list-none p-0 m-0" aria-label="Animations in HomePilot">
          <Demo n={1} name="Text shimmer" where="Working labels while HomePilot thinks or searches">
            <ShimmerText>Thinking</ShimmerText>
          </Demo>
          <Demo n={2} name="Text opacity pulse" where="Saving and syncing labels">
            <PulseText>Saving…</PulseText>
          </Demo>
          <Demo n={3} name="Streaming text" where="A new answer appears progressively">
            <span key={replay} className="truncate">
              <StreamReveal text="Words arrive one after another." active={prefs.level !== 'off' && !reduced} render={(t) => t} />
            </span>
          </Demo>
          <Demo n={4} name="Typing cursor" where="Rides the end of the text being revealed">
            <span>Writing<TypingCursor /></span>
          </Demo>
          <Demo n={5} name="Loading dots" where="Waiting for a reply">
            <LoadingDots label="Waiting" />
          </Demo>
          <Demo n={6} name="Loading spinner" where="Buttons while an action runs">
            <Spinner size={18} label="Working" />
          </Demo>
          <Demo n={7} name="Skeleton shimmer" where="Placeholders while settings and lists load">
            <Skeleton lines={2} height={8} className="w-full" />
          </Demo>
          <Demo n={8} name="Fade in" where="New content arriving">
            <span key={`fi-${tick}`} className="hp-enter-fade">Hello</span>
          </Demo>
          <Demo n={9} name="Fade out" where="Content being dismissed">
            <span key={`fo-${tick}`} className={tick % 2 ? 'hp-exit-fade' : undefined}>Goodbye</span>
          </Demo>
          <Demo n={10} name="Slide in" where="Panels entering from the side">
            <span key={`si-${tick}`} className="hp-enter-slide-left">Panel</span>
          </Demo>
          <Demo n={11} name="Slide out" where="Panels leaving the screen">
            <span key={`so-${tick}`} className={tick % 2 ? 'hp-exit-slide-left' : undefined}>Panel</span>
          </Demo>
          <Demo n={12} name="Accordion expand" where="Sections opening (details, transcripts)">
            <button type="button" onClick={() => setOpen((v) => !v)} className="text-xs text-white/80 underline underline-offset-2 min-h-[28px]" aria-expanded={open}>
              {open ? 'Collapse' : 'Expand'}
            </button>
          </Demo>
          <li className="pl-9 -mt-1 pb-2">
            <Collapsible open={open}>
              <p className="text-xs text-white/60 py-1">Sections open and close smoothly instead of jumping.</p>
            </Collapsible>
          </li>
          <Demo n={13} name="Accordion collapse" where="Sections closing">
            <span className="text-xs text-white/55">Same control, reversed</span>
          </Demo>
          <Demo n={14} name="Button hover transition" where="Every button's hover state eases in">
            <button type="button" className="min-h-[32px] px-3 rounded-lg border border-white/10 bg-white/[0.04] hover:bg-white/[0.12] text-xs">Hover me</button>
          </Demo>
          <Demo n={15} name="Button press feedback" where="Buttons dip slightly when pressed">
            <button type="button" className="min-h-[32px] px-3 rounded-lg border border-white/10 bg-white/[0.04] text-xs">Press me</button>
          </Demo>
          <Demo n={16} name="Message reveal" where="Each new turn rises into place">
            <span key={`mr-${tick}`} className="hp-msg-in rounded-full bg-white/10 px-3 py-1 text-xs">New message</span>
          </Demo>
          <Demo n={17} name="Tool status transition" where="Searching → reading → writing">
            <StatusText text={step} />
          </Demo>
          <Demo n={18} name="Voice orb" where={`Available for voice visuals — now: ${orb}`}>
            <VoiceOrb state={orb} level={level} size={40} />
          </Demo>
          <Demo n={19} name="Audio waveform" where="Available for live audio levels">
            <AudioWaveform level={level || 0.2} bars={14} height={24} />
          </Demo>
          <Demo n={20} name="Modal transition" where="Dialogs rise in and fade out">
            <span key={`mt-${tick}`} className="hp-enter-slide-up rounded-lg border border-white/15 bg-white/[0.06] px-3 py-1 text-xs">Dialog</span>
          </Demo>
          <Demo n={21} name="Sidebar transition" where="The phone menu slides in over a fading backdrop">
            <button type="button" onClick={() => setShown((v) => !v)} className="text-xs text-white/80 underline underline-offset-2 min-h-[28px]">
              {shown ? 'Hide' : 'Show'}
            </button>
          </Demo>
          <li className="pl-9 -mt-1 pb-2 h-8">
            {shown ? <span className="hp-enter-slide-left inline-block rounded-md bg-white/10 px-2 py-1 text-xs text-white/70">Menu</span> : null}
          </li>
          <Demo n={22} name="Progress indicator" where="Uploads, refreshes and long tasks">
            <span className="w-full space-y-1.5">
              <ProgressBar value={progress} label="Upload progress" />
              <ProgressBar label="Refreshing" />
            </span>
          </Demo>
        </ol>
      </div>
    </div>
  )
}

export default MotionGallery

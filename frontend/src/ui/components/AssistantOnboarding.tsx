/**
 * AssistantOnboarding — the first conversation (backend/app/onboarding.py).
 *
 * The account's own assistant already exists when this opens, and the screen is its chat:
 * a greeting, one question with the answer filled in ("What would you like to call me?"),
 * a short introduction, and a few one-tap things to try. No form, no survey: confirming the
 * name, picking a starter, or typing a first message ends onboarding, and the app opens the
 * same thread. The lines come from the server, so a reload shows them without replaying.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUp, Check } from 'lucide-react'
import { assistantAnimates, useAssistantAnimates } from '../chatAppearance'
import AssistantFace, { type FaceState } from './AssistantFace'

export type AssistantHandoff = {
  projectId?: string
  conversationId?: string
  /** Sent as the first real message once the chat is open. */
  firstMessage?: string
  /** A part of the app to open instead (meetings, voice…). */
  mode?: string
}

type Line = { role: string; content: string; onboarding?: string | null }
type Starter = { id: string; icon: string; label: string; kind: 'prompt' | 'mode'; text?: string; mode?: string }
type State = {
  assistant: { id: string; name: string } | null
  conversation_id?: string
  step?: 'created' | 'introduced' | 'done' | null
  created?: boolean
  accepted?: boolean
  messages?: Line[]
  starters?: Starter[]
}

const REVEAL_MS = 650

/** Settings → Chat → "Animate HomePilot" off (or Motion off, or the OS reduce-motion
 *  setting): every line appears at once and nothing moves. */
function still(): boolean {
  return !assistantAnimates()
}

/** Plain text with "- " lines as a list — enough for the introduction. */
function Text({ value }: { value: string }) {
  const blocks = value.split('\n\n')
  return (
    <>
      {blocks.map((block, i) => {
        const lines = block.split('\n')
        if (lines.every((l) => l.startsWith('- '))) {
          return (
            <ul key={i} className="mt-2 space-y-1.5 first:mt-0">
              {lines.map((l, j) => (
                <li key={j} className="flex gap-2.5"><span className="text-white/40">•</span><span>{l.slice(2)}</span></li>
              ))}
            </ul>
          )
        }
        return <p key={i} className="mt-2 first:mt-0">{block}</p>
      })}
    </>
  )
}

function Typing({ animated }: { animated: boolean }) {
  return (
    <div className="flex" role="status" aria-label="HomePilot is typing">
      <div className="flex items-center gap-1.5 rounded-[22px] bg-white/[0.07] px-5 py-4">
        {[0, 1, 2].map((i) => (
          <span key={i} className={`h-2 w-2 rounded-full bg-white/50 ${animated ? 'animate-bounce' : ''}`} style={{ animationDelay: `${i * 140}ms` }} />
        ))}
      </div>
    </div>
  )
}

export default function AssistantOnboarding({
  backendUrl,
  token,
  onDone,
}: {
  backendUrl: string
  token: string
  onDone: (handoff: AssistantHandoff) => void
}) {
  const [state, setState] = useState<State | null>(null)
  const [failed, setFailed] = useState(false)
  const [shown, setShown] = useState(0)        // messages revealed so far
  const [busy, setBusy] = useState(false)
  const [input, setInput] = useState('')
  const animated = useAssistantAnimates()
  const [cheer, setCheer] = useState(false)   // a short smile once the name is settled
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const call = useCallback(async (path: string, body?: unknown): Promise<State> => {
    const res = await fetch(`${backendUrl.replace(/\/+$/, '')}/v1/onboarding${path}`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(body ?? {}),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  }, [backendUrl, token])

  const start = useCallback(async () => {
    setFailed(false)
    try {
      const s = await call('/assistant')
      if (!s.assistant) throw new Error('no assistant')
      if (s.step === 'done') { onDone({ projectId: s.assistant.id, conversationId: s.conversation_id }); return }
      setState(s)
      // A new thread plays in; a reloaded one is simply there.
      setShown(s.created && !still() ? 0 : (s.messages?.length ?? 0))
    } catch {
      setFailed(true)
    }
  }, [call, onDone])

  // Once per mount: a second POST would answer "already created" and skip the reveal.
  const startedRef = useRef(false)
  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    void start()
  }, [start])

  const messages = state?.messages ?? []
  const revealing = shown < messages.length

  // Reveal one line at a time, with the typing dots in between — or all at once when
  // HomePilot's animations are off (switched off here while lines were still playing in).
  useEffect(() => {
    if (!revealing) return
    if (!animated) { setShown(messages.length); return }
    const t = setTimeout(() => setShown((n) => n + 1), shown === 0 ? 350 : REVEAL_MS)
    return () => clearTimeout(t)
  }, [revealing, shown, animated, messages.length])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: still() ? 'auto' : 'smooth', block: 'end' })
  }, [shown, busy])

  const finish = useCallback(async (extra: AssistantHandoff = {}) => {
    if (!state?.assistant) return
    setBusy(true)
    try { await call('/done') } catch { /* the app still opens; onboarding finishes next time */ }
    onDone({ projectId: state.assistant.id, conversationId: state.conversation_id, ...extra })
  }, [call, onDone, state])

  const apply = useCallback((next: State) => {
    if (next.step === 'introduced') { setCheer(true); setTimeout(() => setCheer(false), 1500) }
    setShown(still() ? (next.messages?.length ?? 0) : messages.length)
    setState(next)
  }, [messages.length])

  const keepName = useCallback(async () => {
    setBusy(true)
    try { apply(await call('/name', {})) } catch { await finish() } finally { setBusy(false) }
  }, [apply, call, finish])

  const send = useCallback(async () => {
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    if (state?.step === 'created') {
      setBusy(true)
      try {
        const next = await call('/name', { name: text })
        if (next.accepted) { apply(next); setBusy(false); return }
      } catch { /* fall through: treat it as the first message */ }
      await finish({ firstMessage: text })   // a question, not a name: the chat answers it
      return
    }
    await finish({ firstMessage: text })
  }, [apply, busy, call, finish, input, state?.step])

  const skip = useCallback(async () => {
    if (state?.step === 'created') { try { await call('/name', {}) } catch { /* ignore */ } }
    await finish()
  }, [call, finish, state?.step])

  const name = state?.assistant?.name || 'HomePilot'
  // The face follows the conversation: reading while you type, thinking while it waits,
  // talking while lines play in, a smile right after you name it.
  const face: FaceState = busy ? 'thinking'
    : cheer ? 'happy'
    : revealing ? 'speaking'
    : input.trim() ? 'attentive'
    : 'idle'
  const step = state?.step
  const ready = !!state && !revealing && !busy

  return (
    <div className="fixed inset-0 z-[60] flex flex-col bg-[#0a0a0c] text-white">
      {/* soft light from the top */}
      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-[360px] bg-[radial-gradient(ellipse_at_top,rgba(99,102,241,0.22),transparent_70%)]" />

      <header className="relative flex flex-col items-center gap-3 px-4 pt-[max(1.25rem,env(safe-area-inset-top))] pb-4">
        <button
          type="button"
          onClick={() => { void skip() }}
          disabled={!state || busy}
          className="absolute right-4 top-[max(1.25rem,env(safe-area-inset-top))] min-h-[44px] rounded-full px-4 text-[15px] text-white/50 hover:text-white/80 disabled:opacity-0"
        >
          Skip
        </button>
        <AssistantFace size={64} state={face} animated={animated} />
        <div className="rounded-full border border-white/10 bg-white/[0.06] px-5 py-1.5 text-[17px] font-semibold tracking-tight">{name}</div>
      </header>

      <main className="relative flex-1 overflow-y-auto px-4">
        <div className="mx-auto flex w-full max-w-xl flex-col gap-3 pb-6 pt-2">
          {failed && (
            <div className="mt-10 flex flex-col items-center gap-4 text-center">
              <p className="text-[17px] text-white/70">Couldn't reach HomePilot just now.</p>
              <div className="flex gap-2">
                <button type="button" onClick={() => { void start() }} className="min-h-[44px] rounded-full bg-white px-6 text-[15px] font-semibold text-black">Try again</button>
                <button type="button" onClick={() => onDone({})} className="min-h-[44px] rounded-full px-5 text-[15px] text-white/60">Continue</button>
              </div>
            </div>
          )}

          {messages.slice(0, shown).map((m, i) => (
            m.role === 'user' ? (
              <div key={i} className={`flex justify-end ${animated ? 'animate-[hpFadeUp_.28s_ease-out]' : ''}`}>
                <div className="max-w-[80%] rounded-[22px] bg-white px-5 py-3 text-[17px] leading-relaxed text-black">{m.content}</div>
              </div>
            ) : (
              <div key={i} className={`flex ${animated ? 'animate-[hpFadeUp_.28s_ease-out]' : ''}`}>
                <div className="max-w-[88%] rounded-[22px] bg-white/[0.07] px-5 py-3.5 text-[17px] leading-relaxed text-white/95">
                  <Text value={m.content} />
                </div>
              </div>
            )
          ))}

          {(revealing && shown > 0) || busy ? <Typing animated={animated} /> : null}

          {/* Step 1: the name, already answered */}
          {ready && step === 'created' && (
            <div className={`max-w-[88%] rounded-[26px] border border-white/10 bg-white/[0.03] p-2 ${animated ? 'animate-[hpFadeUp_.28s_ease-out]' : ''}`}>
              <button
                type="button"
                onClick={() => { void keepName() }}
                className="flex min-h-[56px] w-full items-center justify-between rounded-[20px] bg-white/[0.07] px-5 text-left text-[17px] hover:bg-white/[0.1] active:scale-[0.99]"
              >
                {name}
                <Check size={20} className="text-emerald-400" aria-hidden />
              </button>
            </div>
          )}

          {/* Step 2: something to try, one tap */}
          {ready && step === 'introduced' && (state?.starters?.length ?? 0) > 0 && (
            <div className={`grid grid-cols-2 gap-2.5 pt-1 ${animated ? 'animate-[hpFadeUp_.32s_ease-out]' : ''}`}>
              {state!.starters!.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => { void finish(s.kind === 'mode' ? { mode: s.mode } : { firstMessage: s.text }) }}
                  className="flex min-h-[88px] flex-col items-start justify-between rounded-[22px] border border-white/10 bg-white/[0.04] p-4 text-left hover:border-white/20 hover:bg-white/[0.07] active:scale-[0.98]"
                >
                  <span className="text-[26px] leading-none" aria-hidden>{s.icon}</span>
                  <span className="text-[15px] font-medium text-white/90">{s.label}</span>
                </button>
              ))}
            </div>
          )}
          <div ref={endRef} />
        </div>
      </main>

      <footer className="relative px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-2">
        <form
          className="mx-auto flex w-full max-w-xl items-center gap-2 rounded-full border border-white/10 bg-white/[0.06] py-1.5 pl-5 pr-1.5 focus-within:border-white/25"
          onSubmit={(e) => { e.preventDefault(); void send() }}
        >
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={!state || busy}
            placeholder={step === 'created' ? 'Or type a name…' : `Ask ${name}`}
            aria-label={step === 'created' ? 'Name your assistant' : `Message ${name}`}
            className="min-w-0 flex-1 bg-transparent py-2 text-[16px] text-white placeholder:text-white/35 outline-none"
          />
          <button
            type="submit"
            disabled={!input.trim() || busy}
            aria-label="Send"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white text-black disabled:bg-white/15 disabled:text-white/40"
          >
            <ArrowUp size={20} />
          </button>
        </form>
      </footer>

      <style>{`@keyframes hpFadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion: reduce){[class*="hpFadeUp"],.animate-bounce{animation:none!important}}`}</style>
    </div>
  )
}

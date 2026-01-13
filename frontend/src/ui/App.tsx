import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import Typewriter from './Typewriter'
import { Send, X, Sparkles, Image as ImageIcon, Film, Shield, KeyRound } from 'lucide-react'
import type { Msg } from './types'

function uuid() {
return crypto.randomUUID()
}

function isProbablyImageRequest(s: string) {
return /\b(imagine|generate|create|draw|make)\b.*\b(image|picture|photo|art)\b/i.test(s)
}

export default function App() {
const [messages, setMessages] = useState<Msg[]>([])
const [input, setInput] = useState('')
const [conversationId, setConversationId] = useState<string>(() => localStorage.getItem('homepilot_conversation') || uuid())
const [lightbox, setLightbox] = useState<string | null>(null)
const [funMode, setFunMode] = useState<boolean>(() => localStorage.getItem('homepilot_funmode') === '1')
const [apiKeyUi, setApiKeyUi] = useState<string>(() => localStorage.getItem('homepilot_api_key') || '')
const endRef = useRef<HTMLDivElement>(null)

useEffect(() => {
localStorage.setItem('homepilot_conversation', conversationId)
}, [conversationId])

useEffect(() => {
localStorage.setItem('homepilot_funmode', funMode ? '1' : '0')
}, [funMode])

useEffect(() => {
localStorage.setItem('homepilot_api_key', apiKeyUi)
}, [apiKeyUi])

useEffect(() => {
endRef.current?.scrollIntoView({ behavior: 'smooth' })
}, [messages.length])

const canSend = useMemo(() => input.trim().length > 0, [input])

async function sendTextOrIntent(text: string) {
const user: Msg = { id: uuid(), role: 'user', text }
const tmpId = uuid()
const pending: Msg = { id: tmpId, role: 'assistant', text: 'Thinking…', pending: true }

```
setMessages(prev => [...prev, user, pending])

try {
  const { data } = await api.post('/chat', {
    message: text,
    conversation_id: conversationId,
    fun_mode: funMode
  })

  setMessages(prev => prev.map(m => (
    m.id === tmpId ? { ...m, pending: false, text: data.text ?? '…', media: data.media ?? null } : m
  )))

  if (data.conversation_id && data.conversation_id !== conversationId) {
    setConversationId(data.conversation_id)
  }
} catch (e: any) {
  setMessages(prev => prev.map(m => (
    m.id === tmpId ? { ...m, pending: false, text: 'Error: backend unreachable or timeout.' } : m
  )))
}
```

}

async function uploadAndSend(file: File, mode: 'edit' | 'animate') {
const fd = new FormData()
fd.append('file', file)

```
const userText = mode === 'edit'
  ? `Edit this image: ${file.name}`
  : `Animate this image: ${file.name}`

const user: Msg = { id: uuid(), role: 'user', text: userText }
const tmpId = uuid()
const pending: Msg = { id: tmpId, role: 'assistant', text: mode === 'edit' ? 'Uploading + editing…' : 'Uploading + animating…', pending: true }
setMessages(prev => [...prev, user, pending])

try {
  const up = await api.post('/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  const imageUrl = up.data.url as string

  const payload = mode === 'edit'
    ? { message: `edit ${imageUrl} change something subtly cinematic`, conversation_id: conversationId, fun_mode: funMode }
    : { message: `animate ${imageUrl} subtle cinematic camera drift 6 seconds`, conversation_id: conversationId, fun_mode: funMode }

  const { data } = await api.post('/chat', payload)

  setMessages(prev => prev.map(m => (
    m.id === tmpId ? { ...m, pending: false, text: data.text ?? 'Done.', media: data.media ?? null } : m
  )))
} catch (e: any) {
  setMessages(prev => prev.map(m => (
    m.id === tmpId ? { ...m, pending: false, text: 'Upload failed or backend error.' } : m
  )))
}
```

}

return ( <div className="h-screen flex bg-black text-white selection:bg-white/20">
{/* Left bar */} <aside className="w-16 border-r border-white/10 flex flex-col items-center pt-6 gap-8"> <div className="w-9 h-9 rounded bg-white text-black grid place-items-center font-black text-xl">/</div>
<button
className={`w-10 h-10 rounded-xl grid place-items-center border ${funMode ? 'bg-white text-black border-white' : 'bg-white/5 border-white/10 text-white/80 hover:bg-white/10'}`}
title="Fun mode"
onClick={() => setFunMode(v => !v)}
> <Sparkles size={18} /> </button> </aside>

```
  <div className="flex-1 flex flex-col">
    <header className="h-14 border-b border-white/10 px-6 flex items-center justify-between bg-black/80 backdrop-blur sticky top-0 z-10">
      <div className="flex items-center gap-3">
        <div className="font-semibold tracking-tight">Grok</div>
        <span className="text-xs text-white/60 bg-white/10 px-2 py-0.5 rounded">home enterprise mind</span>
      </div>

      <div className="flex items-center gap-3 text-xs text-white/55">
        <div className="hidden md:flex items-center gap-2">
          <Shield size={14} />
          local-only
        </div>

        <div className="hidden md:flex items-center gap-2">
          <KeyRound size={14} />
          <input
            value={apiKeyUi}
            onChange={e => setApiKeyUi(e.target.value)}
            className="bg-white/5 border border-white/10 rounded px-2 py-1 w-40 focus:outline-none focus:border-white/25"
            placeholder="API key (optional)"
          />
        </div>
      </div>
    </header>

    <main className="flex-1 overflow-y-auto px-4 md:px-10 py-8 space-y-8">
      {messages.length === 0 && (
        <div className="h-full grid place-items-center text-white/45">
          <div className="text-center">
            <div className="text-7xl opacity-25 mb-4 animate-floaty">/</div>
            <div className="text-lg">Ask anything. Try “imagine a cinematic robot on Mars”.</div>
            <div className="text-sm mt-2 text-white/35">Upload an image to edit or animate it.</div>
          </div>
        </div>
      )}

      {messages.map(m => (
        <div key={m.id} className={`flex gap-4 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}>
          <div className={`w-8 h-8 rounded-full grid place-items-center font-bold text-sm
            ${m.role === 'user' ? 'bg-white/15' : 'bg-white text-black'}`}>
            {m.role === 'user' ? 'U' : '/'}
          </div>

          <div className="max-w-3xl w-full space-y-3">
            <div className={`px-5 py-3 rounded-2xl border
              ${m.role === 'user'
                ? 'bg-blue-600/90 border-blue-400/20'
                : 'bg-white/5 border-white/10 shadow-soft'
              }`}>
              <div className="text-[15px] leading-relaxed whitespace-pre-wrap">
                {m.role === 'assistant' && !m.pending
                  ? <Typewriter text={m.text} />
                  : m.text}
              </div>
            </div>

            {m.pending && isProbablyImageRequest(m.text) && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="aspect-square rounded-xl bg-white/5 animate-pulse border border-white/10" />
                ))}
              </div>
            )}

            {m.media?.images?.length ? (
              <div className="flex gap-3 overflow-x-auto pb-2">
                {m.media.images.map((src, i) => (
                  <img
                    key={i}
                    src={src}
                    className="h-56 w-56 object-cover rounded-xl border border-white/10 cursor-zoom-in hover:opacity-90"
                    onClick={() => setLightbox(src)}
                    alt={`generated ${i}`}
                  />
                ))}
              </div>
            ) : null}

            {m.media?.video_url ? (
              <video className="w-full max-w-3xl rounded-xl border border-white/10" controls src={m.media.video_url} />
            ) : null}
          </div>
        </div>
      ))}

      <div ref={endRef} />
    </main>

    <footer className="border-t border-white/10 p-4 md:p-6">
      <div className="max-w-4xl mx-auto space-y-3">
        <div className="flex gap-2">
          <label className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-white/5 border border-white/10 cursor-pointer hover:bg-white/10">
            <ImageIcon size={16} />
            <span className="text-sm text-white/80">Upload to edit</span>
            <input
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) uploadAndSend(f, 'edit')
                e.currentTarget.value = ''
              }}
            />
          </label>

          <label className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-white/5 border border-white/10 cursor-pointer hover:bg-white/10">
            <Film size={16} />
            <span className="text-sm text-white/80">Upload to animate</span>
            <input
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) uploadAndSend(f, 'animate')
                e.currentTarget.value = ''
              }}
            />
          </label>

          <button
            className="ml-auto px-3 py-2 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 text-sm"
            onClick={() => {
              const newId = uuid()
              setConversationId(newId)
              setMessages([])
            }}
          >
            New chat
          </button>
        </div>

        <div className="flex gap-3">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                sendTextOrIntent(input.trim())
                setInput('')
              }
            }}
            rows={1}
            placeholder="Ask anything… (try: imagine a cyberpunk city, ultra realistic)"
            className="flex-1 resize-none rounded-2xl bg-white/5 border border-white/10 px-5 py-4 focus:outline-none focus:border-white/25 min-h-[56px] max-h-[200px]"
          />
          <button
            disabled={!canSend}
            onClick={() => { sendTextOrIntent(input.trim()); setInput('') }}
            className="w-14 h-14 rounded-2xl bg-white/15 border border-white/10 grid place-items-center disabled:opacity-40 hover:bg-white/20"
            aria-label="Send"
          >
            <Send size={18} />
          </button>
        </div>

        <div className="text-center text-xs text-white/35">
          HomePilot can be wrong. Verify outputs. Runs locally.
        </div>
      </div>
    </footer>
  </div>

  {lightbox && (
    <div className="fixed inset-0 bg-black/95 z-50 grid place-items-center p-6" onClick={() => setLightbox(null)}>
      <button className="absolute top-6 right-6 w-12 h-12 rounded-full bg-white/10 grid place-items-center" onClick={() => setLightbox(null)}>
        <X />
      </button>
      <img src={lightbox} className="max-h-[90vh] max-w-[90vw] object-contain rounded-xl border border-white/10" onClick={e => e.stopPropagation()} />
    </div>
  )}
</div>
```

)
}

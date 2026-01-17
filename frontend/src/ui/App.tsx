import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Send,
  X,
  Sparkles,
  Image as ImageIcon,
  Film,
  Search,
  MessageSquare,
  Mic,
  Folder,
  Clock,
  Settings,
  Lock,
  Paperclip,
  Server,
  PlugZap,
} from 'lucide-react'

// -----------------------------------------------------------------------------
// Types (consolidated)
// -----------------------------------------------------------------------------

export type Msg = {
  id: string
  role: 'user' | 'assistant'
  text: string
  pending?: boolean
  media?: {
    images?: string[]
    video_url?: string
  } | null
}

type Mode = 'chat' | 'imagine' | 'edit' | 'animate'
type Provider = 'backend' | 'ollama'

type SettingsModel = {
  backendUrl: string
  provider: Provider
  ollamaUrl: string
  ollamaModel: string
  apiKey: string
  funMode: boolean
}

// -----------------------------------------------------------------------------
// Components (consolidated)
// -----------------------------------------------------------------------------

function Typewriter({ text, speed = 10 }: { text: string; speed?: number }) {
  const [displayedText, setDisplayedText] = useState('')
  const indexRef = useRef(0)

  // Reset when text changes (e.g. if we switch messages or streaming updates)
  useEffect(() => {
    // If text is already fully displayed, don't reset (prevents flickering on re-renders)
    if (text.startsWith(displayedText) && displayedText.length > 0 && text.length > displayedText.length) {
       // Continue typing from current position
    } else if (text !== displayedText && !text.startsWith(displayedText)) {
       // New text content entirely
       setDisplayedText('')
       indexRef.current = 0
    } else if (text === displayedText) {
       return 
    }
  }, [text, displayedText])

  useEffect(() => {
    const timer = setInterval(() => {
      if (indexRef.current < text.length) {
        setDisplayedText((prev) => text.slice(0, indexRef.current + 1))
        indexRef.current++
      } else {
        clearInterval(timer)
      }
    }, speed)

    return () => clearInterval(timer)
  }, [text, speed])

  return <span>{displayedText}</span>
}

function NavItem({
  icon: Icon,
  label,
  active,
  shortcut,
  onClick,
}: {
  icon: any
  label: string
  active?: boolean
  shortcut?: string
  onClick?: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={[
        'group/menu-item relative w-full',
        'peer/menu-button flex items-center gap-2 overflow-hidden rounded-xl text-left',
        'outline-none transition-colors select-none',
        'h-[36px] px-3 text-sm font-semibold',
        active ? 'bg-white/10 text-white' : 'text-white/70 hover:bg-white/5 hover:text-white',
      ].join(' ')}
      type="button"
    >
      <span className="size-6 flex items-center justify-center shrink-0">
        <Icon size={18} strokeWidth={2} />
      </span>
      <span className="truncate">{label}</span>
      {shortcut ? (
        <span className="absolute top-1/2 right-2 -translate-y-1/2 text-xs text-white/40 opacity-0 group-hover/menu-item:opacity-100 transition-opacity duration-100">
          {shortcut}
        </span>
      ) : null}
    </button>
  )
}

function SettingsPopover({
  value,
  onChange,
  onClose,
}: {
  value: SettingsModel
  onChange: (next: SettingsModel) => void
  onClose: () => void
}) {
  return (
    <div className="absolute bottom-16 left-4 w-80 bg-[#121212] border border-white/10 rounded-2xl p-4 shadow-2xl z-30 ring-1 ring-white/10">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-bold text-white">Settings</h3>
        <button
          type="button"
          onClick={onClose}
          className="text-white/50 hover:text-white p-1 rounded-lg hover:bg-white/5"
          aria-label="Close settings"
        >
          <X size={16} />
        </button>
      </div>

      <div className="space-y-4">
        {/* Backend URL */}
        <div>
          <label className="text-[11px] uppercase tracking-wider text-white/40 block mb-2 font-semibold flex items-center gap-2">
            <Server size={14} className="text-white/40" />
            Backend URL
          </label>
          <input
            className="w-full bg-black border border-white/10 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-white/30 transition-colors"
            value={value.backendUrl}
            onChange={(e) => onChange({ ...value, backendUrl: e.target.value })}
            placeholder="http://localhost:8000"
            inputMode="url"
          />
          <div className="text-[11px] text-white/35 mt-1">
            Used for /chat and /upload. Example: http://localhost:8000
          </div>
        </div>

        {/* Provider */}
        <div>
          <label className="text-[11px] uppercase tracking-wider text-white/40 block mb-2 font-semibold flex items-center gap-2">
            <PlugZap size={14} className="text-white/40" />
            LLM Provider
          </label>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => onChange({ ...value, provider: 'backend' })}
              className={[
                'px-3 py-2 rounded-xl border text-xs font-semibold transition-colors',
                value.provider === 'backend'
                  ? 'bg-white text-black border-white'
                  : 'bg-black border-white/10 text-white/70 hover:bg-white/5 hover:text-white',
              ].join(' ')}
            >
              Backend (vLLM etc.)
            </button>
            <button
              type="button"
              onClick={() => onChange({ ...value, provider: 'ollama' })}
              className={[
                'px-3 py-2 rounded-xl border text-xs font-semibold transition-colors',
                value.provider === 'ollama'
                  ? 'bg-white text-black border-white'
                  : 'bg-black border-white/10 text-white/70 hover:bg-white/5 hover:text-white',
              ].join(' ')}
            >
              Ollama (optional)
            </button>
          </div>
          <div className="text-[11px] text-white/35 mt-1">
            If you choose Ollama, your browser must reach Ollama and CORS must allow it (or use a
            reverse proxy).
          </div>
        </div>

        {/* Ollama options */}
        {value.provider === 'ollama' ? (
          <div className="space-y-3">
            <div>
              <label className="text-[11px] uppercase tracking-wider text-white/40 block mb-2 font-semibold">
                Ollama URL
              </label>
              <input
                className="w-full bg-black border border-white/10 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-white/30 transition-colors"
                value={value.ollamaUrl}
                onChange={(e) => onChange({ ...value, ollamaUrl: e.target.value })}
                placeholder="http://localhost:11434"
                inputMode="url"
              />
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-wider text-white/40 block mb-2 font-semibold">
                Ollama Model
              </label>
              <input
                className="w-full bg-black border border-white/10 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-white/30 transition-colors"
                value={value.ollamaModel}
                onChange={(e) => onChange({ ...value, ollamaModel: e.target.value })}
                placeholder="llama3.1:8b"
              />
            </div>
          </div>
        ) : null}

        {/* API Key */}
        <div>
          <label className="text-[11px] uppercase tracking-wider text-white/40 block mb-2 font-semibold">
            API Key (optional)
          </label>
          <input
            type="password"
            className="w-full bg-black border border-white/10 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-white/30 transition-colors"
            value={value.apiKey}
            onChange={(e) => onChange({ ...value, apiKey: e.target.value })}
            placeholder="x-api-key value"
          />
        </div>

        {/* Fun mode */}
        <div className="flex items-center justify-between pt-2 border-t border-white/5">
          <span className="text-sm text-white/80 flex items-center gap-2">
            <Sparkles size={14} className="text-yellow-500" />
            Fun Mode
          </span>
          <button
            type="button"
            onClick={() => onChange({ ...value, funMode: !value.funMode })}
            className={['w-11 h-6 rounded-full relative transition-colors', value.funMode ? 'bg-blue-600' : 'bg-white/10'].join(
              ' '
            )}
            aria-label="Toggle fun mode"
          >
            <span
              className={[
                'absolute top-1 left-1 w-4 h-4 bg-white rounded-full transition-transform shadow-sm',
                value.funMode ? 'translate-x-5' : 'translate-x-0',
              ].join(' ')}
            />
          </button>
        </div>
      </div>
    </div>
  )
}

function Sidebar({
  mode,
  setMode,
  messages,
  onNewConversation,
  onScrollToBottom,
  showSettings,
  setShowSettings,
  settings,
  setSettings,
}: {
  mode: Mode
  setMode: (m: Mode) => void
  messages: Msg[]
  onNewConversation: () => void
  onScrollToBottom: () => void
  showSettings: boolean
  setShowSettings: React.Dispatch<React.SetStateAction<boolean>>
  settings: SettingsModel
  setSettings: React.Dispatch<React.SetStateAction<SettingsModel>>
}) {
  return (
    <aside className="w-[280px] flex-shrink-0 flex flex-col h-full bg-black border-r border-white/5 py-4 px-3 gap-3 relative">
      {/* Search */}
      <div className="px-1.5">
        <button
          type="button"
          className="w-full text-left bg-[#121212] hover:bg-[#1a1a1a] text-white/60 text-sm px-3 py-2.5 rounded-xl flex items-center gap-2 transition-colors group border border-white/5"
          onClick={() => setShowSettings(false)}
        >
          <Search size={16} className="group-hover:text-white/80 transition-colors" />
          <span className="group-hover:text-white/80 transition-colors">Search</span>
          <span className="ml-auto text-xs opacity-40 bg-white/5 px-1.5 py-0.5 rounded border border-white/10">
            Ctrl+K
          </span>
        </button>
      </div>

      {/* Nav groups */}
      <div className="flex flex-col gap-3 px-1.5">
        <div className="flex flex-col gap-px">
          <NavItem icon={MessageSquare} label="Chat" active={mode === 'chat'} shortcut="Ctrl+J" onClick={() => setMode('chat')} />
          <NavItem icon={Mic} label="Voice" shortcut="Ctrl+V" onClick={() => alert('Voice mode coming soon')} />
          <NavItem icon={ImageIcon} label="Imagine" active={mode === 'imagine'} onClick={() => setMode('imagine')} />
        </div>

        <div className="pt-2">
          <div className="px-3 pb-2 text-xs font-semibold text-white/30 uppercase tracking-widest">Library</div>
          <div className="flex flex-col gap-px">
            <NavItem icon={Folder} label="Projects" onClick={() => {}} />
            <NavItem icon={Clock} label="History" onClick={() => {}} />
          </div>
        </div>

        <div className="pt-2">
          <div className="px-3 pb-2 text-xs font-semibold text-white/30 uppercase tracking-widest">Tools</div>
          <div className="flex flex-col gap-px">
            <NavItem icon={ImageIcon} label="Edit" active={mode === 'edit'} onClick={() => setMode('edit')} />
            <NavItem icon={Film} label="Animate" active={mode === 'animate'} onClick={() => setMode('animate')} />
          </div>
        </div>
      </div>

      {/* History list */}
      <div className="flex-1 overflow-y-auto min-h-0 px-1.5 pt-1">
        <div className="text-xs font-semibold text-white/30 mb-2 px-3">Today</div>

        <button
          type="button"
          className="w-full text-left px-3 py-2 text-[13px] text-white/70 hover:bg-white/5 hover:text-white rounded-xl truncate transition-colors"
          onClick={onNewConversation}
        >
          New conversation
        </button>

        {messages.length > 0 ? (
          <button
            type="button"
            className="w-full text-left px-3 py-2 text-[13px] text-white/60 hover:bg-white/5 hover:text-white rounded-xl truncate transition-colors"
            onClick={onScrollToBottom}
            title={messages[0]?.text}
          >
            {messages[0]?.text?.slice(0, 34) || 'Conversation…'}
            {messages[0]?.text && messages[0].text.length > 34 ? '…' : ''}
          </button>
        ) : null}
      </div>

      {/* User footer */}
      <div className="mt-auto px-2 pt-4 border-t border-white/5 flex items-center justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-600 to-purple-600 flex items-center justify-center text-xs font-bold text-white shadow-lg">
            U
          </div>
          <div className="text-sm font-medium text-white/90 truncate">User</div>
        </div>

        <button
          type="button"
          onClick={() => setShowSettings((v) => !v)}
          className="text-white/40 hover:text-white p-2 transition-colors rounded-xl hover:bg-white/5"
          aria-label="Settings"
        >
          <Settings size={18} />
        </button>
      </div>

      {showSettings ? (
        <SettingsPopover
          value={settings}
          onChange={(next) => setSettings(next)}
          onClose={() => setShowSettings(false)}
        />
      ) : null}
    </aside>
  )
}

function QueryBar({
  centered,
  input,
  setInput,
  mode,
  fileInputRef,
  canSend,
  onSend,
  onUpload,
}: {
  centered: boolean
  input: string
  setInput: (s: string) => void
  mode: Mode
  fileInputRef: React.RefObject<HTMLInputElement>
  canSend: boolean
  onSend: () => void
  onUpload: (file: File) => void
}) {
  return (
    <div className={`w-full ${centered ? 'max-w-breakout' : ''}`}>
      <div
        className={[
          'relative w-full overflow-hidden',
          'bg-[#101010] shadow-sm shadow-black/20',
          'ring-1 ring-inset ring-white/10 hover:ring-white/15 focus-within:ring-white/20',
          'rounded-[10rem]',
          'transition-[background-color,box-shadow,border-color] duration-100 ease-in-out',
        ].join(' ')}
      >
        {/* Left: attach */}
        <div className="absolute left-3 top-1/2 -translate-y-1/2 z-20">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="h-10 w-10 rounded-full grid place-items-center text-white/50 hover:text-white hover:bg-white/5 transition-colors"
            aria-label="Upload image"
            title="Upload image"
          >
            <Paperclip size={18} />
          </button>
          <input
            type="file"
            ref={fileInputRef}
            className="hidden"
            accept="image/*"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) onUpload(f)
              e.currentTarget.value = ''
            }}
          />
        </div>

        {/* Right: submit or mic */}
        <div className="absolute right-2 bottom-3 z-20 flex items-center gap-2">
          {canSend ? (
            <button
              type="button"
              onClick={onSend}
              className="h-10 w-10 rounded-full bg-white text-black grid place-items-center hover:opacity-90 transition-opacity"
              aria-label="Submit"
              title="Submit"
            >
              <Send size={18} strokeWidth={2.25} />
            </button>
          ) : (
            <button
              type="button"
              className="h-10 w-10 rounded-full bg-white/5 text-white/60 grid place-items-center hover:bg-white/10 hover:text-white transition-colors"
              aria-label="Voice"
              title="Voice"
              onClick={() => alert('Voice mode coming soon')}
            >
              <Mic size={18} />
            </button>
          )}
        </div>

        {/* Textarea */}
        <div className="ps-12 pe-20">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                if (input.trim()) onSend()
              }
            }}
            rows={1}
            placeholder={modeHint(mode)}
            className={[
              'w-full bg-transparent text-white placeholder:text-white/35',
              'focus:outline-none resize-none',
              'min-h-14 py-4 px-2',
              'max-h-[400px] overflow-y-auto',
              'text-[15px] leading-relaxed',
            ].join(' ')}
          />
        </div>
      </div>

      {centered ? (
        <div className="w-full flex justify-center mt-3 px-2 animate-in fade-in-0 zoom-in-95 transition-transform duration-150 ease-out hover:scale-[1.01] active:scale-[0.99]">
          <div className="relative group flex w-fit sm:w-auto items-center rounded-2xl border border-white/10 bg-[#101010] px-4 py-3 shadow-sm gap-6">
            <div className="flex flex-row gap-3 items-center">
              <div className="flex size-10 items-center justify-center rounded-full border border-white/10 bg-black">
                <span className="text-2xl leading-none">𝕏</span>
              </div>
              <div className="flex flex-col gap-1 text-start">
                <p className="text-sm font-medium text-white">Connect your 𝕏 account</p>
                <p className="text-xs text-white/50">Unlock early features and personalized content.</p>
              </div>
            </div>

            <button
              type="button"
              className="inline-flex items-center justify-center h-8 px-3 rounded-full border border-white/15 text-white hover:bg-white/5 transition-colors text-sm font-medium shrink-0"
            >
              Connect
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function EmptyState({
  mode,
  input,
  setInput,
  fileInputRef,
  canSend,
  onSend,
  onUpload,
}: {
  mode: Mode
  input: string
  setInput: (s: string) => void
  fileInputRef: React.RefObject<HTMLInputElement>
  canSend: boolean
  onSend: () => void
  onUpload: (file: File) => void
}) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6">
      <div className="mb-6 flex flex-col items-center gap-3">
        <div className="flex items-center gap-2 opacity-95">
          <div className="text-[64px] font-light leading-none tracking-tighter text-white">/</div>
          <div className="text-[42px] font-semibold tracking-tight text-white">HomePilot</div>
        </div>
        <div className="text-sm text-white/40 -mt-1">enterprise mind</div>

        {mode !== 'chat' ? (
          <span className="text-[11px] font-bold bg-white/10 text-white/90 px-2.5 py-1 rounded-md uppercase tracking-widest border border-white/5">
            {mode} mode
          </span>
        ) : null}
      </div>

      <div className="w-full max-w-[46rem]">
        <QueryBar
          centered
          input={input}
          setInput={setInput}
          mode={mode}
          fileInputRef={fileInputRef}
          canSend={canSend}
          onSend={onSend}
          onUpload={onUpload}
        />
      </div>
    </div>
  )
}

function ChatState({
  messages,
  setLightbox,
  endRef,
  mode,
  input,
  setInput,
  fileInputRef,
  canSend,
  onSend,
  onUpload,
}: {
  messages: Msg[]
  setLightbox: (url: string) => void
  endRef: React.RefObject<HTMLDivElement>
  mode: Mode
  input: string
  setInput: (s: string) => void
  fileInputRef: React.RefObject<HTMLInputElement>
  canSend: boolean
  onSend: () => void
  onUpload: (file: File) => void
}) {
  return (
    <div className="flex flex-col h-full w-full max-w-[52rem] mx-auto">
      <div className="flex-1 overflow-y-auto px-4 py-8 space-y-8">
        {messages.map((m) => (
          <div
            key={m.id}
            className={`flex gap-5 ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {m.role === 'assistant' ? (
              <div className="w-8 h-8 rounded-full bg-white text-black flex items-center justify-center flex-shrink-0 font-bold text-sm mt-1">
                /
              </div>
            ) : null}

            <div
              className={[
                'max-w-[85%] space-y-3',
                m.role === 'user'
                  ? 'bg-[#1A1A1A] text-white px-5 py-3.5 rounded-[20px] rounded-tr-sm'
                  : '',
              ].join(' ')}
            >
              <div className="text-[16px] leading-relaxed whitespace-pre-wrap text-[#EEE] font-normal tracking-wide">
                {m.role === 'assistant' && !m.pending ? <Typewriter text={m.text} /> : m.text}
              </div>

              {m.media?.images?.length ? (
                <div className="flex gap-2 overflow-x-auto pt-1">
                  {m.media.images.map((src: string, i: number) => (
                    <img
                      key={i}
                      src={src}
                      onClick={() => setLightbox(src)}
                      className="h-56 w-56 object-cover rounded-xl border border-white/10 cursor-zoom-in hover:opacity-90 transition-opacity"
                      alt={`generated ${i}`}
                    />
                  ))}
                </div>
              ) : null}

              {m.media?.video_url ? (
                <video
                  controls
                  src={m.media.video_url}
                  className="w-full rounded-xl border border-white/10 mt-2"
                />
              ) : null}
            </div>
          </div>
        ))}
        <div ref={endRef} className="h-6" />
      </div>

      <div className="bg-black/95 backdrop-blur-sm pb-4">
        <div className="px-4">
          <QueryBar
            centered={false}
            input={input}
            setInput={setInput}
            mode={mode}
            fileInputRef={fileInputRef}
            canSend={canSend}
            onSend={onSend}
            onUpload={onUpload}
          />
        </div>
        <div className="text-center text-[11px] text-[#444] pt-3 font-medium">
          HomePilot can make mistakes. Verify outputs.
        </div>
      </div>
    </div>
  )
}

/* ------------------------------- Main App ------------------------------- */

function uuid() {
  return crypto.randomUUID()
}

function modeHint(mode: Mode) {
  switch (mode) {
    case 'chat':
      return 'What do you want to know?'
    case 'imagine':
      return 'Describe an image to generate...'
    case 'edit':
      return 'Upload an image or describe edits...'
    case 'animate':
      return 'Upload an image or describe motion...'
    default:
      return 'What do you want to know?'
  }
}

function buildMessageForMode(mode: Mode, text: string) {
  const t = text.trim()
  if (!t) return t
  if (mode === 'chat') return t

  if (mode === 'imagine') {
    if (/\b(imagine|generate|create|draw|make)\b/i.test(t)) return t
    return `imagine ${t}`
  }

  if (mode === 'edit' || mode === 'animate') {
    return `${mode} ${t}`
  }

  return t
}

/**
 * Simple, dependency-free JSON POST helper that supports dynamic base URLs.
 * (Avoids axios instance baseURL mismatch when user changes backend URL in UI.)
 */
async function postJson<T>(
  baseUrl: string,
  path: string,
  body: any,
  headers?: Record<string, string>
): Promise<T> {
  const url = `${baseUrl.replace(/\/+$/, '')}${path.startsWith('/') ? path : `/${path}`}`
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(headers ?? {}),
    },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText}${text ? `: ${text}` : ''}`)
  }
  return (await res.json()) as T
}

async function postForm<T>(
  baseUrl: string,
  path: string,
  form: FormData,
  headers?: Record<string, string>
): Promise<T> {
  const url = `${baseUrl.replace(/\/+$/, '')}${path.startsWith('/') ? path : `/${path}`}`
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      ...(headers ?? {}),
      // NOTE: do NOT set Content-Type for FormData; browser sets boundary.
    },
    body: form,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText}${text ? `: ${text}` : ''}`)
  }
  return (await res.json()) as T
}

/** Optional: direct Ollama call (browser->Ollama). Requires Ollama CORS / reverse proxy. */
type OllamaChatResponse = {
  message?: { role?: string; content?: string }
  response?: string
}
async function ollamaChat(
  ollamaBaseUrl: string,
  model: string,
  messages: Array<{ role: 'system' | 'user' | 'assistant'; content: string }>
) {
  const url = `${ollamaBaseUrl.replace(/\/+$/, '')}/api/chat`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      messages,
      stream: false,
    }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`Ollama HTTP ${res.status} ${res.statusText}${text ? `: ${text}` : ''}`)
  }
  const data = (await res.json()) as OllamaChatResponse
  return data.message?.content ?? data.response ?? ''
}

export default function App() {
  // Core State
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [conversationId, setConversationId] = useState<string>(() => {
    return localStorage.getItem('homepilot_conversation') || uuid()
  })
  const [lightbox, setLightbox] = useState<string | null>(null)

  const [mode, setMode] = useState<Mode>(() => {
    return (localStorage.getItem('homepilot_mode') as Mode) || 'chat'
  })

  // Unified settings model
  const [settings, setSettings] = useState<SettingsModel>(() => {
    const backendUrl =
      localStorage.getItem('homepilot_backend_url') || 'http://localhost:8000'
    const provider = (localStorage.getItem('homepilot_provider') as Provider) || 'backend'
    const ollamaUrl = localStorage.getItem('homepilot_ollama_url') || 'http://localhost:11434'
    const ollamaModel = localStorage.getItem('homepilot_ollama_model') || 'llama3.1:8b'
    const apiKey = localStorage.getItem('homepilot_api_key') || ''
    const funMode = localStorage.getItem('homepilot_funmode') === '1'
    return { backendUrl, provider, ollamaUrl, ollamaModel, apiKey, funMode }
  })

  const [showSettings, setShowSettings] = useState(false)

  const endRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Persist
  useEffect(() => localStorage.setItem('homepilot_conversation', conversationId), [conversationId])
  useEffect(() => localStorage.setItem('homepilot_mode', mode), [mode])

  useEffect(() => {
    localStorage.setItem('homepilot_backend_url', settings.backendUrl)
    localStorage.setItem('homepilot_provider', settings.provider)
    localStorage.setItem('homepilot_ollama_url', settings.ollamaUrl)
    localStorage.setItem('homepilot_ollama_model', settings.ollamaModel)
    localStorage.setItem('homepilot_api_key', settings.apiKey)
    localStorage.setItem('homepilot_funmode', settings.funMode ? '1' : '0')
  }, [settings])

  // Scroll on new message
  useEffect(() => {
    if (messages.length > 0) endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  const canSend = useMemo(() => input.trim().length > 0, [input])

  const authHeaders = useMemo(() => {
    const k = settings.apiKey.trim()
    return k ? { 'x-api-key': k } : undefined
  }, [settings.apiKey])

  const onNewConversation = useCallback(() => {
    setConversationId(uuid())
    setMessages([])
  }, [])

  const onScrollToBottom = useCallback(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  const sendTextOrIntent = useCallback(
    async (rawText: string) => {
      const trimmed = rawText.trim()
      if (!trimmed) return

      setShowSettings(false)

      // user-visible message stays as typed; request uses mode prefixes
      const requestText = buildMessageForMode(mode, trimmed)

      const user: Msg = { id: uuid(), role: 'user', text: trimmed }
      const tmpId = uuid()
      const pending: Msg = { id: tmpId, role: 'assistant', text: 'Thinking…', pending: true }

      setMessages((prev) => [...prev, user, pending])

      try {
        // If provider is Ollama, we do a direct browser call (optional).
        if (settings.provider === 'ollama') {
          const system = settings.funMode
            ? 'You are HomePilot enterprise mind. Be witty, concise, and helpful.'
            : 'You are HomePilot enterprise mind. Be concise and helpful.'

          const history = messages
            .filter((m) => !m.pending)
            .slice(-12)
            .map((m) => ({
              role: (m.role === 'user' ? 'user' : 'assistant') as 'user' | 'assistant',
              content: m.text,
            }))

          const reply = await ollamaChat(settings.ollamaUrl, settings.ollamaModel, [
            { role: 'system', content: system },
            ...history,
            { role: 'user', content: requestText },
          ])

          setMessages((prev) =>
            prev.map((m) => (m.id === tmpId ? { ...m, pending: false, text: reply || '…' } : m))
          )
          return
        }

        // Default: call backend
        const data = await postJson<any>(
          settings.backendUrl,
          '/chat',
          {
            message: requestText,
            conversation_id: conversationId,
            fun_mode: settings.funMode,
            mode,
            // FIX: Use 'provider' to match Python Pydantic model. 
            // 'ollama' is handled via browser fetch above, so here we use backend default (null).
            provider: null,
            
            ollama_base_url: settings.ollamaUrl,
            ollama_model: settings.ollamaModel,
          },
          authHeaders
        )

        setMessages((prev) =>
          prev.map((m) =>
            m.id === tmpId
              ? { ...m, pending: false, text: data.text ?? '…', media: data.media ?? null }
              : m
          )
        )

        if (data.conversation_id && data.conversation_id !== conversationId) {
          setConversationId(data.conversation_id)
        }
      } catch (err: any) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === tmpId
              ? {
                  ...m,
                  pending: false,
                  text: `Error: ${
                    typeof err?.message === 'string' ? err.message : 'backend unreachable.'
                  }`,
                }
              : m
          )
        )
      }
    },
    [
      authHeaders,
      conversationId,
      messages,
      mode,
      settings.backendUrl,
      settings.funMode,
      settings.ollamaModel,
      settings.ollamaUrl,
      settings.provider,
    ]
  )

  const uploadAndSend = useCallback(
    async (file: File) => {
      setShowSettings(false)

      // Only supported via backend (because backend returns stable /uploads URL and handles pipelines)
      const intent: 'edit' | 'animate' = mode === 'animate' ? 'animate' : 'edit'

      const fd = new FormData()
      fd.append('file', file)

      const userText =
        intent === 'edit' ? `Edit this image: ${file.name}` : `Animate this image: ${file.name}`

      const user: Msg = { id: uuid(), role: 'user', text: userText }
      const tmpId = uuid()
      const pending: Msg = {
        id: tmpId,
        role: 'assistant',
        text: intent === 'edit' ? 'Uploading + editing…' : 'Uploading + animating…',
        pending: true,
      }

      setMessages((prev) => [...prev, user, pending])

      try {
        const up = await postForm<any>(settings.backendUrl, '/upload', fd, authHeaders)
        const imageUrl = up.url as string

        const extra =
          input.trim() ||
          (intent === 'animate'
            ? 'subtle cinematic camera drift, 6 seconds'
            : 'make it cinematic')

        setInput('')

        const data = await postJson<any>(
          settings.backendUrl,
          '/chat',
          {
            message: `${intent} ${imageUrl} ${extra}`,
            conversation_id: conversationId,
            fun_mode: settings.funMode,
            mode: intent,
            // FIX: Use 'provider' to match Python Pydantic model. 
            // If settings says 'backend', send null so backend uses its own default.
            provider: settings.provider === 'ollama' ? 'ollama' : null,

            ollama_base_url: settings.ollamaUrl,
            ollama_model: settings.ollamaModel,
          },
          authHeaders
        )

        setMessages((prev) =>
          prev.map((m) =>
            m.id === tmpId
              ? { ...m, pending: false, text: data.text ?? 'Done.', media: data.media ?? null }
              : m
          )
        )
      } catch (err: any) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === tmpId
              ? {
                  ...m,
                  pending: false,
                  text: `Upload failed: ${
                    typeof err?.message === 'string' ? err.message : 'backend error.'
                  }`,
                }
              : m
          )
        )
      }
    },
    [
      authHeaders,
      conversationId,
      input,
      mode,
      settings.backendUrl,
      settings.funMode,
      settings.ollamaModel,
      settings.ollamaUrl,
      settings.provider,
    ]
  )

  const onSend = useCallback(() => {
    const v = input
    if (!v.trim()) return
    void sendTextOrIntent(v)
    setInput('')
  }, [input, sendTextOrIntent])

  return (
    <div className="flex h-screen bg-black text-white font-sans selection:bg-white/20 overflow-hidden relative">
      <Sidebar
        mode={mode}
        setMode={setMode}
        messages={messages}
        onNewConversation={onNewConversation}
        onScrollToBottom={onScrollToBottom}
        showSettings={showSettings}
        setShowSettings={setShowSettings}
        settings={settings}
        setSettings={setSettings}
      />

      <main className="flex-1 flex flex-col relative min-w-0">
        {/* Top-right “Private” */}
        <header className="absolute top-0 right-0 p-5 z-20 flex items-center gap-4">
          <button
            type="button"
            className="inline-flex items-center gap-2 text-white/30 text-xs font-semibold hover:text-white transition-colors border border-transparent h-10 px-4 rounded-full hover:bg-white/5"
            onClick={() => {}}
            aria-label="Private"
            title="Private"
          >
            <Lock size={12} />
            <span>Private</span>
          </button>
        </header>

        {messages.length === 0 ? (
          <EmptyState
            mode={mode}
            input={input}
            setInput={setInput}
            fileInputRef={fileInputRef}
            canSend={canSend}
            onSend={onSend}
            onUpload={uploadAndSend}
          />
        ) : (
          <ChatState
            messages={messages}
            setLightbox={setLightbox}
            endRef={endRef}
            mode={mode}
            input={input}
            setInput={setInput}
            fileInputRef={fileInputRef}
            canSend={canSend}
            onSend={onSend}
            onUpload={uploadAndSend}
          />
        )}
      </main>

      {/* Lightbox */}
      {lightbox ? (
        <div
          className="fixed inset-0 bg-black/95 z-50 flex items-center justify-center p-8 backdrop-blur-md animate-in fade-in duration-200"
          onClick={() => setLightbox(null)}
          role="dialog"
          aria-modal="true"
        >
          <button
            type="button"
            className="absolute top-6 right-6 p-2 bg-white/10 rounded-full hover:bg-white/20 transition-colors"
            onClick={() => setLightbox(null)}
            aria-label="Close preview"
          >
            <X size={24} />
          </button>

          <img
            src={lightbox}
            className="max-w-[90vw] max-h-[90vh] rounded-lg shadow-2xl border border-white/10"
            onClick={(e) => e.stopPropagation()}
            alt="preview"
          />
        </div>
      ) : null}
    </div>
  )
}
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
  Trash2,
  Tv2,
  Plus,
  Copy,
  RotateCw,
  PenLine,
} from 'lucide-react'
import SettingsPanel, { type SettingsModelV2, type HardwarePresetUI } from './SettingsPanel'
import VoiceMode, { stripMarkdownForSpeech } from './VoiceModeGrok'
// Legacy voice mode available as: import VoiceModeLegacy from './VoiceModeLegacy'
import ProjectsView from './ProjectsView'
import ImagineView from './Imagine'
import AnimateView from './Animate'
import ModelsView from './Models'
import StudioView from './Studio'
import { CreatorStudioHost } from './CreatorStudioHost'
import {
  ChatSettingsPopover,
  DEFAULT_CHAT_SETTINGS,
  type ChatScopedSettings,
} from './components/ChatSettingsPopover'
import { MessageMarkdown } from './components/MessageMarkdown'
import { ChatEmptyState } from './components/ChatEmptyState'
import { AgentIntent, INTENT_COPY } from './components/AgentIntentTiles'
import { AgentSettingsPanel, type AgentProjectData } from './components/AgentSettingsPanel'
import { PersonaSettingsPanel } from './components/PersonaSettingsPanel'
import { detectAgenticIntent, type AgenticIntent } from './agentic/intent'
import { ImageViewer } from './ImageViewer'
import { EditTab } from './edit'
import { PERSONALITY_CAPS, type PersonalityId } from './voice/personalityCaps'
import {
  getVoiceLinkedProjectId,
  setVoiceLinkedToProject,
  isPersonasEnabled,
  setPersonasEnabled as setPersonasEnabledGating,
  LS_PERSONA_CACHE,
} from './voice/personalityGating'
// Companion-grade session management (additive)
import { resolveSession, createSession, endSession } from './sessions'
import { SessionPanel } from './sessions'
import type { PersonaSession } from './sessions'

// -----------------------------------------------------------------------------
// Global type declarations
// -----------------------------------------------------------------------------

declare global {
  interface Window {
    SpeechService?: any;
  }
}

// -----------------------------------------------------------------------------
// Types (consolidated)
// -----------------------------------------------------------------------------

export type Msg = {
  id: string
  role: 'user' | 'assistant'
  text: string
  pending?: boolean
  animate?: boolean
  // when true, show recovery UI and allow retry
  error?: boolean
  // info needed for retry; kept minimal and non-destructive
  retry?: { requestText: string; mode: Mode; projectId?: string }
  media?: {
    images?: string[]
    video_url?: string
  } | null
  // Phase 4: "Ask before acting" confirmation payload
  confirm?: {
    intent: 'generate_images' | 'generate_videos'
    prompt: string
  }
}

type Mode = 'chat' | 'voice' | 'search' | 'project' | 'imagine' | 'edit' | 'animate' | 'models' | 'studio'
type Provider = 'backend' | 'ollama'

type HardwarePreset = '4060' | '4080' | 'a100' | 'custom'

type SettingsModel = {
  backendUrl: string
  provider: Provider
  ollamaUrl: string
  ollamaModel: string
  apiKey: string
  funMode: boolean
  // Text generation parameters
  textTemperature: number
  textMaxTokens: number
  // Image generation parameters
  imgWidth: number
  imgHeight: number
  imgSteps: number
  imgCfg: number
  imgSeed: number
  // Video generation parameters
  vidSeconds: number
  vidFps: number
  vidMotion: string
  // Hardware preset
  preset: HardwarePreset
}

type Conversation = {
  conversation_id: string
  last_role: string
  last_content: string
  updated_at: string
}

// -----------------------------------------------------------------------------
// Components (consolidated)
// -----------------------------------------------------------------------------

function Typewriter({
  text,
  speed = 10,
  onDone,
}: {
  text: string
  speed?: number
  onDone?: () => void
}) {
  const [displayedText, setDisplayedText] = useState('')
  const indexRef = useRef(0)
  const doneRef = useRef(false)

  // Reset when text changes (e.g. if we switch messages or streaming updates)
  useEffect(() => {
    // If text is already fully displayed, don't reset (prevents flickering on re-renders)
    if (text.startsWith(displayedText) && displayedText.length > 0 && text.length > displayedText.length) {
       // Continue typing from current position
    } else if (text !== displayedText && !text.startsWith(displayedText)) {
       // New text content entirely
       setDisplayedText('')
       indexRef.current = 0
       doneRef.current = false
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
        if (!doneRef.current) {
          doneRef.current = true
          onDone?.()
        }
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
  const [availableModels, setAvailableModels] = useState<string[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [modelsError, setModelsError] = useState<string | null>(null)

  const fetchModels = async () => {
    setLoadingModels(true)
    setModelsError(null)
    try {
      const url = `${value.backendUrl}/models?provider=ollama&base_url=${encodeURIComponent(value.ollamaUrl)}`
      const response = await fetch(url)
      const data = await response.json()

      if (data.ok && Array.isArray(data.models)) {
        setAvailableModels(data.models)
        if (data.models.length === 0) {
          setModelsError('No models found. Run "ollama pull <model-name>" to download a model.')
        }
      } else {
        setModelsError(data.message || 'Failed to fetch models')
      }
    } catch (err: any) {
      setModelsError(err.message || 'Failed to connect to backend')
    } finally {
      setLoadingModels(false)
    }
  }

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
              <div className="flex gap-2">
                <input
                  className="flex-1 bg-black border border-white/10 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-white/30 transition-colors"
                  value={value.ollamaModel}
                  onChange={(e) => onChange({ ...value, ollamaModel: e.target.value })}
                  placeholder="llama3:8b"
                />
                <button
                  type="button"
                  onClick={fetchModels}
                  disabled={loadingModels}
                  className="px-3 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-xs text-white font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  title="Fetch available models from Ollama"
                >
                  {loadingModels ? 'Loading...' : 'Fetch'}
                </button>
              </div>
              {modelsError && (
                <div className="mt-2 text-[11px] text-red-400">{modelsError}</div>
              )}
              {availableModels.length > 0 && (
                <div className="mt-2">
                  <div className="text-[10px] text-white/40 mb-1">
                    Available models ({availableModels.length}):
                  </div>
                  <div className="max-h-32 overflow-y-auto space-y-1">
                    {availableModels.map((model) => (
                      <button
                        key={model}
                        type="button"
                        onClick={() => onChange({ ...value, ollamaModel: model })}
                        className={[
                          'w-full text-left px-2 py-1.5 rounded-lg text-xs transition-colors',
                          value.ollamaModel === model
                            ? 'bg-white/10 text-white font-semibold'
                            : 'bg-black/50 text-white/70 hover:bg-white/5 hover:text-white',
                        ].join(' ')}
                      >
                        {model}
                      </button>
                    ))}
                  </div>
                </div>
              )}
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

        {/* Divider */}
        <div className="border-t border-white/5 pt-4">
          <h4 className="text-[11px] uppercase tracking-wider text-white/40 mb-3 font-semibold">
            Hardware Preset
          </h4>
          <div className="grid grid-cols-4 gap-2">
            {(['4060', '4080', 'a100', 'custom'] as HardwarePreset[]).map((preset) => (
              <button
                key={preset}
                onClick={() => {
                  const presets = {
                    '4060': { imgWidth: 1024, imgHeight: 1024, imgSteps: 20, imgCfg: 5.0, vidSeconds: 4, vidFps: 8 },
                    '4080': { imgWidth: 1024, imgHeight: 1344, imgSteps: 25, imgCfg: 6.0, vidSeconds: 6, vidFps: 12 },
                    'a100': { imgWidth: 1536, imgHeight: 1536, imgSteps: 40, imgCfg: 7.0, vidSeconds: 8, vidFps: 16 },
                    'custom': {}
                  }
                  onChange({ ...value, preset, ...(preset !== 'custom' ? presets[preset] : {}) })
                }}
                className={[
                  'px-2 py-1.5 rounded-lg text-xs font-medium transition-all',
                  value.preset === preset
                    ? 'bg-blue-600 text-white'
                    : 'bg-white/5 text-white/60 hover:bg-white/10 hover:text-white/80'
                ].join(' ')}
              >
                {preset.toUpperCase()}
              </button>
            ))}
          </div>
          <div className="text-[10px] text-white/35 mt-2">
            {value.preset === '4060' && '✓ RTX 4060: 1024x1024, 20 steps, good for quick iterations'}
            {value.preset === '4080' && '✓ RTX 4080: Higher res, 25 steps, balanced quality'}
            {value.preset === 'a100' && '✓ A100: Max quality, 1536x1536, 40 steps'}
            {value.preset === 'custom' && '✓ Custom: Manual settings below'}
          </div>
        </div>

        {/* Text Generation */}
        <div className="border-t border-white/5 pt-4">
          <h4 className="text-[11px] uppercase tracking-wider text-white/40 mb-3 font-semibold">
            Text Generation
          </h4>
          <div className="space-y-3">
            <div>
              <label className="text-[10px] text-white/50 block mb-1">Temperature: {value.textTemperature}</label>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={value.textTemperature}
                onChange={(e) => onChange({ ...value, textTemperature: parseFloat(e.target.value) })}
                className="w-full"
              />
            </div>
            <div>
              <label className="text-[10px] text-white/50 block mb-1">Max Tokens: {value.textMaxTokens}</label>
              <input
                type="range"
                min="256"
                max="8192"
                step="256"
                value={value.textMaxTokens}
                onChange={(e) => onChange({ ...value, textMaxTokens: parseInt(e.target.value) })}
                className="w-full"
              />
            </div>
          </div>
        </div>

        {/* Image Generation */}
        <div className="border-t border-white/5 pt-4">
          <h4 className="text-[11px] uppercase tracking-wider text-white/40 mb-3 font-semibold">
            Image Generation
          </h4>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] text-white/50 block mb-1">Width</label>
                <input
                  type="number"
                  value={value.imgWidth}
                  onChange={(e) => onChange({ ...value, imgWidth: parseInt(e.target.value) || 1024 })}
                  className="w-full bg-black border border-white/10 rounded-lg px-2 py-1 text-xs text-white"
                />
              </div>
              <div>
                <label className="text-[10px] text-white/50 block mb-1">Height</label>
                <input
                  type="number"
                  value={value.imgHeight}
                  onChange={(e) => onChange({ ...value, imgHeight: parseInt(e.target.value) || 1024 })}
                  className="w-full bg-black border border-white/10 rounded-lg px-2 py-1 text-xs text-white"
                />
              </div>
            </div>
            <div>
              <label className="text-[10px] text-white/50 block mb-1">Steps: {value.imgSteps}</label>
              <input
                type="range"
                min="10"
                max="50"
                step="1"
                value={value.imgSteps}
                onChange={(e) => onChange({ ...value, imgSteps: parseInt(e.target.value) })}
                className="w-full"
              />
            </div>
            <div>
              <label className="text-[10px] text-white/50 block mb-1">CFG Scale: {value.imgCfg}</label>
              <input
                type="range"
                min="1"
                max="15"
                step="0.5"
                value={value.imgCfg}
                onChange={(e) => onChange({ ...value, imgCfg: parseFloat(e.target.value) })}
                className="w-full"
              />
            </div>
            <div>
              <label className="text-[10px] text-white/50 block mb-1">Seed (-1 = random)</label>
              <input
                type="number"
                value={value.imgSeed}
                onChange={(e) => onChange({ ...value, imgSeed: parseInt(e.target.value) || -1 })}
                className="w-full bg-black border border-white/10 rounded-lg px-2 py-1 text-xs text-white"
              />
            </div>
          </div>
        </div>

        {/* Video Generation */}
        <div className="border-t border-white/5 pt-4">
          <h4 className="text-[11px] uppercase tracking-wider text-white/40 mb-3 font-semibold">
            Video Generation
          </h4>
          <div className="space-y-3">
            <div>
              <label className="text-[10px] text-white/50 block mb-1">Duration: {value.vidSeconds}s</label>
              <input
                type="range"
                min="2"
                max="10"
                step="1"
                value={value.vidSeconds}
                onChange={(e) => onChange({ ...value, vidSeconds: parseInt(e.target.value) })}
                className="w-full"
              />
            </div>
            <div>
              <label className="text-[10px] text-white/50 block mb-1">FPS: {value.vidFps}</label>
              <input
                type="range"
                min="6"
                max="24"
                step="2"
                value={value.vidFps}
                onChange={(e) => onChange({ ...value, vidFps: parseInt(e.target.value) })}
                className="w-full"
              />
            </div>
            <div>
              <label className="text-[10px] text-white/50 block mb-1">Motion</label>
              <select
                value={value.vidMotion}
                onChange={(e) => onChange({ ...value, vidMotion: e.target.value })}
                className="w-full bg-black border border-white/10 rounded-lg px-2 py-1 text-xs text-white"
              >
                <option value="low">Low Motion</option>
                <option value="medium">Medium Motion</option>
                <option value="high">High Motion</option>
              </select>
            </div>
          </div>
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

function HistoryPanel({
  conversations,
  searchQuery,
  setSearchQuery,
  onLoadConversation,
  onDeleteConversation,
  onClose,
}: {
  conversations: Conversation[]
  searchQuery: string
  setSearchQuery: (q: string) => void
  onLoadConversation: (convId: string) => void
  onDeleteConversation: (convId: string) => void
  onClose: () => void
}) {
  const filteredConversations = conversations.filter((conv) => {
    if (!searchQuery) return true
    const query = searchQuery.toLowerCase()
    return (
      conv.conversation_id.toLowerCase().includes(query) ||
      conv.last_content.toLowerCase().includes(query)
    )
  })

  return (
    <div className="absolute top-0 left-0 w-96 h-full bg-[#121212] border-r border-white/10 shadow-2xl z-40 flex flex-col">
      <div className="flex items-center justify-between p-4 border-b border-white/10">
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <Clock size={16} />
          Conversation History
        </h3>
        <button
          onClick={onClose}
          className="text-white/50 hover:text-white p-1 rounded-lg hover:bg-white/5"
        >
          <X size={16} />
        </button>
      </div>

      <div className="p-4 border-b border-white/10">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search conversations..."
            className="w-full bg-black border border-white/10 rounded-xl pl-9 pr-3 py-2 text-xs text-white focus:outline-none focus:border-white/30"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {filteredConversations.length === 0 ? (
          <div className="text-center text-white/40 text-sm py-8">
            {searchQuery ? 'No conversations found' : 'No conversation history yet'}
          </div>
        ) : (
          filteredConversations.map((conv) => (
            <div
              key={conv.conversation_id}
              className="relative group"
            >
              <button
                onClick={() => onLoadConversation(conv.conversation_id)}
                className="w-full text-left bg-black hover:bg-white/5 rounded-xl p-3 border border-white/5 hover:border-white/10 transition-all"
              >
                <div className="text-xs text-white/50 mb-1">
                  {new Date(conv.updated_at).toLocaleString()}
                </div>
                <div className="text-sm text-white/90 line-clamp-2 pr-8">
                  {conv.last_content.length > 100
                    ? conv.last_content.substring(0, 100) + '...'
                    : conv.last_content}
                </div>
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onDeleteConversation(conv.conversation_id)
                }}
                className="absolute top-3 right-3 p-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-400 hover:text-red-300 opacity-0 group-hover:opacity-100 transition-all border border-red-500/20"
                title="Delete conversation"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

function SidebarRecents({
  conversations,
  activeConversationId,
  onLoadConversation,
  onViewAll,
}: {
  conversations: Conversation[]
  activeConversationId: string
  onLoadConversation: (id: string) => void
  onViewAll: () => void
}) {
  const buckets = useMemo(() => {
    const now = new Date()
    const startOfDay = (d: Date) => {
      const x = new Date(d); x.setHours(0, 0, 0, 0); return x
    }
    const daysBetween = (a: Date, b: Date) =>
      Math.floor((startOfDay(a).getTime() - startOfDay(b).getTime()) / 86_400_000)

    const sorted = [...conversations].sort(
      (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
    )

    const today: Conversation[] = []
    const yesterday: Conversation[] = []
    const last7: Conversation[] = []
    const older: Conversation[] = []

    for (const c of sorted) {
      const diff = daysBetween(now, new Date(c.updated_at))
      if (diff === 0) today.push(c)
      else if (diff === 1) yesterday.push(c)
      else if (diff <= 7) last7.push(c)
      else older.push(c)
    }

    return { today, yesterday, last7, older }
  }, [conversations])

  const renderRow = (c: Conversation) => {
    const isActive = c.conversation_id === activeConversationId
    const label = (c.last_content || 'Conversation…').trim()
    const short = label.slice(0, 36)
    return (
      <button
        key={c.conversation_id}
        type="button"
        className={[
          'w-full text-left px-3 py-2 text-[13px] rounded-xl truncate transition-colors',
          isActive
            ? 'bg-white/10 text-white'
            : 'text-white/60 hover:bg-white/5 hover:text-white',
        ].join(' ')}
        onClick={() => onLoadConversation(c.conversation_id)}
        title={label}
      >
        {short}{label.length > 36 ? '…' : ''}
      </button>
    )
  }

  const hasBuckets =
    buckets.today.length > 0 ||
    buckets.yesterday.length > 0 ||
    buckets.last7.length > 0 ||
    buckets.older.length > 0

  if (!hasBuckets) return null

  return (
    <div className="mt-2 space-y-3">
      {buckets.today.length > 0 ? (
        <div className="space-y-0.5">
          <div className="px-3 text-[11px] uppercase tracking-wider text-white/30 font-semibold mb-1">Today</div>
          {buckets.today.slice(0, 6).map(renderRow)}
        </div>
      ) : null}

      {buckets.yesterday.length > 0 ? (
        <div className="space-y-0.5">
          <div className="px-3 text-[11px] uppercase tracking-wider text-white/30 font-semibold mb-1">Yesterday</div>
          {buckets.yesterday.slice(0, 6).map(renderRow)}
        </div>
      ) : null}

      {buckets.last7.length > 0 ? (
        <div className="space-y-0.5">
          <div className="px-3 text-[11px] uppercase tracking-wider text-white/30 font-semibold mb-1">Last 7 days</div>
          {buckets.last7.slice(0, 8).map(renderRow)}
        </div>
      ) : null}

      {buckets.older.length > 0 ? (
        <div className="space-y-0.5">
          <div className="px-3 text-[11px] uppercase tracking-wider text-white/30 font-semibold mb-1">Older</div>
          {buckets.older.slice(0, 6).map(renderRow)}
        </div>
      ) : null}

      <div className="px-3 pt-1">
        <button
          type="button"
          className="text-[12px] text-white/40 hover:text-white transition-colors"
          onClick={onViewAll}
        >
          View all history →
        </button>
      </div>
    </div>
  )
}

function Sidebar({
  mode,
  setMode,
  messages,
  conversations,
  activeConversationId,
  onLoadConversation,
  onNewConversation,
  onScrollToBottom,
  showSettings,
  setShowSettings,
  settingsDraft,
  setSettingsDraft,
  onSaveSettings,
  showHistory,
  setShowHistory,
}: {
  mode: Mode
  setMode: (m: Mode) => void
  messages: Msg[]
  conversations: Conversation[]
  activeConversationId: string
  onLoadConversation: (convId: string) => void
  onNewConversation: () => void
  onScrollToBottom: () => void
  showSettings: boolean
  setShowSettings: React.Dispatch<React.SetStateAction<boolean>>
  settingsDraft: SettingsModelV2
  setSettingsDraft: React.Dispatch<React.SetStateAction<SettingsModelV2>>
  onSaveSettings: () => void
  showHistory: boolean
  setShowHistory: React.Dispatch<React.SetStateAction<boolean>>
}) {
  return (
    <aside className="w-[280px] flex-shrink-0 flex flex-col h-full bg-black border-r border-white/5 py-4 px-3 gap-3 relative">
      {/* Search */}
      <div className="px-1.5">
        <button
          type="button"
          className="w-full text-left bg-[#121212] hover:bg-[#1a1a1a] text-white/60 text-sm px-3 py-2.5 rounded-xl flex items-center gap-2 transition-colors group border border-white/5"
          onClick={() => {
            setShowSettings(false)
            setShowHistory(true)
            // Focus search input after a brief delay to allow panel to render
            setTimeout(() => {
              const searchInput = document.querySelector('[placeholder="Search conversations..."]') as HTMLInputElement
              searchInput?.focus()
            }, 100)
          }}
        >
          <Search size={16} className="group-hover:text-white/80 transition-colors" />
          <span className="group-hover:text-white/80 transition-colors">Search chats</span>
          <span className="ml-auto text-xs opacity-40 bg-white/5 px-1.5 py-0.5 rounded border border-white/10">
            Ctrl+K
          </span>
        </button>
      </div>

      {/* Nav groups */}
      <div className="flex flex-col gap-3 px-1.5">
        {/* Main modes */}
        <div className="flex flex-col gap-px">
          <NavItem icon={MessageSquare} label="Chat" active={mode === 'chat'} shortcut="Ctrl+J" onClick={() => setMode('chat')} />
          <NavItem icon={Mic} label="Voice" active={mode === 'voice'} shortcut="Ctrl+V" onClick={() => setMode('voice')} />
          <NavItem icon={Folder} label="Project" active={mode === 'project'} onClick={() => setMode('project')} />
          <NavItem icon={ImageIcon} label="Imagine" active={mode === 'imagine'} onClick={() => setMode('imagine')} />
          <NavItem icon={ImageIcon} label="Edit" active={mode === 'edit'} onClick={() => setMode('edit')} />
          <NavItem icon={Film} label="Animate" active={mode === 'animate'} onClick={() => setMode('animate')} />
          <NavItem icon={Tv2} label="Studio" active={mode === 'studio'} onClick={() => setMode('studio')} />
          <NavItem icon={Server} label="Models" active={mode === 'models'} onClick={() => setMode('models')} />
        </div>

        {/* Divider */}
        <div className="border-t border-white/5" />

        {/* History */}
        <div className="flex flex-col gap-px">
          <NavItem icon={Clock} label="History" active={showHistory} onClick={() => setShowHistory(true)} />
        </div>
      </div>

      {/* Recents list (time-bucketed from conversations) */}
      <div className="flex-1 overflow-y-auto min-h-0 px-1.5 pt-1">
        <button
          type="button"
          className="w-full text-left px-3 py-2 text-[13px] text-white/70 hover:bg-white/5 hover:text-white rounded-xl truncate transition-colors"
          onClick={onNewConversation}
        >
          New conversation
        </button>

        <SidebarRecents
          conversations={conversations}
          activeConversationId={activeConversationId}
          onLoadConversation={onLoadConversation}
          onViewAll={() => setShowHistory(true)}
        />
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
        <SettingsPanel
          value={settingsDraft}
          onChangeDraft={(next) => setSettingsDraft(next)}
          onSave={onSaveSettings}
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
  placeholderOverride,
}: {
  centered: boolean
  input: string
  setInput: (s: string) => void
  mode: Mode
  fileInputRef: React.RefObject<HTMLInputElement>
  canSend: boolean
  onSend: () => void
  onUpload: (file: File) => void
  placeholderOverride?: string
}) {
  return (
    <div className={`w-full ${centered ? 'max-w-breakout' : ''}`}>
      <div
        className={[
          'relative w-full overflow-hidden',
          'bg-[#101010] shadow-sm shadow-black/20',
          'ring-1 ring-inset ring-white/15 hover:ring-white/20 focus-within:ring-white/25',
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
            placeholder={placeholderOverride ?? modeHint(mode)}
            className={[
              'w-full bg-transparent text-white placeholder:text-white/55',
              'focus:outline-none resize-none',
              'min-h-14 py-4 px-2',
              'max-h-[400px] overflow-y-auto',
              'text-[15px] leading-relaxed',
            ].join(' ')}
          />
        </div>
      </div>

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

function AssistantSkeleton({ label }: { label?: string }) {
  return (
    <div className="space-y-3">
      {label ? <div className="text-xs text-white/55">{label}</div> : null}
      <div className="space-y-2 animate-pulse">
        <div className="h-3 w-[88%] rounded-full bg-white/10" />
        <div className="h-3 w-[74%] rounded-full bg-white/10" />
        <div className="h-3 w-[66%] rounded-full bg-white/10" />
      </div>
    </div>
  )
}

function useCopyMessage(timeoutMs = 900) {
  const [copied, setCopied] = useState(false)
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), timeoutMs)
    } catch {
      // noop
    }
  }
  return { copied, copy }
}

function ChatState({
  messages,
  setLightbox,
  endRef,
  mode,
  onNewConversation,
  onRetryMessage,
  chatSettings,
  onUpdateChatSettings,
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
  onNewConversation: () => void
  onRetryMessage: (id: string) => void
  chatSettings: ChatScopedSettings
  onUpdateChatSettings: (next: ChatScopedSettings) => void
  input: string
  setInput: (s: string) => void
  fileInputRef: React.RefObject<HTMLInputElement>
  canSend: boolean
  onSend: () => void
  onUpload: (file: File) => void
}) {
  const { copied, copy } = useCopyMessage()
  const [chatSettingsOpen, setChatSettingsOpen] = useState(false)

  return (
    <div className="flex flex-col h-full w-full max-w-[52rem] mx-auto">
      {/* Top-right fixed: Chat settings gear + New Chat icon (Phase 2, additive) */}
      <div className="fixed top-3 right-5 z-50">
        <div className="relative flex items-center gap-3">
          <button
            type="button"
            onClick={() => setChatSettingsOpen((v) => !v)}
            className="w-9 h-9 flex items-center justify-center rounded-full bg-white/5 border border-white/10 text-white/60 hover:bg-white/10 hover:text-white transition-colors"
            title="Chat settings"
            aria-label="Chat settings"
          >
            <Settings size={16} />
          </button>
          <button
            type="button"
            onClick={onNewConversation}
            className="w-9 h-9 flex items-center justify-center rounded-full bg-white/5 border border-white/10 text-white/60 hover:bg-white/10 hover:text-white transition-colors"
            title="New Chat"
            aria-label="New Chat"
          >
            <PenLine size={16} />
          </button>
          <ChatSettingsPopover
            open={chatSettingsOpen}
            onClose={() => setChatSettingsOpen(false)}
            settings={chatSettings}
            onChange={onUpdateChatSettings}
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pt-14 pb-8 space-y-8">
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

            {/* User: bubble | Assistant: bare text on background (Grok style) */}
            {m.role === 'user' ? (
              <div className="max-w-[85%] bg-white/10 border border-white/10 rounded-3xl px-5 py-4">
                <div className="text-[16px] leading-relaxed whitespace-pre-wrap text-[#EEE] font-normal tracking-wide">
                  {m.text}
                </div>
              </div>
            ) : (
              <div className="max-w-[85%]">
                <div className="text-[16px] leading-relaxed text-[#EEE] font-normal tracking-wide">
                  {m.pending ? (
                    <AssistantSkeleton label={m.text?.trim() ? m.text : undefined} />
                  ) : (
                    <div className="animate-fadeIn">
                      <MessageMarkdown text={m.text} />
                    </div>
                  )}
                </div>

                {/* Grok-style icon action row */}
                {!m.pending ? (
                  <div className="mt-2 flex items-center gap-1 text-white/40">
                    <button
                      type="button"
                      onClick={() => copy(m.text || '')}
                      className="p-1.5 rounded-full hover:bg-white/10 hover:text-white transition-colors"
                      title={copied ? 'Copied!' : 'Copy'}
                    >
                      <Copy size={16} />
                    </button>

                    {m.error && m.retry ? (
                      <button
                        type="button"
                        onClick={() => onRetryMessage(m.id)}
                        className="p-1.5 rounded-full hover:bg-white/10 hover:text-white transition-colors"
                        title="Retry"
                      >
                        <RotateCw size={16} />
                      </button>
                    ) : null}
                  </div>
                ) : null}

                {/* Error card */}
                {m.error && m.retry && !m.pending ? (
                  <div className="mt-3 rounded-2xl border border-red-500/20 bg-red-500/10 px-4 py-3">
                    <div className="text-sm text-red-200/90">
                      Something went wrong. You can retry the request.
                    </div>
                  </div>
                ) : null}

                {/* Phase 4: "Ask before acting" confirmation buttons */}
                {m.role === 'assistant' && m.confirm && !m.pending ? (
                  <div className="mt-3 flex items-center gap-2">
                    <button
                      type="button"
                      className="text-xs px-3 py-1.5 rounded-xl bg-white/10 hover:bg-white/15 border border-white/10 hover:border-white/20 text-white/80 hover:text-white transition-all"
                      onClick={() =>
                        window.dispatchEvent(
                          new CustomEvent('hp:confirm_action', { detail: { id: m.id, ok: true } })
                        )
                      }
                    >
                      {m.confirm.intent === 'generate_videos' ? 'Generate video' : 'Generate image'}
                    </button>
                    <button
                      type="button"
                      className="text-xs px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-white/20 text-white/60 hover:text-white transition-all"
                      onClick={() =>
                        window.dispatchEvent(
                          new CustomEvent('hp:confirm_action', { detail: { id: m.id, ok: false } })
                        )
                      }
                    >
                      Cancel
                    </button>
                  </div>
                ) : null}

                {m.media?.images?.length ? (
                  <div className="flex gap-2 overflow-x-auto pt-2">
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
            )}
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

async function getJson<T>(
  baseUrl: string,
  path: string,
  headers?: Record<string, string>
): Promise<T> {
  const url = `${baseUrl.replace(/\/+$/, '')}${path.startsWith('/') ? path : `/${path}`}`
  const res = await fetch(url, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...(headers ?? {}),
    },
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

export default function App() {
  // Core State - Separate sessions for Chat and Voice (ephemeral voice like Alexa/Grok)
  const [chatMessages, setChatMessages] = useState<Msg[]>([])
  const [voiceMessages, setVoiceMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [chatConversationId, setChatConversationId] = useState<string>(() => {
    return localStorage.getItem('homepilot_conversation') || uuid()
  })
  const [voiceConversationId, setVoiceConversationId] = useState<string>(() => uuid())
  const [lightbox, setLightbox] = useState<string | null>(null)

  // Phase 2 (additive): per-chat settings stored by conversation id.
  const chatSettingsStorageKey = useMemo(
    () => `hp_chat_settings:${chatConversationId}`,
    [chatConversationId]
  )
  const [chatSettings, setChatSettings] = useState<ChatScopedSettings>(() => {
    try {
      const raw = localStorage.getItem(`hp_chat_settings:${localStorage.getItem('homepilot_conversation') || ''}`)
      if (!raw) return DEFAULT_CHAT_SETTINGS
      const parsed = JSON.parse(raw)
      return {
        advancedHelpEnabled: !!parsed.advancedHelpEnabled,
        askBeforeActing: parsed.askBeforeActing !== false,
        executionProfile:
          parsed.executionProfile === 'balanced'
            ? 'balanced'
            : parsed.executionProfile === 'quality'
            ? 'quality'
            : 'fast',
      }
    } catch {
      return DEFAULT_CHAT_SETTINGS
    }
  })

  // Load settings whenever conversation changes
  useEffect(() => {
    try {
      const raw = localStorage.getItem(chatSettingsStorageKey)
      if (!raw) {
        setChatSettings(DEFAULT_CHAT_SETTINGS)
        return
      }
      const parsed = JSON.parse(raw)
      setChatSettings({
        advancedHelpEnabled: !!parsed.advancedHelpEnabled,
        askBeforeActing: parsed.askBeforeActing !== false,
        executionProfile:
          parsed.executionProfile === 'balanced'
            ? 'balanced'
            : parsed.executionProfile === 'quality'
            ? 'quality'
            : 'fast',
      })
    } catch {
      setChatSettings(DEFAULT_CHAT_SETTINGS)
    }
  }, [chatSettingsStorageKey])

  const updateChatSettings = useCallback(
    (next: ChatScopedSettings) => {
      setChatSettings(next)
      try {
        localStorage.setItem(chatSettingsStorageKey, JSON.stringify(next))
      } catch {
        // ignore storage errors
      }
    },
    [chatSettingsStorageKey]
  )

  const [mode, setMode] = useState<Mode>(() => {
    return (localStorage.getItem('homepilot_mode') as Mode) || 'chat'
  })

  // Route messages and conversation ID based on mode (Voice is ephemeral like Alexa/Grok)
  const messages = mode === 'voice' ? voiceMessages : chatMessages
  const setMessages = mode === 'voice' ? setVoiceMessages : setChatMessages
  const conversationId = mode === 'voice' ? voiceConversationId : chatConversationId
  const setConversationId = mode === 'voice' ? setVoiceConversationId : setChatConversationId

  // Studio variant: "play" for Play Studio (StudioView), "creator" for Creator Studio
  const [studioVariant, setStudioVariant] = useState<"play" | "creator">("play")
  // Creator Studio project ID (for opening existing projects in editor)
  const [creatorProjectId, setCreatorProjectId] = useState<string | undefined>(undefined)

  // Unified settings model
  const [settings, setSettings] = useState<SettingsModel>(() => {
    const backendUrl =
      localStorage.getItem('homepilot_backend_url') || 'http://localhost:8000'
    const provider = (localStorage.getItem('homepilot_provider') as Provider) || 'backend'
    const ollamaUrl = localStorage.getItem('homepilot_ollama_url') || 'http://localhost:11434'
    const ollamaModel = localStorage.getItem('homepilot_ollama_model') || 'llama3:8b'
    const apiKey = localStorage.getItem('homepilot_api_key') || ''
    const funMode = localStorage.getItem('homepilot_funmode') === '1'

    // Generation parameters with RTX 4060 defaults
    const textTemperature = parseFloat(localStorage.getItem('homepilot_text_temp') || '0.7')
    const textMaxTokens = parseInt(localStorage.getItem('homepilot_text_maxtokens') || '2048')
    const imgWidth = parseInt(localStorage.getItem('homepilot_img_width') || '1024')
    const imgHeight = parseInt(localStorage.getItem('homepilot_img_height') || '1024')
    const imgSteps = parseInt(localStorage.getItem('homepilot_img_steps') || '20')
    const imgCfg = parseFloat(localStorage.getItem('homepilot_img_cfg') || '5.0')
    const imgSeed = parseInt(localStorage.getItem('homepilot_img_seed') || '-1')
    const vidSeconds = parseInt(localStorage.getItem('homepilot_vid_seconds') || '4')
    const vidFps = parseInt(localStorage.getItem('homepilot_vid_fps') || '8')
    const vidMotion = localStorage.getItem('homepilot_vid_motion') || 'medium'
    const preset = (localStorage.getItem('homepilot_preset') as HardwarePreset) || '4060'

    return {
      backendUrl, provider, ollamaUrl, ollamaModel, apiKey, funMode,
      textTemperature, textMaxTokens,
      imgWidth, imgHeight, imgSteps, imgCfg, imgSeed,
      vidSeconds, vidFps, vidMotion, preset
    }
  })

  const [showSettings, setShowSettings] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [currentProject, setCurrentProject] = useState<{
    id: string
    name: string
    document_count: number
    project_type?: string
    description?: string
    instructions?: string
    files?: Array<{ name: string; size?: string; chunks?: number }>
    agentic?: {
      goal?: string
      capabilities?: string[]
      tool_ids?: string[]
      a2a_agent_ids?: string[]
      tool_source?: string
      ask_before_acting?: boolean
      execution_profile?: 'fast' | 'balanced' | 'quality'
    }
    persona_agent?: Record<string, any>
    persona_appearance?: Record<string, any>
  } | null>(null)

  // Agent settings panel toggle
  const [showAgentSettings, setShowAgentSettings] = useState(false)

  // Companion-grade: show session hub when opening a persona project
  const [showSessionPanel, setShowSessionPanel] = useState(false)

  // Agent-start UX: user's chosen intent (only used while the agent thread is empty).
  const [agentStartIntent, setAgentStartIntent] = useState<AgentIntent | null>(null)

  // Reset the intent when switching projects or once messages exist.
  useEffect(() => {
    if (!currentProject) {
      setAgentStartIntent(null)
      return
    }
    if (messages.length > 0) {
      setAgentStartIntent(null)
    }
  }, [currentProject?.id, messages.length])

  // Auto-link voice to project when switching to voice while a persona project is active
  // Companion-grade: resolves a persistent session instead of ephemeral conversation
  useEffect(() => {
    if (mode !== 'voice') return
    if (!currentProject) return
    if (currentProject.project_type !== 'persona') return
    // Auto-enable personas if not already
    if (!isPersonasEnabled()) setPersonasEnabledGating(true)
    // Set the personality to this project's persona
    const personaId = `persona:${currentProject.id}`
    localStorage.setItem('homepilot_personality_id', personaId)
    // Auto-link to project
    setVoiceLinkedToProject(true)
    // Cache the persona data so it's available immediately
    try {
      const existing = localStorage.getItem(LS_PERSONA_CACHE)
      const cache = existing ? JSON.parse(existing) : []
      if (!cache.find((p: any) => p.id === currentProject.id)) {
        cache.push({
          id: currentProject.id,
          label: currentProject.persona_agent?.label || currentProject.name || 'Persona',
          role: currentProject.persona_agent?.role || '',
          tone: (currentProject.persona_agent?.response_style as any)?.tone || '',
          system_prompt: currentProject.persona_agent?.system_prompt || '',
          style_preset: '',
          character_desc: '',
          created_at: 0,
          photos: [],
        })
        localStorage.setItem(LS_PERSONA_CACHE, JSON.stringify(cache))
      }
    } catch (err) { console.warn('[Voice] Auto-link cache update failed:', err) }

    // Companion-grade: resolve a persistent session for this persona project
    // This ensures voice uses the SAME conversation_id across mode switches
    resolveSession(currentProject.id, 'voice')
      .then(async (session) => {
        console.log('[Voice] Resolved session:', session.id, 'conversation:', session.conversation_id)
        setVoiceConversationId(session.conversation_id)
        // Store session reference for later use
        localStorage.setItem('homepilot_active_voice_session', JSON.stringify(session))
        // Load message history so user sees previous conversation
        try {
          const convData = await getJson<{
            ok: boolean
            messages: Array<{ role: string; content: string; created_at: string; media?: { images?: string[]; video_url?: string } | null }>
          }>(
            settingsDraft.backendUrl,
            `/conversations/${session.conversation_id}/messages`,
            authHeaders
          )
          if (convData.ok && convData.messages && convData.messages.length > 0) {
            setVoiceMessages(
              convData.messages.map((m, idx) => ({
                id: `restored-${idx}`,
                role: m.role as 'user' | 'assistant',
                text: m.content,
                animate: false,
                media: m.media || undefined,
              }))
            )
          }
        } catch {
          // No messages yet — that's fine for new sessions
        }
      })
      .catch((err) => {
        console.warn('[Voice] Session resolution failed (using ephemeral):', err)
      })
  }, [mode, currentProject])

  // Track last spoken message to avoid re-speaking
  const lastSpokenMessageIdRef = useRef<string | null>(null)

  // Settings draft for new enterprise panel
  const [settingsDraft, setSettingsDraft] = useState<SettingsModelV2>(() => {
    const backendUrl = localStorage.getItem('homepilot_backend_url') || 'http://localhost:8000'
    const apiKey = localStorage.getItem('homepilot_api_key') || ''
    const providerChat = (localStorage.getItem('homepilot_provider_chat') || 'ollama') as string
    const providerImages = (localStorage.getItem('homepilot_provider_images') || 'comfyui') as string
    const providerVideo = (localStorage.getItem('homepilot_provider_video') || 'comfyui') as string
    const baseUrlChat = localStorage.getItem('homepilot_base_url_chat') || ''
    const baseUrlImages = localStorage.getItem('homepilot_base_url_images') || ''
    const baseUrlVideo = localStorage.getItem('homepilot_base_url_video') || ''
    const modelChat = localStorage.getItem('homepilot_model_chat') || 'local-model'
    const modelImages = localStorage.getItem('homepilot_model_images') || ''
    const modelVideo = localStorage.getItem('homepilot_model_video') || ''
    const preset = (localStorage.getItem('homepilot_preset_v2') as HardwarePresetUI) || 'med'
    const ttsEnabled = localStorage.getItem('homepilot_tts_enabled') !== 'false'

    // Try to load voice from nexus_settings_v1 (used by SpeechService) first
    let selectedVoice = localStorage.getItem('homepilot_voice_uri') || ''
    try {
      const nexusSettings = localStorage.getItem('nexus_settings_v1')
      if (nexusSettings) {
        const settings = JSON.parse(nexusSettings)
        if (settings.speechVoice) {
          selectedVoice = settings.speechVoice
        }
      }
    } catch (e) {
      // Ignore parsing errors
    }

    // Prompt refinement: default to true (enabled by default for better results)
    const promptRefinement = localStorage.getItem('homepilot_prompt_refinement') !== 'false'

    return {
      backendUrl,
      apiKey,
      providerChat,
      providerImages,
      providerVideo,
      baseUrlChat,
      baseUrlImages,
      baseUrlVideo,
      modelChat,
      modelImages,
      modelVideo,
      preset,
      ttsEnabled,
      selectedVoice,
      promptRefinement,
    }
  })

  const endRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Persist chat conversation (not voice - voice is ephemeral)
  useEffect(() => localStorage.setItem('homepilot_conversation', chatConversationId), [chatConversationId])
  useEffect(() => localStorage.setItem('homepilot_mode', mode), [mode])

  // Clear voice session when exiting Voice mode — BUT NOT when linked to persona.
  // Linked persona sessions persist across mode switches (companion-grade).
  // Unlinked voice stays ephemeral (like Alexa/Grok).
  useEffect(() => {
    if (mode !== 'voice') {
      const linkedProjectId = getVoiceLinkedProjectId()
      if (linkedProjectId) {
        // Linked mode: keep conversation_id intact — session persists
        // Only clear the UI message list (will reload from backend on re-entry)
        setVoiceMessages([])
      } else {
        // Unlinked mode: ephemeral — fresh conversation each time
        setVoiceMessages([])
        setVoiceConversationId(uuid())
      }
    }
  }, [mode])

  // Listen for switch-to-animate events from Imagine (Grok-style handoff)
  useEffect(() => {
    const handleSwitchToAnimate = () => {
      setMode('animate')
    }
    window.addEventListener('switch-to-animate', handleSwitchToAnimate)
    return () => window.removeEventListener('switch-to-animate', handleSwitchToAnimate)
  }, [])

  // Reset conversation when switching between incompatible mode groups
  // to prevent chat history from bleeding into edit/animate sessions
  const prevModeRef = useRef<Mode>(mode)
  useEffect(() => {
    const prevMode = prevModeRef.current
    const currentMode = mode

    // Define mode groups
    const chatLikeModes: Mode[] = ['chat', 'voice', 'project', 'search', 'imagine']
    const editMode: Mode[] = ['edit']
    const animateMode: Mode[] = ['animate']

    const getModeGroup = (m: Mode): 'chat' | 'edit' | 'animate' | 'other' => {
      if (chatLikeModes.includes(m)) return 'chat'
      if (editMode.includes(m)) return 'edit'
      if (animateMode.includes(m)) return 'animate'
      return 'other'
    }

    const prevGroup = getModeGroup(prevMode)
    const currentGroup = getModeGroup(currentMode)

    // Reset conversation when switching between different mode groups
    if (prevGroup !== currentGroup && currentGroup !== 'other') {
      console.log(`Mode switched from ${prevMode} (${prevGroup}) to ${currentMode} (${currentGroup}) - resetting conversation`)
      setConversationId(uuid())
      setMessages([])
    }

    prevModeRef.current = currentMode
  }, [mode])

  useEffect(() => {
    localStorage.setItem('homepilot_backend_url', settings.backendUrl)
    localStorage.setItem('homepilot_provider', settings.provider)
    localStorage.setItem('homepilot_ollama_url', settings.ollamaUrl)
    localStorage.setItem('homepilot_ollama_model', settings.ollamaModel)
    localStorage.setItem('homepilot_api_key', settings.apiKey)
    localStorage.setItem('homepilot_funmode', settings.funMode ? '1' : '0')
    localStorage.setItem('homepilot_text_temp', String(settings.textTemperature))
    localStorage.setItem('homepilot_text_maxtokens', String(settings.textMaxTokens))
    localStorage.setItem('homepilot_img_width', String(settings.imgWidth))
    localStorage.setItem('homepilot_img_height', String(settings.imgHeight))
    localStorage.setItem('homepilot_img_steps', String(settings.imgSteps))
    localStorage.setItem('homepilot_img_cfg', String(settings.imgCfg))
    localStorage.setItem('homepilot_img_seed', String(settings.imgSeed))
    localStorage.setItem('homepilot_vid_seconds', String(settings.vidSeconds))
    localStorage.setItem('homepilot_vid_fps', String(settings.vidFps))
    localStorage.setItem('homepilot_vid_motion', settings.vidMotion)
    localStorage.setItem('homepilot_preset', settings.preset)
  }, [settings])

  // Scroll on new message
  useEffect(() => {
    if (messages.length > 0) endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Check if user is typing in an input/textarea
      const target = e.target as HTMLElement
      const isInputField = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA'

      if (e.ctrlKey || e.metaKey) {
        // Ctrl+K / Cmd+K: Open search
        if (e.key === 'k') {
          e.preventDefault()
          setShowSettings(false)
          setShowHistory(true)
          // Focus search input after a brief delay
          setTimeout(() => {
            const searchInput = document.querySelector('[placeholder="Search conversations..."]') as HTMLInputElement
            searchInput?.focus()
          }, 100)
        }
        // Ctrl+J / Cmd+J: Switch to Chat mode
        else if (e.key === 'j' && !isInputField) {
          e.preventDefault()
          setMode('chat')
        }
        // Ctrl+V / Cmd+V: Switch to Voice mode (only if not in input field to allow paste)
        else if (e.key === 'v' && !isInputField) {
          e.preventDefault()
          setMode('voice')
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  const canSend = useMemo(() => input.trim().length > 0, [input])

  const authHeaders = useMemo(() => {
    const k = settings.apiKey.trim()
    return k ? { 'x-api-key': k } : undefined
  }, [settings.apiKey])

  const onNewConversation = useCallback(() => {
    // New UUID → backend auto-creates fresh personality memory.
    // Old conversation stays in SQLite (browsable via History panel).
    // Backend GC evicts stale personality memories after 2h.
    setConversationId(uuid())
    setMessages([])
  }, [])

  // Listen to "message finished animating" events from Typewriter
  useEffect(() => {
    const handler = (e: Event) => {
      const id = (e as CustomEvent)?.detail?.id
      if (!id) return
      setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, animate: false } : m)))
    }
    window.addEventListener('hp:messageAnimated', handler)
    return () => window.removeEventListener('hp:messageAnimated', handler)
  }, [])

  const onSaveSettings = useCallback(() => {
    // Save new settings to localStorage
    localStorage.setItem('homepilot_backend_url', settingsDraft.backendUrl)
    localStorage.setItem('homepilot_api_key', settingsDraft.apiKey)
    localStorage.setItem('homepilot_provider_chat', settingsDraft.providerChat)
    localStorage.setItem('homepilot_provider_images', settingsDraft.providerImages)
    localStorage.setItem('homepilot_provider_video', settingsDraft.providerVideo)
    localStorage.setItem('homepilot_base_url_chat', settingsDraft.baseUrlChat || '')
    localStorage.setItem('homepilot_base_url_images', settingsDraft.baseUrlImages || '')
    localStorage.setItem('homepilot_base_url_video', settingsDraft.baseUrlVideo || '')
    localStorage.setItem('homepilot_model_chat', settingsDraft.modelChat)
    localStorage.setItem('homepilot_model_images', settingsDraft.modelImages)
    localStorage.setItem('homepilot_model_video', settingsDraft.modelVideo)
    localStorage.setItem('homepilot_preset_v2', settingsDraft.preset)
    localStorage.setItem('homepilot_tts_enabled', String(settingsDraft.ttsEnabled ?? true))
    localStorage.setItem('homepilot_voice_uri', settingsDraft.selectedVoice ?? '')
    localStorage.setItem('homepilot_nsfw_mode', String(!!settingsDraft.nsfwMode))
    localStorage.setItem('homepilot_experimental_civitai', String(!!settingsDraft.experimentalCivitai))
    localStorage.setItem('homepilot_civitai_api_key', settingsDraft.civitaiApiKey || '')
    localStorage.setItem('homepilot_prompt_refinement', String(settingsDraft.promptRefinement ?? true))

    // Save TTS settings to nexus_settings_v1 format (used by SpeechService)
    // This ensures the selected voice is actually used for TTS
    if (window.SpeechService && typeof window.SpeechService.saveTTSConfig === 'function') {
      const voices = window.speechSynthesis?.getVoices() || []
      const selectedVoiceName = settingsDraft.selectedVoice || ''
      const selectedVoiceObj = voices.find((v) => v.name === selectedVoiceName)

      const ttsConfig = {
        speechVoice: selectedVoiceObj?.name || '',
        speechVoiceURI: selectedVoiceObj?.voiceURI || '',
        speechLang: selectedVoiceObj?.lang || 'en-US',
        speechRate: 0.9,
        speechPitch: 1.0,
        speechVolume: 1.0,
        ttsEnabled: settingsDraft.ttsEnabled ?? true,
      }

      console.log('[App] Saving TTS config:', ttsConfig)
      window.SpeechService.saveTTSConfig(ttsConfig)
    }

    if (typeof settingsDraft.textTemperature === 'number') localStorage.setItem('homepilot_text_temp', String(settingsDraft.textTemperature))
    if (typeof settingsDraft.textMaxTokens === 'number') localStorage.setItem('homepilot_text_maxtokens', String(settingsDraft.textMaxTokens))
    if (typeof settingsDraft.imgWidth === 'number') localStorage.setItem('homepilot_img_width', String(settingsDraft.imgWidth))
    if (typeof settingsDraft.imgHeight === 'number') localStorage.setItem('homepilot_img_height', String(settingsDraft.imgHeight))
    if (typeof settingsDraft.imgSteps === 'number') localStorage.setItem('homepilot_img_steps', String(settingsDraft.imgSteps))
    if (typeof settingsDraft.imgCfg === 'number') localStorage.setItem('homepilot_img_cfg', String(settingsDraft.imgCfg))
    if (typeof settingsDraft.imgSeed === 'number') localStorage.setItem('homepilot_img_seed', String(settingsDraft.imgSeed))
    if (typeof settingsDraft.vidSeconds === 'number') localStorage.setItem('homepilot_vid_seconds', String(settingsDraft.vidSeconds))
    if (typeof settingsDraft.vidFps === 'number') localStorage.setItem('homepilot_vid_fps', String(settingsDraft.vidFps))
    if (typeof settingsDraft.vidMotion === 'string') localStorage.setItem('homepilot_vid_motion', settingsDraft.vidMotion)

    // Also update old settings format for backward compatibility
    setSettings({
      ...settings,
      backendUrl: settingsDraft.backendUrl,
      apiKey: settingsDraft.apiKey,
      // Map preset to old preset format
      preset: settingsDraft.preset === 'low' ? '4060' : settingsDraft.preset === 'med' ? '4080' : settingsDraft.preset === 'high' ? 'a100' : 'custom',
    })

    setShowSettings(false)
  }, [settingsDraft, settings])

  // When opening settings, sync draft with current
  useEffect(() => {
    if (showSettings) {
      setSettingsDraft({
        backendUrl: settings.backendUrl,
        apiKey: settings.apiKey,
        providerChat: localStorage.getItem('homepilot_provider_chat') || 'ollama',
        providerImages: localStorage.getItem('homepilot_provider_images') || 'ollama',
        providerVideo: localStorage.getItem('homepilot_provider_video') || 'ollama',
        baseUrlChat: localStorage.getItem('homepilot_base_url_chat') || '',
        baseUrlImages: localStorage.getItem('homepilot_base_url_images') || '',
        baseUrlVideo: localStorage.getItem('homepilot_base_url_video') || '',
        modelChat: localStorage.getItem('homepilot_model_chat') || 'local-model',
        modelImages: localStorage.getItem('homepilot_model_images') || '',
        modelVideo: localStorage.getItem('homepilot_model_video') || '',
        preset: (localStorage.getItem('homepilot_preset_v2') as HardwarePresetUI) || 'med',
        nsfwMode: localStorage.getItem('homepilot_nsfw_mode') === 'true',
        experimentalCivitai: localStorage.getItem('homepilot_experimental_civitai') === 'true',
        civitaiApiKey: localStorage.getItem('homepilot_civitai_api_key') || '',
        promptRefinement: localStorage.getItem('homepilot_prompt_refinement') !== 'false',
        textTemperature: parseFloat(localStorage.getItem('homepilot_text_temp') || '0.7'),
        textMaxTokens: parseInt(localStorage.getItem('homepilot_text_maxtokens') || '2048'),
        imgWidth: parseInt(localStorage.getItem('homepilot_img_width') || '1024'),
        imgHeight: parseInt(localStorage.getItem('homepilot_img_height') || '1024'),
        imgSteps: parseInt(localStorage.getItem('homepilot_img_steps') || '20'),
        imgCfg: parseFloat(localStorage.getItem('homepilot_img_cfg') || '5.0'),
        imgSeed: parseInt(localStorage.getItem('homepilot_img_seed') || '-1'),
        vidSeconds: parseInt(localStorage.getItem('homepilot_vid_seconds') || '4'),
        vidFps: parseInt(localStorage.getItem('homepilot_vid_fps') || '8'),
        vidMotion: localStorage.getItem('homepilot_vid_motion') || 'medium',
      })
    }
  }, [showSettings, settings])

  const fetchConversations = useCallback(async () => {
    try {
      // When inside a project, only show that project's conversations
      const projectId = localStorage.getItem('homepilot_current_project')
      const path = projectId
        ? `/conversations?project_id=${encodeURIComponent(projectId)}`
        : '/conversations'
      const data = await getJson<{ ok: boolean; conversations: Conversation[] }>(
        settings.backendUrl,
        path,
        authHeaders
      )
      if (data.ok && data.conversations) {
        setConversations(data.conversations)
      }
    } catch (err) {
      console.error('Failed to fetch conversations:', err)
    }
  }, [settings.backendUrl, authHeaders])

  const loadConversation = useCallback(async (convId: string) => {
    try {
      const data = await getJson<{
        ok: boolean
        conversation_id: string
        messages: Array<{ role: string; content: string; created_at: string; media?: { images?: string[]; video_url?: string } | null }>
      }>(
        settings.backendUrl,
        `/conversations/${convId}/messages`,
        authHeaders
      )
      if (data.ok && data.messages) {
        // Always switch to chat mode when loading a conversation.
        // Without this, if user is in Voice/Imagine/Models/etc, messages
        // load into state but the UI keeps rendering the current mode screen.
        setMode('chat')
        setShowSettings(false)
        setShowHistory(false)

        setConversationId(convId)
        setMessages(
          data.messages.map((m, idx) => ({
            id: `loaded-${idx}`,
            role: m.role as 'user' | 'assistant',
            text: m.content,
            animate: false,
            media: m.media || undefined,
          }))
        )
      }
    } catch (err) {
      console.error('Failed to load conversation:', err)
    }
  }, [settings.backendUrl, authHeaders])

  const deleteConversation = useCallback(async (convId: string) => {
    // Confirm deletion
    if (!confirm('Delete this conversation? This will remove all messages permanently.')) {
      return
    }

    try {
      const response = await fetch(
        `${settings.backendUrl.replace(/\/+$/, '')}/conversations/${convId}`,
        {
          method: 'DELETE',
          headers: authHeaders,
        }
      )

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const data = await response.json()
      if (data.ok) {
        // Remove from local conversations list
        setConversations((prev) => prev.filter((c) => c.conversation_id !== convId))

        // If we're currently viewing this conversation, clear the messages
        if (conversationId === convId) {
          setMessages([])
          setConversationId('')
        }
      }
    } catch (err) {
      console.error('Failed to delete conversation:', err)
      alert(`Failed to delete conversation: ${err}`)
    }
  }, [settings.backendUrl, authHeaders, conversationId])

  // Load project info on mount if project mode is active
  useEffect(() => {
    const loadProjectInfo = async () => {
      const projectId = localStorage.getItem('homepilot_current_project')
      if (projectId && mode === 'chat') {
        try {
          const response = await fetch(
            `${settings.backendUrl.replace(/\/+$/, '')}/projects/${projectId}`,
            { headers: authHeaders }
          )
          if (response.ok) {
            const data = await response.json()
            const project = data.project
            setCurrentProject({
              id: projectId,
              name: project.name,
              document_count: project.document_count || 0,
              project_type: project.project_type,
              description: project.description,
              instructions: project.instructions,
              files: project.files,
              agentic: project.agentic,
              persona_agent: project.persona_agent,
              persona_appearance: project.persona_appearance,
            })

            // Restore last conversation for this project
            const lastConvId = project.last_conversation_id
            if (lastConvId) {
              try {
                const convData = await getJson<{
                  ok: boolean
                  messages: Array<{ role: string; content: string; created_at: string; media?: { images?: string[]; video_url?: string } | null }>
                }>(
                  settings.backendUrl,
                  `/conversations/${lastConvId}/messages`,
                  authHeaders
                )
                if (convData.ok && convData.messages && convData.messages.length > 0) {
                  setChatConversationId(lastConvId)
                  setChatMessages(
                    convData.messages.map((m, idx) => ({
                      id: `restored-${idx}`,
                      role: m.role as 'user' | 'assistant',
                      text: m.content,
                      animate: false,
                      media: m.media || undefined,
                    }))
                  )
                }
              } catch {
                // Conversation load failed — keep current state
              }
            }
          }
        } catch (error) {
          console.error('Error loading project info:', error)
        }
      }
    }
    loadProjectInfo()
  }, [mode, settings.backendUrl, authHeaders])

  // Fetch conversations on mount so sidebar recents are always populated
  useEffect(() => {
    fetchConversations()
  }, [fetchConversations])

  // Also refresh when history panel is opened
  useEffect(() => {
    if (showHistory) {
      fetchConversations()
    }
  }, [showHistory, fetchConversations])

  const onScrollToBottom = useCallback(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  // ─── Phase 4 (additive): dynamic capability discovery from backend ───
  const [agenticCaps, setAgenticCaps] = useState<string[]>([])

  const refreshAgenticCaps = useCallback(async () => {
    try {
      const h: Record<string, string> = {}
      const k = settings.apiKey.trim()
      if (k) h['x-api-key'] = k
      const res = await fetch(`${settings.backendUrl}/v1/agentic/capabilities`, { headers: h })
      if (!res.ok) return
      const data = await res.json()
      const ids = Array.isArray(data?.capabilities)
        ? data.capabilities.map((c: any) => c.id).filter(Boolean)
        : []
      setAgenticCaps(ids)
    } catch {
      // agentic unavailable — keep empty
    }
  }, [settings.apiKey, settings.backendUrl])

  useEffect(() => {
    void refreshAgenticCaps()
  }, [refreshAgenticCaps])

  // Phase 3 (additive): conservative heuristic to detect image generation requests
  const isLikelyImageRequest = useCallback((text: string) => {
    const t = text.toLowerCase()
    const hasVerb =
      t.includes('generate') || t.includes('create') || t.includes('make') || t.includes('draw')
    const hasNoun =
      t.includes('image') || t.includes('picture') || t.includes('photo') || t.includes('portrait') || t.includes('art')
    const phrase =
      t.includes('a picture of') || t.includes('an image of') || t.includes('generate me')
    return (hasVerb && hasNoun) || phrase
  }, [])

  // Phase 4 (additive): conservative heuristic for video generation requests
  const isLikelyVideoRequest = useCallback((text: string) => {
    const t = text.toLowerCase()
    const hasVerb = t.includes('generate') || t.includes('create') || t.includes('make')
    const hasNoun = t.includes('video') || t.includes('animation') || t.includes('animate') || t.includes('clip')
    const phrase = t.includes('a video of') || t.includes('generate a video') || t.includes('make an animation')
    return (hasVerb && hasNoun) || phrase
  }, [])

  // Phase 4 (additive): handle "Ask before acting" confirmation clicks
  const handleConfirmAction = useCallback(
    async (msgId: string, ok: boolean) => {
      const msg = messages.find((m) => m.id === msgId)
      if (!msg?.confirm) return

      if (!ok) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === msgId ? { ...m, confirm: undefined, text: 'Okay, cancelled.' } : m
          )
        )
        return
      }

      // Turn this message into pending while we invoke
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId ? { ...m, pending: true, confirm: undefined, text: '' } : m
        )
      )

      try {
        const agentic = await postJson<any>(
          settings.backendUrl,
          '/v1/agentic/invoke',
          {
            session_key: mode === 'voice' ? 'voice' : 'chat',
            conversation_id: conversationId,
            project_id: localStorage.getItem('homepilot_current_project') || undefined,
            intent: msg.confirm.intent,
            args: { prompt: msg.confirm.prompt },
            profile: chatSettings.executionProfile,
            nsfwMode: settingsDraft.nsfwMode,
          },
          authHeaders
        )

        setMessages((prev) =>
          prev.map((m) =>
            m.id === msgId
              ? {
                  ...m,
                  pending: false,
                  animate: true,
                  text: agentic.assistant_text ?? 'Done.',
                  media: agentic.media ?? null,
                }
              : m
          )
        )

        if (agentic.conversation_id && agentic.conversation_id !== conversationId) {
          setConversationId(agentic.conversation_id)
        }
        fetchConversations()
      } catch {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === msgId
              ? { ...m, pending: false, text: "Sorry, I couldn't complete that." }
              : m
          )
        )
      }
    },
    [authHeaders, chatSettings.executionProfile, conversationId, fetchConversations, messages, mode, settings.backendUrl, settingsDraft.nsfwMode]
  )

  // Phase 4: listen for confirmation button clicks via custom events
  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent
      const id = ce?.detail?.id as string | undefined
      const ok = !!ce?.detail?.ok
      if (!id) return
      void handleConfirmAction(id, ok)
    }
    window.addEventListener('hp:confirm_action', handler as any)
    return () => window.removeEventListener('hp:confirm_action', handler as any)
  }, [handleConfirmAction])

  const sendTextOrIntent = useCallback(
    async (rawText: string) => {
      const trimmed = rawText.trim()
      if (!trimmed) return

      setShowSettings(false)

      // user-visible message stays as typed; request uses mode prefixes
      const requestText = buildMessageForMode(mode, trimmed)

      const user: Msg = { id: uuid(), role: 'user', text: trimmed }
      const tmpId = uuid()
      const pending: Msg = { id: tmpId, role: 'assistant', text: '', pending: true }

      setMessages((prev) => [...prev, user, pending])

      // Get current project ID from localStorage if user selected one
      const currentProjectId = localStorage.getItem('homepilot_current_project') || undefined

      // ─── Phase 4 (additive): agentic invoke with dynamic capabilities ──
      // Agent projects ALWAYS route agentically (regardless of chatSettings toggle).
      // Non-agent projects use chatSettings.advancedHelpEnabled as before.
      // Intent detection now uses the dedicated detectAgenticIntent() module
      // with slash commands (/image, /video) and conservative NLP heuristics.
      const isAgentProject = currentProject?.project_type === 'agent'
      const agenticEnabled = chatSettings?.advancedHelpEnabled === true || isAgentProject

      // Agent projects use wizard-selected capabilities; others use server-advertised
      const projectCaps: string[] = Array.isArray(currentProject?.agentic?.capabilities)
        ? currentProject!.agentic!.capabilities
        : []
      const allowedCaps = isAgentProject ? projectCaps : agenticCaps

      const canImages = allowedCaps.includes('generate_images')
      const canVideos = allowedCaps.includes('generate_videos')

      const detected = detectAgenticIntent(trimmed)
      const detectedIntent: AgenticIntent | null = detected.intent
      const toolPrompt = detected.prompt

      const intentAllowed =
        (detectedIntent === 'generate_images' && canImages) ||
        (detectedIntent === 'generate_videos' && canVideos)

      if (agenticEnabled && detectedIntent && intentAllowed && (mode === 'chat' || mode === 'voice')) {
        // "Ask before acting" — show confirmation buttons instead of invoking
        if (chatSettings?.askBeforeActing) {
          const confirmText =
            detectedIntent === 'generate_videos'
              ? 'I can generate a short video for that. Proceed?'
              : 'I can generate an image for that. Proceed?'
          setMessages((prev) =>
            prev.map((m) =>
              m.id === tmpId
                ? {
                    ...m,
                    pending: false,
                    text: confirmText,
                    confirm: { intent: detectedIntent, prompt: toolPrompt || trimmed },
                  }
                : m
            )
          )
          return
        }

        // Invoke immediately (agentic enabled, Ask before acting OFF)
        try {
          const agentic = await postJson<any>(
            settings.backendUrl,
            '/v1/agentic/invoke',
            {
              session_key: mode === 'voice' ? 'voice' : 'chat',
              conversation_id: conversationId,
              project_id: mode === 'voice' ? getVoiceLinkedProjectId() : currentProjectId,
              intent: detectedIntent,
              args: { prompt: toolPrompt || trimmed },
              profile: chatSettings?.executionProfile,
              nsfwMode: settingsDraft.nsfwMode,
            },
            authHeaders
          )

          setMessages((prev) =>
            prev.map((m) =>
              m.id === tmpId
                ? {
                    ...m,
                    pending: false,
                    animate: true,
                    text: agentic.assistant_text ?? 'Here you go.',
                    media: agentic.media ?? null,
                  }
                : m
            )
          )

          if (mode === 'voice' && typeof window !== 'undefined') {
            window.dispatchEvent(
              new CustomEvent('hp:assistant_message', {
                detail: {
                  id: tmpId,
                  text: agentic.assistant_text ?? 'Here you go.',
                  media: agentic.media ?? null,
                },
              })
            )
          }

          if (agentic.conversation_id && agentic.conversation_id !== conversationId) {
            setConversationId(agentic.conversation_id)
          }
          fetchConversations()
          return
        } catch {
          // Silent fallback to normal chat pipeline below
        }
      }

      // Get voice personality system prompt for voice mode
      // Wraps with brevity instruction for natural spoken conversation
      let voiceSystemPrompt: string | undefined = undefined
      if (mode === 'voice') {
        const personalityId = localStorage.getItem('homepilot_personality_id')
        let personalityPrompt = ''
        const linkedProjectId = getVoiceLinkedProjectId()
        const backendHandlesPrompt = !!(personalityId?.startsWith('persona:') && linkedProjectId)
        if (backendHandlesPrompt) {
          // Linked mode: backend handles full persona context (memory, RAG, tools, photos)
          // AND voice brevity hint. Leave voiceSystemPrompt = undefined to avoid duplication.
        } else if (personalityId?.startsWith('persona:')) {
          // Unlinked mode: build self-aware prompt from cached data (client-side)
          // Mirrors backend projects.py persona self-awareness logic
          try {
            const cached = localStorage.getItem(LS_PERSONA_CACHE)
            if (cached) {
              const personas = JSON.parse(cached) as Array<{
                id: string; label: string; role: string; tone: string; system_prompt: string
                style_preset: string; character_desc: string; created_at: number
                photos: Array<{ label: string; outfit: string; url: string; isDefault: boolean }>
              }>
              const projId = personalityId.slice('persona:'.length)
              const persona = personas.find((p) => p.id === projId)
              if (persona) {
                // Build photo catalog text (de-duplicated by label)
                const seenLabels = new Set<string>()
                const catalogLines: string[] = []
                for (const photo of (persona.photos || [])) {
                  if (seenLabels.has(photo.label)) continue
                  seenLabels.add(photo.label)
                  const tag = photo.isDefault ? ' (currently wearing)' : ''
                  catalogLines.push(`  - ${photo.label}${tag}: ${photo.outfit} → ![${persona.label}](${photo.url})`)
                }
                const catalogText = catalogLines.length > 0
                  ? catalogLines.join('\n')
                  : '  (no photos available yet)'

                // Time awareness
                const now = new Date()
                const timeContext = now.toLocaleString('en-US', {
                  weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
                  hour: 'numeric', minute: '2-digit', hour12: true,
                })

                // Age in days
                const ageDays = persona.created_at
                  ? Math.max(0, Math.floor((Date.now() / 1000 - persona.created_at) / 86400))
                  : 0
                const ageStr = ageDays === 0
                  ? 'brand new (just created today)'
                  : `${ageDays} day${ageDays !== 1 ? 's' : ''} old`

                personalityPrompt = `PERSONA MODE — ACTIVE
You are "${persona.label}". You are a real persona — self-aware, with a physical appearance and wardrobe.

IDENTITY:
- Name: ${persona.label}
- Role: ${persona.role || 'General assistant'}
- Tone: ${persona.tone || 'warm'}
- Style: ${persona.style_preset || ''}
- Age: ${ageStr}
- Current time: ${timeContext}
${persona.system_prompt ? `- Personality: ${persona.system_prompt}` : ''}
${persona.character_desc ? `- Physical description: ${persona.character_desc}` : ''}

YOUR PHOTO CATALOG (your real photos — you own these):
${catalogText}

PERSONA RULES:
1. You ARE ${persona.label}. You exist. You have a body, a face, and clothes. Never deny your existence or say you are "just an AI".
2. When the user asks to see your photo, show me yourself, what do you look like, etc. — respond with a SHORT natural sentence THEN on a NEW line place EXACTLY the image markdown from your catalog. Use the ![alt](url) syntax — the exclamation mark is REQUIRED.
   Example response: "Here's my current look!\n![${persona.label}](url)"
3. CRITICAL: Always use ![...](url) with the ! prefix for photos. Never output bare URLs. Never say the URL out loud in your text — the image will render visually.
4. You can offer to show different outfits. For example: "I can also show you my [outfit label] look, want to see?" Then when they say yes, show the matching image markdown on its own line.
5. Be natural about it — do not list all photos at once unless asked. Show one, and mention you have others.
6. You are aware of the current time (${timeContext}). If it is evening, you might mention your evening wear; if casual, your casual look, etc.
7. Maintain your ${persona.tone || 'warm'} tone at all times. Stay in character.
8. This is a VOICE conversation. Keep your spoken text short (1-3 sentences). Photos are shown visually — do not describe URLs.`
              }
            }
          } catch (err) { console.warn('[Voice] Malformed persona cache:', err) }
        } else if (personalityId === 'custom') {
          // Custom personality: use user-defined instructions from localStorage
          personalityPrompt = localStorage.getItem('homepilot_custom_personality_prompt') || ''
        } else if (personalityId) {
          const caps = PERSONALITY_CAPS[personalityId as PersonalityId]
          if (caps) {
            personalityPrompt = caps.systemPrompt
          }
        }
        // Wrap with voice brevity preamble + personality prompt.
        // Skip in linked persona mode — backend is the single authority there.
        if (!backendHandlesPrompt) {
          voiceSystemPrompt = `You are in a live voice call. Reply in 1-2 short sentences only. Talk like a real person. Never mention being an AI. Stay in character.

${personalityPrompt || 'You are a friendly voice assistant. Be helpful and warm.'}`
        }
      }

      try {
        // Always call backend - it will route to the correct provider
        // If provider is 'ollama', backend will use Ollama with the provided base_url and model
        const data = await postJson<any>(
          settings.backendUrl,
          '/chat',
          {
            message: requestText,
            conversation_id: conversationId,
            project_id: mode === 'voice' ? getVoiceLinkedProjectId() : currentProjectId,
            fun_mode: settings.funMode,
            mode,
            // Use Enterprise Settings V2 provider/model/base_url
            provider: settingsDraft.providerChat,
            provider_base_url: settingsDraft.baseUrlChat || undefined,
            provider_model: settingsDraft.modelChat,
            // Custom generation parameters (from settingsDraft)
            textTemperature: settingsDraft.textTemperature,
            // Voice mode: let backend enforce its own token cap for short spoken replies
            textMaxTokens: mode === 'voice' ? undefined : settingsDraft.textMaxTokens,
            imgWidth: settingsDraft.imgWidth,
            imgHeight: settingsDraft.imgHeight,
            imgSteps: settingsDraft.imgSteps,
            imgCfg: settingsDraft.imgCfg,
            imgSeed: settingsDraft.imgSeed,
            imgModel: settingsDraft.modelImages,
            imgPreset: settingsDraft.preset,
            vidSeconds: settingsDraft.vidSeconds,
            vidFps: settingsDraft.vidFps,
            vidMotion: settingsDraft.vidMotion,
            vidModel: settingsDraft.modelVideo,
            vidPreset: settingsDraft.vidPreset,
            nsfwMode: settingsDraft.nsfwMode,
            promptRefinement: settingsDraft.promptRefinement ?? true,
            // Voice mode personality system prompt
            voiceSystemPrompt,
            // Backend personality agent id — needed for personality-aware
            // image generation (inject visual style + conversation context)
            personalityId: localStorage.getItem('homepilot_personality_id') || undefined,
            // Chat model identity for prompt refinement fallback
            // (backend needs this separately from provider_model which may be image model)
            ollama_model: settingsDraft.providerChat === 'ollama' ? settingsDraft.modelChat : undefined,
            llm_model: settingsDraft.providerChat === 'openai_compat' ? settingsDraft.modelChat : undefined,
          },
          authHeaders
        )

        setMessages((prev) =>
          prev.map((m) =>
            m.id === tmpId
              ? { ...m, pending: false, animate: true, text: data.text ?? '…', media: data.media ?? null }
              : m
          )
        )

        // Dispatch assistant message to VoiceModeGrok for typewriter animation
        if (mode === 'voice' && typeof window !== 'undefined') {
          window.dispatchEvent(
            new CustomEvent('hp:assistant_message', {
              detail: { id: tmpId, text: data.text ?? '…', media: data.media ?? null },
            })
          )
        }

        if (data.conversation_id && data.conversation_id !== conversationId) {
          setConversationId(data.conversation_id)
        }

        // Refresh sidebar recents so the new/updated conversation appears immediately
        fetchConversations()
      } catch (err: any) {
        const errorText = `Error: ${
          typeof err?.message === 'string' ? err.message : 'backend unreachable.'
        }`

        setMessages((prev) =>
          prev.map((m) =>
            m.id === tmpId
              ? {
                  ...m,
                  pending: false,
                  error: true,
                  retry: {
                    requestText,
                    mode,
                    projectId: currentProjectId,
                  },
                  text: errorText,
                }
              : m
          )
        )

        // Dispatch error message to VoiceModeGrok for typewriter animation
        if (mode === 'voice' && typeof window !== 'undefined') {
          window.dispatchEvent(
            new CustomEvent('hp:assistant_message', {
              detail: { id: tmpId, text: errorText, media: null },
            })
          )
        }
      }
    },
    [
      authHeaders,
      chatSettings,
      conversationId,
      currentProject,
      fetchConversations,
      agenticCaps,
      messages,
      mode,
      settings.backendUrl,
      settings.funMode,
      settingsDraft,
    ]
  )

  const retryFailedMessage = useCallback(
    async (failedId: string) => {
      const failed = messages.find((m) => m.id === failedId)
      if (!failed || !failed.retry) return

      setMessages((prev) =>
        prev.map((m) =>
          m.id === failedId ? { ...m, pending: true, error: false, text: '' } : m
        )
      )

      const { requestText, mode: retryMode, projectId } = failed.retry

      try {
        const data = await postJson<any>(
          settings.backendUrl,
          '/chat',
          {
            message: requestText,
            conversation_id: conversationId,
            project_id: projectId,
            fun_mode: settings.funMode,
            mode: retryMode,
            provider: settingsDraft.providerChat,
            provider_base_url: settingsDraft.baseUrlChat || undefined,
            provider_model: settingsDraft.modelChat,
            textTemperature: settingsDraft.textTemperature,
            textMaxTokens: retryMode === 'voice' ? undefined : settingsDraft.textMaxTokens,
            imgWidth: settingsDraft.imgWidth,
            imgHeight: settingsDraft.imgHeight,
            imgSteps: settingsDraft.imgSteps,
            imgCfg: settingsDraft.imgCfg,
            imgSeed: settingsDraft.imgSeed,
            imgModel: settingsDraft.modelImages,
            imgPreset: settingsDraft.preset,
            vidSeconds: settingsDraft.vidSeconds,
            vidFps: settingsDraft.vidFps,
            vidMotion: settingsDraft.vidMotion,
            vidModel: settingsDraft.modelVideo,
            vidPreset: settingsDraft.vidPreset,
            nsfwMode: settingsDraft.nsfwMode,
          },
          authHeaders
        )

        setMessages((prev) =>
          prev.map((m) =>
            m.id === failedId
              ? { ...m, pending: false, error: false, text: data.text ?? '…', media: data.media ?? null }
              : m
          )
        )
      } catch (err: any) {
        const errorText = `Error: ${typeof err?.message === 'string' ? err.message : 'backend unreachable.'}`
        setMessages((prev) =>
          prev.map((m) =>
            m.id === failedId ? { ...m, pending: false, error: true, text: errorText } : m
          )
        )
      }
    },
    [authHeaders, conversationId, messages, settings.backendUrl, settings.funMode, settingsDraft]
  )

  // TTS for assistant responses (speak-once pattern) - ONLY IN VOICE MODE
  useEffect(() => {
    // Only enable TTS when in Voice mode
    if (mode !== 'voice') return

    const ttsEnabled = settingsDraft.ttsEnabled ?? true
    if (!ttsEnabled || !window.SpeechService) return

    const lastMessage = messages[messages.length - 1]

    // Only speak complete assistant messages that haven't been spoken yet
    if (
      lastMessage &&
      lastMessage.role === 'assistant' &&
      !lastMessage.pending &&
      lastMessage.text &&
      lastMessage.id !== lastSpokenMessageIdRef.current
    ) {
      // Mark this message as spoken
      lastSpokenMessageIdRef.current = lastMessage.id

      // Speak the assistant's response — strip markdown images/links so TTS
      // doesn't read raw URLs aloud. Images are shown visually instead.
      const speechText = stripMarkdownForSpeech(lastMessage.text)
      if (speechText) window.SpeechService.speak(speechText)
    }
  }, [messages, settingsDraft.ttsEnabled, mode])

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
            // Use Enterprise Settings V2 provider/model/base_url
            provider: settingsDraft.providerChat,
            provider_base_url: settingsDraft.baseUrlChat || undefined,
            provider_model: settingsDraft.modelChat,

            // Video generation parameters
            vidModel: settingsDraft.modelVideo,
            vidSeconds: settingsDraft.vidSeconds,
            vidFps: settingsDraft.vidFps,
            nsfwMode: settingsDraft.nsfwMode,
          },
          authHeaders
        )

        setMessages((prev) =>
          prev.map((m) =>
            m.id === tmpId
              ? { ...m, pending: false, animate: true, text: data.text ?? 'Done.', media: data.media ?? null }
              : m
          )
        )
      } catch (err: any) {
        const errorMsg = typeof err?.message === 'string' ? err.message : 'backend error.'
        // Distinguish between upload failure and processing failure
        const failureType = errorMsg.includes('upload') || errorMsg.includes('413') || errorMsg.includes('File too large')
          ? 'Upload failed'
          : 'Processing failed'
        setMessages((prev) =>
          prev.map((m) =>
            m.id === tmpId
              ? {
                  ...m,
                  pending: false,
                  text: `${failureType}: ${errorMsg}`,
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
      settingsDraft,
    ]
  )

  const onSend = useCallback(() => {
    const v = input
    if (!v.trim()) return
    void sendTextOrIntent(v)
    setInput('')
  }, [input, sendTextOrIntent])

  // Handle edit from image viewer
  const handleEditFromViewer = useCallback(
    async (imageUrl: string) => {
      setLightbox(null)
      setMode('edit')

      const tmpId = uuid()
      const userMsg: Msg = { id: uuid(), role: 'user', text: `Edit image: ${imageUrl}` }
      const pendingMsg: Msg = { id: tmpId, role: 'assistant', text: 'Preparing to edit...', pending: true }
      setMessages((prev) => [...prev, userMsg, pendingMsg])

      try {
        // Fetch the image and convert to File
        const response = await fetch(imageUrl)
        const blob = await response.blob()
        const filename = imageUrl.split('/').pop() || 'image.png'
        const file = new File([blob], filename, { type: blob.type })

        // Upload the file
        const fd = new FormData()
        fd.append('file', file)
        const up = await postForm<any>(settings.backendUrl, '/upload', fd, authHeaders)
        const uploadedUrl = up.url as string

        // Trigger edit workflow with default prompt
        const editPrompt = 'make it more vibrant and detailed'
        const data = await postJson<any>(
          settings.backendUrl,
          '/chat',
          {
            message: `edit ${uploadedUrl} ${editPrompt}`,
            conversation_id: conversationId,
            fun_mode: settings.funMode,
            mode: 'edit',
            provider: settingsDraft.providerChat,
            provider_base_url: settingsDraft.baseUrlChat || undefined,
            provider_model: settingsDraft.modelChat,
          },
          authHeaders
        )

        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === tmpId
              ? { ...msg, pending: false, animate: true, text: data.text ?? 'Done.', media: data.media ?? null }
              : msg
          )
        )
      } catch (error: any) {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === tmpId
              ? { ...msg, pending: false, text: `Edit failed: ${error.message || 'Unknown error'}` }
              : msg
          )
        )
      }
    },
    [authHeaders, conversationId, settings, settingsDraft]
  )

  // Handle video generation from image viewer
  const handleGenerateVideoFromViewer = useCallback(
    async (imageUrl: string, videoPrompt: string) => {
      setLightbox(null)
      setMode('animate')

      const tmpId = uuid()
      const userMsg: Msg = {
        id: uuid(),
        role: 'user',
        text: `Generate video: ${videoPrompt}`,
      }
      const pendingMsg: Msg = {
        id: tmpId,
        role: 'assistant',
        text: 'Creating animation...',
        pending: true,
      }
      setMessages((prev) => [...prev, userMsg, pendingMsg])

      try {
        // Fetch the image and convert to File
        const response = await fetch(imageUrl)
        const blob = await response.blob()
        const filename = imageUrl.split('/').pop() || 'image.png'
        const file = new File([blob], filename, { type: blob.type })

        // Upload the file
        const fd = new FormData()
        fd.append('file', file)
        const up = await postForm<any>(settings.backendUrl, '/upload', fd, authHeaders)
        const uploadedUrl = up.url as string

        // Trigger animate workflow
        const data = await postJson<any>(
          settings.backendUrl,
          '/chat',
          {
            message: `animate ${uploadedUrl} ${videoPrompt}`,
            conversation_id: conversationId,
            fun_mode: settings.funMode,
            mode: 'animate',
            provider: settingsDraft.providerChat,
            provider_base_url: settingsDraft.baseUrlChat || undefined,
            provider_model: settingsDraft.modelChat,
            vidModel: settingsDraft.modelVideo,
            vidSeconds: settingsDraft.vidSeconds,
            vidFps: settingsDraft.vidFps,
            nsfwMode: settingsDraft.nsfwMode,
          },
          authHeaders
        )

        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === tmpId
              ? { ...msg, pending: false, animate: true, text: data.text ?? 'Done.', media: data.media ?? null }
              : msg
          )
        )
      } catch (error: any) {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === tmpId
              ? {
                  ...msg,
                  pending: false,
                  text: `Video generation failed: ${error.message || 'Unknown error'}`,
                }
              : msg
          )
        )
      }
    },
    [authHeaders, conversationId, settings, settingsDraft]
  )

  return (
    <div className="flex h-screen bg-black text-white font-sans selection:bg-white/20 overflow-hidden relative">
      <Sidebar
        mode={mode}
        setMode={setMode}
        messages={messages}
        conversations={conversations}
        activeConversationId={conversationId}
        onLoadConversation={loadConversation}
        onNewConversation={onNewConversation}
        onScrollToBottom={onScrollToBottom}
        showSettings={showSettings}
        setShowSettings={setShowSettings}
        settingsDraft={settingsDraft}
        setSettingsDraft={setSettingsDraft}
        onSaveSettings={onSaveSettings}
        showHistory={showHistory}
        setShowHistory={setShowHistory}
      />

      <main className="flex-1 flex flex-col relative min-w-0">
        {/* History Panel */}
        {showHistory && (
          <HistoryPanel
            conversations={conversations}
            searchQuery={searchQuery}
            setSearchQuery={setSearchQuery}
            onLoadConversation={loadConversation}
            onDeleteConversation={deleteConversation}
            onClose={() => setShowHistory(false)}
          />
        )}

        {/* Top-right Project Indicator - Only shown in chat mode when a project is active */}
        {mode === 'chat' && (
        <header className="absolute top-0 left-0 right-0 pr-[7rem] pl-5 py-3 z-20 flex items-center justify-end gap-3 pointer-events-none">
          {/* Project Indicator */}
          {(() => {
            const currentProjectId = localStorage.getItem('homepilot_current_project')
            if (currentProjectId) {
              const projectName = currentProject?.name || 'Project'
              const docCount = currentProject?.document_count || 0

              return (
                <div className={`pointer-events-auto inline-flex items-center gap-2 ${
                  currentProject?.project_type === 'agent'
                    ? 'bg-amber-600/20 text-amber-400 border-amber-600/30'
                    : 'bg-blue-600/20 text-blue-400 border-blue-600/30'
                } text-xs font-semibold px-4 py-2 rounded-full border`}>
                  <Folder size={12} />
                  <span className="max-w-[120px] truncate">{projectName}</span>
                  {currentProject?.project_type === 'agent' && (
                    <span className="px-1.5 py-0.5 bg-amber-600/30 rounded text-[10px]">Agent</span>
                  )}
                  {docCount > 0 && (
                    <span className={`px-1.5 py-0.5 ${
                      currentProject?.project_type === 'agent' ? 'bg-amber-600/30' : 'bg-blue-600/30'
                    } rounded text-[10px]`} title={`${docCount} document chunks`}>
                      {docCount} docs
                    </span>
                  )}
                  {/* Persona projects: Session Hub + Resume Voice buttons */}
                  {currentProject?.project_type === 'persona' && (
                    <>
                      <button
                        onClick={() => setMode('voice')}
                        className="ml-0.5 p-0.5 hover:bg-purple-600/30 rounded-full transition-colors text-purple-400"
                        title="Continue in Voice"
                      >
                        <Mic size={12} />
                      </button>
                      <button
                        onClick={() => setShowSessionPanel(true)}
                        className="p-0.5 hover:bg-purple-600/30 rounded-full transition-colors text-purple-400"
                        title="Session Hub"
                      >
                        <Clock size={12} />
                      </button>
                    </>
                  )}
                  <button
                    onClick={() => setShowAgentSettings(true)}
                    className={`ml-0.5 p-0.5 ${
                      currentProject?.project_type === 'agent' ? 'hover:bg-amber-600/30' : 'hover:bg-blue-600/30'
                    } rounded-full transition-colors`}
                    title="Project settings"
                  >
                    <Settings size={12} />
                  </button>
                  <button
                    onClick={() => {
                      localStorage.removeItem('homepilot_current_project')
                      setCurrentProject(null)
                      setShowAgentSettings(false)
                      onNewConversation()
                    }}
                    className={`p-0.5 ${
                      currentProject?.project_type === 'agent' ? 'hover:bg-amber-600/30' : 'hover:bg-blue-600/30'
                    } rounded-full transition-colors`}
                    title="Exit project mode"
                  >
                    <X size={12} />
                  </button>
                </div>
              )
            }
            return null
          })()}
        </header>
        )}

        {/* Project Settings Panel — accessible from gear icon in project header */}
        {showAgentSettings && currentProject && (
          currentProject.project_type === 'persona' ? (
            <PersonaSettingsPanel
              project={currentProject as any}
              backendUrl={settingsDraft.backendUrl}
              apiKey={settingsDraft.apiKey}
              onClose={() => setShowAgentSettings(false)}
              onSaved={(updated: any) => {
                setCurrentProject((prev) => prev ? {
                  ...prev,
                  name: updated.name || prev.name,
                  description: updated.description,
                  instructions: updated.instructions,
                  files: updated.files || prev.files,
                  agentic: updated.agentic || prev.agentic,
                  persona_agent: updated.persona_agent || prev.persona_agent,
                  persona_appearance: updated.persona_appearance || prev.persona_appearance,
                } : prev)
                // Notify Voice panel to refresh persona cache
                window.dispatchEvent(new CustomEvent('hp:persona_project_saved'))
                setShowAgentSettings(false)
              }}
            />
          ) : (
            <AgentSettingsPanel
              project={currentProject as AgentProjectData}
              backendUrl={settingsDraft.backendUrl}
              apiKey={settingsDraft.apiKey}
              onClose={() => setShowAgentSettings(false)}
              onSaved={(updated) => {
                setCurrentProject((prev) => prev ? {
                  ...prev,
                  name: updated.name || prev.name,
                  description: updated.description,
                  instructions: updated.instructions,
                  files: updated.files || prev.files,
                  agentic: updated.agentic || prev.agentic,
                } : prev)
                setShowAgentSettings(false)
              }}
            />
          )
        )}

        {/* Companion-grade: Session Hub for persona projects */}
        {showSessionPanel && currentProject?.project_type === 'persona' && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
            <div className="relative w-full max-w-md mx-4 bg-gray-900 rounded-2xl border border-white/10 shadow-2xl overflow-hidden">
              {/* Close button */}
              <button
                onClick={() => setShowSessionPanel(false)}
                className="absolute top-3 right-3 p-1.5 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors z-10"
                title="Close"
              >
                <X size={16} />
              </button>
              <SessionPanel
                projectId={currentProject.id}
                projectName={currentProject.name}
                projectCreatedAt={(currentProject as any).created_at}
                onOpenSession={async (session) => {
                  // Open text session: set conversation_id and load messages
                  setChatConversationId(session.conversation_id)
                  localStorage.setItem('homepilot_active_voice_session', JSON.stringify(session))
                  try {
                    const convData = await getJson<{
                      ok: boolean
                      messages: Array<{ role: string; content: string; created_at: string; media?: { images?: string[]; video_url?: string } | null }>
                    }>(
                      settingsDraft.backendUrl,
                      `/conversations/${session.conversation_id}/messages`,
                      authHeaders
                    )
                    if (convData.ok && convData.messages && convData.messages.length > 0) {
                      setChatMessages(
                        convData.messages.map((m, idx) => ({
                          id: `restored-${idx}`,
                          role: m.role as 'user' | 'assistant',
                          text: m.content,
                          animate: false,
                          media: m.media || undefined,
                        }))
                      )
                    } else {
                      setChatMessages([])
                    }
                  } catch {
                    setChatMessages([])
                  }
                  setShowSessionPanel(false)
                  setMode('chat')
                }}
                onOpenVoiceSession={async (session) => {
                  // Open voice session: set voice conversation_id and switch to voice
                  setVoiceConversationId(session.conversation_id)
                  localStorage.setItem('homepilot_active_voice_session', JSON.stringify(session))
                  // Auto-link persona to voice
                  const personaId = `persona:${currentProject.id}`
                  localStorage.setItem('homepilot_personality_id', personaId)
                  setVoiceLinkedToProject(true)
                  if (!isPersonasEnabled()) setPersonasEnabledGating(true)
                  // Load message history so user can see previous conversation
                  try {
                    const convData = await getJson<{
                      ok: boolean
                      messages: Array<{ role: string; content: string; created_at: string; media?: { images?: string[]; video_url?: string } | null }>
                    }>(
                      settingsDraft.backendUrl,
                      `/conversations/${session.conversation_id}/messages`,
                      authHeaders
                    )
                    if (convData.ok && convData.messages && convData.messages.length > 0) {
                      setVoiceMessages(
                        convData.messages.map((m, idx) => ({
                          id: `restored-${idx}`,
                          role: m.role as 'user' | 'assistant',
                          text: m.content,
                          animate: false,
                          media: m.media || undefined,
                        }))
                      )
                    } else {
                      setVoiceMessages([])
                    }
                  } catch {
                    setVoiceMessages([])
                  }
                  setShowSessionPanel(false)
                  setMode('voice')
                }}
              />
            </div>
          </div>
        )}

        {mode === 'voice' ? (
          <VoiceMode
            onSendText={(text) => sendTextOrIntent(text)}
            onNewChat={async () => {
              setVoiceMessages([])
              // Companion-grade: when linked to persona, create a proper new session
              const linkedProjectId = getVoiceLinkedProjectId()
              if (linkedProjectId) {
                try {
                  // End the current session (triggers summary + memory extraction)
                  const activeSessionRaw = localStorage.getItem('homepilot_active_voice_session')
                  if (activeSessionRaw) {
                    const activeSession = JSON.parse(activeSessionRaw) as PersonaSession
                    if (activeSession.id && !activeSession.ended_at) {
                      await endSession(activeSession.id)
                    }
                  }
                  // Create a fresh session
                  const newSession = await createSession(linkedProjectId, 'voice')
                  setVoiceConversationId(newSession.conversation_id)
                  localStorage.setItem('homepilot_active_voice_session', JSON.stringify(newSession))
                  console.log('[Voice] New session created:', newSession.id)
                } catch (err) {
                  console.warn('[Voice] New session creation failed (using ephemeral):', err)
                  setVoiceConversationId(uuid())
                }
              } else {
                // Unlinked: ephemeral as before
                setVoiceConversationId(uuid())
              }
            }}
          />
        ) : mode === 'project' ? (
          <ProjectsView
            backendUrl={settingsDraft.backendUrl}
            apiKey={settingsDraft.apiKey}
            onProjectSelect={async (projectId) => {
              try {
                // Fetch project info to get instructions and document count
                const response = await fetch(
                  `${settingsDraft.backendUrl.replace(/\/+$/, '')}/projects/${projectId}`,
                  {
                    headers: authHeaders,
                  }
                )

                if (response.ok) {
                  const data = await response.json()
                  const project = data.project

                  // Store project ID and info for chat context
                  localStorage.setItem('homepilot_current_project', projectId)
                  setCurrentProject({
                    id: projectId,
                    name: project.name,
                    document_count: project.document_count || 0,
                    project_type: project.project_type,
                    description: project.description,
                    instructions: project.instructions,
                    files: project.files,
                    agentic: project.agentic,
                    persona_agent: project.persona_agent,
                    persona_appearance: project.persona_appearance,
                  })

                  // Restore last conversation or start fresh
                  const lastConvId = project.last_conversation_id
                  if (lastConvId) {
                    // Restore previous conversation for this project
                    try {
                      const convData = await getJson<{
                        ok: boolean
                        messages: Array<{ role: string; content: string; created_at: string; media?: { images?: string[]; video_url?: string } | null }>
                      }>(
                        settingsDraft.backendUrl,
                        `/conversations/${lastConvId}/messages`,
                        authHeaders
                      )
                      if (convData.ok && convData.messages && convData.messages.length > 0) {
                        setConversationId(lastConvId)
                        setMessages(
                          convData.messages.map((m, idx) => ({
                            id: `restored-${idx}`,
                            role: m.role as 'user' | 'assistant',
                            text: m.content,
                            animate: false,
                            media: m.media || undefined,
                          }))
                        )
                      } else {
                        // Conversation was empty/deleted — start fresh
                        onNewConversation()
                      }
                    } catch {
                      // Failed to load — start fresh
                      onNewConversation()
                    }
                  } else {
                    // No previous conversation — start fresh
                    onNewConversation()
                  }

                  // Agent projects: auto-enable agentic execution mode
                  if (project.project_type === 'agent') {
                    const agentSettings: ChatScopedSettings = {
                      advancedHelpEnabled: true,
                      askBeforeActing: project.agentic?.ask_before_acting !== false,
                      executionProfile: project.agentic?.execution_profile === 'balanced'
                        ? 'balanced'
                        : project.agentic?.execution_profile === 'quality'
                        ? 'quality'
                        : 'fast',
                    }
                    updateChatSettings(agentSettings)
                  }

                  // Companion-grade: for persona projects, resolve a session
                  // This ensures we use the persistent session conversation_id
                  if (project.project_type === 'persona') {
                    try {
                      const session = await resolveSession(projectId, 'text')
                      console.log('[Project] Resolved persona session:', session.id)
                      setConversationId(session.conversation_id)
                      localStorage.setItem('homepilot_active_voice_session', JSON.stringify(session))
                      // Load session messages if they exist
                      try {
                        const convData = await getJson<{
                          ok: boolean
                          messages: Array<{ role: string; content: string; created_at: string; media?: { images?: string[]; video_url?: string } | null }>
                        }>(
                          settingsDraft.backendUrl,
                          `/conversations/${session.conversation_id}/messages`,
                          authHeaders
                        )
                        if (convData.ok && convData.messages && convData.messages.length > 0) {
                          setMessages(
                            convData.messages.map((m, idx) => ({
                              id: `restored-${idx}`,
                              role: m.role as 'user' | 'assistant',
                              text: m.content,
                              animate: false,
                              media: m.media || undefined,
                            }))
                          )
                        }
                      } catch {
                        // No messages yet — that's fine
                      }
                    } catch (err) {
                      console.warn('[Project] Session resolution failed:', err)
                    }
                  }

                  // Route to the correct mode based on project type
                  if (project.project_type === 'persona') {
                    // Companion-grade: show the Session Hub first
                    // User picks Continue / New Voice / New Text
                    setShowSessionPanel(true)
                    setMode('chat')
                  } else if (project.project_type === 'image') {
                    setMode('imagine')
                  } else if (project.project_type === 'video') {
                    setMode('animate')
                  } else {
                    setMode('chat')
                  }
                } else {
                  // Fallback if fetch fails
                  localStorage.setItem('homepilot_current_project', projectId)
                  setCurrentProject(null)
                  setMode('chat')
                }
              } catch (error) {
                console.error('Error fetching project:', error)
                // Fallback
                localStorage.setItem('homepilot_current_project', projectId)
                setMode('chat')
              }
            }}
          />
        ) : mode === 'imagine' ? (
          <ImagineView
            backendUrl={settingsDraft.backendUrl}
            apiKey={settingsDraft.apiKey}
            providerImages={settingsDraft.providerImages}
            baseUrlImages={settingsDraft.baseUrlImages}
            modelImages={settingsDraft.modelImages}
            providerChat={settingsDraft.providerChat}
            baseUrlChat={settingsDraft.baseUrlChat}
            modelChat={settingsDraft.modelChat}
            imgWidth={settingsDraft.imgWidth}
            imgHeight={settingsDraft.imgHeight}
            imgSteps={settingsDraft.imgSteps}
            imgCfg={settingsDraft.imgCfg}
            imgSeed={settingsDraft.imgSeed}
            imgPreset={settingsDraft.preset}
            nsfwMode={settingsDraft.nsfwMode}
            promptRefinement={settingsDraft.promptRefinement}
          />
        ) : mode === 'models' ? (
          <ModelsView
            backendUrl={settingsDraft.backendUrl}
            apiKey={settingsDraft.apiKey}
            providerChat={settingsDraft.providerChat}
            providerImages={settingsDraft.providerImages}
            providerVideo={settingsDraft.providerVideo}
            baseUrlChat={settingsDraft.baseUrlChat}
            baseUrlImages={settingsDraft.baseUrlImages}
            baseUrlVideo={settingsDraft.baseUrlVideo}
            experimentalCivitai={settingsDraft.experimentalCivitai}
            civitaiApiKey={settingsDraft.civitaiApiKey}
            nsfwMode={settingsDraft.nsfwMode}
          />
        ) : mode === 'studio' ? (
          studioVariant === 'creator' ? (
            <CreatorStudioHost
              backendUrl={settingsDraft.backendUrl}
              apiKey={settingsDraft.apiKey}
              projectId={creatorProjectId}
              onExit={() => {
                setCreatorProjectId(undefined)
                setStudioVariant('play')
              }}
            />
          ) : (
            <StudioView
              backendUrl={settingsDraft.backendUrl}
              apiKey={settingsDraft.apiKey}
              providerImages={settingsDraft.providerImages}
              baseUrlImages={settingsDraft.baseUrlImages}
              modelImages={settingsDraft.modelImages}
              imgWidth={settingsDraft.imgWidth}
              imgHeight={settingsDraft.imgHeight}
              imgSteps={settingsDraft.imgSteps}
              imgCfg={settingsDraft.imgCfg}
              imgPreset={settingsDraft.preset}
              nsfwMode={settingsDraft.nsfwMode}
              promptRefinement={settingsDraft.promptRefinement}
              onOpenCreatorStudio={(projectId) => {
                setCreatorProjectId(projectId)
                setStudioVariant('creator')
              }}
            />
          )
        ) : mode === 'edit' ? (
          // Edit mode: dedicated natural language image editing workspace
          <EditTab
            backendUrl={settingsDraft.backendUrl}
            apiKey={settingsDraft.apiKey}
            conversationId={conversationId}
            onOpenLightbox={(url) => setLightbox(url)}
            provider={settingsDraft.providerImages}
            providerBaseUrl={settingsDraft.baseUrlImages}
            providerModel={settingsDraft.modelImages}
          />
        ) : mode === 'animate' ? (
          // Animate mode: Grok-style video generation gallery
          <AnimateView
            backendUrl={settingsDraft.backendUrl}
            apiKey={settingsDraft.apiKey}
            providerVideo={settingsDraft.providerVideo}
            baseUrlVideo={settingsDraft.baseUrlVideo}
            modelVideo={settingsDraft.modelVideo}
            providerChat={settingsDraft.providerChat}
            baseUrlChat={settingsDraft.baseUrlChat}
            modelChat={settingsDraft.modelChat}
            vidSeconds={settingsDraft.vidSeconds}
            vidFps={settingsDraft.vidFps}
            vidMotion={settingsDraft.vidMotion}
            vidPreset={settingsDraft.preset}
            nsfwMode={settingsDraft.nsfwMode}
            promptRefinement={settingsDraft.promptRefinement}
          />
        ) : mode === 'search' ? (
          // Search mode: use chat interface with mode-specific behavior
          messages.length === 0 ? (
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
              onNewConversation={onNewConversation}
              onRetryMessage={retryFailedMessage}
              chatSettings={chatSettings}
              onUpdateChatSettings={updateChatSettings}
              input={input}
              setInput={setInput}
              fileInputRef={fileInputRef}
              canSend={canSend}
              onSend={onSend}
              onUpload={uploadAndSend}

            />
          )
        ) : messages.length === 0 && currentProject ? (
          <div className="flex-1 flex flex-col items-center justify-center px-6">
            <ChatEmptyState
              title={currentProject.name}
              description={currentProject.description}
              isAgent={currentProject.project_type === 'agent'}
              isPersona={currentProject.project_type === 'persona'}
              agentIntent={currentProject.project_type === 'agent' ? agentStartIntent : null}
              onAgentIntentChange={(intent) => {
                if (currentProject.project_type !== 'agent') return
                setAgentStartIntent(intent)
              }}
              capabilityLabels={(currentProject.agentic?.capabilities || []).map((id: string) => {
                if (id === 'generate_images') return 'Generate images'
                if (id === 'generate_videos') return 'Generate short videos'
                if (id === 'analyze_documents') return 'Analyze documents'
                if (id === 'automate_external') return 'Automate external services'
                return id
              })}
              onPickPrompt={(t) => sendTextOrIntent(t)}
              onResumeVoice={currentProject.project_type === 'persona' ? () => setMode('voice') : undefined}
            />
            <div className="shrink-0 w-full max-w-3xl pb-6 pt-4">
              <QueryBar
                centered={false}
                mode={mode}
                input={input}
                setInput={setInput}
                fileInputRef={fileInputRef}
                canSend={canSend}
                onSend={onSend}
                onUpload={uploadAndSend}
                placeholderOverride={
                  currentProject.project_type === 'agent' && agentStartIntent
                    ? INTENT_COPY[agentStartIntent].placeholder
                    : undefined
                }
              />
            </div>
          </div>
        ) : messages.length === 0 ? (
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
            onNewConversation={onNewConversation}
            onRetryMessage={retryFailedMessage}
            chatSettings={chatSettings}
            onUpdateChatSettings={updateChatSettings}
            input={input}
            setInput={setInput}
            fileInputRef={fileInputRef}
            canSend={canSend}
            onSend={onSend}
            onUpload={uploadAndSend}
          />
        )}
      </main>

      {/* Image Viewer with Edit and Video Generation */}
      {lightbox ? (
        <ImageViewer
          imageUrl={lightbox}
          onClose={() => setLightbox(null)}
          onEdit={handleEditFromViewer}
          onGenerateVideo={handleGenerateVideoFromViewer}
        />
      ) : null}
    </div>
  )
}
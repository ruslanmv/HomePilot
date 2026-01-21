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
import SettingsPanel, { type SettingsModelV2, type HardwarePresetUI } from './SettingsPanel'
import VoiceMode from './VoiceMode'
import ProjectsView from './ProjectsView'
import ImagineView from './Imagine'
import ModelsView from './Models'
import { ImageViewer } from './ImageViewer'

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
  media?: {
    images?: string[]
    video_url?: string
  } | null
}

type Mode = 'chat' | 'voice' | 'search' | 'project' | 'imagine' | 'edit' | 'animate' | 'models'
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
  onClose,
}: {
  conversations: Conversation[]
  searchQuery: string
  setSearchQuery: (q: string) => void
  onLoadConversation: (convId: string) => void
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
            <button
              key={conv.conversation_id}
              onClick={() => onLoadConversation(conv.conversation_id)}
              className="w-full text-left bg-black hover:bg-white/5 rounded-xl p-3 border border-white/5 hover:border-white/10 transition-all"
            >
              <div className="text-xs text-white/50 mb-1">
                {new Date(conv.updated_at).toLocaleString()}
              </div>
              <div className="text-sm text-white/90 line-clamp-2">
                {conv.last_content.length > 100
                  ? conv.last_content.substring(0, 100) + '...'
                  : conv.last_content}
              </div>
            </button>
          ))
        )}
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
  settingsDraft,
  setSettingsDraft,
  onSaveSettings,
  showHistory,
  setShowHistory,
}: {
  mode: Mode
  setMode: (m: Mode) => void
  messages: Msg[]
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
          <NavItem icon={Server} label="Models" active={mode === 'models'} onClick={() => setMode('models')} />
        </div>

        {/* Divider */}
        <div className="border-t border-white/5" />

        {/* History */}
        <div className="flex flex-col gap-px">
          <NavItem icon={Clock} label="History" active={showHistory} onClick={() => setShowHistory(true)} />
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

  // Track last spoken message to avoid re-speaking
  const lastSpokenMessageIdRef = useRef<string | null>(null)

  // Settings draft for new enterprise panel
  const [settingsDraft, setSettingsDraft] = useState<SettingsModelV2>(() => {
    const backendUrl = localStorage.getItem('homepilot_backend_url') || 'http://localhost:8000'
    const apiKey = localStorage.getItem('homepilot_api_key') || ''
    const providerChat = (localStorage.getItem('homepilot_provider_chat') || 'ollama') as string
    const providerImages = (localStorage.getItem('homepilot_provider_images') || 'ollama') as string
    const providerVideo = (localStorage.getItem('homepilot_provider_video') || 'ollama') as string
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
    setConversationId(uuid())
    setMessages([])
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
      const data = await getJson<{ ok: boolean; conversations: Conversation[] }>(
        settings.backendUrl,
        '/conversations',
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
        messages: Array<{ role: string; content: string; created_at: string }>
      }>(
        settings.backendUrl,
        `/conversations/${convId}/messages`,
        authHeaders
      )
      if (data.ok && data.messages) {
        setConversationId(convId)
        setMessages(
          data.messages.map((m, idx) => ({
            id: `loaded-${idx}`,
            role: m.role as 'user' | 'assistant',
            text: m.content,
          }))
        )
        setShowHistory(false)
      }
    } catch (err) {
      console.error('Failed to load conversation:', err)
    }
  }, [settings.backendUrl, authHeaders])

  // Fetch conversations when history panel is opened
  useEffect(() => {
    if (showHistory) {
      fetchConversations()
    }
  }, [showHistory, fetchConversations])

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

      // Get current project ID from localStorage if user selected one
      const currentProjectId = localStorage.getItem('homepilot_current_project') || undefined

      try {
        // Always call backend - it will route to the correct provider
        // If provider is 'ollama', backend will use Ollama with the provided base_url and model
        const data = await postJson<any>(
          settings.backendUrl,
          '/chat',
          {
            message: requestText,
            conversation_id: conversationId,
            project_id: currentProjectId, // Include project_id for dynamic prompts
            fun_mode: settings.funMode,
            mode,
            // Use Enterprise Settings V2 provider/model/base_url
            provider: settingsDraft.providerChat,
            provider_base_url: settingsDraft.baseUrlChat || undefined,
            provider_model: settingsDraft.modelChat,
            // Custom generation parameters (from settingsDraft)
            textTemperature: settingsDraft.textTemperature,
            textMaxTokens: settingsDraft.textMaxTokens,
            imgWidth: settingsDraft.imgWidth,
            imgHeight: settingsDraft.imgHeight,
            imgSteps: settingsDraft.imgSteps,
            imgCfg: settingsDraft.imgCfg,
            imgSeed: settingsDraft.imgSeed,
            imgModel: settingsDraft.modelImages,
            vidSeconds: settingsDraft.vidSeconds,
            vidFps: settingsDraft.vidFps,
            vidMotion: settingsDraft.vidMotion,
            vidModel: settingsDraft.modelVideo,
            nsfwMode: settingsDraft.nsfwMode,
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
      settingsDraft,
    ]
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

      // Speak the assistant's response
      window.SpeechService.speak(lastMessage.text)
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
              ? { ...m, pending: false, text: data.text ?? 'Done.', media: data.media ?? null }
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
              ? { ...msg, pending: false, text: data.text ?? 'Done.', media: data.media ?? null }
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
              ? { ...msg, pending: false, text: data.text ?? 'Done.', media: data.media ?? null }
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
            onClose={() => setShowHistory(false)}
          />
        )}

        {/* Top-right "Private" and Project Indicator */}
        <header className="absolute top-0 right-0 p-5 z-20 flex items-center gap-4">
          {/* Project Indicator */}
          {(() => {
            const currentProjectId = localStorage.getItem('homepilot_current_project')
            if (currentProjectId && mode === 'chat') {
              return (
                <div className="inline-flex items-center gap-2 bg-blue-600/20 text-blue-400 text-xs font-semibold px-4 py-2 rounded-full border border-blue-600/30">
                  <Folder size={12} />
                  <span>Project Mode</span>
                  <button
                    onClick={() => {
                      localStorage.removeItem('homepilot_current_project')
                      onNewConversation() // Start fresh conversation
                    }}
                    className="ml-1 p-0.5 hover:bg-blue-600/30 rounded-full transition-colors"
                    title="Exit project mode"
                  >
                    <X size={12} />
                  </button>
                </div>
              )
            }
            return null
          })()}

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

        {mode === 'voice' ? (
          <VoiceMode onSendText={(text) => sendTextOrIntent(text)} />
        ) : mode === 'project' ? (
          <ProjectsView
            backendUrl={settingsDraft.backendUrl}
            apiKey={settingsDraft.apiKey}
            onProjectSelect={(projectId) => {
              // When a project is selected, switch to chat mode with project context
              // Store project ID for later use in chat
              localStorage.setItem('homepilot_current_project', projectId)
              setMode('chat')
            }}
          />
        ) : mode === 'imagine' ? (
          <ImagineView
            backendUrl={settingsDraft.backendUrl}
            apiKey={settingsDraft.apiKey}
            providerImages={settingsDraft.providerImages}
            baseUrlImages={settingsDraft.baseUrlImages}
            modelImages={settingsDraft.modelImages}
            imgWidth={settingsDraft.imgWidth}
            imgHeight={settingsDraft.imgHeight}
            imgSteps={settingsDraft.imgSteps}
            imgCfg={settingsDraft.imgCfg}
            imgSeed={settingsDraft.imgSeed}
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
              input={input}
              setInput={setInput}
              fileInputRef={fileInputRef}
              canSend={canSend}
              onSend={onSend}
              onUpload={uploadAndSend}
            />
          )
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
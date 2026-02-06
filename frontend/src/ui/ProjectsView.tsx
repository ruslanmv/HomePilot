import React, { useState, useEffect, useRef } from 'react';
import {
  FolderKanban,
  Plus,
  BookOpen,
  Briefcase,
  StickyNote,
  Apple,
  X,
  UploadCloud,
  FileText,
  Sparkles,
  ChevronRight,
  Settings,
  Image as ImageIcon,
  Search,
  ArrowRight,
  MessageSquare,
  Film,
  Trash2,
  Edit,
  Bot,
} from 'lucide-react';

// --- Components ---

const ProjectCard = ({
  icon: Icon,
  iconColor,
  title,
  type,
  description,
  onClick,
  onDelete,
  onEdit,
  isExample,
}: {
  icon: React.ElementType
  iconColor: string
  title: string
  type: string
  description: string
  onClick: () => void
  onDelete?: () => void
  onEdit?: () => void
  isExample?: boolean
}) => (
  <div className="relative group">
    <div
      onClick={onClick}
      className="flex flex-col gap-3 p-5 rounded-2xl bg-white/5 hover:bg-white/10 transition-all duration-200 cursor-pointer border border-white/10 hover:border-white/20 h-full"
    >
      {/* Header */}
      <div className="flex justify-between items-start gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div
            className={`w-10 h-10 shrink-0 rounded-xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 border border-white/10 flex items-center justify-center ${iconColor}`}
          >
            <Icon size={18} strokeWidth={2} />
          </div>
          <h3 className="font-semibold text-base text-white truncate">{title}</h3>
        </div>

        {type ? (
          <span
            className={`shrink-0 text-xs px-2 py-0.5 rounded-full font-medium ${
              type === 'Template' || type === 'Example'
                ? 'bg-purple-500/20 text-purple-300'
                : type === 'Agent'
                ? 'bg-amber-500/20 text-amber-300'
                : type === 'Image'
                ? 'bg-fuchsia-500/20 text-fuchsia-300'
                : type === 'Video'
                ? 'bg-emerald-500/20 text-emerald-300'
                : 'bg-blue-500/20 text-blue-300'
            }`}
          >
            {type}
          </span>
        ) : null}
      </div>

      {/* Description */}
      <p className="text-sm text-white/60 leading-relaxed line-clamp-2">
        {description}
      </p>

      {/* Actions row (below content, no overlap with badge) */}
      {!isExample && (onDelete || onEdit) ? (
        <div className="mt-2 flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {onEdit ? (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onEdit()
              }}
              className="p-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-white transition-colors"
              title="Edit project"
            >
              <Edit size={14} />
            </button>
          ) : null}

          {onDelete ? (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onDelete()
              }}
              className="p-1.5 bg-red-500/20 hover:bg-red-500/40 rounded-lg text-red-400 hover:text-red-300 transition-colors"
              title="Delete project"
            >
              <Trash2 size={14} />
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  </div>
);

const TabButton = ({ active, label, onClick }: {
  active: boolean
  label: string
  onClick: () => void
}) => (
  <button
    onClick={onClick}
    className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
      active
        ? 'border-purple-500 text-white'
        : 'border-transparent text-white/50 hover:text-white/80 hover:border-white/20'
    }`}
  >
    {label}
  </button>
);

const FileUploadItem = ({ name, size, onRemove }: {
  name: string
  size: string
  onRemove?: () => void
}) => (
  <div className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/10 group">
    <div className="flex items-center gap-3">
      <div className="p-1.5 bg-purple-500/20 rounded-md text-purple-400">
        <FileText size={16} />
      </div>
      <div className="flex flex-col">
        <span className="text-sm text-white truncate max-w-[150px]">{name}</span>
        <span className="text-xs text-white/50">{size}</span>
      </div>
    </div>
    {onRemove && (
      <button
        onClick={onRemove}
        className="p-1 text-white/40 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
      >
        <X size={16} />
      </button>
    )}
  </div>
);

type AgentCapability = { id: string; label: string; description?: string }

const ProjectWizard = ({
  onClose,
  onSave,
  backendUrl,
  apiKey,
}: {
  onClose: () => void
  onSave: (data: any) => void
  backendUrl: string
  apiKey?: string
}) => {
  const [step, setStep] = useState(1)
  const [files, setFiles] = useState<Array<{ name: string; size: string; file?: File }>>([])
  const [projectName, setProjectName] = useState('')
  const [description, setDescription] = useState('')
  const [instructions, setInstructions] = useState('')
  const [projectType, setProjectType] = useState<'chat' | 'image' | 'video' | 'agent'>('chat')
  const fileInputRef = useRef<HTMLInputElement>(null)

  // --- Agent project settings (additive only) ---
  const [agentGoal, setAgentGoal] = useState('')
  const [agentCapabilities, setAgentCapabilities] = useState<string[]>([])
  const [agentAskBeforeActing, setAgentAskBeforeActing] = useState(true)
  const [agentExecutionProfile, setAgentExecutionProfile] = useState<'fast' | 'balanced' | 'quality'>('fast')

  // Dynamic capabilities from backend
  const [availableCapabilities, setAvailableCapabilities] = useState<AgentCapability[]>([])
  const [capabilitiesLoaded, setCapabilitiesLoaded] = useState(false)

  const totalSteps = projectType === 'agent' ? 4 : 2

  // Catalog: human labels only — no MCP/tool/agent IDs shown to user
  const capabilityCatalog: Array<{
    id: string
    label: string
    desc: string
    requiresHint: string
  }> = [
    {
      id: 'generate_images',
      label: 'Generate images',
      desc: 'Create images from text prompts.',
      requiresHint: 'Requires image generation tools to be installed.',
    },
    {
      id: 'generate_videos',
      label: 'Generate short videos',
      desc: 'Create short videos from prompts.',
      requiresHint: 'Requires video generation tools to be installed.',
    },
    {
      id: 'analyze_documents',
      label: 'Analyze documents',
      desc: 'Answer questions using uploaded files.',
      requiresHint: 'Requires document analysis tools to be installed.',
    },
    {
      id: 'automate_external',
      label: 'Automate external services',
      desc: 'Run actions across connected apps.',
      requiresHint: 'Requires automation tools to be installed.',
    },
  ]

  const availableSet = new Set(availableCapabilities.map((c) => c.id))

  const toggleCapability = (id: string) => {
    setAgentCapabilities((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  // Fetch dynamic capabilities (best-effort, graceful fallback)
  useEffect(() => {
    if (projectType !== 'agent') return
    if (capabilitiesLoaded) return

    const run = async () => {
      try {
        const headers: Record<string, string> = {}
        if (apiKey) headers['x-api-key'] = apiKey

        const res = await fetch(`${backendUrl}/v1/agentic/capabilities`, { headers })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()

        const caps: AgentCapability[] = Array.isArray(data?.capabilities)
          ? data.capabilities
              .map((c: any) => ({
                id: String(c?.id || ''),
                label: String(c?.label || c?.id || ''),
                description: typeof c?.description === 'string' ? c.description : undefined,
              }))
              .filter((c: any) => c.id && c.label)
          : []

        setAvailableCapabilities(caps)
      } catch {
        // Degrade gracefully: show everything disabled
        setAvailableCapabilities([])
      } finally {
        setCapabilitiesLoaded(true)
      }
    }

    void run()
  }, [apiKey, backendUrl, capabilitiesLoaded, projectType])

  // Smart defaults: preselect capabilities that match the user's goal text
  useEffect(() => {
    if (projectType !== 'agent') return
    if (!capabilitiesLoaded) return
    if (agentCapabilities.length > 0) return

    const goalText = `${agentGoal} ${description} ${instructions}`.toLowerCase()
    const availIds = new Set(availableCapabilities.map((c) => c.id))
    const next: string[] = []

    if (
      (goalText.includes('image') || goalText.includes('logo') || goalText.includes('design') || goalText.includes('picture')) &&
      availIds.has('generate_images')
    )
      next.push('generate_images')
    if (
      (goalText.includes('video') || goalText.includes('animation') || goalText.includes('clip')) &&
      availIds.has('generate_videos')
    )
      next.push('generate_videos')

    setAgentCapabilities(next)
  }, [agentCapabilities.length, agentGoal, availableCapabilities, capabilitiesLoaded, description, instructions, projectType])

  // --- File handlers (unchanged) ---
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const droppedFiles = Array.from(e.dataTransfer.files)
    const newFiles = droppedFiles.map((f) => ({
      name: f.name,
      size: `${(f.size / 1024 / 1024).toFixed(2)} MB`,
      file: f,
    }))
    setFiles([...files, ...newFiles])
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const selectedFiles = Array.from(e.target.files)
      const newFiles = selectedFiles.map((f) => ({
        name: f.name,
        size: `${(f.size / 1024 / 1024).toFixed(2)} MB`,
        file: f,
      }))
      setFiles([...files, ...newFiles])
    }
  }

  const handleCreate = () => {
    const projectData: any = {
      name: projectName || 'Untitled Project',
      description,
      instructions,
      files: files,
      project_type: projectType,
    }

    // Agent metadata: human-level only, no tool IDs exposed
    if (projectType === 'agent') {
      projectData.agentic = {
        goal: agentGoal,
        capabilities: agentCapabilities,
        ask_before_acting: agentAskBeforeActing,
        execution_profile: agentExecutionProfile,
      }
    }

    onSave(projectData)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div
        className="w-full max-w-2xl bg-[#1a1a2e] rounded-2xl border border-white/10 shadow-2xl flex flex-col max-h-[90vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <div>
            <h2 className="text-lg font-semibold text-white">Create new project</h2>
            <p className="text-sm text-white/50">
              Step {step} of {totalSteps}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
          {/* STEP 1: Details */}
          {step === 1 && (
            <div className="space-y-6">
              {/* Project Type Selection */}
              <div className="space-y-3">
                <label className="block text-sm font-medium text-white/80 flex items-center gap-2">
                  <Sparkles size={14} className="text-purple-400" />
                  Project Type
                </label>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {[
                    { id: 'chat', icon: MessageSquare, label: 'Chat / LLM', desc: 'Custom AI assistant', color: 'blue' },
                    { id: 'image', icon: ImageIcon, label: 'Image', desc: 'Image generation', color: 'purple' },
                    { id: 'video', icon: Film, label: 'Video', desc: 'Video generation', color: 'green' },
                    { id: 'agent', icon: Bot, label: 'Agent', desc: 'Advanced help with tools', color: 'amber' },
                  ].map((type) => (
                    <button
                      key={type.id}
                      type="button"
                      onClick={() => {
                        setProjectType(type.id as any)
                        setStep(1)
                      }}
                      className={`p-4 rounded-xl border-2 transition-all text-left ${
                        projectType === type.id
                          ? `border-${type.color}-500 bg-${type.color}-500/10`
                          : 'border-white/10 bg-white/5 hover:border-white/20'
                      }`}
                    >
                      <type.icon
                        size={24}
                        className={`mb-2 ${projectType === type.id ? `text-${type.color}-400` : 'text-white/50'}`}
                      />
                      <div className="text-sm font-medium text-white">{type.label}</div>
                      <div className="text-xs text-white/50 mt-1">{type.desc}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Project Name & Description */}
              <div className="space-y-3">
                <label className="block text-sm font-medium text-white/80">Project Details</label>
                <input
                  type="text"
                  placeholder="Project Name"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-white/40 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 transition-all"
                />
                <input
                  type="text"
                  placeholder="Short description (optional)"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder-white/40 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 transition-all"
                />
              </div>

              {/* Agent Goal (only for Agent type) */}
              {projectType === 'agent' && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-white/80 flex items-center gap-2">
                      <Bot size={14} className="text-purple-400" />
                      Agent goal
                    </label>
                    <span className="text-xs text-white/40">What is this agent for?</span>
                  </div>
                  <textarea
                    value={agentGoal}
                    onChange={(e) => setAgentGoal(e.target.value)}
                    className="w-full h-24 bg-white/5 border border-white/10 rounded-xl p-4 text-sm text-white placeholder-white/40 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 transition-all resize-none"
                    placeholder="E.g., Help me create marketing assets, summarize documents, and generate short videos for social media."
                  />
                </div>
              )}

              {/* Custom Instructions */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <label className="text-sm font-medium text-white/80 flex items-center gap-2">
                    <Sparkles size={14} className="text-purple-400" />
                    Custom Instructions
                  </label>
                  <span className="text-xs text-white/40">How should HomePilot behave?</span>
                </div>

                <textarea
                  value={instructions}
                  onChange={(e) => setInstructions(e.target.value)}
                  className="w-full h-32 bg-white/5 border border-white/10 rounded-xl p-4 text-sm text-white placeholder-white/40 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 transition-all resize-none"
                  placeholder={
                    projectType === 'chat'
                      ? 'E.g., You are an expert Python developer. Always prefer functional programming patterns...'
                      : projectType === 'image'
                      ? 'E.g., Generate images in a cyberpunk art style with neon colors...'
                      : projectType === 'video'
                      ? 'E.g., Create cinematic videos with smooth camera movements...'
                      : 'E.g., Be concise, ask clarifying questions, and use available capabilities when needed.'
                  }
                />
              </div>
            </div>
          )}

          {/* STEP 2 (Agent only): Capabilities + Behavior */}
          {step === 2 && projectType === 'agent' && (
            <div className="space-y-6">
              {/* Capabilities */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <label className="block text-sm font-medium text-white/80">Capabilities</label>
                  <span className="text-xs text-white/40">Choose what this agent can do</span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {capabilityCatalog.map((cap) => {
                    const available = availableSet.has(cap.id)
                    const checked = agentCapabilities.includes(cap.id)
                    return (
                      <button
                        key={cap.id}
                        type="button"
                        disabled={!available}
                        onClick={() => (available ? toggleCapability(cap.id) : undefined)}
                        title={!available ? cap.requiresHint : ''}
                        className={`p-4 rounded-xl border text-left transition-all ${
                          available
                            ? checked
                              ? 'border-purple-500/60 bg-purple-500/10'
                              : 'border-white/10 bg-white/5 hover:border-white/20 hover:bg-white/10'
                            : 'border-white/5 bg-white/[0.03] opacity-50 cursor-not-allowed'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-sm font-semibold text-white">{cap.label}</div>
                            <div className="text-xs text-white/50 mt-1">{cap.desc}</div>
                          </div>

                          <div
                            className={`h-5 w-5 rounded-md border flex items-center justify-center ${
                              checked ? 'border-purple-400 bg-purple-500/20' : 'border-white/20 bg-white/5'
                            }`}
                          >
                            {checked ? <span className="text-purple-300 text-xs">&#10003;</span> : null}
                          </div>
                        </div>

                        {!available && (
                          <div className="mt-2 text-[11px] text-white/45">Not available in this installation</div>
                        )}
                      </button>
                    )
                  })}
                </div>

                {/* Trust-building badges (read-only) */}
                <div className="mt-4 rounded-xl border border-white/10 bg-white/5 p-4">
                  <div className="text-xs font-semibold text-white/70">This assistant can:</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {agentCapabilities.length === 0 ? (
                      <span className="text-xs text-white/45">No capabilities selected yet.</span>
                    ) : (
                      agentCapabilities.map((id) => {
                        const label = capabilityCatalog.find((c) => c.id === id)?.label || id
                        return (
                          <span
                            key={id}
                            className="text-xs px-2 py-1 rounded-full bg-white/10 border border-white/10 text-white/80"
                          >
                            {label}
                          </span>
                        )
                      })
                    )}
                  </div>
                  <div className="mt-2 text-[11px] text-white/40">
                    Why? This workspace enables capabilities through advanced tools.
                  </div>
                </div>
              </div>

              {/* Behavior */}
              <div className="space-y-3">
                <label className="block text-sm font-medium text-white/80">Behavior</label>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                    <div className="text-sm font-semibold text-white">Execution style</div>
                    <div className="text-xs text-white/50 mt-1">Speed vs quality preference.</div>

                    <div className="mt-3 grid grid-cols-3 gap-2">
                      {(['fast', 'balanced', 'quality'] as const).map((p) => {
                        const active = agentExecutionProfile === p
                        return (
                          <button
                            key={p}
                            type="button"
                            onClick={() => setAgentExecutionProfile(p)}
                            className={`px-3 py-2 rounded-xl text-xs font-semibold border transition-all ${
                              active
                                ? 'bg-white/15 border-white/25 text-white'
                                : 'bg-white/5 border-white/10 text-white/70 hover:bg-white/10 hover:border-white/15'
                            }`}
                          >
                            {p === 'fast' ? 'Fast' : p === 'balanced' ? 'Balanced' : 'Quality'}
                          </button>
                        )
                      })}
                    </div>
                  </div>

                  <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                    <div className="text-sm font-semibold text-white">Confirmation</div>
                    <div className="text-xs text-white/50 mt-1">Ask before running advanced actions.</div>

                    <div className="mt-3 flex items-center justify-between">
                      <div className="text-xs text-white/70">Ask first</div>
                      <button
                        type="button"
                        onClick={() => setAgentAskBeforeActing((v) => !v)}
                        className={`w-10 h-6 rounded-full border transition-all relative ${
                          agentAskBeforeActing ? 'bg-white/20 border-white/25' : 'bg-white/5 border-white/10'
                        }`}
                        aria-pressed={agentAskBeforeActing}
                      >
                        <span
                          className={`absolute top-1/2 -translate-y-1/2 w-4 h-4 rounded-full transition-all ${
                            agentAskBeforeActing ? 'left-[22px] bg-white/80' : 'left-[4px] bg-white/40'
                          }`}
                        />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Knowledge base (Step 2 for non-agent, Step 3 for agent) */}
          {((step === 2 && projectType !== 'agent') || (step === 3 && projectType === 'agent')) && (
            <div className="space-y-6">
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <label className="text-sm font-medium text-white/80">Knowledge Base</label>
                  <span className="text-xs text-white/40">PDF, TXT, MD supported</span>
                </div>

                <div
                  className="w-full h-32 border-2 border-dashed border-white/10 rounded-xl bg-white/5 flex flex-col items-center justify-center gap-2 cursor-pointer hover:border-purple-500/50 hover:bg-white/10 transition-all"
                  onClick={() => fileInputRef.current?.click()}
                  onDrop={handleDrop}
                  onDragOver={(e) => e.preventDefault()}
                >
                  <div className="p-3 bg-purple-500/20 rounded-full text-purple-400">
                    <UploadCloud size={24} />
                  </div>
                  <p className="text-sm text-white/60">Click to upload or drag & drop</p>
                </div>

                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept=".pdf,.txt,.md"
                  onChange={handleFileSelect}
                  className="hidden"
                />

                {files.length > 0 && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-4">
                    {files.map((f, i) => (
                      <FileUploadItem
                        key={i}
                        name={f.name}
                        size={f.size}
                        onRemove={() => setFiles(files.filter((_, idx) => idx !== i))}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Step 4 (Agent only): Review */}
          {step === 4 && projectType === 'agent' && (
            <div className="space-y-6">
              <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
                <div className="text-sm font-semibold text-white">Review</div>
                <div className="text-xs text-white/50 mt-1">A quick summary of this agent project.</div>

                <div className="mt-4 space-y-3 text-sm text-white/80">
                  <div>
                    <span className="text-white/50">Goal:</span>{' '}
                    {agentGoal || <span className="text-white/40">(not set)</span>}
                  </div>

                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-white/50">Capabilities:</span>
                    {agentCapabilities.length === 0 ? (
                      <span className="text-white/40">None selected</span>
                    ) : (
                      agentCapabilities.map((id) => (
                        <span
                          key={id}
                          className="text-xs px-2 py-1 rounded-full bg-white/10 border border-white/10 text-white/80"
                        >
                          {capabilityCatalog.find((c) => c.id === id)?.label || id}
                        </span>
                      ))
                    )}
                  </div>

                  <div>
                    <span className="text-white/50">Execution style:</span>{' '}
                    {agentExecutionProfile === 'fast'
                      ? 'Fast'
                      : agentExecutionProfile === 'balanced'
                      ? 'Balanced'
                      : 'Quality'}
                  </div>

                  <div>
                    <span className="text-white/50">Confirmation:</span>{' '}
                    {agentAskBeforeActing ? 'Ask first' : 'Auto'}
                  </div>
                </div>

                <div className="mt-4 text-[11px] text-white/40">
                  Capabilities are based on installed advanced tools and may change over time. If a capability becomes
                  unavailable, the agent will fall back gracefully.
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-white/10 bg-[#1a1a2e] flex justify-end gap-3">
          {step > 1 && (
            <button
              onClick={() => setStep((s) => Math.max(1, s - 1))}
              className="px-4 py-2 text-sm font-medium text-white/60 hover:text-white transition-colors"
            >
              Back
            </button>
          )}

          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-white/60 hover:text-white transition-colors"
          >
            Cancel
          </button>

          <button
            onClick={() => {
              if (step < totalSteps) {
                setStep((s) => Math.min(totalSteps, s + 1))
              } else {
                handleCreate()
              }
            }}
            className="px-6 py-2 bg-purple-500 hover:bg-purple-600 text-white text-sm font-semibold rounded-full transition-colors flex items-center gap-2"
          >
            {step < totalSteps ? (
              <>
                {projectType === 'agent' && step === totalSteps - 1 ? 'Review' : 'Next'} <ChevronRight size={16} />
              </>
            ) : (
              'Create Project'
            )}
          </button>
        </div>
      </div>
    </div>
  )
};

// --- Edit Project Modal Component ---
const EditProjectModal = ({ project, onClose, onSave, backendUrl, apiKey }: {
  project: any
  onClose: () => void
  onSave: (project: any) => void
  backendUrl: string
  apiKey?: string
}) => {
  const [projectName, setProjectName] = useState(project?.name || '');
  const [description, setDescription] = useState(project?.description || '');
  const [instructions, setInstructions] = useState(project?.instructions || '');
  const [documents, setDocuments] = useState<any[]>(project?.files || []);
  const [isLoading, setIsLoading] = useState(false);

  const handleSave = async () => {
    setIsLoading(true);
    try {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json'
      };
      if (apiKey) {
        headers['x-api-key'] = apiKey;
      }

      const response = await fetch(`${backendUrl}/projects/${project.id}`, {
        method: 'PUT',
        headers,
        body: JSON.stringify({
          name: projectName,
          description,
          instructions
        })
      });

      if (response.ok) {
        const result = await response.json();
        onSave(result.project);
        onClose();
      } else {
        alert('Failed to update project');
      }
    } catch (error) {
      console.error('Error updating project:', error);
      alert('Failed to update project');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDeleteDocument = async (documentName: string) => {
    if (!confirm(`Delete document "${documentName}"?`)) {
      return;
    }

    try {
      const headers: Record<string, string> = {};
      if (apiKey) {
        headers['x-api-key'] = apiKey;
      }

      const response = await fetch(`${backendUrl}/projects/${project.id}/documents/${encodeURIComponent(documentName)}`, {
        method: 'DELETE',
        headers
      });

      if (response.ok) {
        setDocuments(documents.filter(d => d.name !== documentName));
      } else {
        alert('Failed to delete document');
      }
    } catch (error) {
      console.error('Error deleting document:', error);
      alert('Failed to delete document');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div
        className="w-full max-w-2xl bg-[#1a1a2e] rounded-2xl border border-white/10 shadow-2xl flex flex-col max-h-[90vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <div>
            <h2 className="text-lg font-semibold text-white">Edit Project</h2>
            <p className="text-sm text-white/50">Update project details and manage documents</p>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 custom-scrollbar space-y-6">
          {/* Project Name */}
          <div className="space-y-2">
            <label className="block text-sm font-medium text-white/80">Project Name</label>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-white/40 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 transition-all"
            />
          </div>

          {/* Description */}
          <div className="space-y-2">
            <label className="block text-sm font-medium text-white/80">Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder-white/40 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 transition-all"
            />
          </div>

          {/* Custom Instructions */}
          <div className="space-y-2">
            <label className="block text-sm font-medium text-white/80">Custom Instructions</label>
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              className="w-full h-32 bg-white/5 border border-white/10 rounded-xl p-4 text-sm text-white placeholder-white/40 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 transition-all resize-none"
              placeholder="How should HomePilot behave in this project?"
            />
          </div>

          {/* Documents */}
          <div className="space-y-2">
            <label className="block text-sm font-medium text-white/80">Documents ({documents.length})</label>
            {documents.length === 0 ? (
              <div className="text-sm text-white/40 p-4 border border-white/10 rounded-xl bg-white/5">
                No documents uploaded yet
              </div>
            ) : (
              <div className="space-y-2">
                {documents.map((doc, i) => (
                  <div key={i} className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/10 group">
                    <div className="flex items-center gap-3">
                      <div className="p-1.5 bg-purple-500/20 rounded-md text-purple-400">
                        <FileText size={16} />
                      </div>
                      <div className="flex flex-col">
                        <span className="text-sm text-white truncate max-w-[200px]">{doc.name}</span>
                        <span className="text-xs text-white/40">{doc.size} • {doc.chunks || 0} chunks</span>
                      </div>
                    </div>
                    <button
                      onClick={() => handleDeleteDocument(doc.name)}
                      className="p-1.5 text-white/40 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity rounded-lg hover:bg-red-500/10"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-white/10 bg-[#1a1a2e] flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-white/60 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={isLoading}
            className="px-6 py-2 bg-purple-500 hover:bg-purple-600 text-white text-sm font-semibold rounded-full transition-colors disabled:opacity-50"
          >
            {isLoading ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
};

// --- Search Modal Component ---
const SearchModal = ({ onClose, projects, exampleProjects, onSelectProject, onCreateFromExample }: {
  onClose: () => void
  projects: any[]
  exampleProjects: any[]
  onSelectProject?: (projectId: string) => void
  onCreateFromExample?: (exampleId: string) => void
}) => {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const iconMap: Record<string, React.ElementType> = {
    BookOpen,
    Briefcase,
    StickyNote,
    Apple,
    FolderKanban
  };

  React.useEffect(() => {
    inputRef.current?.focus();
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const allItems = [
    ...projects.map(p => ({ ...p, type: 'project', icon: 'FolderKanban', icon_color: 'text-purple-400' })),
    ...exampleProjects.map(e => ({ ...e, type: 'example' }))
  ];

  const filteredItems = query
    ? allItems.filter(item =>
        item.name.toLowerCase().includes(query.toLowerCase()) ||
        item.description?.toLowerCase().includes(query.toLowerCase())
      )
    : allItems;

  const handleItemClick = (item: any) => {
    if (item.type === 'example' && onCreateFromExample) {
      onCreateFromExample(item.id);
    } else if (item.type === 'project' && onSelectProject) {
      onSelectProject(item.id);
    }
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center pt-[15vh] px-4 bg-black/80 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl bg-[#1a1a2e] rounded-2xl border border-white/10 shadow-2xl flex flex-col overflow-hidden animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search Input Header */}
        <div className="flex items-center gap-3 px-4 py-4 border-b border-white/10">
          <Search size={20} className="text-white/50" />
          <input
            ref={inputRef}
            type="text"
            placeholder="Search projects..."
            className="flex-1 bg-transparent text-lg text-white placeholder-white/40 focus:outline-none"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button
            onClick={onClose}
            className="p-1 text-white/40 hover:text-white bg-white/10 rounded-md text-xs font-medium px-2 py-1 transition-colors"
          >
            ESC
          </button>
        </div>

        {/* Results List */}
        <div className="max-h-[60vh] overflow-y-auto custom-scrollbar p-2">
          {filteredItems.length > 0 ? (
            <div className="space-y-1">
              {query && <div className="px-3 py-2 text-xs font-semibold text-white/40">Results ({filteredItems.length})</div>}
              {filteredItems.map((item) => {
                const IconComponent = iconMap[item.icon] || FolderKanban;
                return (
                  <div
                    key={item.id}
                    className="group flex items-center gap-4 p-3 rounded-xl hover:bg-white/10 cursor-pointer transition-colors"
                    onClick={() => handleItemClick(item)}
                  >
                    <div className={`p-2 rounded-lg bg-purple-500/20 ${item.icon_color || 'text-purple-400'}`}>
                      <IconComponent size={20} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <h4 className="text-sm font-medium text-white group-hover:text-white truncate">
                          {item.name}
                        </h4>
                        {item.type === 'example' && (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-300">Template</span>
                        )}
                      </div>
                      <p className="text-xs text-white/50 truncate">
                        {item.description || 'No description'}
                      </p>
                    </div>
                    <ArrowRight size={16} className="text-white/20 opacity-0 group-hover:opacity-100 -translate-x-2 group-hover:translate-x-0 transition-all" />
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="py-12 text-center text-white/50">
              <p>No projects found matching "{query}"</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default function ProjectsView({
  backendUrl,
  apiKey,
  onProjectSelect
}: {
  backendUrl: string
  apiKey?: string
  onProjectSelect?: (projectId: string) => void
}) {
  const [activeTab, setActiveTab] = useState('My Projects');
  const [showWizard, setShowWizard] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingProject, setEditingProject] = useState<any>(null);
  const [projects, setProjects] = useState<any[]>([]);
  const [exampleProjects, setExampleProjects] = useState<any[]>([]);
  const [isLoadingExamples, setIsLoadingExamples] = useState(false);

  const iconMap: Record<string, React.ElementType> = {
    BookOpen,
    Briefcase,
    StickyNote,
    Apple,
    FolderKanban
  };

  const prettyProjectType = (t: any) => {
    const v = String(t || '').toLowerCase()
    if (v === 'chat') return 'Chat / LLM'
    if (v === 'image') return 'Image'
    if (v === 'video') return 'Video'
    if (v === 'agent') return 'Agent'
    return t || 'Chat / LLM'
  }

  const handleDeleteProject = async (projectId: string, projectName: string) => {
    if (!confirm(`Delete project "${projectName}"? This will remove all associated data and documents.`)) {
      return
    }

    try {
      const headers: Record<string, string> = {};
      if (apiKey) {
        headers['x-api-key'] = apiKey;
      }

      const response = await fetch(`${backendUrl}/projects/${projectId}`, {
        method: 'DELETE',
        headers
      });

      if (response.ok) {
        setProjects(projects.filter(p => p.id !== projectId));
      } else {
        alert('Failed to delete project');
      }
    } catch (error) {
      console.error('Error deleting project:', error);
      alert('Failed to delete project');
    }
  };

  const handleEditProject = async (projectId: string) => {
    try {
      const headers: Record<string, string> = {};
      if (apiKey) {
        headers['x-api-key'] = apiKey;
      }

      const response = await fetch(`${backendUrl}/projects/${projectId}`, { headers });
      if (response.ok) {
        const result = await response.json();
        setEditingProject(result.project);
        setShowEditModal(true);
      }
    } catch (error) {
      console.error('Error fetching project:', error);
    }
  };

  const ExamplesGrid = () => (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {exampleProjects.map((example) => {
        const IconComponent = iconMap[example.icon] || FolderKanban;
        return (
          <ProjectCard
            key={example.id}
            icon={IconComponent}
            iconColor={example.icon_color || 'text-purple-400'}
            title={example.name}
            type="Template"
            description={example.description}
            onClick={() => handleCreateFromExample(example.id)}
            isExample={true}
          />
        );
      })}
    </div>
  );

  const handleCreateFromExample = async (exampleId: string) => {
    try {
      const headers: Record<string, string> = {};
      if (apiKey) {
        headers['x-api-key'] = apiKey;
      }

      const response = await fetch(`${backendUrl}/projects/from-example/${exampleId}`, {
        method: 'POST',
        headers
      });

      if (response.ok) {
        const result = await response.json();
        setProjects([result.project, ...projects]);
        setActiveTab('My Projects');
        onProjectSelect?.(result.project.id);
      } else {
        console.error('Failed to create project from example');
      }
    } catch (error) {
      console.error('Error creating project from example:', error);
    }
  };

  const uploadFilesToProject = async (projectId: string, files: File[]) => {
    const headers: Record<string, string> = {};
    if (apiKey) {
      headers['x-api-key'] = apiKey;
    }

    for (const file of files) {
      try {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch(`${backendUrl}/projects/${projectId}/upload`, {
          method: 'POST',
          headers,
          body: formData
        });

        if (!response.ok) {
          console.error(`Failed to upload file: ${file.name}`);
        }
      } catch (error) {
        console.error(`Error uploading file ${file.name}:`, error);
      }
    }
  };

  const handleSaveProject = async (projectData: any) => {
    try {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json'
      };
      if (apiKey) {
        headers['x-api-key'] = apiKey;
      }

      const files = projectData.files || [];
      const projectDataWithoutFiles = {
        ...projectData,
        files: files.map((f: any) => ({ name: f.name, size: f.size }))
      };

      const response = await fetch(`${backendUrl}/projects`, {
        method: 'POST',
        headers,
        body: JSON.stringify(projectDataWithoutFiles)
      });

      if (response.ok) {
        const result = await response.json();
        setProjects([result.project, ...projects]);
        setShowWizard(false);

        const actualFiles = files.filter((f: any) => f.file).map((f: any) => f.file);
        if (actualFiles.length > 0) {
          await uploadFilesToProject(result.project.id, actualFiles);
        }

        onProjectSelect?.(result.project.id);
      } else {
        console.error('Failed to create project');
      }
    } catch (error) {
      console.error('Error creating project:', error);
    }
  };

  React.useEffect(() => {
    const loadProjects = async () => {
      try {
        const headers: Record<string, string> = {};
        if (apiKey) {
          headers['x-api-key'] = apiKey;
        }

        const response = await fetch(`${backendUrl}/projects`, { headers });
        if (response.ok) {
          const result = await response.json();
          setProjects(result.projects || []);
        }
      } catch (error) {
        console.error('Error loading projects:', error);
      }
    };
    loadProjects();
  }, [backendUrl, apiKey]);

  React.useEffect(() => {
    const loadExamples = async () => {
      setIsLoadingExamples(true);
      try {
        const headers: Record<string, string> = {};
        if (apiKey) {
          headers['x-api-key'] = apiKey;
        }

        const response = await fetch(`${backendUrl}/projects/examples`, { headers });
        if (response.ok) {
          const result = await response.json();
          setExampleProjects(result.examples || []);
        }
      } catch (error) {
        console.error('Error loading example projects:', error);
      } finally {
        setIsLoadingExamples(false);
      }
    };
    loadExamples();
  }, [backendUrl, apiKey]);

  return (
    <div className="h-full w-full bg-black text-white font-sans overflow-hidden flex flex-col">

      {/* Modals */}
      {showWizard && (
        <ProjectWizard
          onClose={() => setShowWizard(false)}
          onSave={handleSaveProject}
          backendUrl={backendUrl}
          apiKey={apiKey}
        />
      )}
      {showSearch && (
        <SearchModal
          onClose={() => setShowSearch(false)}
          projects={projects}
          exampleProjects={exampleProjects}
          onSelectProject={onProjectSelect}
          onCreateFromExample={handleCreateFromExample}
        />
      )}
      {showEditModal && editingProject && (
        <EditProjectModal
          project={editingProject}
          onClose={() => setShowEditModal(false)}
          onSave={(updatedProject) => {
            setProjects(projects.map(p => p.id === updatedProject.id ? updatedProject : p));
            setShowEditModal(false);
          }}
          backendUrl={backendUrl}
          apiKey={apiKey}
        />
      )}

      {/* Header */}
      <div className="flex justify-between items-center px-6 py-4 border-b border-white/10">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 border border-white/10 flex items-center justify-center">
            <FolderKanban size={18} className="text-purple-400" />
          </div>
          <div>
            <div className="text-sm font-semibold text-white leading-tight">HomePilot</div>
            <div className="text-xs text-white/50 leading-tight">Projects</div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowSearch(true)}
            className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-xl transition-colors"
            title="Search projects (Ctrl+K)"
          >
            <Search size={20} />
          </button>

          <button
            onClick={() => setShowWizard(true)}
            className="flex items-center gap-2 bg-purple-500 hover:bg-purple-600 px-4 py-2 rounded-full text-sm font-semibold transition-all"
          >
            <Plus size={16} />
            Create Project
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="px-6 border-b border-white/10">
        <div className="flex items-center gap-1">
          {['My Projects', 'Shared with me', 'Examples'].map(tab => (
            <TabButton key={tab} label={tab} active={activeTab === tab} onClick={() => setActiveTab(tab)} />
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {activeTab === 'My Projects' && (
          <>
            {projects.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-64 text-white/50">
                <FolderKanban size={48} className="mb-4 opacity-50" />
                <p className="text-lg font-semibold mb-2">No projects yet</p>
                <p className="text-sm text-white/40 mb-4">Create your first project to get started</p>
                <button
                  onClick={() => setShowWizard(true)}
                  className="flex items-center gap-2 bg-white/10 hover:bg-white/20 px-4 py-2 rounded-full text-sm font-medium transition-colors"
                >
                  <Plus size={16} />
                  New project
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {projects.map((project) => (
                  <ProjectCard
                    key={project.id}
                    icon={FolderKanban}
                    iconColor="text-purple-400"
                    title={project.name}
                    type={prettyProjectType(project.project_type)}
                    description={project.description || 'No description'}
                    onClick={() => onProjectSelect?.(project.id)}
                    onDelete={() => handleDeleteProject(project.id, project.name)}
                    onEdit={() => handleEditProject(project.id)}
                    isExample={false}
                  />
                ))}
              </div>
            )}

            {/* Show examples below My Projects */}
            {projects.length > 0 && exampleProjects.length > 0 && (
              <>
                <div className="text-xs font-semibold text-white/40 mt-8 mb-4">Template Projects</div>
                <ExamplesGrid />
              </>
            )}
          </>
        )}

        {activeTab === 'Shared with me' && (
          <div className="flex flex-col items-center justify-center h-64 text-white/50">
            <p className="text-sm">No projects have been shared with you yet.</p>
          </div>
        )}

        {activeTab === 'Examples' && <ExamplesGrid />}
      </div>

      <style>{`
        .line-clamp-2 {
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
      `}</style>
    </div>
  );
}

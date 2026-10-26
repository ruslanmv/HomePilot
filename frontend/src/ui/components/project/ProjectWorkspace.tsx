/**
 * Project Chat — the same chat as Home, plus the project's own context, kept out of the way.
 *
 *   ProjectSwitcher  the header pill "📁 <project> ▾": switch project, All projects, the
 *                    project's Files / Tasks / Instructions, settings, leave the project.
 *   ProjectLanding   an empty conversation: icon, name, "Ask anything about this project.",
 *                    the composer centred under it, and the three project tools. After the first
 *                    message the normal chat (composer at the bottom) takes its place.
 *   ProjectPanel     Files / Tasks / Instructions, one focused side sheet, opened on request.
 *
 * Files are the project's knowledge (/projects/{id}/documents, /upload); Tasks are a checklist
 * stored on the project whose open items the assistant sees; Instructions are the project's
 * own system instructions. Nothing here changes how messages, bubbles or the composer look.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  BookOpen, Check, ChevronDown, File as FileIcon, Folder, FolderOpen, ListChecks, Loader2,
  LogOut, Mic, Plus, Settings, Trash2, Upload, X,
} from 'lucide-react'
import AssistantFace from '../AssistantFace'
import { useAssistantAnimates } from '../../chatAppearance'

export type ProjectTool = 'files' | 'tasks' | 'instructions'

export type ProjectTask = { id: string; text: string; done: boolean }

export type WorkspaceProject = {
  id: string
  name: string
  description?: string
  instructions?: string
  project_type?: string
  is_default_assistant?: boolean
  files?: Array<{ name: string; size?: string; chunks?: number; source_type?: string }>
  tasks?: ProjectTask[]
}

/** Open a project tool from anywhere (the switcher, the landing, a shortcut). */
export const OPEN_PROJECT_TOOL_EVENT = 'homepilot:open-project-tool'

export function openProjectTool(tool: ProjectTool) {
  window.dispatchEvent(new CustomEvent(OPEN_PROJECT_TOOL_EVENT, { detail: { tool } }))
}

const TOOLS: Array<{ id: ProjectTool; label: string; Icon: typeof FileIcon }> = [
  { id: 'files', label: 'Files', Icon: FileIcon },
  { id: 'tasks', label: 'Tasks', Icon: ListChecks },
  { id: 'instructions', label: 'Instructions', Icon: BookOpen },
]

function base(backendUrl: string) {
  return (backendUrl || '').replace(/\/+$/, '')
}

// ── Landing ──────────────────────────────────────────────────────────────────

export function ProjectLanding({
  project,
  avatar,
  composer,
  extra,
}: {
  project: WorkspaceProject
  /** The project's own picture (personas), shown in place of the folder. */
  avatar?: React.ReactNode
  /** The chat composer, centred under the title while the conversation is empty. */
  composer: React.ReactNode
  /** Type-specific extras (Continue in Voice, agent intents), kept quiet under the tools. */
  extra?: React.ReactNode
}) {
  const animates = useAssistantAnimates()
  const subtitle = project.is_default_assistant
    ? 'Your assistant. Ask anything.'
    : project.description?.trim() || 'Ask anything about this project.'
  return (
    <div className="flex h-full w-full flex-col items-center justify-center px-4 pb-10">
      <div className="flex w-full max-w-3xl flex-col items-center">
        <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.04] text-white/80">
          {project.is_default_assistant ? (
            <AssistantFace size={44} animated={animates} />
          ) : avatar ? avatar : (
            <Folder size={26} strokeWidth={1.6} aria-hidden />
          )}
        </div>
        <h1 className="text-center text-[28px] font-semibold tracking-tight text-white sm:text-[32px]">{project.name}</h1>
        <p className="mt-1.5 line-clamp-2 max-w-xl text-center text-[15px] text-white/55">{subtitle}</p>

        <div className="mt-7 w-full">{composer}</div>

        <ProjectToolsRow className="mt-4" />
        {extra ? <div className="mt-5 w-full max-w-2xl">{extra}</div> : null}
      </div>
    </div>
  )
}

export function ProjectToolsRow({ className = '' }: { className?: string }) {
  return (
    <div className={`flex flex-wrap items-center justify-center gap-2 ${className}`}>
      {TOOLS.map(({ id, label, Icon }) => (
        <button
          key={id}
          type="button"
          onClick={() => openProjectTool(id)}
          className="inline-flex min-h-[40px] items-center gap-2 rounded-full border border-white/10 px-4 text-[14px] text-white/75 transition hover:border-white/20 hover:bg-white/[0.05] hover:text-white"
        >
          <Icon size={15} aria-hidden /> {label}
        </button>
      ))}
    </div>
  )
}

// ── Switcher (header pill) ───────────────────────────────────────────────────

type ProjectRow = { id: string; name: string; project_type?: string; is_default_assistant?: boolean; updated_at?: number }

export function ProjectSwitcher({
  project,
  avatar,
  backendUrl,
  headers,
  onSwitch,
  onAllProjects,
  onSettings,
  onLeave,
  onVoice,
  onSessions,
}: {
  project: WorkspaceProject
  avatar?: React.ReactNode
  backendUrl: string
  headers?: Record<string, string>
  onSwitch: (id: string) => void
  onAllProjects: () => void
  onSettings: () => void
  onLeave: () => void
  onVoice?: () => void
  onSessions?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [rows, setRows] = useState<ProjectRow[] | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    let alive = true
    fetch(`${base(backendUrl)}/projects`, { headers, credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!alive) return
        const list: ProjectRow[] = Array.isArray(d?.projects) ? d.projects : []
        list.sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0))
        setRows(list.filter((p) => p.id !== project.id).slice(0, 6))
      })
      .catch(() => { if (alive) setRows([]) })
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    window.addEventListener('keydown', onKey)
    return () => { alive = false; document.removeEventListener('mousedown', onDoc); window.removeEventListener('keydown', onKey) }
  }, [open, backendUrl, headers, project.id])

  const pick = (fn: () => void) => () => { setOpen(false); fn() }
  const item = 'flex w-full min-h-[38px] items-center gap-2.5 rounded-lg px-2.5 text-left text-[14px] text-white/80 hover:bg-white/[0.06] hover:text-white'

  return (
    <div ref={ref} className="pointer-events-auto relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex min-h-[38px] max-w-[min(60vw,320px)] items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] pl-3 pr-2.5 text-[14px] font-medium text-white/90 backdrop-blur transition hover:border-white/20 hover:bg-white/[0.07]"
      >
        {project.is_default_assistant ? (
          <AssistantFace size={18} animated={false} />
        ) : avatar ? avatar : <Folder size={15} className="shrink-0 text-white/70" aria-hidden />}
        <span className="truncate">{project.name}</span>
        <ChevronDown size={15} className={`shrink-0 text-white/50 transition ${open ? 'rotate-180' : ''}`} aria-hidden />
      </button>

      {open && (
        <div role="menu" className="absolute left-0 top-[calc(100%+6px)] z-50 w-[272px] rounded-2xl border border-white/10 bg-[#141418] p-1.5 shadow-2xl shadow-black/60">
          <div className="px-2.5 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wider text-white/35">This project</div>
          {TOOLS.map(({ id, label, Icon }) => (
            <button key={id} role="menuitem" type="button" className={item} onClick={pick(() => openProjectTool(id))}>
              <Icon size={15} className="text-white/55" aria-hidden /> {label}
            </button>
          ))}
          {onVoice ? (
            <button role="menuitem" type="button" className={item} onClick={pick(onVoice)}>
              <Mic size={15} className="text-white/55" aria-hidden /> Continue in Voice
            </button>
          ) : null}
          {onSessions ? (
            <button role="menuitem" type="button" className={item} onClick={pick(onSessions)}>
              <ListChecks size={15} className="text-white/55" aria-hidden /> Session Hub
            </button>
          ) : null}
          <button role="menuitem" type="button" className={item} onClick={pick(onSettings)}>
            <Settings size={15} className="text-white/55" aria-hidden /> Project settings
          </button>

          <div className="my-1.5 h-px bg-white/[0.07]" />
          <div className="px-2.5 pb-1 pt-0.5 text-[11px] font-semibold uppercase tracking-wider text-white/35">Switch to</div>
          {rows === null ? (
            <div className="flex items-center gap-2 px-2.5 py-2 text-[13px] text-white/40"><Loader2 size={14} className="animate-spin" /> Loading…</div>
          ) : rows.length === 0 ? (
            <div className="px-2.5 py-2 text-[13px] text-white/40">No other projects yet.</div>
          ) : rows.map((p) => (
            <button key={p.id} role="menuitem" type="button" className={item} onClick={pick(() => onSwitch(p.id))}>
              {p.is_default_assistant ? <AssistantFace size={15} animated={false} /> : <Folder size={15} className="text-white/45" aria-hidden />}
              <span className="truncate">{p.name}</span>
            </button>
          ))}
          <button role="menuitem" type="button" className={item} onClick={pick(onAllProjects)}>
            <FolderOpen size={15} className="text-white/55" aria-hidden /> All projects
          </button>

          <div className="my-1.5 h-px bg-white/[0.07]" />
          <button role="menuitem" type="button" className={item} onClick={pick(onLeave)}>
            <LogOut size={15} className="text-white/55" aria-hidden /> Leave project
          </button>
        </div>
      )}
    </div>
  )
}

// ── Panel (Files / Tasks / Instructions) ─────────────────────────────────────

export function ProjectPanel({
  project,
  tool,
  backendUrl,
  headers,
  onToolChange,
  onClose,
  onProjectChange,
}: {
  project: WorkspaceProject
  tool: ProjectTool
  backendUrl: string
  headers?: Record<string, string>
  onToolChange: (tool: ProjectTool) => void
  onClose: () => void
  /** The saved project fields, so the open chat uses them right away. */
  onProjectChange: (patch: Partial<WorkspaceProject>) => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-[70] flex justify-end bg-black/40 backdrop-blur-[2px]" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <aside role="dialog" aria-modal="true" aria-label={`${project.name} — ${tool}`}
        className="flex h-full w-full max-w-[420px] flex-col border-l border-white/10 bg-[#0f0f12] shadow-2xl">
        <div className="flex items-center gap-2 px-4 pb-2 pt-4">
          <div className="min-w-0 flex-1">
            <div className="truncate text-[12px] text-white/40">{project.name}</div>
          </div>
          <button type="button" onClick={onClose} aria-label="Close"
            className="flex h-9 w-9 items-center justify-center rounded-full text-white/50 hover:bg-white/[0.06] hover:text-white">
            <X size={18} />
          </button>
        </div>
        <div role="tablist" className="mx-4 flex gap-1 rounded-full border border-white/10 bg-white/[0.03] p-1">
          {TOOLS.map(({ id, label }) => (
            <button key={id} role="tab" type="button" aria-selected={tool === id} onClick={() => onToolChange(id)}
              className={`min-h-[34px] flex-1 rounded-full text-[13px] font-medium transition ${tool === id ? 'bg-white text-black' : 'text-white/60 hover:text-white'}`}>
              {label}
            </button>
          ))}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          {tool === 'files' ? <FilesTool project={project} backendUrl={backendUrl} headers={headers} onProjectChange={onProjectChange} /> : null}
          {tool === 'tasks' ? <TasksTool project={project} backendUrl={backendUrl} headers={headers} onProjectChange={onProjectChange} /> : null}
          {tool === 'instructions' ? <InstructionsTool project={project} backendUrl={backendUrl} headers={headers} onProjectChange={onProjectChange} /> : null}
        </div>
      </aside>
    </div>
  )
}

type ToolProps = {
  project: WorkspaceProject
  backendUrl: string
  headers?: Record<string, string>
  onProjectChange: (patch: Partial<WorkspaceProject>) => void
}

async function saveProject(backendUrl: string, headers: Record<string, string> | undefined, id: string, body: object) {
  const res = await fetch(`${base(backendUrl)}/projects/${encodeURIComponent(id)}`, {
    method: 'PUT', credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(headers || {}) },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
}

function FilesTool({ project, backendUrl, headers, onProjectChange }: ToolProps) {
  const [files, setFiles] = useState(project.files || [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${base(backendUrl)}/projects/${encodeURIComponent(project.id)}/documents`, { headers, credentials: 'include' })
      const d = await res.json()
      if (res.ok && Array.isArray(d.documents)) {
        setFiles(d.documents)
        onProjectChange({ files: d.documents })
      }
    } catch { /* keep what we have */ }
  }, [backendUrl, headers, project.id]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void load() }, [load])

  async function upload(list: FileList | null) {
    if (!list?.length) return
    setBusy(true)
    setError('')
    try {
      for (const f of Array.from(list)) {
        const form = new FormData()
        form.append('file', f)
        const res = await fetch(`${base(backendUrl)}/projects/${encodeURIComponent(project.id)}/upload`, {
          method: 'POST', body: form, headers, credentials: 'include',
        })
        if (!res.ok) {
          const d = await res.json().catch(() => ({}))
          throw new Error(d?.detail || d?.error || d?.message || `Could not add ${f.name}`)
        }
      }
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed.')
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  async function remove(name: string) {
    setBusy(true)
    try {
      await fetch(`${base(backendUrl)}/projects/${encodeURIComponent(project.id)}/documents/${encodeURIComponent(name)}`, {
        method: 'DELETE', headers, credentials: 'include',
      })
      await load()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-[13px] leading-relaxed text-white/50">Knowledge the assistant can use in every chat of this project.</p>
      <button type="button" disabled={busy} onClick={() => input.current?.click()}
        className="flex min-h-[88px] w-full flex-col items-center justify-center gap-1.5 rounded-2xl border border-dashed border-white/15 text-[14px] text-white/70 hover:border-white/30 hover:bg-white/[0.03] disabled:opacity-60">
        {busy ? <Loader2 size={18} className="animate-spin" /> : <Upload size={18} aria-hidden />}
        {busy ? 'Adding…' : 'Add files'}
        <span className="text-[12px] text-white/35">PDF, TXT, MD, DOCX, XLSX or images</span>
      </button>
      <input ref={input} type="file" multiple hidden
        accept=".pdf,.txt,.md,.docx,.xlsx,.png,.jpg,.jpeg,.webp,.gif,.bmp"
        onChange={(e) => { void upload(e.target.files) }} />
      {error ? <p role="alert" className="text-[13px] text-red-300">{error}</p> : null}
      {files.length ? (
        <ul className="divide-y divide-white/[0.06] overflow-hidden rounded-2xl border border-white/[0.06]">
          {files.map((f) => (
            <li key={f.name} className="flex items-center gap-3 px-3.5 py-3">
              <FileIcon size={16} className="shrink-0 text-white/45" aria-hidden />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[14px] text-white/85">{f.name}</div>
                <div className="text-[12px] text-white/35">{[f.size, f.chunks ? `${f.chunks} chunks` : ''].filter(Boolean).join(' · ')}</div>
              </div>
              <button type="button" onClick={() => { void remove(f.name) }} aria-label={`Remove ${f.name}`}
                className="flex h-8 w-8 items-center justify-center rounded-full text-white/35 hover:bg-white/[0.06] hover:text-red-300">
                <Trash2 size={15} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-center text-[13px] text-white/35">No files yet.</p>
      )}
    </div>
  )
}

function newId() {
  try { return crypto.randomUUID().slice(0, 12) } catch { return Math.random().toString(36).slice(2, 14) }
}

function TasksTool({ project, backendUrl, headers, onProjectChange }: ToolProps) {
  const [tasks, setTasks] = useState<ProjectTask[]>(project.tasks || [])
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')

  // The list on the server is the truth; read it when the panel opens.
  useEffect(() => {
    let alive = true
    fetch(`${base(backendUrl)}/projects/${encodeURIComponent(project.id)}`, { headers, credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (alive && Array.isArray(d?.project?.tasks)) setTasks(d.project.tasks) })
      .catch(() => { /* keep local */ })
    return () => { alive = false }
  }, [backendUrl, headers, project.id])

  async function commit(next: ProjectTask[]) {
    const before = tasks
    setTasks(next)
    setError('')
    try {
      await saveProject(backendUrl, headers, project.id, { tasks: next })
      onProjectChange({ tasks: next })
    } catch {
      setTasks(before)
      setError('Could not save. Check the connection to HomePilot.')
    }
  }

  const open = tasks.filter((t) => !t.done)
  const done = tasks.filter((t) => t.done)

  return (
    <div className="space-y-4">
      <p className="text-[13px] leading-relaxed text-white/50">The assistant sees the open tasks and can help you finish them.</p>
      <form className="flex gap-2" onSubmit={(e) => {
        e.preventDefault()
        const text = draft.trim()
        if (!text) return
        setDraft('')
        void commit([...tasks, { id: newId(), text, done: false }])
      }}>
        <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Add a task…" aria-label="New task"
          className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-2.5 text-[15px] text-white outline-none placeholder:text-white/30 focus:border-white/25" />
        <button type="submit" disabled={!draft.trim()} aria-label="Add task"
          className="flex h-[44px] w-[44px] items-center justify-center rounded-xl bg-white text-black disabled:opacity-30">
          <Plus size={18} />
        </button>
      </form>
      {error ? <p role="alert" className="text-[13px] text-red-300">{error}</p> : null}
      {[...open, ...done].length ? (
        <ul className="space-y-1">
          {[...open, ...done].map((t) => (
            <li key={t.id} className="group flex items-center gap-3 rounded-xl px-2 py-2 hover:bg-white/[0.03]">
              <button type="button" role="checkbox" aria-checked={t.done} aria-label={t.text}
                onClick={() => { void commit(tasks.map((x) => (x.id === t.id ? { ...x, done: !x.done } : x))) }}
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition ${t.done ? 'border-white bg-white text-black' : 'border-white/25 hover:border-white/50'}`}>
                {t.done ? <Check size={13} strokeWidth={3} /> : null}
              </button>
              <span className={`min-w-0 flex-1 text-[14px] ${t.done ? 'text-white/35 line-through' : 'text-white/85'}`}>{t.text}</span>
              <button type="button" aria-label={`Delete ${t.text}`}
                onClick={() => { void commit(tasks.filter((x) => x.id !== t.id)) }}
                className="flex h-7 w-7 items-center justify-center rounded-full text-white/30 opacity-0 hover:text-red-300 focus:opacity-100 group-hover:opacity-100">
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-center text-[13px] text-white/35">No tasks yet.</p>
      )}
    </div>
  )
}

function InstructionsTool({ project, backendUrl, headers, onProjectChange }: ToolProps) {
  const [text, setText] = useState(project.instructions || '')
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const dirty = text !== (project.instructions || '')

  async function save() {
    setState('saving')
    try {
      await saveProject(backendUrl, headers, project.id, { instructions: text })
      onProjectChange({ instructions: text })
      setState('saved')
    } catch {
      setState('error')
    }
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <p className="text-[13px] leading-relaxed text-white/50">How the assistant should work in this project: tone, goals, what to always or never do.</p>
      <textarea value={text} onChange={(e) => { setText(e.target.value); setState('idle') }}
        aria-label="Project instructions"
        placeholder="e.g. Answer as a senior 3D engineer. Prefer three.js examples. Keep answers short."
        className="min-h-[260px] flex-1 resize-none rounded-2xl border border-white/10 bg-white/[0.03] p-3.5 text-[15px] leading-relaxed text-white outline-none placeholder:text-white/25 focus:border-white/25" />
      <div className="flex items-center gap-3">
        <button type="button" disabled={!dirty || state === 'saving'} onClick={() => { void save() }}
          className="flex min-h-[42px] items-center gap-2 rounded-full bg-white px-5 text-[14px] font-semibold text-black disabled:opacity-30">
          {state === 'saving' ? <Loader2 size={15} className="animate-spin" /> : null} Save
        </button>
        <span className="text-[13px] text-white/45" aria-live="polite">
          {state === 'saved' ? 'Saved' : state === 'error' ? 'Could not save' : dirty ? 'Unsaved changes' : ''}
        </span>
      </div>
    </div>
  )
}

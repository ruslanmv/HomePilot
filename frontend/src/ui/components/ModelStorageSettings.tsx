/**
 * ModelStorageSettings — where ComfyUI models (image, video, edit, upscale, LoRA) are stored.
 *
 * The built-in folder (models/comfy) is always kept and never changed. Extra locations, such as
 * an external drive (E:\homepilot-models), can be added, and one of them chosen for new
 * downloads. Backend: GET/PUT /v1/models/storage (backend/app/model_storage.py).
 */
import React, { useCallback, useEffect, useState } from 'react'
import { authFetch } from '../lib/authFetch'
import { resolveBackendUrl } from '../lib/backendUrl'

export type StorageLocation = {
  path: string
  display_path: string
  label: string
  builtin: boolean
  exists: boolean
  writable: boolean
  is_download_target: boolean
  free_gb: number | null
  total_gb: number | null
  model_files: number | null
}

type StorageStatus = {
  locations: StorageLocation[]
  download_target: string
  download_target_fallback: boolean
  restart_note: string
}

function endpoint(): string {
  return `${resolveBackendUrl()}/v1/models/storage`
}

export default function ModelStorageSettings() {
  const [status, setStatus] = useState<StorageStatus | null>(null)
  const [newPath, setNewPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')

  const load = useCallback(async () => {
    try {
      const r = await authFetch(endpoint())
      const data = await r.json()
      if (!r.ok) throw new Error(data?.detail || `HTTP ${r.status}`)
      setStatus(data)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load model storage')
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const save = useCallback(async (locations: { path: string; label?: string }[], downloadTarget: string, message: string) => {
    setBusy(true)
    setError('')
    setSaved('')
    try {
      const r = await authFetch(endpoint(), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ locations, download_target: downloadTarget }),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data?.detail || `HTTP ${r.status}`)
      setStatus(data)
      setSaved(message)
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save')
      return false
    } finally {
      setBusy(false)
    }
  }, [])

  if (!status) {
    return <p className="text-xs text-white/45">{error || 'Loading model storage…'}</p>
  }

  const extras = status.locations.filter((l) => !l.builtin)
  const currentTarget = status.locations.find((l) => l.is_download_target)
  const targetValue = (l: StorageLocation) => (l.builtin ? 'builtin' : l.path)
  const extraList = (list: StorageLocation[]) => list.map((l) => ({ path: l.path, label: l.label }))

  const addLocation = async () => {
    const path = newPath.trim()
    if (!path) return
    const ok = await save([...extraList(extras), { path }],
      currentTarget ? targetValue(currentTarget) : 'builtin',
      `Added ${path}. ${status.restart_note}`)
    if (ok) setNewPath('')
  }

  const setTarget = (l: StorageLocation) =>
    save(extraList(extras), targetValue(l), `New downloads will go to ${l.display_path}.`)

  const remove = (l: StorageLocation) =>
    save(extraList(extras.filter((x) => x.path !== l.path)),
      l.is_download_target ? 'builtin' : (currentTarget ? targetValue(currentTarget) : 'builtin'),
      `Removed ${l.display_path} from the list. Its files were not deleted.`)

  return (
    <div className="space-y-3">
      <ul className="space-y-2" aria-label="Model storage locations">
        {status.locations.map((l) => (
          <li key={l.path} className="rounded-xl border border-white/[0.08] bg-white/[0.02] px-3 py-2.5">
            <div className="flex items-start justify-between gap-3">
              <label className="flex items-start gap-2.5 min-w-0 cursor-pointer">
                <input
                  type="radio"
                  name="model-download-target"
                  className="mt-1 accent-[#9b5cff]"
                  checked={l.is_download_target}
                  disabled={busy || !l.exists || !l.writable}
                  onChange={() => { void setTarget(l) }}
                  aria-label={`Use ${l.display_path} for new downloads`}
                />
                <span className="min-w-0">
                  <span className="block text-sm text-white/90 truncate">{l.label}</span>
                  <span className="block text-xs text-white/45 font-mono truncate">{l.display_path}</span>
                  <span className="block text-[11px] text-white/40 mt-0.5">
                    {!l.exists
                      ? 'Not available (drive not connected?) — skipped until it is back'
                      : `${l.free_gb ?? '?'} GB free of ${l.total_gb ?? '?'} GB · ${l.model_files ?? 0} model files`}
                    {l.is_download_target ? ' · default for new downloads' : ''}
                  </span>
                </span>
              </label>
              {!l.builtin && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => { void remove(l) }}
                  className="shrink-0 text-xs text-white/50 hover:text-white/85 px-2 py-1 rounded-lg hover:bg-white/5"
                >
                  Remove
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>

      <div className="flex gap-2">
        <input
          type="text"
          value={newPath}
          onChange={(e) => setNewPath(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') void addLocation() }}
          placeholder="Add a folder, e.g. E:\homepilot-models"
          aria-label="Folder to add as a model storage location"
          className="flex-1 min-w-0 h-9 rounded-lg bg-black/30 border border-white/10 px-3 text-sm text-white/90 placeholder:text-white/30 outline-none focus:border-[#9b5cff]/60"
        />
        <button
          type="button"
          disabled={busy || !newPath.trim()}
          onClick={() => { void addLocation() }}
          className="h-9 px-3 rounded-lg bg-[#9b5cff]/20 border border-[#9b5cff]/30 text-sm text-white/90 hover:bg-[#9b5cff]/30 disabled:opacity-50"
        >
          {busy ? 'Saving…' : 'Add'}
        </button>
      </div>

      {status.download_target_fallback && (
        <p className="text-xs text-amber-300/80" role="status">
          The chosen download location is not available right now, so new downloads go to the built-in folder.
        </p>
      )}
      {error && <p className="text-xs text-red-300/90" role="alert">{error}</p>}
      {saved && <p className="text-xs text-emerald-300/80" role="status">{saved}</p>}
      <p className="text-[11px] text-white/35 leading-relaxed">
        Existing models stay where they are. ComfyUI reads every location listed here; it picks up a
        new location after HomePilot restarts. Chat models (Ollama) are not affected.
      </p>
    </div>
  )
}

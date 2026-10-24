import React, { useCallback, useEffect, useState } from 'react'
import { hfSetupCopy, hfSuggestCopy, rememberHfChatModel, type HfSession } from '../lib/hfAccount'

const EMPTY: HfSession = {
  on_huggingface: false,
  oauth_configured: false,
  signed_in: false,
}

/**
 * Setup for the Hugging Face chat provider: sign in with the visitor's
 * account. No API key is typed into the browser.
 */
export default function HfAccountCard({
  backendUrl,
  onUseForChat,
  activeModel,
  variant = 'setup',
  providerChat = 'ollama',
}: {
  backendUrl: string
  onUseForChat?: (model: string) => void
  activeModel?: string
  variant?: 'setup' | 'suggest'
  providerChat?: string
}) {
  const base = (backendUrl || '').replace(/\/+$/, '')
  const [session, setSession] = useState<HfSession>(EMPTY)
  const [models, setModels] = useState<string[]>([])
  const [picked, setPicked] = useState(activeModel || '')
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async (): Promise<HfSession | null> => {
    try {
      const res = await fetch(`${base}/v1/hf/session`, { credentials: 'include' })
      if (!res.ok) return null
      const data = (await res.json()) as HfSession
      setSession(data)
      if (!data.on_huggingface || variant === 'suggest') return data
      const listed = await fetch(`${base}/models?provider=huggingface`, { credentials: 'include' })
      if (!listed.ok) return data
      const body = await listed.json()
      const names = Array.isArray(body.models) ? body.models.map(String) : []
      setModels(names)
      setPicked((current) => current || names[0] || '')
      return data
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reach Hugging Face sign-in.')
      return null
    }
  }, [base, variant])

  useEffect(() => {
    let stop = false
    let timer = 0
    const tick = async () => {
      const data = await refresh()
      if (stop || !data?.on_huggingface || data.signed_in) return
      timer = window.setTimeout(() => { void tick() }, 4000)
    }
    void tick()
    return () => {
      stop = true
      window.clearTimeout(timer)
    }
  }, [refresh])

  if (!session.on_huggingface) return null
  if (variant === 'suggest') {
    const line = hfSuggestCopy(session, providerChat)
    if (!line) return null
    return (
      <p className="text-xs leading-relaxed text-white/60">
        {line}{' '}
        <a href={`${base}/v1/hf/login`} target="_blank" rel="noopener noreferrer" className="font-semibold text-white underline">
          Sign in with Hugging Face
        </a>
      </p>
    )
  }
  const copy = hfSetupCopy(session)

  const useModel = () => {
    const model = picked || models[0]
    if (!model) return
    rememberHfChatModel(model)
    onUseForChat?.(model)
  }

  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 md:p-5 text-sm text-white/80">
      <div className="font-semibold text-white">{copy.title}</div>
      <p className="mt-2 text-xs leading-relaxed text-white/60">{copy.body}</p>
      {error ? <p className="mt-2 text-xs text-rose-300">{error}</p> : null}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {copy.showSignIn ? (
          <a
            href={`${base}/v1/hf/login`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-[40px] items-center rounded-xl bg-white px-4 text-sm font-semibold text-black"
          >
            Sign in with Hugging Face
          </a>
        ) : null}
        {copy.showSignOut ? (
          <button
            type="button"
            className="inline-flex min-h-[40px] items-center rounded-xl border border-white/15 px-4 text-sm font-semibold"
            onClick={() => {
              void fetch(`${base}/v1/hf/logout`, { method: 'POST', credentials: 'include' }).then(() => refresh())
            }}
          >
            Sign out
          </button>
        ) : null}
      </div>
      {session.signed_in && models.length > 0 ? (
        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center">
          <label className="text-[11px] font-bold uppercase tracking-wider text-white/50" htmlFor="hp-hf-model">
            Model
          </label>
          <select
            id="hp-hf-model"
            value={picked}
            onChange={(e) => setPicked(e.target.value)}
            className="min-h-[40px] flex-1 rounded-xl border border-white/10 bg-white/5 px-3 text-sm"
          >
            {models.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={useModel}
            className="inline-flex min-h-[40px] items-center rounded-xl bg-white px-4 text-sm font-semibold text-black"
          >
            Use for chat
          </button>
        </div>
      ) : null}
    </div>
  )
}

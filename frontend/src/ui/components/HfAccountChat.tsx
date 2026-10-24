/**
 * Hugging Face account chat, on a Space only.
 *
 * The backend advertises this when SPACE_ID is set. Sign-in opens the
 * Hugging Face login; the access token stays on the server. "Use for chat"
 * selects the provider. While chat is still on Ollama, the Space suggests
 * signing in and does not require an account.
 */
import React, { useCallback, useEffect, useState } from 'react'
import { resolveBackendUrl } from '../lib/backendUrl'

export type HfAccount = {
  space: boolean
  signed_in: boolean
  oauth_ready: boolean
  username: string | null
  default_model: string
  models: string[]
}

const EMPTY: HfAccount = {
  space: false,
  signed_in: false,
  oauth_ready: false,
  username: null,
  default_model: '',
  models: [],
}

const DISMISS_KEY = 'hp.hf.suggest.dismissed'

export function useHfAccount(backendUrl?: string): { account: HfAccount; reload: () => Promise<void> } {
  const [account, setAccount] = useState<HfAccount>(EMPTY)
  const reload = useCallback(async () => {
    try {
      const res = await fetch(`${resolveBackendUrl(backendUrl)}/v1/hf/account`, {
        credentials: 'include',
        cache: 'no-store',
      })
      if (!res.ok) {
        setAccount(EMPTY)
        return
      }
      const data = await res.json()
      setAccount({
        space: !!data.space,
        signed_in: !!data.signed_in,
        oauth_ready: !!data.oauth_ready,
        username: typeof data.username === 'string' && data.username ? data.username : null,
        default_model: typeof data.default_model === 'string' ? data.default_model : '',
        models: Array.isArray(data.models) ? data.models.filter((m: unknown) => typeof m === 'string') : [],
      })
    } catch {
      setAccount(EMPTY)
    }
  }, [backendUrl])

  useEffect(() => {
    void reload()
    const onFocus = () => { void reload() }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [reload])

  return { account, reload }
}

export function openHfLogin(backendUrl?: string) {
  const url = `${resolveBackendUrl(backendUrl)}/v1/hf/login`
  // The session cookie is first-party on the Space itself. Inside the
  // huggingface.co iframe, finish sign-in in a top-level tab.
  let framed = false
  try { framed = window.top !== window.self } catch { framed = true }
  if (framed) window.open(url, '_blank', 'noopener')
  else window.location.assign(url)
}

export function useHfForChat(model: string) {
  window.dispatchEvent(new CustomEvent('homepilot:use-hf-chat', { detail: { model } }))
}

function SignInButton({
  account,
  backendUrl,
  onNeedRebuild,
}: {
  account: HfAccount
  backendUrl?: string
  onNeedRebuild: (message: string) => void
}) {
  return (
    <button
      type="button"
      onClick={() => {
        if (!account.oauth_ready) {
          onNeedRebuild('Sign-in starts after this Space rebuilds. Until then, chat uses the local model.')
          return
        }
        openHfLogin(backendUrl)
      }}
      className="h-10 px-4 rounded-xl bg-white text-black text-sm font-semibold hover:bg-white/90"
    >
      Sign in with Hugging Face
    </button>
  )
}

/** Models → Chat and Settings, once Hugging Face (your account) is chosen. */
export function HfAccountSetup({
  backendUrl,
  active = false,
  activeModel = '',
}: {
  backendUrl?: string
  active?: boolean
  activeModel?: string
}) {
  const { account, reload } = useHfAccount(backendUrl)
  const [model, setModel] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const [applied, setApplied] = useState<string | null>(null)
  const models = account.models.length ? account.models : (account.default_model ? [account.default_model] : [])

  useEffect(() => {
    if (active && activeModel && (account.models.includes(activeModel) || activeModel === account.default_model)) {
      setModel(activeModel)
      return
    }
    setModel((current) => current || account.default_model)
  }, [active, activeModel, account.default_model, account.models])

  if (!account.space) return null

  const chosen = model || account.default_model
  const inUse = applied === chosen || (active && !!chosen && (!activeModel || activeModel === chosen))

  return (
    <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 md:p-5">
      <h3 className="text-sm font-semibold text-white">Hugging Face (your account)</h3>
      <p className="mt-1.5 text-[13px] leading-relaxed text-white/60">
        Sign in with your Hugging Face account. Chat then goes through Inference Providers
        and uses your free monthly credits or your Pro plan. The access token stays on the server.
        If you stay signed out, or the account cannot run a request, the reply comes from the local model.
      </p>

      {account.signed_in ? (
        <p className="mt-3 text-[13px] text-emerald-200/90">
          Signed in{account.username ? ` as ${account.username}` : ''}.
        </p>
      ) : (
        <div className="mt-3">
          <SignInButton account={account} backendUrl={backendUrl} onNeedRebuild={setNotice} />
        </div>
      )}

      {models.length > 0 && (
        <label className="mt-4 block">
          <span className="text-[11px] font-bold uppercase tracking-wider text-white/45">Model</span>
          <select
            className="mt-1.5 w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-white outline-none focus:border-white/30"
            value={chosen}
            onChange={(e) => setModel(e.target.value)}
          >
            {models.map((id) => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        </label>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => {
            if (!chosen) return
            useHfForChat(chosen)
            setApplied(chosen)
          }}
          disabled={!chosen}
          className={`h-10 px-4 rounded-xl text-sm font-semibold disabled:opacity-40 ${
            inUse
              ? 'bg-emerald-500/20 text-emerald-200 border border-emerald-500/30'
              : 'bg-white text-black hover:bg-white/90'
          }`}
        >
          {inUse ? 'Using for chat' : 'Use for chat'}
        </button>
        {account.signed_in && (
          <button
            type="button"
            onClick={async () => {
              await fetch(`${resolveBackendUrl(backendUrl)}/v1/hf/logout`, { method: 'POST', credentials: 'include' })
              setNotice(null)
              await reload()
            }}
            className="h-10 px-3 rounded-xl border border-white/10 bg-white/5 text-sm text-white/70 hover:text-white"
          >
            Sign out
          </button>
        )}
      </div>
      {notice ? <p className="mt-3 text-[12px] text-amber-200/90">{notice}</p> : null}
    </section>
  )
}

/** Shown while the Space is still on the local model. Hidden off a Space. */
export function HfOllamaSuggestion({
  backendUrl,
  providerChat,
  className = '',
}: {
  backendUrl?: string
  providerChat?: string
  className?: string
}) {
  const { account } = useHfAccount(backendUrl)
  const [dismissed, setDismissed] = useState(() => {
    try { return sessionStorage.getItem(DISMISS_KEY) === '1' } catch { return false }
  })
  const [notice, setNotice] = useState<string | null>(null)
  const onOllama = !providerChat || providerChat === 'ollama'
  if (!account.space || !onOllama || dismissed) return null

  return (
    <div className={`rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3 ${className}`}>
      <p className="text-[13px] leading-relaxed text-white/70">
        {account.signed_in
          ? 'You are signed in. Choose Hugging Face (your account) to run a larger model on your own credits.'
          : 'This chat uses the local model. Sign in with Hugging Face so a larger model uses your own credits. An account is optional.'}
      </p>
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        {account.signed_in ? (
          <button
            type="button"
            onClick={() => useHfForChat(account.default_model)}
            className="h-9 px-3 rounded-xl bg-white text-black text-xs font-semibold hover:bg-white/90"
          >
            Use for chat
          </button>
        ) : (
          <SignInButton account={account} backendUrl={backendUrl} onNeedRebuild={setNotice} />
        )}
        <button
          type="button"
          onClick={() => {
            try { sessionStorage.setItem(DISMISS_KEY, '1') } catch { /* ignore */ }
            setDismissed(true)
          }}
          className="h-9 px-3 rounded-xl text-xs text-white/50 hover:text-white/80"
        >
          Not now
        </button>
      </div>
      {notice ? <p className="mt-2 text-[12px] text-amber-200/90">{notice}</p> : null}
    </div>
  )
}

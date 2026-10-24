/**
 * Hugging Face account inference, web edition only.
 *
 * The Space already answers with the local model. Signing in spends the
 * visitor's own Inference Providers credits (free monthly credits or Pro).
 * The access token stays on the server.
 */

export interface HfSession {
  on_huggingface: boolean
  oauth_configured: boolean
  signed_in: boolean
  username?: string | null
  name?: string | null
}

export interface HfSetupCopy {
  title: string
  body: string
  showSignIn: boolean
  showSignOut: boolean
}

export function hfSetupCopy(session: HfSession): HfSetupCopy {
  if (!session.on_huggingface) {
    return { title: '', body: '', showSignIn: false, showSignOut: false }
  }
  if (session.signed_in) {
    const who = session.username || session.name || 'your Hugging Face account'
    return {
      title: `Signed in as ${who}`,
      body: 'Larger models use the credits on this Hugging Face account — free monthly credits, or your Pro plan. If a request cannot be billed, HomePilot uses the local model.',
      showSignIn: false,
      showSignOut: true,
    }
  }
  if (!session.oauth_configured) {
    return {
      title: 'Hugging Face account',
      body: 'Sign-in is not enabled on this Space yet. Chat keeps using the local model.',
      showSignIn: false,
      showSignOut: false,
    }
  }
  return {
    title: 'Use your Hugging Face account',
    body: 'Sign in to run a larger model on your own credits — the free monthly credits, or your Pro plan. If you stay signed out, this session keeps using the local model.',
    showSignIn: true,
    showSignOut: false,
  }
}

export function hfSuggestCopy(session: HfSession, providerChat: string): string | null {
  if (!session.on_huggingface || session.signed_in) return null
  if (providerChat === 'huggingface') return null
  if (!session.oauth_configured) return null
  return 'This session uses the local model. Sign in with Hugging Face when you want a larger model on your own credits.'
}

/** Make Hugging Face the chat provider immediately, not only after Settings → Save. */
export function rememberHfChatModel(model: string): void {
  localStorage.setItem('homepilot_provider_chat', 'huggingface')
  localStorage.setItem('homepilot_model_chat', model)
  localStorage.setItem('homepilot_base_url_chat', '')
}

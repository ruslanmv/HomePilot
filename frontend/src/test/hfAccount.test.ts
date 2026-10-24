import { describe, expect, it } from 'vitest'

import { hfSetupCopy, hfSuggestCopy } from '../ui/lib/hfAccount'

const signedOut = {
  on_huggingface: true,
  oauth_configured: true,
  signed_in: false,
}

describe('Hugging Face account inference copy', () => {
  it('suggests sign-in on a Space while the local model stays the default', () => {
    expect(hfSuggestCopy(signedOut, 'ollama')).toMatch(/local model/)
    expect(hfSuggestCopy(signedOut, 'ollama')).toMatch(/credits/)
    expect(hfSuggestCopy({ ...signedOut, on_huggingface: false }, 'ollama')).toBeNull()
    expect(hfSuggestCopy({ ...signedOut, signed_in: true, username: 'ada' }, 'ollama')).toBeNull()
  })

  it('asks for the account login and does not ask for an API key', () => {
    const copy = hfSetupCopy(signedOut)
    expect(copy.showSignIn).toBe(true)
    expect(copy.body).toMatch(/own credits/)
    expect(copy.body).toMatch(/local model/)
    expect(copy.body.toLowerCase()).not.toMatch(/api key/)
  })

  it('stays on the local model when sign-in is not enabled', () => {
    const copy = hfSetupCopy({ ...signedOut, oauth_configured: false })
    expect(copy.showSignIn).toBe(false)
    expect(copy.body).toMatch(/local model/)
  })

  it('names the signed-in account', () => {
    const copy = hfSetupCopy({ ...signedOut, signed_in: true, username: 'ada' })
    expect(copy.title).toBe('Signed in as ada')
    expect(copy.showSignOut).toBe(true)
    expect(copy.showSignIn).toBe(false)
  })
})

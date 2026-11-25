import { describe, expect, it } from 'vitest'
import { describeOutfitError } from './useOutfitGeneration'

describe('describeOutfitError', () => {
  it("shows the backend's reason on 503 (running, frozen or models missing)", () => {
    const frozen = 'ComfyUI at http://localhost:8188 is running but not responding. Restart it.'
    expect(describeOutfitError(503, JSON.stringify({ detail: frozen }))).toBe(frozen)
  })
  it('falls back to a start hint on a bare 503', () => {
    const msg = describeOutfitError(503, '')
    expect(msg).toMatch(/make start-comfyui/)
  })
  it('says when avatar generation is turned off', () => {
    expect(describeOutfitError(503, JSON.stringify({ detail: 'Avatar generator is disabled (AVATAR_ENABLED=false).' })))
      .toMatch(/turned off/)
  })
  it('passes the server detail through for other errors', () => {
    expect(describeOutfitError(500, JSON.stringify({ detail: 'Outfit generation failed: boom' }))).toMatch(/boom/)
    expect(describeOutfitError(0, '')).toMatch(/backend/)
  })
})

/**
 * Avatar types — pure type-level tests (no DOM required).
 *
 * Validates that type definitions match expected shapes and that
 * helper constants are consistent.
 */

import { describe, it, expect } from 'vitest'
import type {
  AvatarMode,
  AvatarPackInfo,
  AvatarPacksResponse,
  AvatarGenerateRequest,
  AvatarResult,
  AvatarGenerateResponse,
} from './types'

describe('Avatar types', () => {
  it('AvatarMode accepts all valid mode values', () => {
    const modes: AvatarMode[] = [
      'creative',
      'studio_random',
      'studio_reference',
      'studio_faceswap',
    ]
    expect(modes).toHaveLength(4)
    expect(new Set(modes).size).toBe(4) // no duplicates
  })

  it('AvatarPackInfo has required fields', () => {
    const pack: AvatarPackInfo = {
      id: 'basic',
      title: 'Basic Pack',
      installed: true,
      license: 'MIT',
      commercial_ok: true,
      modes_enabled: ['studio_random'],
    }
    expect(pack.id).toBe('basic')
    expect(pack.installed).toBe(true)
  })

  it('AvatarPacksResponse aggregates packs and enabled modes', () => {
    const response: AvatarPacksResponse = {
      packs: [
        {
          id: 'basic',
          title: 'Basic',
          installed: true,
          license: 'MIT',
          commercial_ok: true,
          modes_enabled: ['studio_random'],
        },
      ],
      enabled_modes: ['studio_random'],
    }
    expect(response.packs).toHaveLength(1)
    expect(response.enabled_modes).toContain('studio_random')
  })

  it('AvatarGenerateRequest supports all optional fields', () => {
    const minimal: AvatarGenerateRequest = { mode: 'studio_random' }
    expect(minimal.mode).toBe('studio_random')

    const full: AvatarGenerateRequest = {
      mode: 'studio_reference',
      count: 4,
      seed: 42,
      truncation: 0.7,
      prompt: 'professional headshot',
      reference_image_url: 'http://localhost:8000/uploads/face.png',
      persona_id: 'persona_123',
    }
    expect(full.count).toBe(4)
    expect(full.seed).toBe(42)
  })

  it('AvatarResult contains url and optional seed', () => {
    const result: AvatarResult = {
      url: '/files/avatar_001.png',
      seed: 12345,
      metadata: { model: 'instantid' },
    }
    expect(result.url).toBeTruthy()
    expect(result.seed).toBe(12345)
  })

  it('AvatarGenerateResponse contains results array', () => {
    const response: AvatarGenerateResponse = {
      mode: 'studio_random',
      results: [
        { url: '/files/a1.png', seed: 1 },
        { url: '/files/a2.png', seed: 2 },
      ],
      warnings: ['Non-commercial model used'],
    }
    expect(response.results).toHaveLength(2)
    expect(response.warnings).toHaveLength(1)
  })
})

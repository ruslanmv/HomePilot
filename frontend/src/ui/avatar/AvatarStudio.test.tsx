/**
 * AvatarStudio component tests — lightweight, CI-friendly.
 *
 * Tests rendering, mode selection, generate button states,
 * and action callbacks without real API calls.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'
import AvatarStudio from './AvatarStudio'

// ---------------------------------------------------------------------------
// Mock hooks — prevent real API calls
// ---------------------------------------------------------------------------

const mockPacksData = {
  packs: [
    {
      id: 'basic',
      title: 'Basic',
      installed: true,
      license: 'Apache-2.0',
      commercial_ok: true,
      modes_enabled: ['studio_random', 'studio_reference'],
    },
  ],
  enabled_modes: ['studio_random', 'studio_reference', 'studio_faceswap'],
}

const mockRun = vi.fn().mockResolvedValue({
  mode: 'studio_random',
  results: [{ url: '/files/avatar.png', seed: 42 }],
})
const mockReset = vi.fn()

vi.mock('./useAvatarPacks', () => ({
  useAvatarPacks: () => ({
    data: mockPacksData,
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}))

vi.mock('./useGenerateAvatars', () => ({
  useGenerateAvatars: () => ({
    loading: false,
    result: null,
    error: null,
    run: mockRun,
    reset: mockReset,
  }),
}))

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AvatarStudio', () => {
  beforeEach(() => {
    mockRun.mockClear()
  })

  it('renders the header', () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)
    expect(screen.getByText('Avatar Studio')).toBeInTheDocument()
    expect(
      screen.getByText('Generate reusable portrait avatars for your personas'),
    ).toBeInTheDocument()
  })

  it('renders all three mode pills', () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)
    expect(screen.getByText('From Reference')).toBeInTheDocument()
    expect(screen.getByText('Random Face')).toBeInTheDocument()
    expect(screen.getByText('Face + Style')).toBeInTheDocument()
  })

  it('renders pack badges', () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)
    expect(screen.getByText('Basic')).toBeInTheDocument()
  })

  it('renders the prompt input with default value', () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)
    const input = screen.getByLabelText('Avatar generation prompt')
    expect(input).toBeInTheDocument()
    expect((input as HTMLInputElement).value).toBe(
      'studio headshot, soft light, photorealistic',
    )
  })

  it('renders count selector buttons (1, 4, 8)', () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText('4')).toBeInTheDocument()
    expect(screen.getByText('8')).toBeInTheDocument()
  })

  it('shows generate button with count', () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)
    // Default mode is studio_reference which requires a reference image
    // Switch to studio_random first
    fireEvent.click(screen.getByText('Random Face'))
    expect(screen.getByText('Generate 4')).toBeInTheDocument()
  })

  it('switching mode changes active pill', () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)
    const randomBtn = screen.getByText('Random Face')
    fireEvent.click(randomBtn)

    // Random Face should now be aria-checked
    expect(randomBtn.closest('button')).toHaveAttribute('aria-checked', 'true')
  })

  it('shows reference upload when mode requires it', () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)

    // Default mode is studio_reference — should show upload
    expect(screen.getByText('Reference Image')).toBeInTheDocument()
    expect(screen.getByLabelText('Upload reference photo')).toBeInTheDocument()

    // Switch to Random Face — should hide upload
    fireEvent.click(screen.getByText('Random Face'))
    expect(screen.queryByText('Reference Image')).not.toBeInTheDocument()
  })

  it('shows empty state hint', () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)
    // Switch to Random Face to see the non-reference empty state
    fireEvent.click(screen.getByText('Random Face'))
    expect(
      screen.getByText('Choose a mode and click Generate'),
    ).toBeInTheDocument()
  })

  it('clicking generate calls gen.run with correct params', async () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)

    // Switch to Random Face (doesn't need reference)
    fireEvent.click(screen.getByText('Random Face'))

    // Click Generate
    fireEvent.click(screen.getByText('Generate 4'))

    await waitFor(() => {
      expect(mockRun).toHaveBeenCalledWith(
        expect.objectContaining({
          mode: 'studio_random',
          count: 4,
          truncation: 0.7,
        }),
      )
    })
  })

  it('count selector updates the count', async () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)
    fireEvent.click(screen.getByText('Random Face'))

    // Change count to 8
    fireEvent.click(screen.getByText('8'))
    fireEvent.click(screen.getByText('Generate 8'))

    await waitFor(() => {
      expect(mockRun).toHaveBeenCalledWith(
        expect.objectContaining({ count: 8 }),
      )
    })
  })

  it('onSendToEdit callback is passed to AvatarStudio', () => {
    const onSendToEdit = vi.fn()
    render(
      <AvatarStudio
        backendUrl="http://localhost:8000"
        onSendToEdit={onSendToEdit}
      />,
    )
    // The callback exists — it will be used on avatar cards once results render
    expect(onSendToEdit).not.toHaveBeenCalled()
  })

  it('onOpenLightbox callback is passed to AvatarStudio', () => {
    const onOpenLightbox = vi.fn()
    render(
      <AvatarStudio
        backendUrl="http://localhost:8000"
        onOpenLightbox={onOpenLightbox}
      />,
    )
    expect(onOpenLightbox).not.toHaveBeenCalled()
  })

  it('Enter key in prompt field triggers generation', async () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)
    fireEvent.click(screen.getByText('Random Face'))

    const input = screen.getByLabelText('Avatar generation prompt')
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => {
      expect(mockRun).toHaveBeenCalled()
    })
  })

  it('prompt input updates on user typing', () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)
    const input = screen.getByLabelText('Avatar generation prompt') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'cyberpunk portrait' } })
    expect(input.value).toBe('cyberpunk portrait')
  })
})

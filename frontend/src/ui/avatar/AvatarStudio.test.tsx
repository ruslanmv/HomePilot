/**
 * AvatarStudio component tests — lightweight, CI-friendly.
 *
 * Tests the two-view architecture:
 *   1. Gallery view (landing) — default, shows avatar library
 *   2. Designer view — accessible via "New Avatar" button
 *
 * Also tests mode selection, generate button states,
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
// Helpers
// ---------------------------------------------------------------------------

/** Render AvatarStudio and click "New Avatar" to enter designer view. */
function renderDesignerView(props?: Partial<React.ComponentProps<typeof AvatarStudio>>) {
  const result = render(
    <AvatarStudio backendUrl="http://localhost:8000" {...props} />,
  )
  // Navigate to designer view
  fireEvent.click(screen.getByText('New Avatar'))
  return result
}

// ---------------------------------------------------------------------------
// Tests — Gallery View (Landing)
// ---------------------------------------------------------------------------

describe('AvatarStudio — Gallery View', () => {
  it('renders the landing page header', () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)
    expect(screen.getByText('Avatar Studio')).toBeInTheDocument()
  })

  it('shows "New Avatar" button in header', () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)
    expect(screen.getByText('New Avatar')).toBeInTheDocument()
  })

  it('shows empty state with create CTAs when no avatars exist', () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)
    expect(screen.getByText('Create your first avatar')).toBeInTheDocument()
    expect(screen.getByText('From Reference Photo')).toBeInTheDocument()
    expect(screen.getByText('Random Face')).toBeInTheDocument()
  })

  it('clicking "New Avatar" navigates to designer view', () => {
    render(<AvatarStudio backendUrl="http://localhost:8000" />)
    fireEvent.click(screen.getByText('New Avatar'))
    // Should now see designer header
    expect(screen.getByText('Avatar Studio')).toBeInTheDocument()
    expect(screen.getByLabelText('Back to Avatar Gallery')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Tests — Designer View
// ---------------------------------------------------------------------------

describe('AvatarStudio — Designer View', () => {
  beforeEach(() => {
    mockRun.mockClear()
  })

  it('renders the designer header with back button', () => {
    renderDesignerView()
    expect(screen.getByLabelText('Back to Avatar Gallery')).toBeInTheDocument()
    expect(screen.getByText('Avatar Studio')).toBeInTheDocument()
  })

  it('renders all three mode pills', () => {
    renderDesignerView()
    // In designer view: mode pills as radio buttons
    expect(screen.getByRole('radio', { name: /From Reference/ })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Random Face/ })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Face \+ Style/ })).toBeInTheDocument()
  })

  it('renders pack badges', () => {
    renderDesignerView()
    expect(screen.getByText('Basic')).toBeInTheDocument()
  })

  it('renders the prompt input with default value', () => {
    renderDesignerView()
    const input = screen.getByLabelText('Avatar generation prompt')
    expect(input).toBeInTheDocument()
    expect((input as HTMLInputElement).value).toBe(
      'studio headshot, soft light, photorealistic',
    )
  })

  it('renders count selector buttons (1, 4, 8)', () => {
    renderDesignerView()
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText('4')).toBeInTheDocument()
    expect(screen.getByText('8')).toBeInTheDocument()
  })

  it('shows generate button with count', () => {
    renderDesignerView()
    // Switch to studio_random first
    fireEvent.click(screen.getByRole('radio', { name: /Random Face/ }))
    expect(screen.getByText('Generate 4')).toBeInTheDocument()
  })

  it('switching mode changes active pill', () => {
    renderDesignerView()
    const randomBtn = screen.getByRole('radio', { name: /Random Face/ })
    fireEvent.click(randomBtn)
    expect(randomBtn).toHaveAttribute('aria-checked', 'true')
  })

  it('shows reference upload when mode requires it', () => {
    renderDesignerView()
    // Default mode is studio_reference — should show upload
    expect(screen.getByText('Reference Image')).toBeInTheDocument()
    expect(screen.getByLabelText('Upload reference photo')).toBeInTheDocument()

    // Switch to Random Face — should hide upload
    fireEvent.click(screen.getByRole('radio', { name: /Random Face/ }))
    expect(screen.queryByText('Reference Image')).not.toBeInTheDocument()
  })

  it('shows empty state hint', () => {
    renderDesignerView()
    // Switch to Random Face to see the non-reference empty state
    fireEvent.click(screen.getByRole('radio', { name: /Random Face/ }))
    expect(
      screen.getByText('Click Generate to create a new avatar'),
    ).toBeInTheDocument()
  })

  it('clicking generate calls gen.run with correct params', async () => {
    renderDesignerView()
    fireEvent.click(screen.getByRole('radio', { name: /Random Face/ }))
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
    renderDesignerView()
    fireEvent.click(screen.getByRole('radio', { name: /Random Face/ }))
    fireEvent.click(screen.getByText('8'))
    fireEvent.click(screen.getByText('Generate 8'))

    await waitFor(() => {
      expect(mockRun).toHaveBeenCalledWith(
        expect.objectContaining({ count: 8 }),
      )
    })
  })

  it('back button returns to gallery view', () => {
    renderDesignerView()
    fireEvent.click(screen.getByLabelText('Back to Avatar Gallery'))
    // Should see gallery landing again
    expect(screen.getByText('New Avatar')).toBeInTheDocument()
  })

  it('onSendToEdit callback is passed to AvatarStudio', () => {
    const onSendToEdit = vi.fn()
    renderDesignerView({ onSendToEdit })
    expect(onSendToEdit).not.toHaveBeenCalled()
  })

  it('onOpenLightbox callback is passed to AvatarStudio', () => {
    const onOpenLightbox = vi.fn()
    renderDesignerView({ onOpenLightbox })
    expect(onOpenLightbox).not.toHaveBeenCalled()
  })

  it('prompt input updates on user typing', () => {
    renderDesignerView()
    const input = screen.getByLabelText('Avatar generation prompt') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'cyberpunk portrait' } })
    expect(input.value).toBe('cyberpunk portrait')
  })
})

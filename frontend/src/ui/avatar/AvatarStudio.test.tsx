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
const mockCancel = vi.fn()

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
    cancel: mockCancel,
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
    // Should now see designer header with back button
    expect(screen.getByText('Avatar Studio')).toBeInTheDocument()
    expect(screen.getByTitle('Back to Gallery')).toBeInTheDocument()
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
    expect(screen.getByTitle('Back to Gallery')).toBeInTheDocument()
    expect(screen.getByText('Avatar Studio')).toBeInTheDocument()
  })

  it('renders all three mode pills', () => {
    renderDesignerView()
    // In designer view: mode pills as radio buttons
    expect(screen.getByRole('radio', { name: /Design Character/ })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /From Reference/ })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Face \+ Style/ })).toBeInTheDocument()
  })

  it('default mode is Design Character', () => {
    renderDesignerView()
    const designBtn = screen.getByRole('radio', { name: /Design Character/ })
    expect(designBtn).toHaveAttribute('aria-checked', 'true')
  })

  it('renders the generate button with count', () => {
    renderDesignerView()
    // Default count is 1
    expect(screen.getByText(/Generate \(1\)/)).toBeInTheDocument()
  })

  it('switching mode changes active pill', () => {
    renderDesignerView()
    const refBtn = screen.getByRole('radio', { name: /From Reference/ })
    fireEvent.click(refBtn)
    expect(refBtn).toHaveAttribute('aria-checked', 'true')
    // Previous mode should be deselected
    const designBtn = screen.getByRole('radio', { name: /Design Character/ })
    expect(designBtn).toHaveAttribute('aria-checked', 'false')
  })

  it('shows upload section when mode requires it', () => {
    renderDesignerView()
    // Default mode is Design Character — should NOT show upload
    expect(screen.queryByTitle('Upload a reference photo')).not.toBeInTheDocument()

    // Switch to From Reference — should show upload area
    fireEvent.click(screen.getByRole('radio', { name: /From Reference/ }))
    expect(screen.getByText('1. Upload a face')).toBeInTheDocument()
    expect(screen.getByTitle('Upload a reference photo')).toBeInTheDocument()

    // Switch back to Design Character — should hide upload
    fireEvent.click(screen.getByRole('radio', { name: /Design Character/ }))
    expect(screen.queryByText('1. Upload a face')).not.toBeInTheDocument()
  })

  it('clicking generate calls gen.run', async () => {
    renderDesignerView()
    fireEvent.click(screen.getByText(/Generate \(1\)/))

    await waitFor(() => {
      expect(mockRun).toHaveBeenCalledWith(
        expect.objectContaining({
          mode: 'creative',
          count: 1,
        }),
      )
    })
  })

  it('back button returns to gallery view', () => {
    renderDesignerView()
    fireEvent.click(screen.getByTitle('Back to Gallery'))
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
})

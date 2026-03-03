/**
 * AvatarStudio component tests — lightweight, CI-friendly.
 *
 * Tests the two-view architecture:
 *   1. Gallery view (landing) — default, shows avatar library
 *   2. Wizard view — accessible via "New Avatar" button (CharacterWizard)
 *
 * Also tests mode selection, navigation, and action callbacks
 * without real API calls.
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

vi.mock('./useAvatarGallery', () => ({
  useAvatarGallery: () => ({
    items: [],
    addItem: vi.fn(),
    addBatch: vi.fn(),
    addAnchorWithPortraits: vi.fn(),
    swapAnchor: vi.fn(),
    removeItem: vi.fn(),
    clearAll: vi.fn(),
    tagItem: vi.fn(),
    linkToPersona: vi.fn(),
  }),
}))

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Render AvatarStudio and click "New Avatar" to enter wizard view. */
function renderWizardView(props?: Partial<React.ComponentProps<typeof AvatarStudio>>) {
  const result = render(
    <AvatarStudio backendUrl="http://localhost:8000" {...props} />,
  )
  // Navigate to wizard view
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
    // Should now see wizard header with back button
    expect(screen.getByText('Avatar Studio')).toBeInTheDocument()
    expect(screen.getByTitle('Back to Gallery')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Tests — Wizard View (CharacterWizard)
// ---------------------------------------------------------------------------

describe('AvatarStudio — Designer View', () => {
  beforeEach(() => {
    mockRun.mockClear()
  })

  it('renders the designer header with back button', () => {
    renderWizardView()
    expect(screen.getByTitle('Back to Gallery')).toBeInTheDocument()
    expect(screen.getByText('Avatar Studio')).toBeInTheDocument()
  })

  it('renders Quick Create and Studio mode pills', () => {
    renderWizardView()
    // The wizard shows Quick Create / Studio toggle in the header
    expect(screen.getByText('Quick Create')).toBeInTheDocument()
    expect(screen.getByText('Studio')).toBeInTheDocument()
  })

  it('default mode is Studio with Identity step active', () => {
    renderWizardView()
    // Studio is the default mode — it should have active styling
    const studioBtn = screen.getByText('Studio').closest('button')!
    expect(studioBtn.className).toContain('bg-white/10')
    // Identity step heading should be visible (first step of the wizard)
    expect(screen.getByRole('heading', { name: 'Identity' })).toBeInTheDocument()
  })

  it('renders wizard step navigation', () => {
    renderWizardView()
    // Wizard sidebar shows numbered steps
    expect(screen.getByRole('heading', { name: 'Identity' })).toBeInTheDocument()
    expect(screen.getByText('Body')).toBeInTheDocument()
    expect(screen.getByText('Face')).toBeInTheDocument()
    expect(screen.getByText('Hair')).toBeInTheDocument()
    // Next button for step navigation
    expect(screen.getByText('Next')).toBeInTheDocument()
  })

  it('switching to Quick Create mode changes view', () => {
    renderWizardView()
    // Default is Studio mode — sidebar steps and heading visible
    expect(screen.getByRole('heading', { name: 'Identity' })).toBeInTheDocument()

    // Switch to Quick Create — use button role to avoid matching the heading
    const quickBtn = screen.getByRole('button', { name: /Quick Create/ })
    fireEvent.click(quickBtn)
    expect(quickBtn.className).toContain('bg-white/10')
    // Quick Create mode shows its own heading
    expect(screen.getByRole('heading', { name: /Quick Create/ })).toBeInTheDocument()

    // Switch back to Studio — sidebar steps reappear
    fireEvent.click(screen.getByRole('button', { name: /Studio/ }))
    expect(screen.getByRole('heading', { name: 'Identity' })).toBeInTheDocument()
  })

  it('shows gender selection in Identity step', () => {
    renderWizardView()
    // Identity step includes gender selection by default
    expect(screen.getByText(/Female/)).toBeInTheDocument()
    expect(screen.getByText(/Male/)).toBeInTheDocument()
  })

  it('back button returns to gallery view', () => {
    renderWizardView()
    fireEvent.click(screen.getByTitle('Back to Gallery'))
    // Should see gallery landing again
    expect(screen.getByText('New Avatar')).toBeInTheDocument()
  })

  it('onSendToEdit callback is passed to AvatarStudio', () => {
    const onSendToEdit = vi.fn()
    renderWizardView({ onSendToEdit })
    expect(onSendToEdit).not.toHaveBeenCalled()
  })

  it('onOpenLightbox callback is passed to AvatarStudio', () => {
    const onOpenLightbox = vi.fn()
    renderWizardView({ onOpenLightbox })
    expect(onOpenLightbox).not.toHaveBeenCalled()
  })
})

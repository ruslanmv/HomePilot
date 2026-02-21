/**
 * EditDropzone component tests — validates dual primary action pattern.
 *
 * Tests:
 * - Upload Image button renders
 * - Create Avatar button renders when callback provided
 * - Create Avatar button is hidden when no callback
 * - Click behavior on both buttons
 * - Drag & drop zone
 * - Disabled state
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import React from 'react'
import { EditDropzone } from './EditDropzone'

describe('EditDropzone', () => {
  it('renders with Upload Image button', () => {
    render(<EditDropzone onPickFile={vi.fn()} />)
    expect(screen.getByText('Upload Image')).toBeInTheDocument()
  })

  it('renders the title', () => {
    render(<EditDropzone onPickFile={vi.fn()} />)
    expect(screen.getByText('Start editing')).toBeInTheDocument()
  })

  it('renders description text', () => {
    render(<EditDropzone onPickFile={vi.fn()} />)
    expect(
      screen.getByText(/Upload an existing image to edit/),
    ).toBeInTheDocument()
  })

  it('shows Create Avatar button when onCreateAvatar is provided', () => {
    render(
      <EditDropzone onPickFile={vi.fn()} onCreateAvatar={vi.fn()} />,
    )
    expect(screen.getByText('Create Avatar')).toBeInTheDocument()
  })

  it('hides Create Avatar button when onCreateAvatar is not provided', () => {
    render(<EditDropzone onPickFile={vi.fn()} />)
    expect(screen.queryByText('Create Avatar')).not.toBeInTheDocument()
  })

  it('clicking Create Avatar calls the callback', () => {
    const onCreateAvatar = vi.fn()
    render(
      <EditDropzone onPickFile={vi.fn()} onCreateAvatar={onCreateAvatar} />,
    )
    fireEvent.click(screen.getByText('Create Avatar'))
    expect(onCreateAvatar).toHaveBeenCalledOnce()
  })

  it('shows avatar subtext when onCreateAvatar is provided', () => {
    render(
      <EditDropzone onPickFile={vi.fn()} onCreateAvatar={vi.fn()} />,
    )
    expect(
      screen.getByText('Create a reusable character from photos'),
    ).toBeInTheDocument()
  })

  it('shows supported formats hint', () => {
    render(<EditDropzone onPickFile={vi.fn()} />)
    expect(
      screen.getByText(/Supports PNG, JPEG, and WebP/),
    ).toBeInTheDocument()
  })

  it('applies disabled styling when disabled', () => {
    const { container } = render(
      <EditDropzone onPickFile={vi.fn()} disabled />,
    )
    // The root div should have opacity-50
    const dropzone = container.firstChild as HTMLElement
    expect(dropzone.className).toContain('opacity-50')
  })

  it('Create Avatar button has correct ARIA label', () => {
    render(
      <EditDropzone onPickFile={vi.fn()} onCreateAvatar={vi.fn()} />,
    )
    const btn = screen.getByLabelText('Create a reusable avatar character')
    expect(btn).toBeInTheDocument()
    expect(btn.tagName).toBe('BUTTON')
  })

  it('Upload Image label has correct ARIA label', () => {
    render(<EditDropzone onPickFile={vi.fn()} />)
    const label = screen.getByLabelText('Upload an image to edit')
    expect(label).toBeInTheDocument()
  })

  it('drop zone shows visual feedback on drag over', () => {
    const { container } = render(<EditDropzone onPickFile={vi.fn()} />)
    const dropzone = container.firstChild as HTMLElement

    fireEvent.dragOver(dropzone, { dataTransfer: { files: [] } })
    expect(dropzone.className).toContain('border-blue-500')

    fireEvent.dragLeave(dropzone, { dataTransfer: { files: [] } })
    expect(dropzone.className).not.toContain('border-blue-500')
  })

  it('both buttons have equal visual hierarchy', () => {
    render(
      <EditDropzone onPickFile={vi.fn()} onCreateAvatar={vi.fn()} />,
    )
    // Both buttons should be in the same container
    const uploadBtn = screen.getByText('Upload Image')
    const avatarBtn = screen.getByText('Create Avatar')

    // Both should have the same font-semibold class (equal hierarchy)
    expect(uploadBtn.closest('label, button')?.className).toContain('font-semibold')
    expect(avatarBtn.closest('button')?.className).toContain('font-semibold')
  })
})

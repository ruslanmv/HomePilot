/**
 * EditDropzone component tests — validates upload area for Edit tab.
 *
 * Tests:
 * - Upload Image button renders
 * - Click behavior
 * - Drag & drop zone
 * - Disabled state
 *
 * Note: "Create Avatar" button has moved to the Avatar tab landing page.
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
      screen.getByText(/Upload an image to start editing/),
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
})

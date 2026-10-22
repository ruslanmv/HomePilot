/**
 * A long paste becomes a chip above the composer (as in ChatGPT and Claude) instead of a wall
 * of text that stretches the field over the conversation; compaction has its own indicator.
 */
import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { CompactingIndicator, PastedChips, isLongPaste, withPastes } from '../ui/components/ComposerExtras'

describe('long pastes', () => {
  it('keeps short pastes in the field and turns long ones into a chip', () => {
    expect(isLongPaste('a short sentence')).toBe(false)
    expect(isLongPaste('x'.repeat(1199))).toBe(false)
    expect(isLongPaste('x'.repeat(1200))).toBe(true)
    expect(isLongPaste(Array.from({ length: 15 }, (_, i) => `line ${i}`).join('\n'))).toBe(true)
  })

  it('sends what was typed, then each paste', () => {
    expect(withPastes('  Summarize this:  ', ['A long document'])).toBe('Summarize this:\n\nA long document')
    expect(withPastes('', ['only the paste'])).toBe('only the paste')
  })

  it('shows a chip that opens to the text and can be removed', () => {
    const paste = Array.from({ length: 20 }, (_, i) => `line ${i}`).join('\n')
    const onOpen = vi.fn()
    const onRemove = vi.fn()
    const { rerender } = render(<PastedChips pastes={[paste]} open={null} onOpen={onOpen} onRemove={onRemove} />)
    expect(screen.getByText('Pasted · 20 lines')).toBeTruthy()
    expect(screen.queryByTestId('composer-paste-preview')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Pasted text, 20 lines/ }))
    expect(onOpen).toHaveBeenCalledWith(0)
    rerender(<PastedChips pastes={[paste]} open={0} onOpen={onOpen} onRemove={onRemove} />)
    expect(screen.getByTestId('composer-paste-preview').textContent).toContain('line 19')
    fireEvent.click(screen.getByRole('button', { name: 'Remove pasted text' }))
    expect(onRemove).toHaveBeenCalledWith(0)
  })
})

describe('CompactingIndicator', () => {
  it('says what is happening, politely, with the condensing lines', () => {
    render(<CompactingIndicator text="Compacting the conversation: summarizing 8 earlier messages…" />)
    const el = screen.getByTestId('compacting')
    expect(el.getAttribute('role')).toBe('status')
    expect(el.textContent).toContain('summarizing 8 earlier messages')
    expect(el.querySelectorAll('.hp-compact-lines > span').length).toBe(3)
  })
})

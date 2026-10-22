/**
 * Equations in chat replies: the delimiters models write (\( \), \[ \], $ and $$) render with
 * KaTeX; prices stay prices; code stays code.
 */
import React from 'react'
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MessageMarkdown, normalizeMath } from '../ui/components/MessageMarkdown'

describe('normalizeMath', () => {
  it('turns bracket delimiters into dollar math', () => {
    expect(normalizeMath('Energy \\(E = mc^2\\) here')).toBe('Energy $E = mc^2$ here')
    expect(normalizeMath('Then\n\\[ i\\hbar \\partial_t \\Psi = \\hat H \\Psi \\]\nDone'))
      .toBe('Then\n\n$$\ni\\hbar \\partial_t \\Psi = \\hat H \\Psi\n$$\n\nDone')
  })

  it('keeps prices and code as written', () => {
    expect(normalizeMath('It costs $5 and $10.')).toBe('It costs \\$5 and \\$10.')
    expect(normalizeMath('Use `\\(x\\)` or\n```\n\\[y\\] $5\n```')).toBe('Use `\\(x\\)` or\n```\n\\[y\\] $5\n```')
    expect(normalizeMath('$x^2$ and $$y$$')).toBe('$x^2$ and $$y$$')
  })
})

describe('MessageMarkdown math', () => {
  it('renders inline and display equations with KaTeX', () => {
    const { container } = render(
      <MessageMarkdown text={'Inline \\(E = mc^2\\) and $a^2+b^2=c^2$.\n\n\\[ i\\hbar \\frac{\\partial}{\\partial t}\\Psi = \\hat H \\Psi \\]'} />,
    )
    expect(container.querySelectorAll('.katex').length).toBeGreaterThanOrEqual(3)
    expect(container.querySelector('.katex-display')).not.toBeNull()
  })

  it('leaves a price as text and survives a malformed formula', () => {
    const { container } = render(<MessageMarkdown text={'It costs $5 and $10. Broken: $\\frac{1}{$'} />)
    expect(container.textContent).toContain('$5 and $10')
    expect(container.querySelector('.katex-display')).toBeNull()
  })
})

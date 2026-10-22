/**
 * Citations as ChatGPT shows them: whatever marker the model writes (`[n]`, `【n†L1-L2】`,
 * `[2, 3]`) becomes a small numbered pill linked to its source, and the sources row leads with
 * the sources the answer actually cites.
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MessageMarkdown } from '../ui/components/MessageMarkdown'
import { WebSources, citedNumbers, linkCitations, normalizeCitations, orderSources } from '../ui/components/WebSources'

const sources = [
  { n: 1, title: 'EU energy prices', url: 'https://reuters.example/energy', domain: 'reuters.example' },
  { n: 6, title: 'Italy - Wikipedia', url: 'https://en.wikipedia.org/wiki/Italy', domain: 'en.wikipedia.org' },
  { n: 11, title: 'Rome - Wikipedia', url: 'https://en.wikipedia.org/wiki/Rome', domain: 'en.wikipedia.org' },
] as any

describe('normalizeCitations', () => {
  it('turns browsing-style and grouped markers into [n]', () => {
    expect(normalizeCitations('Rome【6†L1-L2】【11†L1-L2】.')).toBe('Rome[6][11].')
    expect(normalizeCitations('See 【3】 and [4†source].')).toBe('See[3] and [4].')
    expect(normalizeCitations('Mexico City [2, 3].')).toBe('Mexico City [2][3].')
    expect(normalizeCitations('code `【6†L1】` stays')).toBe('code `【6†L1】` stays')
    expect(normalizeCitations('a link [[6]](https://x) stays')).toBe('a link [[6]](https://x) stays')
  })

  it('finds what an answer cites, in order', () => {
    expect(citedNumbers('Rome【6†L1-L2】 on the Tiber [11]; again [6].')).toEqual([6, 11])
  })
})

describe('citations in the chat', () => {
  it('renders each citation as a numbered pill linked to its source', () => {
    render(<MessageMarkdown text={linkCitations('The capital of Italy is Rome【6†L1-L2】【11†L1-L2】.', sources)} />)
    const pills = screen.getAllByTestId('citation')
    expect(pills.map((p) => p.textContent)).toEqual(['6', '11'])
    expect(pills[0].getAttribute('href')).toBe('https://en.wikipedia.org/wiki/Italy')
    expect(document.body.textContent).not.toContain('†')
  })

  it('shows the cited sources first', () => {
    expect(orderSources(sources, [11, 6]).map((s: any) => s.n)).toEqual([11, 6, 1])
    render(<WebSources web={{ status: 'ok', query: 'capital of italy', sources } as any} text={'Rome [6][11].'} />)
    const chips = screen.getAllByTestId('web-source')
    expect(chips[0].textContent).toContain('Italy - Wikipedia')
    expect(chips[1].textContent).toContain('Rome - Wikipedia')
  })
})

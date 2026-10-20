/**
 * "Search the web" in the standard chat — the UI half (backend/app/web_search.py is the rest).
 *
 * The switch lives in two places that must never disagree — the composer's + menu and Chat
 * settings — and only in the standard chat. A grounded answer shows what was searched and its
 * sources, and every [n] in it opens source n. When search could not run, the answer says so
 * in amber instead of passing old knowledge off as current.
 */
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { WebSearchToggleContext, WebSources, linkCitations, parseWebSearch } from '../ui/components/WebSources';
import { ChatSettingsPopover, DEFAULT_CHAT_SETTINGS } from '../ui/components/ChatSettingsPopover';
import { ComposerPlusMenu } from '../ui/components/ComposerPlusMenu';

const SOURCES = [
  { n: 1, title: 'AI weekly', url: 'https://ai.test/weekly', domain: 'ai.test', published: '2026-10-19T08:00:00' },
  { n: 2, title: 'Model news', url: 'https://models.test/n', domain: 'models.test' },
];

describe('citations', () => {
  it('turns [n] into a link to source n, and leaves everything else alone', () => {
    const out = linkCitations('New models shipped [1][2]. See [3]. `code [1]` and [docs](https://x.test).', SOURCES);
    expect(out).toContain('[[1]](https://ai.test/weekly "AI weekly")[[2]](https://models.test/n "Model news")');
    expect(out).toContain('See [3].');          // not a source
    expect(out).toContain('`code [1]`');        // code is code
    expect(out).toContain('[docs](https://x.test)');
    expect(linkCitations(out, SOURCES)).toBe(out); // idempotent while the text streams in
  });

  it('accepts only well-formed sources', () => {
    expect(parseWebSearch(null)).toBeNull();
    expect(parseWebSearch({ status: 'weird' })).toBeNull();
    const parsed = parseWebSearch({ status: 'ok', query: 'q', sources: [...SOURCES, { n: 3, url: 'javascript:alert(1)' }] });
    expect(parsed?.sources.map((s) => s.url)).toEqual(['https://ai.test/weekly', 'https://models.test/n']);
  });
});

describe('the sources under an answer', () => {
  it('say what was searched and link each source', () => {
    render(<WebSources web={{ status: 'ok', query: 'AI news today', sources: SOURCES }} />);
    expect(screen.getByText(/Searched the web for/)).toBeTruthy();
    expect(screen.getByText('“AI news today”')).toBeTruthy();
    expect(screen.getByText(/2 sources/)).toBeTruthy();
    const links = screen.getAllByTestId('web-source') as HTMLAnchorElement[];
    expect(links.map((a) => a.href)).toEqual(['https://ai.test/weekly', 'https://models.test/n']);
    expect(links[0].target).toBe('_blank');
    expect(links[0].rel).toContain('noopener');
    expect(links[0].textContent).toContain('2026-10-19');
  });

  it('say plainly when search could not run', () => {
    render(<WebSources web={{ status: 'unavailable', query: 'q', sources: [],
      message: "Web search isn't available right now, so this answer is from the model's own knowledge and may be out of date.",
      hint: 'SearXNG is not running. Start it with `make start-searxng`.' }} />);
    const note = screen.getByTestId('web-unavailable');
    expect(note.textContent).toContain('may be out of date');
    expect(note.textContent).toContain('make start-searxng');
  });
});

function withSwitch(ui: React.ReactElement, { available = true, on = false, status = { available: true, provider: 'searxng' } } = {}) {
  const setOn = vi.fn();
  const check = vi.fn(async () => status);
  render(<WebSearchToggleContext.Provider value={{ available, on, setOn, check }}>{ui}</WebSearchToggleContext.Provider>);
  return { setOn, check };
}

describe('the switch', () => {
  it('is in the + menu of the standard chat and flips this chat', () => {
    const { setOn } = withSwitch(<ComposerPlusMenu onAddFile={() => undefined} />);
    fireEvent.click(screen.getByTestId('composer-plus-button'));
    const item = screen.getByTestId('composer-plus-web');
    expect(item.getAttribute('aria-checked')).toBe('false');
    fireEvent.click(item);
    expect(setOn).toHaveBeenCalledWith(true);
  });

  it('is absent outside the standard chat', () => {
    withSwitch(<ComposerPlusMenu onAddFile={() => undefined} />, { available: false });
    fireEvent.click(screen.getByTestId('composer-plus-button'));
    expect(screen.queryByTestId('composer-plus-web')).toBeNull();
  });

  it('is in Chat settings, and says when search cannot run', async () => {
    const onChange = vi.fn();
    withSwitch(
      <ChatSettingsPopover open onClose={() => undefined} settings={{ ...DEFAULT_CHAT_SETTINGS, webSearch: true }} onChange={onChange} />,
      { on: true, status: { available: false, hint: 'SearXNG is not running. Start it with `make start-searxng`.' } as never },
    );
    await waitFor(() => expect(screen.getByTestId('chat-web-search-status').textContent).toContain('make start-searxng'));
    fireEvent.click(screen.getByRole('button', { name: 'Search the web' }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ webSearch: false }));
  });

  it('shows Ready when it can run', async () => {
    withSwitch(
      <ChatSettingsPopover open onClose={() => undefined} settings={{ ...DEFAULT_CHAT_SETTINGS, webSearch: true }} onChange={() => undefined} />,
      { on: true },
    );
    await waitFor(() => expect(screen.getByTestId('chat-web-search-status').textContent).toBe('Ready · SearXNG on this computer'));
  });
});

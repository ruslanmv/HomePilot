import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const read = (path) => readFileSync(resolve(ROOT, path), 'utf8');

const wrapper = read('frontend/src/ui/SettingsPanelWithMedia.tsx');
const vite = read('frontend/vite.config.ts');

describe('Audio & Video settings pane routing contract', () => {
  it('never accepts the navigation sidebar as the media content host', () => {
    expect(wrapper).toContain("node.tagName !== 'NAV'");
    expect(wrapper).toContain('!navElements.includes(node)');
    expect(wrapper).toContain("node.classList.contains('flex-1')");
    expect(wrapper).toContain("node.classList.contains('overflow-y-auto')");
  });

  it('mounts Audio & Video into the right content pane and lets it fill the pane', () => {
    expect(wrapper).toContain('content.appendChild(contentHost)');
    expect(wrapper).toContain("contentHost.style.width = '100%'");
    expect(wrapper).toContain("contentHost.style.minWidth = '0'");
    expect(wrapper).toContain("mounted.contentHost.style.display = 'block'");
  });

  it('keeps navigation mounted while replacing and restoring only main-pane content', () => {
    expect(wrapper).toContain('mounted.content.children');
    expect(wrapper).toContain("child.style.display = 'none'");
    expect(wrapper).toContain("child.setAttribute('data-hp-previous-display'");
    expect(wrapper).toContain("child.removeAttribute('data-hp-previous-display')");
    expect(wrapper).toContain('createPortal(<AudioVideoSettings />, mounted.contentHost)');
  });

  it('keeps the Vite redirect scoped to App.tsx so the wrapper resolves the canonical panel', () => {
    expect(vite).toContain("source === './SettingsPanel'");
    expect(vite).toContain("normalizedImporter.endsWith('/src/ui/App.tsx')");
    expect(vite).toContain('SETTINGS_WITH_MEDIA');
  });
});

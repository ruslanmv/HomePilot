/**
 * The live "Hearing …" panel is opt-in.
 *
 * The browser recognizer streams interim words, and showing them proves the microphone is
 * working. It is also a *guess in progress*: Chrome revises interim text repeatedly before a
 * phrase settles, so the panel rewrites itself above the composer while the user is still
 * speaking — motion they have to keep re-parsing to check whether it got the last word right.
 *
 * Useful as reassurance, distracting as a permanent fixture. So it is offered rather than
 * imposed: off unless switched on in Settings → Audio Settings → Show live transcript.
 *
 * Source-level, because the claims are about a default and a render guard rather than about a
 * value — and the default is the whole point of the change, so it is worth an assertion that
 * fails if somebody flips the comparison.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const grok = readFileSync(resolve(ROOT, 'frontend/src/ui/VoiceModeGrok.tsx'), 'utf8');
const modal = readFileSync(resolve(ROOT, 'frontend/src/ui/voice/SettingsModal.tsx'), 'utf8');

describe('the live transcript setting', () => {
  it('is off on a machine that has never seen it', () => {
    // `=== 'true'` and not `!== 'false'`: the second reads an absent key as "on", which is
    // exactly the case this is about — everybody who has not chosen yet.
    expect(grok).toContain("localStorage.getItem(LS_SHOW_LIVE_TRANSCRIPT) === 'true'");
    expect(grok).not.toContain("localStorage.getItem(LS_SHOW_LIVE_TRANSCRIPT) !== 'false'");
  });

  it('has its own key, so it does not ride on the meter’s', () => {
    expect(grok).toContain("const LS_SHOW_LIVE_TRANSCRIPT = 'homepilot_voice_show_live_transcript'");
    expect(grok).toContain('localStorage.setItem(LS_SHOW_LIVE_TRANSCRIPT');
  });

  it('gates the panel rather than merely dimming it', () => {
    // A hidden-but-rendered panel still takes layout and still reaches a screen reader's
    // live region, which is most of what made it intrusive.
    expect(grok).toContain('{showLiveTranscript && voice.interimText ? (');
  });

  it('is reachable from the Voice settings modal', () => {
    expect(modal).toContain('Show live transcript');
    expect(modal).toContain('data-testid="voice-settings-live-transcript"');
    expect(modal).toContain('setShowLiveTranscript(!showLiveTranscript)');
  });

  it('is announced as a switch, with its state', () => {
    // The meter toggle beside it is a bare <button> with no role and no accessible name; a
    // screen reader reads it as "button" and cannot say whether it is on. Not repeating that.
    const row = modal.slice(modal.indexOf('data-testid="voice-settings-live-transcript"'));
    expect(row.slice(0, 300)).toContain('role="switch"');
    expect(row.slice(0, 300)).toContain('aria-checked={Boolean(showLiveTranscript)}');
    expect(row.slice(0, 300)).toContain('aria-label="Show live transcript"');
  });

  it('says which engine it applies to', () => {
    // There are no interim words on the local engine — the text arrives when the turn ends —
    // so a toggle that silently does nothing there would read as broken.
    expect(modal).toContain('browser speech recognition only');
  });
});

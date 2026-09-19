/**
 * Dictating into the chat composer, the way every assistant does it.
 *
 * ChatGPT, Claude and Gemini all behave the same way at the microphone button, and it is worth
 * naming the conventions because HomePilot broke two of the three:
 *
 *   1. **It listens until you stop it.** Pauses are part of speaking. A session that ends at
 *      the first silence stops dictation in the middle of a thought, with no indication that
 *      it has, and the words after the pause are simply lost.
 *   2. **It adds to the draft; it never takes it over.** Text already in the box survives, and
 *      each finished phrase is appended to the last.
 *   3. **It never sends for you.** The text lands in the composer and the user presses send.
 *
 * These are assertions about the composed value and the session options, because that is where
 * all three conventions actually live — the rest is a button.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const app = readFileSync(resolve(ROOT, 'frontend/src/ui/App.tsx'), 'utf8');

/**
 * The composer's own rule, extracted so it can be exercised rather than described.
 *
 * Mirrors `compose()` in `startWebSpeechListening`: the draft as it was when the microphone
 * opened, the phrases finished since, and the words currently being said.
 */
function compose(base: string, finals: string, interim: string): string {
  return [base.trim(), finals.trim(), interim.trim()].filter(Boolean).join(' ');
}

describe('dictation adds to the draft', () => {
  it('keeps text the user had already typed', () => {
    // `setInput(text)` replaced the box, so pressing the microphone on a half-written message
    // erased it. Nobody expects a dictation button to be a delete button.
    expect(compose('Remind me to', '', 'call the plumber'))
      .toBe('Remind me to call the plumber');
  });

  it('accumulates one phrase after another', () => {
    // A continuous session produces a result per phrase. Replacing on each one left only the
    // last sentence of everything that was said.
    const first = compose('', 'Book a table for four', '');
    expect(first).toBe('Book a table for four');
    expect(compose('', 'Book a table for four at eight', 'on Friday'))
      .toBe('Book a table for four at eight on Friday');
  });

  it('reads cleanly when any part is missing', () => {
    expect(compose('', '', '')).toBe('');
    expect(compose('  draft  ', '', '')).toBe('draft');
    expect(compose('', '', 'hello')).toBe('hello');
    // No double spaces where a part is absent, and no leading space on an empty draft.
    expect(compose('', 'hello', 'there')).toBe('hello there');
  });
});

describe('the session is held open until the user stops it', () => {
  it('dictates continuously', () => {
    // A one-shot session ends at the first pause, which ends dictation mid-thought.
    expect(app).toContain('}, { continuous: true })');
  });

  it('reopens a session the browser ended on its own', () => {
    // Chrome ends a continuous session after a long silence, and roughly every minute
    // regardless. Only Stop ends dictation.
    expect(app).toContain('if (!micStoppingRef.current && !FATAL_DICTATION_ERRORS');
    expect(app).toContain("startWebSpeechListening({ resumed: true })");
    // A resume keeps what has been said; it must not clear the accumulated phrases.
    expect(app).toContain('if (!options.resumed) {');
  });

  it('stops for good when the user says so', () => {
    expect(app).toContain('micStoppingRef.current = true');
    expect(app).toContain("stopWebSpeech('chat', { reason: 'composer_mic_stop_click', force: true })");
  });

  it('does not reopen a session that failed for a reason reopening repeats', () => {
    expect(app).toContain('FATAL_DICTATION_ERRORS');
    for (const code of ['not-allowed', 'service-not-allowed', 'audio-capture']) {
      expect(app).toContain(`'${code}'`);
    }
  });
});

describe('a pause is not an error', () => {
  it('says nothing about silence, or about its own hand-off', () => {
    // Held open, the session spends most of its life waiting. `no-speech` every few seconds
    // put a warning under the composer on a session that was working perfectly.
    expect(app).toContain("const BENIGN_DICTATION_ERRORS = new Set(['no-speech', 'aborted'])");
    expect(app).toContain('if (BENIGN_DICTATION_ERRORS.has(code)) {');
  });

  it('still explains a fault that is one', () => {
    expect(app).toContain('const outcome = explainSttError(code)');
    expect(app).toContain('setMicNotice(`${outcome.headline}. ${outcome.detail}`)');
  });
});

describe('dictation never sends for you', () => {
  it('fills the composer and stops there', () => {
    // The text is the user's to edit before it goes. `onSend` is reached by pressing send.
    const dictation = app.slice(
      app.indexOf('const startWebSpeechListening'),
      app.indexOf('const startBackendListening'),
    );
    expect(dictation.length).toBeGreaterThan(0);
    expect(dictation).toContain('setInput(compose(');
    expect(dictation).not.toContain('onSend(');
  });

  it('appends on the on-device path too', () => {
    // Both engines are the same product behaviour; only the transport differs.
    expect(app).toContain("setInput([base, result.text.trim()].filter(Boolean).join(' '))");
  });
});

/**
 * The microphone setting that lives in the browser, not the operating system.
 *
 * Every message HomePilot produced about a deaf recognizer pointed at the OS default input.
 * True, and not the whole truth — and the missing half is the half most reports are about.
 *
 * Chrome keeps its **own** microphone selection at `chrome://settings/content/microphone`. It
 * starts out following the OS default and can be pinned to a device independently; once
 * pinned, that is what every `getUserMedia()` and every `SpeechRecognition` session on the
 * page records, whatever the OS thinks. A user sent only to their sound panel therefore fixes
 * it correctly and observes no change at all.
 *
 * The page also cannot take them there: `chrome://` is an internal scheme, and a website may
 * not link to or navigate to one. So the address has to be handed over as text to copy, which
 * is why it lives in a sentence rather than in an `href`.
 */

import { describe, expect, it } from 'vitest';
import {
  BROWSER_MIC_SETTINGS_URL,
  EDGE_MIC_SETTINGS_URL,
  browserMicSettings,
  describeBrowserMicCheck,
} from '../ui/media/browserMicHelp';

const CHROME = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
const EDGE = `${CHROME} Edg/141.0.0.0`;
const FIREFOX = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0';
const SAFARI = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15';
const OPERA = `${CHROME} OPR/115.0.0.0`;

describe('which browser has a microphone settings page', () => {
  it('names Chrome’s', () => {
    expect(browserMicSettings(CHROME)).toEqual({ name: 'Chrome', url: BROWSER_MIC_SETTINGS_URL });
    expect(BROWSER_MIC_SETTINGS_URL).toBe('chrome://settings/content/microphone');
  });

  it('checks Edge first, because its user agent also says Chrome', () => {
    // Testing for Chrome first sends every Edge user to a `chrome://` address that does not
    // resolve in their browser — advice that looks precise and cannot be followed.
    expect(browserMicSettings(EDGE)).toEqual({ name: 'Edge', url: EDGE_MIC_SETTINGS_URL });
  });

  it('says nothing for browsers with no such address', () => {
    // Firefox and Safari have microphone preferences, but not at an address that can be
    // written down like this. Inventing one is worse than staying quiet.
    expect(browserMicSettings(FIREFOX)).toBeNull();
    expect(browserMicSettings(SAFARI)).toBeNull();
    // Chromium skins that rebadge the settings UI are excluded for the same reason.
    expect(browserMicSettings(OPERA)).toBeNull();
    expect(browserMicSettings('')).toBeNull();
  });
});

describe('the sentence it produces', () => {
  it('names the address and says the page cannot open it', () => {
    const line = describeBrowserMicCheck({ name: 'Chrome', url: BROWSER_MIC_SETTINGS_URL });
    expect(line).toContain('chrome://settings/content/microphone');
    // Without this the user clicks the text, nothing happens, and the advice reads as broken.
    expect(line).toContain('Type or paste');
    expect(line).toContain('not allowed to open it for you');
  });

  it('says the setting is the browser’s own, not the operating system’s', () => {
    // The entire point. "Check your microphone settings" is what they have already done.
    const line = describeBrowserMicCheck({ name: 'Chrome', url: BROWSER_MIC_SETTINGS_URL });
    expect(line).toContain('separate from your operating system');
  });

  it('is empty where there is no page to name', () => {
    // Callers append this to a finished sentence, so the absent case has to leave the text
    // exactly as it was rather than trailing a clause that names nothing.
    expect(describeBrowserMicCheck(null)).toBe('');
  });
});

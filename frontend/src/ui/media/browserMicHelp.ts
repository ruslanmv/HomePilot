/**
 * The microphone setting that lives in the *browser*, not in the operating system.
 *
 * ── Why this file exists ─────────────────────────────────────────────────────────────────
 *
 * Everything HomePilot said about a deaf recognizer pointed at the operating system's default
 * input. That is true and it is not the whole truth, and the half that was missing is the half
 * that actually explains most reports.
 *
 * **Chrome keeps its own microphone selection**, at `chrome://settings/content/microphone`. It
 * starts out following the OS default, but it is a separate setting that can be pinned to a
 * device independently — and once pinned it is what every `getUserMedia()` and every
 * `SpeechRecognition` session on that machine records, whatever the operating system thinks
 * the default is. A user who fixes their Windows sound panel and finds nothing has changed has
 * hit exactly this: Chrome was never using the OS default in the first place.
 *
 * The device that ends up pinned there is usually one nobody chose — a virtual input shipped
 * with a game client or a headset suite, silent to every recorder, selected because it was
 * present when the permission was first granted. Naming the OS default alone sends that user
 * to the wrong panel.
 *
 * **And the page cannot take them there.** `chrome://` URLs are internal pages; a website
 * cannot navigate to one, cannot link to one, and cannot open one in a new tab — the
 * navigation is refused silently. So the address has to be given as *text to copy*, which is
 * the whole reason {@link BROWSER_MIC_SETTINGS_URL} is a string in the copy rather than an
 * `href` somewhere.
 *
 * ── The order to check things in ─────────────────────────────────────────────────────────
 *
 * Before touching `vad.ts`, `useVoiceController.ts`, `speech-service.js`, a threshold, or any
 * `SpeechRecognition` logic:
 *
 *   1. Is microphone permission allowed for the site at all?
 *   2. `chrome://settings/content/microphone` — is the correct *physical* microphone selected,
 *      rather than an Oculus/Steam/virtual input or a laptop array nobody speaks into?
 *   3. Site permissions for this origin — Microphone → Allow.
 *   4. Does Chrome show "Microphone — In use" while a turn is open? If it does, the browser has
 *      given HomePilot the device it selected, and the capture path is working.
 *   5. Only then is it HomePilot's code.
 *
 * Steps 1–4 are outside HomePilot's control. JavaScript can request permission and can
 * enumerate devices, but which device the browser hands over is the browser's decision unless
 * the application passes an explicit `deviceId` — and `SpeechRecognition` accepts none, which
 * is why the browser engine cannot opt out of this and the local engine can.
 */

/** The internal Chrome page that owns the browser's microphone selection. */
export const BROWSER_MIC_SETTINGS_URL = 'chrome://settings/content/microphone';

/** The Edge equivalent. Same engine, same behaviour, different scheme. */
export const EDGE_MIC_SETTINGS_URL = 'edge://settings/content/microphone';

/**
 * Whether this browser has a settings page of the kind above, and what it is called.
 *
 * Chromium-family only, and Edge is checked first because its user agent also contains
 * "Chrome" — testing for Chrome first would send every Edge user to a `chrome://` address that
 * does not resolve in their browser. Firefox and Safari return `null`: they have microphone
 * preferences too, but not at an address that can be written down like this, and inventing one
 * is worse than saying nothing.
 */
export function browserMicSettings(
  userAgent: string = typeof navigator === 'undefined' ? '' : navigator.userAgent,
): { name: string; url: string } | null {
  const ua = userAgent || '';
  if (/Edg\//.test(ua)) return { name: 'Edge', url: EDGE_MIC_SETTINGS_URL };
  // `Chromium` covers the Linux builds; the OPR/SamsungBrowser exclusions keep skins that
  // rebadge the settings UI from being told to open a page they do not have.
  if (/Chrome\/|Chromium\//.test(ua) && !/OPR\/|SamsungBrowser\//.test(ua)) {
    return { name: 'Chrome', url: BROWSER_MIC_SETTINGS_URL };
  }
  return null;
}

/**
 * The sentence to add to any "the microphone opened and heard nothing" message.
 *
 * Deliberately phrased as a *check*, not a diagnosis. HomePilot cannot read the browser's
 * microphone selection — there is no API for it — so this can only tell the user where to
 * look. Claiming to know what is selected there would be a guess dressed as a fact.
 *
 * Returns `''` on browsers with no such page, and every caller has to read correctly without
 * it rather than trailing a sentence that names nothing.
 */
export function describeBrowserMicCheck(
  settings: { name: string; url: string } | null = browserMicSettings(),
): string {
  if (!settings) return '';
  return (
    ` In ${settings.name}, check which microphone is selected at ${settings.url} — that is a `
    + 'browser setting separate from your operating system’s, and it decides what every '
    + 'recording on this page hears. Type or paste the address; a web page is not allowed to '
    + 'open it for you.'
  );
}

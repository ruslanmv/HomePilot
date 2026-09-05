/**
 * System audio for MeetingSense on the desktop (batch MS11).
 *
 * In a browser, `getDisplayMedia({ audio: true })` gets the call's audio only when the user
 * shares a *tab* and ticks a box; a window share carries no audio anywhere, and on Linux a
 * whole-screen share carries none either. So on the two platforms where most meetings happen,
 * the browser recorder often records one side of the conversation.
 *
 * Electron can do better, and only on one platform. `setDisplayMediaRequestHandler` may answer
 * with `audio: 'loopback'`, which is the machine's own output — everything the user hears,
 * including the other people in the call.
 *
 * **On Electron 33 that is Windows only.** There is no loopback on macOS: the platform has no
 * public API for capturing system output, and every product that appears to do it ships a
 * kernel extension or asks the user to install a virtual audio device (BlackHole, Loopback,
 * Soundflower). Shipping a kernel extension is not something this app is going to do quietly,
 * and pretending the option exists is worse than saying it does not — a user who believes the
 * call is being recorded and finds out afterwards that it was not has lost the meeting.
 *
 * So this module's real job is to be **honest about the platform**, and its output is a
 * sentence the popover shows before recording starts, not just a boolean.
 *
 * Deliberately a plain CommonJS module with no `require("electron")` at the top. Everything it
 * needs is passed in, which is what lets it be unit-tested in Node — an Electron main-process
 * file cannot be, and "manual QA on Windows and macOS" is not a test that runs in CI.
 */

/** Platforms whose Electron build can answer a display-media request with `audio: 'loopback'`. */
const LOOPBACK_PLATFORMS = ["win32"];

/** Read by the renderer, and by the popover. */
const MODES = {
  loopback: "loopback",
  mic: "mic",
};

function loopbackSupported(platform) {
  return LOOPBACK_PLATFORMS.indexOf(platform) !== -1;
}

/**
 * The sentence the popover shows. Written for the person about to record, not for a log.
 *
 * The macOS one names the workaround rather than stopping at "not supported": somebody who
 * records meetings weekly will install a virtual audio device once and never think about it
 * again, and they cannot do that if nobody told them it was the answer.
 */
function audioHint(platform, enabled) {
  if (!enabled) {
    return "Desktop system audio is off. The meeting records this microphone; turn on system audio in Settings to record the call as well.";
  }
  if (loopbackSupported(platform)) {
    return "The call's audio and this microphone are both recorded.";
  }
  if (platform === "darwin") {
    return "macOS cannot share system audio, so only this microphone is recorded. To record the call as well, install a virtual audio device (BlackHole or Loopback) and select it as the input.";
  }
  return "This platform cannot share system audio, so only this microphone is recorded.";
}

/** What the renderer is told. One object, so the popover never has to infer anything. */
function capabilities(options) {
  const opts = options || {};
  const platform = opts.platform || process.platform;
  const enabled = !!opts.enabled;
  const loopback = enabled && loopbackSupported(platform);
  return {
    desktop: true,
    enabled: enabled,
    platform: platform,
    // `supported` and `loopback` are two different facts and the popover needs both: off on
    // Windows means "turn it on in Settings", and off on macOS means nothing the user can do.
    // One flag conflating them would give a mac user advice that does not help.
    supported: loopbackSupported(platform),
    loopback: loopback,
    mode: loopback ? MODES.loopback : MODES.mic,
    hint: audioHint(platform, enabled),
  };
}

/**
 * The answer to one `getDisplayMedia` call.
 *
 * `audio: 'loopback'` is added **only** where it works. Sending it on macOS does not fail
 * loudly; the request resolves with a stream that has no audio track, and the recorder reports
 * `system+mic` for a meeting that recorded one side of itself.
 */
function displayMediaResponse(source, platform) {
  if (!source) return null;
  return loopbackSupported(platform)
    ? { video: source, audio: "loopback" }
    : { video: source };
}

/**
 * Register the handler, if the flag is on. Returns whether it did.
 *
 * **Nothing is registered when the flag is off**, which is the point rather than an
 * optimisation: an installed handler changes what every `getDisplayMedia` call in the app
 * does, including ScreenSense's, so a desktop build with MeetingSense off has to behave
 * exactly as it did before this batch.
 *
 * Everything is injected. An Electron main-process module that reaches for `electron` at
 * import time cannot be tested anywhere but inside Electron, and the decisions here — which
 * platform gets loopback, what happens when there is no source — are exactly the ones a manual
 * pass on two machines is worst at covering.
 */
function install(options) {
  const opts = options || {};
  const platform = opts.platform || process.platform;
  const log = opts.log || function () {};
  if (!opts.enabled) return false;

  const session = opts.session;
  const capturer = opts.desktopCapturer;
  if (!session || typeof session.setDisplayMediaRequestHandler !== "function") return false;

  session.setDisplayMediaRequestHandler(
    async (request, callback) => {
      try {
        const sources = await capturer.getSources({ types: ["screen", "window"] });
        if (!sources || !sources.length) {
          // An empty callback is a refusal, and a refusal the renderer can handle: the
          // recorder falls back to the microphone rather than failing to start.
          callback({});
          return;
        }
        callback(displayMediaResponse(sources[0], platform));
      } catch (err) {
        log("[MeetingSense] display media request failed:", err);
        callback({});
      }
    },
    // The OS picker where there is one: it is the dialog the user already recognises, and on
    // macOS it is the only one that can grant screen recording without a restart.
    { useSystemPicker: true },
  );
  return true;
}

module.exports = {
  LOOPBACK_PLATFORMS,
  MODES,
  loopbackSupported,
  audioHint,
  capabilities,
  displayMediaResponse,
  install,
};

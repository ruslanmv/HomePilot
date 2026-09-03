/**
 * Preload script — exposes a safe bridge between Electron and the renderer.
 */

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("homepilot", {
  // Marks the renderer as running inside the native desktop shell.
  // ScreenSense uses this to pick native local capture over browser screen-share.
  isDesktop: true,

  // Splash screen
  onSplashUpdate: (callback) => {
    ipcRenderer.on("splash-update", (_event, data) => callback(data));
  },

  // Setup wizard
  setupComplete: (data) => ipcRenderer.send("setup-complete", data),
  setupSkip: () => ipcRenderer.send("setup-skip"),

  // ScreenSense — native, fully-local screen capture (desktop only).
  // Returns a PNG data URL of the primary display, captured in the main
  // process via Electron's desktopCapturer. No browser share dialog: on the
  // user's own machine the app already holds screen-recording permission.
  // Resolves to null if capture is unavailable or denied by the OS.
  captureScreen: () => ipcRenderer.invoke("screensense:capture"),

  // MeetingSense — what system audio this machine can actually capture (MS11).
  //
  // Answered whether the flag is on or off, because "system audio is off" is a sentence the
  // consent popover needs as much as "it is on". On Electron 33 loopback is Windows-only:
  // macOS has no public API for capturing system output, so the hint names the virtual audio
  // device workaround rather than stopping at "unsupported". Resolves to null if the main
  // process could not answer, which the renderer should read as "browser rules apply".
  meetingSenseAudio: () => ipcRenderer.invoke("meetingsense:audio"),
});

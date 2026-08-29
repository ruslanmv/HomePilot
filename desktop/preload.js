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
});

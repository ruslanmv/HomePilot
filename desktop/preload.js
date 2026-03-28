/**
 * Preload script — exposes a safe bridge between Electron and the renderer.
 */

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("homepilot", {
  // Splash screen
  onSplashUpdate: (callback) => {
    ipcRenderer.on("splash-update", (_event, data) => callback(data));
  },

  // Setup wizard
  setupComplete: (data) => ipcRenderer.send("setup-complete", data),
  setupSkip: () => ipcRenderer.send("setup-skip"),
});

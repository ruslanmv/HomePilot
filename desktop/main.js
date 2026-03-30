/**
 * HomePilot Desktop — Electron main process.
 *
 * Manages the Docker container lifecycle and provides a native app shell
 * around the HomePilot web UI running at localhost:7860.
 */

const {
  app,
  BrowserWindow,
  Tray,
  Menu,
  shell,
  dialog,
  nativeImage,
  ipcMain,
} = require("electron");
const path = require("path");
const Store = require("electron-store");
const { DockerManager, PORT } = require("./docker-manager");

// Single-instance lock
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
}

// ── State ─────────────────────────────────────────────────────────────────

const store = new Store({
  defaults: {
    openaiKey: "",
    anthropicKey: "",
    llmBackend: "openai",
    launchOnStartup: false,
    minimizeToTray: true,
    setupComplete: false,
  },
});

const docker = new DockerManager();
let mainWindow = null;
let splashWindow = null;
let setupWindow = null;
let tray = null;
let isQuitting = false;

// ── Splash screen ─────────────────────────────────────────────────────────

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 520,
    height: 400,
    frame: false,
    transparent: false,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    backgroundColor: "#050a18",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
    },
  });

  splashWindow.loadFile(path.join(__dirname, "splash.html"));
  splashWindow.center();
}

function updateSplash(message, percent = -1) {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.send("splash-update", { message, percent });
  }
}

function closeSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.close();
    splashWindow = null;
  }
}

// ── Setup wizard (first run) ──────────────────────────────────────────────

function createSetupWindow() {
  return new Promise((resolve) => {
    setupWindow = new BrowserWindow({
      width: 560,
      height: 640,
      frame: false,
      resizable: false,
      backgroundColor: "#050a18",
      icon: getIconPath(),
      webPreferences: {
        preload: path.join(__dirname, "preload.js"),
        contextIsolation: true,
      },
    });

    setupWindow.loadFile(path.join(__dirname, "setup.html"));
    setupWindow.center();

    ipcMain.once("setup-complete", (_event, data) => {
      if (data.openaiKey) store.set("openaiKey", data.openaiKey);
      if (data.anthropicKey) store.set("anthropicKey", data.anthropicKey);
      if (data.llmBackend) store.set("llmBackend", data.llmBackend);
      store.set("setupComplete", true);
      setupWindow.close();
      setupWindow = null;
      resolve();
    });

    ipcMain.once("setup-skip", () => {
      store.set("setupComplete", true);
      setupWindow.close();
      setupWindow = null;
      resolve();
    });
  });
}

// ── Main window ───────────────────────────────────────────────────────────

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 900,
    minHeight: 640,
    title: "HomePilot",
    icon: getIconPath(),
    show: false,
    backgroundColor: "#0a0f1e",
    titleBarStyle: process.platform === "darwin" ? "hiddenInset" : "default",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Show branded loading page first, switch to app when ready
  mainWindow.loadFile(path.join(__dirname, "loading.html"));
  mainWindow.once("ready-to-show", () => {
    closeSplash();
    mainWindow.show();
    mainWindow.focus();
    // Now load the actual app
    tryLoadApp();
  });

  mainWindow.on("close", (e) => {
    if (!isQuitting && store.get("minimizeToTray")) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

async function tryLoadApp() {
  // Poll until backend responds, then navigate
  const maxAttempts = 40;
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const res = await fetch(`http://localhost:${PORT}/api/health`);
      if (res.ok) {
        mainWindow.loadURL(`http://localhost:${PORT}`);
        return;
      }
    } catch {
      // Not ready yet
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  // Fallback — try loading anyway
  mainWindow.loadURL(`http://localhost:${PORT}`);
}

// ── System tray ───────────────────────────────────────────────────────────

function createTray() {
  const icon = nativeImage.createFromPath(getTrayIconPath());
  tray = new Tray(icon.resize({ width: 16, height: 16 }));
  tray.setToolTip("HomePilot — AI Assistant");

  const contextMenu = Menu.buildFromTemplate([
    {
      label: "Open HomePilot",
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      },
    },
    { type: "separator" },
    {
      label: "Open in Browser",
      click: () => shell.openExternal(`http://localhost:${PORT}`),
    },
    { type: "separator" },
    {
      label: "Check for Updates",
      click: () => checkForContainerUpdate(true),
    },
    { type: "separator" },
    {
      label: "Restart Container",
      click: async () => {
        await docker.stop();
        await startContainer();
      },
    },
    {
      label: "Stop Container",
      click: () => docker.stop(),
    },
    { type: "separator" },
    {
      label: "Quit HomePilot",
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);
  tray.on("click", () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

// ── Icon helpers ──────────────────────────────────────────────────────────

function getIconPath() {
  const iconsDir = path.join(__dirname, "icons");
  if (process.platform === "win32") return path.join(iconsDir, "icon.ico");
  if (process.platform === "darwin") return path.join(iconsDir, "icon.icns");
  return path.join(iconsDir, "icon.png");
}

function getTrayIconPath() {
  return path.join(__dirname, "icons", "tray-icon.png");
}

// ── Docker bootstrap ──────────────────────────────────────────────────────

async function startContainer() {
  const envVars = {
    OPENAI_API_KEY: store.get("openaiKey"),
    ANTHROPIC_API_KEY: store.get("anthropicKey"),
    HOMEPILOT_LLM_BACKEND: store.get("llmBackend"),
  };
  await docker.start(envVars);
}

async function bootstrap() {
  createSplash();

  // Step 0: First-run setup wizard
  if (!store.get("setupComplete")) {
    closeSplash();
    await createSetupWindow();
    createSplash();
  }

  // Step 1: Check Docker
  updateSplash("Checking Docker environment...");
  const dockerOk = await docker.isDockerRunning();
  if (!dockerOk) {
    closeSplash();
    const { response } = await dialog.showMessageBox({
      type: "error",
      title: "Docker Required",
      message: "Docker is not running.",
      detail:
        "HomePilot needs Docker Desktop to run.\n\n" +
        "Please install and start Docker Desktop, then relaunch HomePilot.\n\n" +
        "Download: https://www.docker.com/products/docker-desktop/",
      buttons: ["Download Docker", "Quit"],
      defaultId: 0,
    });
    if (response === 0) {
      shell.openExternal("https://www.docker.com/products/docker-desktop/");
    }
    app.quit();
    return;
  }

  // Step 2: Pull image if missing
  const hasImage = await docker.hasImage();
  if (!hasImage) {
    updateSplash("Downloading HomePilot (first time only)...", 0);
    docker.on("pull-progress", ({ percent }) => {
      updateSplash(`Downloading HomePilot... ${percent}%`, percent);
    });
    try {
      await docker.pullImage();
    } catch (err) {
      closeSplash();
      dialog.showErrorBox(
        "Download Failed",
        `Could not download the HomePilot image.\n\n${err.message}\n\nPlease check your internet connection and try again.`
      );
      app.quit();
      return;
    }
  }

  // Step 3: Start container
  const alreadyRunning = await docker.isContainerRunning();
  if (!alreadyRunning) {
    updateSplash("Starting AI services...");
    try {
      await startContainer();
    } catch (err) {
      closeSplash();
      dialog.showErrorBox(
        "Start Failed",
        `Could not start the HomePilot container.\n\n${err.message}`
      );
      app.quit();
      return;
    }
  }

  // Step 4: Wait for healthy
  updateSplash("Initializing backend...");
  await docker.waitForHealthy(15000); // Quick check, main window has its own retry

  // Step 5: Show main window (with branded loading state)
  createMainWindow();
  createTray();

  // Step 6: Check for updates once at launch (non-blocking, after UI is ready)
  setTimeout(() => checkForContainerUpdate(false), 30 * 1000);
}

// ── Container updates ─────────────────────────────────────────────────────
//
// Best-practice update flow (like VS Code, Slack, Spotify):
//   1. Check once at app launch (non-blocking, after UI is ready).
//   2. If an update exists, show a non-intrusive native notification.
//   3. User clicks "Update Now" → apply; or "Later" → dismiss.
//   4. Manual "Check for Updates" in tray menu always works.
//   5. No recurring timers or scheduled polling.
//

async function checkForContainerUpdate(userInitiated) {
  try {
    // Only show a blocking "checking" dialog when the user explicitly asks
    if (userInitiated && mainWindow && !mainWindow.isDestroyed()) {
      dialog.showMessageBox(mainWindow, {
        type: "info",
        title: "Checking for Updates",
        message: "Checking for a newer version of HomePilot...",
        buttons: ["OK"],
      });
    }

    const result = await docker.checkForUpdate();

    // ── Network / registry error ──
    if (result.error) {
      if (userInitiated && mainWindow && !mainWindow.isDestroyed()) {
        dialog.showMessageBox(mainWindow, {
          type: "warning",
          title: "Update Check Failed",
          message: "Could not check for updates.",
          detail: result.error,
          buttons: ["OK"],
        });
      }
      return;
    }

    // ── Already up to date ──
    if (!result.available) {
      if (userInitiated && mainWindow && !mainWindow.isDestroyed()) {
        dialog.showMessageBox(mainWindow, {
          type: "info",
          title: "No Updates",
          message: "HomePilot is up to date.",
          buttons: ["OK"],
        });
      }
      return;
    }

    // ── Update available ──
    // For automatic (launch) checks: show a non-intrusive OS notification
    // For manual checks: show a dialog immediately
    if (!userInitiated) {
      const notification = new (require("electron").Notification)({
        title: "HomePilot Update Available",
        body: "A new version is ready. Click to update.",
        icon: getIconPath(),
        silent: true,
      });
      notification.on("click", () => promptAndApplyUpdate());
      notification.show();
    } else {
      await promptAndApplyUpdate();
    }
  } catch (err) {
    if (userInitiated) {
      dialog.showErrorBox("Update Error", err.message);
    }
  }
}

async function promptAndApplyUpdate() {
  if (!mainWindow || mainWindow.isDestroyed()) return;

  const { response } = await dialog.showMessageBox(mainWindow, {
    type: "info",
    title: "Update Available",
    message: "A new version of HomePilot is available.",
    detail:
      "The update has been downloaded. Applying it will restart HomePilot.\n\n" +
      "Your data and settings are preserved.",
    buttons: ["Update Now", "Later"],
    defaultId: 0,
    cancelId: 1,
  });

  if (response === 0) {
    const envVars = {
      OPENAI_API_KEY: store.get("openaiKey"),
      ANTHROPIC_API_KEY: store.get("anthropicKey"),
      HOMEPILOT_LLM_BACKEND: store.get("llmBackend"),
    };
    await docker.applyUpdate(envVars);

    // Reload the main window to pick up any frontend changes
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.loadURL(`http://localhost:${PORT}`);
    }
  }
}

// ── App lifecycle ─────────────────────────────────────────────────────────

app.on("second-instance", () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  }
});

app.on("ready", bootstrap);

app.on("window-all-closed", () => {
  // Keep running in tray on all platforms
});

app.on("activate", () => {
  if (mainWindow) {
    mainWindow.show();
  }
});

app.on("before-quit", () => {
  isQuitting = true;
});

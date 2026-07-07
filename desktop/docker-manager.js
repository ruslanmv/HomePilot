/**
 * Docker Manager — pulls, starts, stops, and monitors the HomePilot container.
 *
 * Uses `dockerode` to talk to the local Docker daemon (socket or named pipe).
 */

const Docker = require("dockerode");
const { EventEmitter } = require("events");

const IMAGE = "ruslanmv/homepilot";
const TAG = "latest";
const FULL_IMAGE = `${IMAGE}:${TAG}`;
const CONTAINER_NAME = "homepilot-desktop";
const PORT = 7860;

// ── OllaBridge Local sidecar (provider node) ─────────────────────────────────
// The installed (desktop) HomePilot is a *provider*: it can expose its GPU/models
// to the user's OllaBridge account. We run the official `ruslanmv/ollabridge`
// package (v0.1.5+) as a sidecar container next to HomePilot on a shared Docker
// network. It serves an OpenAI-compatible gateway + dashboard on :11435 and
// dials OUT to OllaBridge Cloud (no port forwarding). Best-effort: if it can't
// start, HomePilot runs exactly as before — nothing about the local app breaks.
//
// Guardrail (installed ≠ paired ≠ shared): the sidecar is installed + running by
// default, but PAIRING and SHARING are opt-in — the user drives them from the
// OllaBridge dashboard (:11435/ui) or HomePilot's "OllaBridge Link" tab. And
// GPU generation advertisement is itself opt-in via OLLABRIDGE_NODE_GEN_ENABLED
// (default off), matching the upstream default.
const SIDECAR_IMAGE = "ruslanmv/ollabridge";
const SIDECAR_TAG = "latest";
const SIDECAR_FULL_IMAGE = `${SIDECAR_IMAGE}:${SIDECAR_TAG}`;
const SIDECAR_CONTAINER = "ollabridge-local";
const SIDECAR_PORT = 11435; // `ollabridge start` canonical port (dashboard at /ui)
const NETWORK_NAME = "homepilot-local";
const DEFAULT_CLOUD_URL = "https://ruslanmv-ollabridge.hf.space";

class DockerManager extends EventEmitter {
  constructor() {
    super();
    this.docker = new Docker();
    this.container = null;
  }

  // ── Health ──────────────────────────────────────────────────────────────

  /** Check if Docker daemon is reachable */
  async isDockerRunning() {
    try {
      await this.docker.ping();
      return true;
    } catch {
      return false;
    }
  }

  /** Check if the container is currently running */
  async isContainerRunning() {
    try {
      const container = this.docker.getContainer(CONTAINER_NAME);
      const info = await container.inspect();
      return info.State.Running;
    } catch {
      return false;
    }
  }

  // ── Image ───────────────────────────────────────────────────────────────

  /** Check if image exists locally */
  async hasImage() {
    try {
      await this.docker.getImage(FULL_IMAGE).inspect();
      return true;
    } catch {
      return false;
    }
  }

  /** Pull image with progress events */
  async pullImage() {
    this.emit("status", "Downloading HomePilot...");

    const stream = await this.docker.pull(FULL_IMAGE);

    return new Promise((resolve, reject) => {
      const layers = {};

      this.docker.modem.followProgress(
        stream,
        (err) => {
          if (err) {
            this.emit("error", `Pull failed: ${err.message}`);
            return reject(err);
          }
          this.emit("pull-complete");
          resolve();
        },
        (event) => {
          // Track per-layer progress
          if (event.id && event.progressDetail) {
            const { current, total } = event.progressDetail;
            if (current && total) {
              layers[event.id] = { current, total };
              const sumCurrent = Object.values(layers).reduce((s, l) => s + l.current, 0);
              const sumTotal = Object.values(layers).reduce((s, l) => s + l.total, 0);
              const pct = Math.round((sumCurrent / sumTotal) * 100);
              this.emit("pull-progress", { percent: pct, status: event.status });
            }
          }
          if (event.status) {
            this.emit("status", event.status);
          }
        }
      );
    });
  }

  // ── Container lifecycle ─────────────────────────────────────────────────

  /** Start (or create + start) the container */
  async start(envVars = {}) {
    // Remove stale container with same name (stopped)
    try {
      const old = this.docker.getContainer(CONTAINER_NAME);
      const info = await old.inspect();
      if (info.State.Running) {
        this.container = old;
        this.emit("status", "HomePilot is already running");
        return;
      }
      await old.remove({ force: true });
    } catch {
      // No existing container — fine
    }

    this.emit("status", "Starting HomePilot...");

    // Ensure the shared network exists so HomePilot and the OllaBridge sidecar
    // can reach each other by container name. Best-effort — a failure here just
    // means the sidecar (optional) won't be reachable; HomePilot still runs.
    await this.ensureNetwork();

    // Edition + sidecar wiring (additive). Mark this as the *local* edition and
    // tell the backend where to probe the sidecar (over the shared network).
    const mergedEnv = {
      HOMEPILOT_EDITION: "local",
      OLLABRIDGE_LOCAL_URL: `http://${SIDECAR_CONTAINER}:${SIDECAR_PORT}`,
      ...envVars,
    };

    // Build env array
    const env = Object.entries(mergedEnv)
      .filter(([, v]) => v)
      .map(([k, v]) => `${k}=${v}`);

    // Detect GPU support
    let deviceRequests = [];
    try {
      const info = await this.docker.info();
      const runtimes = info.Runtimes || {};
      if (runtimes.nvidia || info.DefaultRuntime === "nvidia") {
        deviceRequests = [{ Driver: "", Count: -1, Capabilities: [["gpu"]] }];
        this.emit("status", "GPU detected — enabling NVIDIA acceleration");
      }
    } catch {
      // No GPU info available
    }

    this.container = await this.docker.createContainer({
      Image: FULL_IMAGE,
      name: CONTAINER_NAME,
      Env: env,
      ExposedPorts: { [`${PORT}/tcp`]: {} },
      HostConfig: {
        PortBindings: { [`${PORT}/tcp`]: [{ HostPort: String(PORT) }] },
        Binds: ["homepilot-data:/home/user/app/data"],
        RestartPolicy: { Name: "unless-stopped" },
        DeviceRequests: deviceRequests,
        NetworkMode: NETWORK_NAME,
      },
    });

    await this.container.start();
    this.emit("status", "HomePilot is running");
  }

  // ── OllaBridge Local sidecar ────────────────────────────────────────────

  /** Create the shared Docker network if it doesn't already exist. */
  async ensureNetwork() {
    try {
      const nets = await this.docker.listNetworks({ filters: { name: [NETWORK_NAME] } });
      if (!nets.some((n) => n.Name === NETWORK_NAME)) {
        await this.docker.createNetwork({ Name: NETWORK_NAME, Driver: "bridge" });
      }
    } catch (err) {
      // Non-fatal: sidecar simply won't be reachable by name.
      this.emit("status", `Network setup skipped: ${err.message}`);
    }
  }

  async hasSidecarImage() {
    try {
      await this.docker.getImage(SIDECAR_FULL_IMAGE).inspect();
      return true;
    } catch {
      return false;
    }
  }

  async pullSidecarImage() {
    this.emit("status", "Downloading OllaBridge Local...");
    const stream = await this.docker.pull(SIDECAR_FULL_IMAGE);
    return new Promise((resolve, reject) => {
      this.docker.modem.followProgress(
        stream,
        (err) => (err ? reject(err) : resolve()),
        (event) => { if (event.status) this.emit("status", event.status); },
      );
    });
  }

  async isSidecarRunning() {
    try {
      const info = await this.docker.getContainer(SIDECAR_CONTAINER).inspect();
      return info.State.Running;
    } catch {
      return false;
    }
  }

  /**
   * Start (or create + start) the OllaBridge Local sidecar. Best-effort and
   * NON-FATAL: any failure is emitted as status and swallowed so it can never
   * block HomePilot. Provider sharing/pairing remain opt-in (driven from the UI
   * / :11435/ui dashboard); this only ensures the sidecar is installed+running.
   *
   * @param {object} opts
   * @param {string} [opts.cloudUrl]   OllaBridge Cloud base URL
   * @param {boolean} [opts.genEnabled] Advertise GPU + run ComfyUI generation (opt-in)
   * @param {string} [opts.workflowsDir] Container path to ComfyUI workflow templates
   */
  async startSidecar(opts = {}) {
    try {
      await this.ensureNetwork();

      // Reuse a running sidecar; clear a stale (stopped) one.
      try {
        const old = this.docker.getContainer(SIDECAR_CONTAINER);
        const info = await old.inspect();
        if (info.State.Running) {
          this.emit("status", "OllaBridge Local already running");
          return true;
        }
        await old.remove({ force: true });
      } catch {
        /* none */
      }

      if (!(await this.hasSidecarImage())) {
        try {
          await this.pullSidecarImage();
        } catch (err) {
          this.emit("status", `OllaBridge Local unavailable (image pull failed): ${err.message}`);
          return false;
        }
      }

      // Share the GPU with the sidecar so it can run generation when enabled.
      let deviceRequests = [];
      try {
        const info = await this.docker.info();
        const runtimes = info.Runtimes || {};
        if (runtimes.nvidia || info.DefaultRuntime === "nvidia") {
          deviceRequests = [{ Driver: "", Count: -1, Capabilities: [["gpu"]] }];
        }
      } catch {
        /* no gpu info */
      }

      const env = {
        // Cloud + local wiring (dial-out; no inbound ports needed on the PC).
        OLLABRIDGE_CLOUD_URL: opts.cloudUrl || DEFAULT_CLOUD_URL,
        // Point the node's runtimes at HomePilot's services over the shared net.
        OLLABRIDGE_HOMEPILOT_URL: `http://${CONTAINER_NAME}:${PORT}`,
        OLLABRIDGE_COMFYUI_URL: `http://${CONTAINER_NAME}:8188`,
        // GPU generation advertise is OPT-IN (default off), matching upstream.
        OLLABRIDGE_NODE_GEN_ENABLED: opts.genEnabled ? "true" : "false",
        // Persist pairing/device config across restarts.
        OLLABRIDGE_HOME: "/data",
        // Headless container — never try to open a browser.
        OLLABRIDGE_NO_BROWSER: "1",
      };
      if (opts.workflowsDir) env.OLLABRIDGE_COMFYUI_WORKFLOWS_DIR = opts.workflowsDir;

      const sidecar = await this.docker.createContainer({
        Image: SIDECAR_FULL_IMAGE,
        name: SIDECAR_CONTAINER,
        // Run the turnkey gateway on the canonical port so the dashboard lives
        // at http://localhost:11435/ui and the backend probe (OLLABRIDGE_LOCAL_URL)
        // resolves over the shared network.
        Cmd: ["ollabridge", "start", "--host", "0.0.0.0", "--port", String(SIDECAR_PORT)],
        Env: Object.entries(env).filter(([, v]) => v).map(([k, v]) => `${k}=${v}`),
        ExposedPorts: { [`${SIDECAR_PORT}/tcp`]: {} },
        HostConfig: {
          // Bind to localhost only — the dashboard/API must never be exposed
          // on the LAN; sharing goes out through the Cloud relay, not this port.
          PortBindings: { [`${SIDECAR_PORT}/tcp`]: [{ HostIp: "127.0.0.1", HostPort: String(SIDECAR_PORT) }] },
          Binds: ["ollabridge-local-data:/data"],
          RestartPolicy: { Name: "unless-stopped" },
          DeviceRequests: deviceRequests,
          NetworkMode: NETWORK_NAME,
        },
      });
      await sidecar.start();
      this.emit("status", "OllaBridge Local is running");
      return true;
    } catch (err) {
      // NEVER fatal — HomePilot works without the provider sidecar.
      this.emit("status", `OllaBridge Local not started (optional): ${err.message}`);
      return false;
    }
  }

  async stopSidecar() {
    try {
      await this.docker.getContainer(SIDECAR_CONTAINER).stop({ t: 10 });
    } catch (err) {
      if (err.statusCode !== 304 && err.statusCode !== 404) {
        this.emit("status", `OllaBridge Local stop: ${err.message}`);
      }
    }
  }

  /** Stop the container */
  async stop() {
    try {
      const container = this.docker.getContainer(CONTAINER_NAME);
      await container.stop({ t: 10 });
      this.emit("status", "HomePilot stopped");
    } catch (err) {
      if (err.statusCode !== 304) {
        this.emit("error", `Stop failed: ${err.message}`);
      }
    }
  }

  /** Remove the container entirely */
  async remove() {
    try {
      const container = this.docker.getContainer(CONTAINER_NAME);
      await container.remove({ force: true });
    } catch {
      // Already gone
    }
  }

  /** Wait for the backend health endpoint to respond */
  async waitForHealthy(timeoutMs = 60000) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      try {
        const res = await fetch(`http://localhost:${PORT}/api/health`);
        if (res.ok) return true;
      } catch {
        // Not ready yet
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
    return false;
  }

  // ── Updates ─────────────────────────────────────────────────────────────

  /** Get the local image digest (sha256) */
  async getLocalDigest() {
    try {
      const img = await this.docker.getImage(FULL_IMAGE).inspect();
      // RepoDigests contains "ruslanmv/homepilot@sha256:abc..."
      const digests = img.RepoDigests || [];
      const match = digests.find((d) => d.startsWith(IMAGE));
      return match ? match.split("@")[1] : null;
    } catch {
      return null;
    }
  }

  /**
   * Check if a newer image is available on the registry.
   * Pulls the manifest only (not the full image) by doing a pull
   * and comparing digests before/after.
   *
   * Returns { available: true, localDigest, remoteDigest } or { available: false }
   */
  async checkForUpdate() {
    const localDigest = await this.getLocalDigest();

    // Pull latest — Docker only downloads changed layers
    try {
      await this.pullImage();
    } catch {
      return { available: false, error: "Could not reach registry" };
    }

    const newDigest = await this.getLocalDigest();

    if (!localDigest || !newDigest) {
      return { available: false };
    }

    return {
      available: localDigest !== newDigest,
      localDigest,
      remoteDigest: newDigest,
    };
  }

  /**
   * Apply an update: stop the old container, remove it, and start fresh
   * with the newly pulled image.
   */
  async applyUpdate(envVars = {}) {
    this.emit("status", "Updating HomePilot...");
    await this.stop();
    await this.remove();
    await this.start(envVars);
    this.emit("status", "Update complete — HomePilot restarted");
  }

  /** Get container logs stream */
  async logs(tail = 100) {
    try {
      const container = this.docker.getContainer(CONTAINER_NAME);
      const stream = await container.logs({
        stdout: true,
        stderr: true,
        tail,
        follow: false,
      });
      return stream.toString("utf8");
    } catch {
      return "";
    }
  }
}

module.exports = {
  DockerManager,
  CONTAINER_NAME,
  PORT,
  FULL_IMAGE,
  SIDECAR_CONTAINER,
  SIDECAR_PORT,
  SIDECAR_FULL_IMAGE,
  NETWORK_NAME,
};

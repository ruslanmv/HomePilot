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

    // Build env array
    const env = Object.entries(envVars)
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
      },
    });

    await this.container.start();
    this.emit("status", "HomePilot is running");
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

module.exports = { DockerManager, CONTAINER_NAME, PORT, FULL_IMAGE };

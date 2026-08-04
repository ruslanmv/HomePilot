import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const testComputeSource = vi.hoisted(() => vi.fn(async () => ({ ok: true, reason: "Reachable." })));
const putComputeSettings = vi.hoisted(() => vi.fn(async (p) => ({ computeMode: p.computeMode })));
const syncFromCloud = vi.hoisted(() => vi.fn(async () => ({ ok: true, linked: true, devices: 1, models: 4 })));

vi.mock("../../api", () => ({
  computeClient: {
    getComputeStatus: async () => ({ message: "Using this PC — Private GPU", localGpuAvailable: true }),
    getLocalResources: async () => ({
      gpus: [{ index: 0, available: true, name: "GeForce RTX 4090", vramTotalMb: 24576, usedPercent: 25, utilizationPercent: 10 }],
      gpu: { available: true },
      cpu: { name: "Core i9-13900K", logicalCores: 32, percent: 12 },
      ram: { percent: 40 },
    }),
    listComputeSources: async () => [
      { id: "colab", name: "Google Colab", kind: "ollabridge", enabled: true, executionType: "relay" },
    ],
    listComputeDevices: async () => [
      { id: "t4", sourceId: "colab", name: "Colab T4", online: true, onlineEffective: true, ephemeral: true,
        gpuName: "NVIDIA T4", vramMb: 16384, capacity: 1, activeJobs: 0, heartbeatAgeS: 8 },
    ],
    listModelManifests: async () => [],
    getComputeSettings: async () => ({ computeMode: "local" }),
    testComputeSource,
    putComputeSettings,
    syncFromCloud,
    deleteComputeSource: async () => undefined,
  },
}));

import ComputeResourcesPanel from "./ComputeResourcesPanel";

beforeEach(() => {
  testComputeSource.mockClear();
  putComputeSettings.mockClear();
  syncFromCloud.mockClear();
});

describe("ComputeResourcesPanel", () => {
  it("renders local GPU, an ephemeral online device, and tests a source", async () => {
    render(<ComputeResourcesPanel />);

    await waitFor(() => expect(screen.getByText("GeForce RTX 4090")).toBeInTheDocument());
    // Local status + device presentation.
    expect(screen.getByText(/Using this PC/)).toBeInTheDocument();
    expect(screen.getByText("Colab T4")).toBeInTheDocument();
    expect(screen.getByText("Ephemeral")).toBeInTheDocument();
    // "Online" appears for both This PC and the device badge.
    expect(screen.getAllByText("Online").length).toBeGreaterThanOrEqual(1);

    // Test action calls the source-test endpoint and shows the result.
    fireEvent.click(screen.getByText("Test"));
    await waitFor(() => expect(testComputeSource).toHaveBeenCalledWith("colab"));
    await waitFor(() => expect(screen.getByText("✓ Reachable")).toBeInTheDocument());
  });

  it("syncs devices from OllaBridge Cloud and reports the result", async () => {
    render(<ComputeResourcesPanel />);
    await waitFor(() => expect(screen.getByText("Sync from Cloud")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Sync from Cloud"));
    await waitFor(() => expect(syncFromCloud).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByText(/Synced 1 device · 4 models/)).toBeInTheDocument(),
    );
  });

  it("toggles the global remote-resources default to auto", async () => {
    render(<ComputeResourcesPanel />);
    await waitFor(() => expect(screen.getByText(/Use remote resources/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("checkbox"));
    await waitFor(() =>
      expect(putComputeSettings).toHaveBeenCalledWith({ computeMode: "auto" }),
    );
  });
});

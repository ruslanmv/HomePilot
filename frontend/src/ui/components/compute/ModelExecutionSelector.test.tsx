import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// Mock the app api module so the component talks to an in-memory client.
// vi.mock is hoisted, so the fns must be created via vi.hoisted.
const { upsertRoute, deleteRoute } = vi.hoisted(() => ({
  upsertRoute: vi.fn(async (r: unknown) => r),
  deleteRoute: vi.fn(async () => undefined),
}));

vi.mock("../../api", () => ({
  computeClient: {
    listComputeSources: async () => [
      { id: "oa", name: "My vLLM", kind: "openai_compatible", enabled: true, executionType: "direct" },
    ],
    listComputeDevices: async () => [
      { id: "colab", sourceId: "ob", name: "Colab T4", online: true, ephemeral: true, capacity: 1, activeJobs: 0, onlineEffective: true },
    ],
    listModelManifests: async () => [],
    listRoutes: async () => [],
    upsertRoute,
    deleteRoute,
  },
}));

import ModelExecutionSelector from "./ModelExecutionSelector";

beforeEach(() => {
  upsertRoute.mockClear();
  deleteRoute.mockClear();
});

describe("ModelExecutionSelector", () => {
  it("renders execution options and pins a route on change", async () => {
    render(<ModelExecutionSelector modelId="deepseek-r1" modality="chat" />);

    // The "Runs on" select appears once data loads.
    await waitFor(() => expect(screen.getByText("Runs on")).toBeInTheDocument());
    const selects = screen.getAllByRole("combobox");
    const runsOn = selects[0];

    // The "Runs on" select offers Auto, This PC, and the online Colab device.
    const labels = Array.from(runsOn.querySelectorAll("option")).map((o) => o.textContent);
    expect(labels).toEqual(expect.arrayContaining(["Auto", "This PC", "Colab T4"]));

    fireEvent.change(runsOn, { target: { value: "device:colab" } });

    await waitFor(() =>
      expect(upsertRoute).toHaveBeenCalledWith(
        expect.objectContaining({ modelId: "deepseek-r1", primaryTarget: "device:colab" }),
      ),
    );
  });
});

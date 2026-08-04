import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import RouteBadge from "./RouteBadge";

describe("RouteBadge", () => {
  it("stays hidden for a plain local reply (signal, not chrome)", () => {
    const { container } = render(
      <RouteBadge compute={{ target: "local", label: "This PC", fell_back: false }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows which device served a remote reply", () => {
    render(<RouteBadge compute={{ target: "device:colab", device_id: "colab", label: "Colab T4", fell_back: false }} />);
    expect(screen.getByText(/Ran on Colab T4/)).toBeInTheDocument();
  });

  it("explains a fallback with its reason", () => {
    render(
      <RouteBadge
        compute={{ target: "local", label: "This PC", fell_back: true, reason: "cloud unreachable" }}
      />,
    );
    expect(screen.getByText(/Fell back to This PC/)).toBeInTheDocument();
    expect(screen.getByText(/cloud unreachable/)).toBeInTheDocument();
  });
});

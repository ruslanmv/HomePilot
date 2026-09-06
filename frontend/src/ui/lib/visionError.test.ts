/**
 * The message a person actually reads when vision fails.
 *
 * The strings below are the real ones from a real session, pasted rather than invented.
 */
import { describe, it, expect } from "vitest";
import { visionErrorMessage, parseVisionFailure } from "./visionError";

/** Exactly what the chat was handed when the local model's runner crashed. */
const RUNNER_STOPPED = new Error(
  'HTTP 422 Unprocessable Entity: {"ok":false,"error":"Ollama could not keep model \'moondream:latest\' running. It may exceed this computer\'s available RAM or VRAM. Select a smaller multimodal model or check the Ollama server logs.","error_code":"model_runner_stopped","analysis_text":"","meta":{"model":"moondream:latest","mode":"both"}}',
);

/** And when the model loaded but said nothing about a tall screenshot. */
const EMPTY = new Error(
  'HTTP 422 Unprocessable Entity: {"ok":false,"error":"moondream:latest returned no description of the image.","error_code":"empty_model_response","analysis_text":"","meta":{"model":"moondream:latest","mode":"both","image_size_bytes":278904}}',
);

describe("it stops dumping JSON at people", () => {
  it("shows the backend sentence, not the envelope", () => {
    const msg = visionErrorMessage(RUNNER_STOPPED);
    expect(msg).toContain("could not keep model");
    expect(msg).not.toContain("{");
    expect(msg).not.toContain("error_code");
    expect(msg).not.toContain("422");
  });

  it("and never shows the raw meta block", () => {
    expect(visionErrorMessage(EMPTY)).not.toContain("image_size_bytes");
  });
});

describe("it stops giving advice that is wrong", () => {
  it("does not tell someone to install the model they are looking at", () => {
    // This is the sentence that sent a user to check something already true: Moondream
    // was installed and visible in the model list while the chat told them to pull it.
    expect(visionErrorMessage(RUNNER_STOPPED)).not.toMatch(
      /ollama pull moondream/i,
    );
    expect(visionErrorMessage(EMPTY)).not.toMatch(
      /make sure a multimodal model is installed/i,
    );
  });

  it("gives the advice that matches what actually failed", () => {
    // "close some applications" appears only in the advice. An earlier version matched
    // "smaller multimodal model", which the backend's own sentence already contains — so
    // the test passed with the advice removed entirely, and a mutation proved it.
    expect(visionErrorMessage(RUNNER_STOPPED)).toMatch(
      /close some applications/i,
    );
    expect(visionErrorMessage(EMPTY)).toMatch(/larger multimodal model/i);
  });

  it("and says to install one only when none is installed", () => {
    const none = new Error(
      '{"ok":false,"error":"No multimodal model found.","error_code":"no_vision_model"}',
    );
    expect(visionErrorMessage(none)).toMatch(/ollama pull/i);
  });

  it("adds nothing when there is no code to go on", () => {
    // A guess about the cause is what caused this. Silence beats invention.
    const bare = new Error(
      '{"ok":false,"error":"Failed to connect to Ollama: timed out"}',
    );
    const msg = visionErrorMessage(bare);
    expect(msg).toBe("Failed to connect to Ollama: timed out.");
  });
});

describe("the shapes that are not a tidy envelope", () => {
  it("a plain transport error still reads as a sentence", () => {
    expect(visionErrorMessage(new Error("Network request failed"))).toBe(
      "Network request failed.",
    );
  });

  it("an envelope whose error is itself JSON is not shown raw", () => {
    // The nested case from the original report: the backend had wrapped a provider blob.
    const nested = new Error(
      '{"ok":false,"error":"{\\"error\\":\\"runner stopped\\"}","error_code":""}',
    );
    const msg = visionErrorMessage(nested);
    expect(msg).not.toContain("{");
    expect(msg).toBe("That image couldn't be analysed.");
  });

  it("null, undefined and nonsense do not throw", () => {
    for (const bad of [null, undefined, 42, {}, []]) {
      expect(() => visionErrorMessage(bad)).not.toThrow();
    }
  });

  it("never ends in a double full stop", () => {
    const dotted = new Error(
      '{"ok":false,"error":"Something failed.","error_code":"model_runner_stopped"}',
    );
    expect(visionErrorMessage(dotted)).not.toMatch(/\.\./);
  });
});

describe("parsing the envelope out of a transport message", () => {
  it("finds it where it actually sits", () => {
    expect(parseVisionFailure(RUNNER_STOPPED)?.error_code).toBe(
      "model_runner_stopped",
    );
  });

  it("returns null when there is none", () => {
    expect(parseVisionFailure(new Error("Network request failed"))).toBeNull();
    expect(parseVisionFailure(null)).toBeNull();
  });
});

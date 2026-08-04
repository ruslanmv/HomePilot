import { describe, expect, it, vi } from "vitest";
import { parseSseBuffer, streamChat } from "./streamChat";

describe("parseSseBuffer", () => {
  it("splits complete frames and keeps the remainder", () => {
    const { frames, rest } = parseSseBuffer(
      'data: {"delta":"a"}\n\ndata: {"delta":"b"}\n\ndata: {"del',
    );
    expect(frames).toEqual([{ delta: "a" }, { delta: "b" }]);
    expect(rest).toBe('data: {"del');
  });
});

function sseStream(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) controller.enqueue(enc.encode(chunks[i++]));
      else controller.close();
    },
  });
}

describe("streamChat", () => {
  it("delivers deltas in order and the final route info", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(
        sseStream([
          'data: {"delta":"Hi"}\n\n',
          'data: {"delta":" there"}\n\n',
          'data: {"done":true,"compute":{"target":"device:colab","label":"Colab T4","fell_back":false}}\n\n',
        ]),
        { status: 200, headers: { "content-type": "text/event-stream" } },
      ),
    ));

    const deltas: string[] = [];
    let compute: any = null;
    await streamChat("http://x", { messages: [{ role: "user", content: "hi" }] }, {
      onDelta: (t) => deltas.push(t),
      onDone: (c) => (compute = c),
    });

    expect(deltas.join("")).toBe("Hi there");
    expect(compute).toMatchObject({ label: "Colab T4" });
    vi.unstubAllGlobals();
  });

  it("reports an error frame", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(sseStream(['data: {"error":"cloud unreachable"}\n\n', 'data: {"done":true,"compute":null}\n\n']), {
        status: 200,
      }),
    ));
    const errors: string[] = [];
    await streamChat("http://x", { messages: [] }, { onDelta: () => {}, onError: (e) => errors.push(e) });
    expect(errors).toEqual(["cloud unreachable"]);
    vi.unstubAllGlobals();
  });
});

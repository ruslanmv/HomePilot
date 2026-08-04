/**
 * streamChat — consume the /v1/compute/chat/stream SSE endpoint (P1).
 *
 * Reads token deltas as they arrive (live typewriter) and hands back the final
 * route diagnostics (which device served the reply). Frame format, one JSON
 * object per `data:` line:
 *   {delta:"..."} | {error:"..."} | {done:true, compute:{...}}
 */

export interface RouteInfo {
  target: string;
  device_id?: string | null;
  label: string;
  fell_back: boolean;
  reason?: string | null;
}

export interface StreamChatBody {
  messages: Array<{ role: string; content: string }>;
  model?: string;
  provider?: string;
  modality?: string;
  base_url?: string;
  temperature?: number;
  max_tokens?: number;
}

export interface StreamChatCallbacks {
  onDelta: (text: string) => void;
  onDone?: (compute: RouteInfo | null) => void;
  onError?: (message: string) => void;
}

/** Split a raw SSE buffer into complete frames, returning [frames, remainder]. */
export function parseSseBuffer(buffer: string): { frames: unknown[]; rest: string } {
  const frames: unknown[] = [];
  let rest = buffer;
  let idx: number;
  while ((idx = rest.indexOf("\n\n")) >= 0) {
    const block = rest.slice(0, idx);
    rest = rest.slice(idx + 2);
    const dataLine = block.split("\n").find((l) => l.startsWith("data:"));
    if (!dataLine) continue;
    const payload = dataLine.slice("data:".length).trim();
    if (!payload) continue;
    try {
      frames.push(JSON.parse(payload));
    } catch {
      /* ignore malformed frame */
    }
  }
  return { frames, rest };
}

function dispatch(frame: any, cb: StreamChatCallbacks): void {
  if (frame == null) return;
  if (typeof frame.delta === "string") cb.onDelta(frame.delta);
  else if (typeof frame.error === "string") cb.onError?.(frame.error);
  else if (frame.done) cb.onDone?.((frame.compute as RouteInfo) ?? null);
}

export async function streamChat(
  baseUrl: string,
  body: StreamChatBody,
  cb: StreamChatCallbacks,
  opts: { signal?: AbortSignal; headers?: Record<string, string> } = {},
): Promise<void> {
  const res = await fetch(`${baseUrl.replace(/\/+$/, "")}/v1/compute/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    body: JSON.stringify(body),
    signal: opts.signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`Streaming request failed (HTTP ${res.status}).`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { frames, rest } = parseSseBuffer(buffer);
    buffer = rest;
    for (const f of frames) dispatch(f, cb);
  }
  // Flush any trailing frame without the final blank line.
  const { frames } = parseSseBuffer(buffer + "\n\n");
  for (const f of frames) dispatch(f, cb);
}

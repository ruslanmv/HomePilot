/**
 * Turning a vision failure into a sentence somebody can act on.
 *
 * What the chat used to show, verbatim, when a local model crashed:
 *
 *     Image analysis failed: HTTP 422 Unprocessable Entity: {"ok":false,"error":"Ollama HTTP
 *     500: {\"error\":\"model runner has unexpectedly stopped, this may be due to resource
 *     limitations or an internal error, check ollama server logs for details\"}",
 *     "error_code":"","analysis_text":"","meta":{...}}. Make sure a multimodal model is
 *     installed (e.g. ollama pull moondream).
 *
 * Two separate failures there, and the second is the worse one.
 *
 * **It dumps JSON at a person.** A transport status, a nested provider status and a serialised
 * envelope, none of which is the thing that went wrong. The backend already writes a sentence
 * for exactly this — `error` — and it was buried inside the blob rather than shown.
 *
 * **The advice was wrong.** Moondream *was* installed; the user was looking at it in the model
 * list while being told to install it. That sentence was appended unconditionally, so the one
 * piece of advice on screen pointed away from the actual problem — a model too large for the
 * machine's memory — and sent them to check something that was already true.
 *
 * So the rule here is: say what the backend said, and add advice only when the error code says
 * that advice applies. Where there is no code to go on, add nothing rather than guess.
 */

/** The failure envelope the backend returns. Every field is optional in practice. */
export type VisionFailure = {
  error?: string;
  error_code?: string;
  meta?: { model?: string; fallback_from?: string } | null;
};

/** Pull the backend's own envelope out of a thrown transport error, if it is in there. */
export function parseVisionFailure(raw: unknown): VisionFailure | null {
  const text = typeof raw === "string" ? raw : (raw as any)?.message;
  if (typeof text !== "string") return null;
  // The envelope arrives embedded in a transport message, so find the JSON rather than
  // assuming the whole string is JSON.
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end <= start) return null;
  try {
    const parsed = JSON.parse(text.slice(start, end + 1));
    if (parsed && typeof parsed === "object") return parsed as VisionFailure;
  } catch {
    /* not JSON: fall through to the raw text, which is all there is */
  }
  return null;
}

/**
 * Advice, keyed on what actually failed. `''` when there is nothing honest to add.
 *
 * `no_vision_model` is the only case where "install one" is true, and it is the only case that
 * says it.
 */
function adviceFor(code: string): string {
  switch (code) {
    case "model_runner_stopped":
      return "Try a smaller multimodal model in Settings, or close some applications and try again.";
    case "empty_model_response":
      return "That model had nothing to say about this image. A larger multimodal model in Settings will usually do better.";
    case "image_too_large":
      return "A screenshot of a single screen, or a smaller copy, will work.";
    case "no_vision_model":
      return "Install one first, for example: ollama pull gemma3:4b";
    default:
      return "";
  }
}

/**
 * The line to show in the chat.
 *
 * Prefers the backend's own sentence, which is written for a person and names the model that
 * failed. Falls back to the transport message only when there is nothing better — and even
 * then says nothing further, because a guess about the cause is what caused this.
 */
export function visionErrorMessage(raw: unknown): string {
  const failure = parseVisionFailure(raw);
  const backendSentence = String(failure?.error || "").trim();
  const transport =
    typeof raw === "string" ? raw : String((raw as any)?.message || "").trim();

  // A nested envelope can leave JSON inside `error` too. If what we have still looks like a
  // blob, it is not a sentence, and showing it is the bug rather than the fix.
  const looksLikeJson = (s: string) =>
    s.startsWith("{") || s.includes('"error_code"');
  const sentence =
    backendSentence && !looksLikeJson(backendSentence)
      ? backendSentence
      : transport && !looksLikeJson(transport)
        ? transport
        : "That image couldn't be analysed.";

  const advice = adviceFor(String(failure?.error_code || ""));
  const head = sentence.replace(/\s*\.\s*$/, "");
  return advice ? `${head}. ${advice}` : `${head}.`;
}

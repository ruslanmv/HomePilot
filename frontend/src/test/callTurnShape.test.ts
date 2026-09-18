/**
 * A call turn is generated as speech, not as chat prose.
 *
 * ── The bug ──────────────────────────────────────────────────────────────────────────────
 *
 * Measured from a real call, end-of-speech to first audio: 4099 ms, 5986 ms, 4700 ms. The
 * Voice tab, on the same microphone, the same controller and the same endpoint, is fast.
 *
 * The 📞 overlay is a call, but opening it does not swap the app out of chat mode, and the
 * send path keyed every voice decision off `mode === 'voice'`. So each call turn went out
 * shaped like a chat message:
 *
 *   - no `voiceSystemPrompt`, so the backend's `is_voice_mode` stayed false and the model
 *     got `BASE_SYSTEM`, which carries no brevity instruction at all;
 *   - `textMaxTokens` instead of the voice ceiling — `orchestrator.py` caps a voice turn at
 *     VOICE_MAX_TOKENS = 80 and everything else at 900.
 *
 * And because `POST /chat` does not stream, time-to-first-audio is the *whole* generation.
 * A longer answer is not merely longer to listen to; it is longer before a single word is
 * spoken. The design budget for this path is 600 ms (docs/analysis/voice-call-streaming-
 * design.md §1).
 *
 * `App.tsx` is a single ~7000-line component that cannot be mounted in a unit test, so this
 * asserts the wiring at the source level — the same approach as
 * `microphoneDiagnostics.test.js`. It is deliberately narrow: it checks the decision, the
 * one call site that sets it, and that nothing latency-shaping is keyed off the app mode
 * again by accident.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const app = readFileSync(resolve(ROOT, 'frontend/src/ui/App.tsx'), 'utf8');

/** `sendTextOrIntent`, from its declaration to the start of the next top-level callback. */
function sendPathSource(): string {
  const start = app.indexOf('const sendTextOrIntent = useCallback(');
  expect(start).toBeGreaterThan(-1);
  const end = app.indexOf('const retryFailedMessage', start);
  expect(end).toBeGreaterThan(start);
  return app.slice(start, end);
}

describe('a call is sent as a spoken turn', () => {
  it('takes a spoken flag and folds it into one voice decision', () => {
    const send = sendPathSource();
    expect(send).toContain('async (rawText: string, opts?: { spoken?: boolean })');
    expect(send).toContain("const spokenTurn = opts?.spoken === true");
    expect(send).toContain("const voiceLike = mode === 'voice' || spokenTurn");
  });

  it('is the flag the call overlay actually passes', () => {
    // The Voice tab keeps the plain call; only the overlay marks its turns spoken.
    expect(app).toContain('onSendText={(text) => sendTextOrIntent(text, { spoken: true })}');
    const overlay = app.indexOf('<CallOverlay');
    const spoken = app.indexOf('sendTextOrIntent(text, { spoken: true })');
    expect(spoken).toBeGreaterThan(overlay);
  });

  it('shapes the reply for speech: brevity prompt and the voice token ceiling', () => {
    const send = sendPathSource();
    // The block that builds `voiceSystemPrompt` runs for a call, not only in voice mode.
    expect(send).toContain('if (voiceLike) {');
    expect(send).toContain('Reply in 1-2 short sentences only');
    // Token ceilings follow the same decision, so the backend applies VOICE_MAX_TOKENS.
    expect(send).toContain('textMaxTokens: voiceLike ? undefined : settingsDraft.textMaxTokens');
    expect(send).toContain('max_tokens: voiceLike ? 300 :');
  });

  it('never lets a call fall through to the chat prompt', () => {
    const send = sendPathSource();
    // Linked-persona mode leaves `voiceSystemPrompt` undefined on purpose — the backend owns
    // the prompt there, but only when the request carries that persona. A call that carries
    // neither would be a chat turn again, which is the whole defect.
    expect(send).toContain('if (spokenTurn && !voiceSystemPrompt && !carriesPersonaId)');
  });

  it('leaves identity and routing keyed off the real app mode', () => {
    const send = sendPathSource();
    // A call answers as whoever the user is already talking to: `spoken` shapes the reply,
    // it does not redirect the conversation to the voice-linked project or session.
    expect(send).toContain("session_key: mode === 'voice' ? 'voice' : 'chat'");
    expect(send).toContain("project_id: mode === 'voice' ? getVoiceLinkedProjectId() : currentProjectId");
    expect(send).not.toContain('project_id: voiceLike');
    expect(send).not.toContain('session_key: voiceLike');
  });

  it('has no latency-shaping decision left on the app mode alone', () => {
    const send = sendPathSource();
    // The regression this guards: re-keying a ceiling or the prompt back to `mode`, which
    // silently returns calls to the 900-token chat shape.
    expect(send).not.toContain("textMaxTokens: mode === 'voice'");
    expect(send).not.toContain("max_tokens: mode === 'voice'");
    expect(send).not.toContain("if (mode === 'voice') {");
  });
});

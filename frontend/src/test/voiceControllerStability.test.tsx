/**
 * The microphone must not reopen on every render.
 *
 * `VoiceModeGrok` passes `onSendText` as a plain function declared in its component body
 * (`function handleVoiceInput(text) {...}`), so its identity changes on every render. When a
 * `useCallback` listed it, and the hands-free effect listed *that* callback, the effect
 * restarted every render — and because the restart calls `setState`, the restart caused the
 * next render. The capture tore down and reopened forever:
 *
 *     handsfree_vad_start_requested {generation: 76}
 *     handsfree_vad_cleanup         {generation: 76}
 *     handsfree_vad_start_requested {generation: 77}
 *     ...
 *
 * These are source assertions rather than a render harness, deliberately. The invariant is
 * "no render-scoped identity reaches the capture effect's dependencies", and that is a
 * property of the dependency lists themselves — a jsdom harness would be testing React's
 * scheduler as much as this hook. Each assertion below fails on the code that shipped the
 * loop, which is the only thing that makes a regression test worth having.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const CONTROLLER = readFileSync(
  resolve(ROOT, 'frontend/src/ui/voice/useVoiceController.ts'), 'utf8',
);

/** The body of the `useCallback` that opens a recording turn. */
function startRecordingTurnBody(): string {
  const from = CONTROLLER.indexOf('const startRecordingTurn = useCallback(');
  expect(from).toBeGreaterThan(-1);
  const to = CONTROLLER.indexOf('const finishRecordingTurn', from);
  expect(to).toBeGreaterThan(from);
  return CONTROLLER.slice(from, to);
}

describe('the hands-free capture effect', () => {
  it('never depends on the caller’s handler identity', () => {
    // This exact list is what shipped the loop.
    expect(startRecordingTurnBody()).not.toContain('}, [isHandsFree, onSendText]);');
    expect(startRecordingTurnBody()).not.toContain('onSendText]');
  });

  it('reads the caller’s handler through a ref instead', () => {
    const body = startRecordingTurnBody();
    expect(body).toContain('onSendTextRef.current(');
    // Reading `isHandsFree` directly would put it back in the dependency list.
    expect(body).not.toContain("setState(isHandsFree ? 'IDLE' : 'OFF')");
    expect(body).toContain("isHandsFreeRef.current ? 'IDLE' : 'OFF'");
  });

  it('keeps the refs fed with the newest values', () => {
    expect(CONTROLLER).toContain('onSendTextRef.current = onSendText');
    expect(CONTROLLER).toContain('isHandsFreeRef.current = isHandsFree');
  });

  it('leaves the turn handlers identity-stable', () => {
    // All three are listed in the capture effect's dependencies, so all three must be
    // stable; one unstable entry is enough to restart the capture on every render.
    for (const name of ['startRecordingTurn', 'finishRecordingTurn', 'discardRecording']) {
      const from = CONTROLLER.indexOf(`const ${name} = useCallback(`);
      expect(from, `${name} should be a useCallback`).toBeGreaterThan(-1);
      const deps = CONTROLLER.slice(from).match(/\}, \[([^\]]*)\]\);/);
      expect(deps, `${name} should close with a dependency list`).not.toBeNull();
      expect((deps as RegExpMatchArray)[1].trim(), `${name} must have no dependencies`).toBe('');
    }
  });
});

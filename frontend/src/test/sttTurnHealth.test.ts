/**
 * The detector behind "it recognizes my voice however does not send".
 *
 * The reported trace, three surfaces in a row:
 *
 *     stt_onend { hadResult: false, sawAudioStart: true, sawSpeechStart: false }
 *
 * while the VAD meter tracked the speaker and MediaRecorder captured 78 KB from the selected
 * microphone. The Web Speech API reports no error for this — it recorded a silent room and
 * considers that a success — so the only way to catch it is to notice the pattern.
 *
 * Every exclusion below is a different fault with a different fix. Firing on one of those
 * would change the user's transcription engine in response to a problem that changing the
 * engine cannot solve, which is worse than doing nothing.
 */

import { describe, expect, it } from 'vitest';
import {
  DEAF_TURNS_BEFORE_RECOVERY,
  isDeafTurn,
  planSttRecovery,
} from '../ui/media/sttTurnHealth';

describe('isDeafTurn', () => {
  it('fires on the reported signature: capture opened, nothing heard', () => {
    expect(isDeafTurn({ sawAudioStart: true, sawSpeechStart: false, hadResult: false }))
      .toBe(true);
  });

  it('does not fire when the turn produced a transcript', () => {
    expect(isDeafTurn({ sawAudioStart: true, sawSpeechStart: false, hadResult: true }))
      .toBe(false);
  });

  it('does not fire when interim words came back', () => {
    // It was hearing the user. Whatever went wrong afterwards is not the device.
    expect(isDeafTurn({ sawAudioStart: true, sawInterim: true, hadResult: false })).toBe(false);
  });

  it('does not fire when speech was heard but not matched', () => {
    // The wrong recognition language, or a stop that cut the turn short. Switching engines
    // would not fix either, and would hide both.
    expect(isDeafTurn({ sawAudioStart: true, sawSpeechStart: true, hadResult: false }))
      .toBe(false);
  });

  it('does not fire when the capture never opened', () => {
    // A permission or device failure, which names itself.
    expect(isDeafTurn({ sawAudioStart: false, hadResult: false })).toBe(false);
  });

  it('does not fire on a reported error', () => {
    for (const error of ['not-allowed', 'network', 'audio-capture', 'aborted']) {
      expect(isDeafTurn({ sawAudioStart: true, sawSpeechStart: false, hadResult: false, error }))
        .toBe(false);
    }
  });

  it('does not guess when the browser reported no lifecycle at all', () => {
    // `undefined` is "this was not observed", not "this did not happen". Treating a missing
    // signal as evidence would make the detector fire on any browser that omits the events.
    expect(isDeafTurn({ hadResult: false })).toBe(false);
    expect(isDeafTurn({})).toBe(false);
  });
});

describe('planSttRecovery', () => {
  it('waits: one bad turn is a cough, not a device', () => {
    expect(planSttRecovery(1, { backendUsable: true })).toEqual({ action: 'none' });
    expect(DEAF_TURNS_BEFORE_RECOVERY).toBeGreaterThan(1);
  });

  it('switches to on-device transcription once there is something to switch to', () => {
    const plan = planSttRecovery(DEAF_TURNS_BEFORE_RECOVERY, { backendUsable: true });
    expect(plan.action).toBe('switch-to-backend');
  });

  it('always explains the switch, and where to undo it', () => {
    // Silently moving somebody's audio off the browser recognizer — or onto it — is the
    // exact failure the engine split exists to prevent. A recovery is not exempt.
    const plan = planSttRecovery(DEAF_TURNS_BEFORE_RECOVERY, { backendUsable: true });
    if (plan.action === 'none') throw new Error('expected a recovery');
    expect(plan.message).toContain('Speech Recognition');
    expect(plan.message).toContain('default');
  });

  it('advises instead of switching when there is no other engine', () => {
    const plan = planSttRecovery(DEAF_TURNS_BEFORE_RECOVERY, { backendUsable: false });
    expect(plan.action).toBe('advise');
    if (plan.action !== 'advise') return;
    // Both ways out, because either one fixes it and the user may only be able to do one.
    expect(plan.message).toContain('system default input');
    expect(plan.message).toContain('speech model');
  });

  it('keeps recovering past the threshold rather than giving up', () => {
    expect(planSttRecovery(9, { backendUsable: true }).action).toBe('switch-to-backend');
  });
});

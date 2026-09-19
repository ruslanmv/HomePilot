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
  turnsBeforeRecovery,
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

  it('blames the device split outright when nothing else was holding the microphone', () => {
    const plan = planSttRecovery(DEAF_TURNS_BEFORE_RECOVERY, { backendUsable: true });
    if (plan.action === 'none') throw new Error('expected a recovery');
    expect(plan.message).toContain('system default input');
    expect(plan.message).not.toContain('Two things');
  });

  it('names both causes when HomePilot held the microphone too', () => {
    // Hands-free keeps the selected microphone open for the whole session, and some drivers
    // hand a second recorder on the same device a live but silent track. That produces a
    // trace identical to the device split and needs a different fix, so asserting the split
    // as fact would send the user to rearrange their operating system for nothing.
    const plan = planSttRecovery(DEAF_TURNS_BEFORE_RECOVERY, {
      backendUsable: true,
      homepilotHoldsMicrophone: true,
    });
    if (plan.action === 'none') throw new Error('expected a recovery');
    expect(plan.message).toContain('Two things');
    expect(plan.message).toContain('preventing the browser from opening the same device');
    // And the test that separates them, or naming two causes is just hedging.
    expect(plan.message).toContain('chat composer');
  });

  it('does not claim contention when it was not observed', () => {
    // `undefined` is "not known", and must read the same as "not happening" rather than
    // inventing a second cause on every machine.
    const quiet = planSttRecovery(DEAF_TURNS_BEFORE_RECOVERY, { backendUsable: false });
    const explicit = planSttRecovery(DEAF_TURNS_BEFORE_RECOVERY, {
      backendUsable: false,
      homepilotHoldsMicrophone: false,
    });
    expect(quiet).toEqual(explicit);
  });

  it('keeps recovering past the threshold rather than giving up', () => {
    expect(planSttRecovery(9, { backendUsable: true }).action).toBe('switch-to-backend');
  });
});

describe('sending the user to the browser’s own microphone setting', () => {
  /*
   * The setting that turned out to explain it. `chrome://settings/content/microphone` is
   * separate from the OS default: it starts out following it and can be pinned to a device
   * independently, and once pinned that is what every recording on the page hears. A user sent
   * only to their sound panel fixes it correctly and sees no change.
   */
  const CHECK = 'In Chrome, check which microphone is selected at chrome://settings/content/microphone';

  it('names it in the message that switches engines', () => {
    const plan = planSttRecovery(1, {
      backendUsable: true,
      turnWasDeliberate: true,
      browserMicCheck: CHECK,
    });
    if (plan.action === 'none') throw new Error('expected a recovery');
    expect(plan.message).toContain('chrome://settings/content/microphone');
  });

  it('names it in the message that only advises', () => {
    // The install with no local model is the one that most needs it: there is no engine to
    // switch to, so the browser's device selection is the only thing left to fix.
    const plan = planSttRecovery(1, {
      backendUsable: false,
      turnWasDeliberate: true,
      browserMicCheck: CHECK,
    });
    if (plan.action === 'none') throw new Error('expected a recovery');
    expect(plan.action).toBe('advise');
    expect(plan.message).toContain('chrome://settings/content/microphone');
  });

  it('puts the check before the fix', () => {
    // It decides *which* fix is right, so advice that arrives after it reads as the answer to
    // a question the user has not been asked yet.
    const plan = planSttRecovery(1, {
      backendUsable: true,
      turnWasDeliberate: true,
      browserMicCheck: CHECK,
    });
    if (plan.action === 'none') throw new Error('expected a recovery');
    expect(plan.message.indexOf('chrome://'))
      .toBeLessThan(plan.message.indexOf('HomePilot has switched'));
  });

  it('reads correctly on a browser that has no such page', () => {
    const withoutField = planSttRecovery(1, { backendUsable: true, turnWasDeliberate: true });
    for (const missing of [null, undefined, '', '   ']) {
      expect(planSttRecovery(1, {
        backendUsable: true,
        turnWasDeliberate: true,
        browserMicCheck: missing,
      })).toEqual(withoutField);
    }
    if (withoutField.action === 'none') throw new Error('expected a recovery');
    expect(withoutField.message).not.toContain('chrome://');
    expect(withoutField.message).not.toContain('  ');
  });
});

describe('naming the device the recognizer is actually recording', () => {
  /*
   * The message explained the mechanism perfectly and still left the user stuck. "It records
   * your system default input, not the microphone you selected" sends somebody to an OS sound
   * panel where the entire difficulty is working out *which* of eight entries is the wrong
   * one — and the one holding the default slot is typically a virtual device nobody chose.
   * The trace this was written from read `Microphone (Steam Streaming Microphone)`, a name the
   * device list had all along and nothing ever looked at.
   */

  it('names the default input in the single-cause message', () => {
    const plan = planSttRecovery(1, {
      backendUsable: true,
      turnWasDeliberate: true,
      systemDefaultLabel: 'Microphone (Steam Streaming Microphone)',
    });
    if (plan.action === 'none') throw new Error('expected a recovery');
    expect(plan.message).toContain('Microphone (Steam Streaming Microphone)');
    expect(plan.message).toContain('your system default input');
  });

  it('names it in the two-cause message as well', () => {
    const plan = planSttRecovery(1, {
      backendUsable: true,
      turnWasDeliberate: true,
      homepilotHoldsMicrophone: true,
      systemDefaultLabel: 'Microphone (Steam Streaming Microphone)',
    });
    if (plan.action === 'none') throw new Error('expected a recovery');
    expect(plan.message).toContain('Two things');
    expect(plan.message).toContain('Microphone (Steam Streaming Microphone)');
  });

  it('reads correctly on a browser that will not say', () => {
    // Chrome on Windows often exposes no `default` alias, so the name is genuinely
    // unavailable. The sentence has to survive that without a dangling clause — and must be
    // byte-identical to what it said before the label existed.
    const withoutField = planSttRecovery(1, { backendUsable: true, turnWasDeliberate: true });
    for (const missing of [null, undefined, '', '   ']) {
      const plan = planSttRecovery(1, {
        backendUsable: true,
        turnWasDeliberate: true,
        systemDefaultLabel: missing,
      });
      expect(plan).toEqual(withoutField);
    }
    if (withoutField.action === 'none') throw new Error('expected a recovery');
    expect(withoutField.message).not.toContain('on this computer that is');
    expect(withoutField.message).toContain('system default input, not the microphone');
  });
});

describe('how much evidence one turn is worth', () => {
  /*
   * Two turns was written for turns a voice-activity detector opened, where a deaf turn might
   * be a cough, a door, or a sentence too quiet to reach the recognizer.
   *
   * A turn the user started and stopped themselves is a different kind of fact: they pressed
   * record, spoke, and pressed stop. Waiting for a second one only costs them another turn to
   * learn what the first already proved.
   */
  it('acts on the first turn a person deliberately recorded', () => {
    expect(turnsBeforeRecovery({ backendUsable: true, turnWasDeliberate: true })).toBe(1);
    expect(planSttRecovery(1, { backendUsable: true, turnWasDeliberate: true }).action)
      .toBe('switch-to-backend');
  });

  it('still wants two from a turn nobody asked for', () => {
    expect(turnsBeforeRecovery({ backendUsable: true })).toBe(DEAF_TURNS_BEFORE_RECOVERY);
    expect(planSttRecovery(1, { backendUsable: true }).action).toBe('none');
  });

  it('describes what it actually saw, not a fixed sentence', () => {
    // The old text claimed the recognizer failed "twice" while "HomePilot's own microphone
    // meter heard you clearly". Neither half survives: a deliberate turn recovers on the
    // first, and on the browser engine HomePilot holds no capture, so there is no meter to
    // have heard anything. Describing evidence nobody gathered is worse than saying less.
    const deliberate = planSttRecovery(1, { backendUsable: true, turnWasDeliberate: true });
    if (deliberate.action === 'none') throw new Error('expected a recovery');
    expect(deliberate.message).toContain('You recorded a turn');
    expect(deliberate.message).not.toContain('twice');
    expect(deliberate.message).not.toContain('microphone meter heard you clearly');

    const automatic = planSttRecovery(3, { backendUsable: true });
    if (automatic.action === 'none') throw new Error('expected a recovery');
    expect(automatic.message).toContain('3 times in a row');
  });
});

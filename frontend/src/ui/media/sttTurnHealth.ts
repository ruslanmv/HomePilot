/**
 * Noticing that the browser recognizer is listening to the wrong microphone — and doing
 * something about it.
 *
 * ── The failure this exists for ──────────────────────────────────────────────────────────
 *
 * `SpeechRecognition` accepts no `deviceId`. It always records the operating system's
 * default input, regardless of the microphone chosen in Audio & Video. When those two are
 * different devices and the default one is silent — unplugged, muted, a disconnected headset
 * still holding the default slot — every turn looks like this:
 *
 *     stt_onend { hadResult: false, sawAudioStart: true, sawSpeechStart: false }
 *
 * The capture opened. It heard nothing. Meanwhile HomePilot's own VAD, which *does* honour
 * the selection, heard the user perfectly well and is what opened the turn in the first
 * place. So the orb reacts to the voice, the turn ends, and nothing at all comes out: no
 * text, no error, no message. From the outside that is indistinguishable from a broken
 * product, and it is exactly the bug report "it recognizes my voice however does not send".
 *
 * Nothing in the Web Speech API reports this. There is no error, because from the
 * recognizer's point of view nothing went wrong — it recorded a silent room. The only way to
 * know is to compare what the recognizer heard against what HomePilot's own capture heard,
 * which is what {@link isDeafTurn} does.
 *
 * ── Why act, rather than only explain ───────────────────────────────────────────────────
 *
 * The advice this produces ("change your system default input") is a trip into operating
 * system settings, and HomePilot already has a transcription path that records the selected
 * microphone directly. When that path is usable, switching to it fixes the problem in place
 * and the next sentence the user speaks arrives as text. Telling somebody how to repair
 * their machine when you could simply stop needing the repair is not a good trade.
 *
 * The switch is never silent. It changes which service sees the audio — the browser's
 * recognizer sends it to Google; HomePilot's own keeps it on the machine — and a change of
 * that kind that the user did not ask for and is not told about is a betrayal of the choice
 * they made in Settings. So every recovery carries a message, and it names both what
 * happened and where to change it back.
 *
 * The session preference is deliberately *not* rewritten. The user chose it; a heuristic
 * reacting to two bad turns has no business overruling that permanently. This recovers the
 * session in progress and says so.
 */

export interface SttTurnSignals {
  /** The recognizer's capture opened (`onaudiostart`). */
  sawAudioStart?: boolean | null;
  /** The capture heard speech-level sound (`onspeechstart`). */
  sawSpeechStart?: boolean | null;
  /** Interim words came back, so it was hearing something. */
  sawInterim?: boolean | null;
  /** A final transcript was produced. */
  hadResult?: boolean | null;
  /** A reported error code, when there was one. */
  error?: string | null;
}

/**
 * Whether this turn is evidence that the recognizer is recording a silent device.
 *
 * Every exclusion below is a *different* fault with a different fix, and folding any of them
 * in here would make the detector fire on problems switching engines cannot solve:
 *
 * - a transcript, or interim words, means the device is fine;
 * - `sawSpeechStart` without a result means it heard the user and failed to match — the
 *   wrong recognition language, or a stop that cut the turn short;
 * - a reported error (`not-allowed`, `network`, `audio-capture`) already names its own
 *   cause, and each needs an answer this has nothing to do with;
 * - `sawAudioStart: false` means the capture never opened at all, which is a permission or
 *   device failure, not a routing one.
 *
 * What is left — the capture opened, stayed open, and heard nothing — is the routing split.
 */
export function isDeafTurn(signals: SttTurnSignals): boolean {
  if (signals.hadResult) return false;
  if (signals.error) return false;
  if (signals.sawInterim) return false;
  if (signals.sawSpeechStart) return false;
  return signals.sawAudioStart === true;
}

/**
 * How many consecutive deaf turns before recovering.
 *
 * One is not enough: a cough, a false VAD trigger or a genuinely too-quiet sentence all
 * produce a single deaf turn on a perfectly healthy machine, and reacting to one would mean
 * changing engines under people whose setup is fine. Two consecutive is a device, not a
 * person — nobody speaks twice in a row and is heard neither time by a microphone that
 * works. The cost of the extra turn is one turn; the cost of being hasty is an unasked-for
 * change of where the audio goes.
 */
export const DEAF_TURNS_BEFORE_RECOVERY = 2;

/**
 * One deliberate turn is worth two automatic ones.
 *
 * The two-turn rule above was written for turns a voice-activity detector opened: there, a
 * deaf turn might be a cough, a door, or a sentence too quiet to reach the recognizer, and
 * reacting to one would change engines under people whose setup is fine.
 *
 * A turn the user *started and stopped themselves* is a different kind of fact. They pressed
 * record, spoke, and pressed stop; there is a person asserting they said something. When that
 * turn reports that a capture opened and heard not one syllable, waiting for a second one
 * only costs them a second turn to learn what the first already proved.
 */
export function turnsBeforeRecovery(context: SttRecoveryContext): number {
  return context.turnWasDeliberate ? 1 : DEAF_TURNS_BEFORE_RECOVERY;
}

export type SttRecovery =
  /** Keep going: not enough evidence yet. */
  | { action: 'none' }
  /** Move this session onto HomePilot's own transcription, and say so. */
  | { action: 'switch-to-backend'; message: string }
  /** Nothing to switch to. Explain the fault and what would fix it. */
  | { action: 'advise'; message: string };

export interface SttRecoveryContext {
  /** HomePilot's own transcription can run here, so there is somewhere to switch to. */
  backendUsable: boolean;
  /**
   * HomePilot's own capture was open on the selected microphone throughout these turns.
   *
   * This changes the diagnosis, so it must not be assumed either way. See {@link describeCause}.
   */
  homepilotHoldsMicrophone?: boolean;
  /**
   * The user opened and closed this turn themselves — a press of the composer microphone, or
   * of the manual listen button.
   *
   * This is the difference between evidence and noise, and it decides how many turns are
   * needed. A turn somebody deliberately started, spoke into and stopped has a person behind
   * it asserting they said something; a turn opened automatically has nothing behind it, and
   * "the recognizer heard nothing" may simply mean nobody was talking. See
   * {@link turnsBeforeRecovery}.
   */
  turnWasDeliberate?: boolean;
}

/**
 * What was actually observed, stated without embellishment.
 *
 * This used to be one fixed sentence claiming the recognizer failed "twice" while "HomePilot's
 * own microphone meter heard you clearly". Neither half survives the engines being exclusive:
 * a deliberate turn recovers on the first one, and on the browser engine HomePilot holds no
 * capture, so there is no meter to have heard anything. A message that describes evidence
 * nobody gathered is worse than a shorter one that describes what happened.
 */
function describeObservation(consecutiveDeafTurns: number, context: SttRecoveryContext): string {
  if (context.turnWasDeliberate) {
    return 'You recorded a turn and the browser’s speech recognition found no speech in it, '
      + 'even though its microphone opened normally.';
  }
  const times = consecutiveDeafTurns === 2 ? 'twice' : `${consecutiveDeafTurns} times in a row`;
  return `Your browser’s speech recognition opened a microphone and heard nothing, ${times}.`;
}

/**
 * Name the cause with the confidence the evidence actually supports.
 *
 * The usual reason is the device split: `SpeechRecognition` takes no `deviceId` and records
 * the system default input, so it is simply pointed somewhere else. But when HomePilot's own
 * capture is open on the selected microphone at the same time, there is a second explanation
 * that produces an identical trace — some audio drivers (Windows DSP-backed inputs among
 * them) will hand a second recorder on the same endpoint a live but silent track.
 *
 * Those two have different fixes, and stating the first as fact when the second is equally
 * consistent with what was observed sends the user to rearrange their operating system for
 * nothing. So when both are possible, both are named, along with the one-minute test that
 * separates them.
 */
function describeCause(context: SttRecoveryContext): string {
  if (!context.homepilotHoldsMicrophone) {
    return (
      ' The Web Speech API takes no device setting: it records your system default input, ' +
      'not the microphone you selected in Audio & Video.'
    );
  }
  return (
    ' Two things can cause this and they need different fixes. Either the Web Speech API is ' +
    'recording your system default input — it takes no device setting, so it cannot use the ' +
    'microphone you selected in Audio & Video — or HomePilot’s own capture, which was open ' +
    'on that microphone at the time, is preventing the browser from opening the same device. ' +
    'To tell them apart: turn hands-free off and use the microphone button in the chat ' +
    'composer, which records nothing in the background. If that works, it was the second.'
  );
}

/**
 * Decide what to do about a run of deaf turns.
 *
 * Pure, and separate from the controller, because the interesting part is the decision and
 * the decision needs to be exercised across every combination rather than reasoned about in
 * the middle of a state machine.
 */
export function planSttRecovery(
  consecutiveDeafTurns: number,
  context: SttRecoveryContext,
): SttRecovery {
  if (consecutiveDeafTurns < turnsBeforeRecovery(context)) return { action: 'none' };

  const observed = describeObservation(consecutiveDeafTurns, context) + describeCause(context);

  if (context.backendUsable) {
    return {
      action: 'switch-to-backend',
      message:
        `${observed} HomePilot has switched this session to transcribing on this computer, ` +
        'which records the microphone you selected. Change this in Settings → Voice ' +
        'Assistant → Speech Recognition.',
    };
  }

  return {
    action: 'advise',
    message:
      `${observed} Either make that microphone your system default input, or install a ` +
      'speech model and set Settings → Voice Assistant → Speech Recognition to “On this ' +
      'computer”.',
  };
}

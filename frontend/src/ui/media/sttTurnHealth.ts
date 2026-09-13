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

export type SttRecovery =
  /** Keep going: not enough evidence yet. */
  | { action: 'none' }
  /** Move this session onto HomePilot's own transcription, and say so. */
  | { action: 'switch-to-backend'; message: string }
  /** Nothing to switch to. Explain the fault and what would fix it. */
  | { action: 'advise'; message: string };

const OBSERVED =
  'Your browser’s speech recognition opened your computer’s default microphone and heard ' +
  'nothing, twice, while HomePilot’s own microphone meter heard you. It cannot use the ' +
  'microphone you selected in Audio & Video — the Web Speech API always records the system ' +
  'default input.';

/**
 * Decide what to do about a run of deaf turns.
 *
 * Pure, and separate from the controller, because the interesting part is the decision and
 * the decision needs to be exercised across every combination rather than reasoned about in
 * the middle of a state machine.
 */
export function planSttRecovery(
  consecutiveDeafTurns: number,
  options: { backendUsable: boolean },
): SttRecovery {
  if (consecutiveDeafTurns < DEAF_TURNS_BEFORE_RECOVERY) return { action: 'none' };

  if (options.backendUsable) {
    return {
      action: 'switch-to-backend',
      message:
        `${OBSERVED} HomePilot has switched this session to transcribing on this computer, ` +
        'which records the microphone you selected. Change this in Settings → Voice ' +
        'Assistant → Speech Recognition.',
    };
  }

  return {
    action: 'advise',
    message:
      `${OBSERVED} Either make that microphone your system default input, or install a ` +
      'speech model and set Settings → Voice Assistant → Speech Recognition to “On this ' +
      'computer”.',
  };
}

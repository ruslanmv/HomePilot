/**
 * The shared speech-to-text runtime, as React state.
 *
 * Thin on purpose: the decision lives in `media/sttRuntime`, which has no React in it, so
 * chat and Voice subscribe to one object rather than each keeping a copy that agrees by
 * coincidence. A recovery or a preference change lands in both surfaces on the same tick.
 */

import { useEffect, useState } from 'react';
import {
  ensureSttRuntimeResolved,
  getSttRuntime,
  subscribeSttRuntime,
  type SttRuntimeState,
} from './sttRuntime';

export function useSttRuntime(): SttRuntimeState {
  const [state, setState] = useState<SttRuntimeState>(() => getSttRuntime());

  useEffect(() => {
    const unsubscribe = subscribeSttRuntime(setState);
    // Mounting is what starts the probe, so a surface that opens first is the one that pays
    // for it and every later surface joins the answer.
    void ensureSttRuntimeResolved().then(setState);
    return unsubscribe;
  }, []);

  return state;
}

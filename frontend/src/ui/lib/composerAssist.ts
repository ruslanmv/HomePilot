/**
 * What the app offers the composer while a reply is in flight, or before an expensive one:
 * a Stop control for the running stream, and the one-time Deep research hint for a trivial
 * message ("Use Fast for this" / "Run Deep research"). A context, so the composer needs no
 * new props wherever it is rendered.
 */
import { createContext } from 'react'

export type DeepHint = { text: string }

export type ComposerAssist = {
  /** A reply is streaming; the send button becomes Stop. */
  streaming: boolean
  stop: () => void
  deepHint: DeepHint | null
  chooseDeepHint: (choice: 'fast' | 'deep' | 'dismiss') => void
}

export const ComposerAssistContext = createContext<ComposerAssist>({
  streaming: false,
  stop: () => {},
  deepHint: null,
  chooseDeepHint: () => {},
})

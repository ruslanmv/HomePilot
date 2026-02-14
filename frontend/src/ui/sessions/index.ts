/**
 * Sessions module — Companion-grade persona session management
 */
export { default as SessionPanel } from './SessionPanel'
export {
  resolveSession,
  createSession,
  endSession,
  listSessions,
  getSession,
  getMemories,
  upsertMemory,
  forgetMemory,
} from './sessionsApi'
export type { PersonaSession, PersonaMemoryEntry } from './sessionsApi'

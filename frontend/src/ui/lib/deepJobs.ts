/**
 * The Deep research job a conversation is waiting on, remembered in this browser so a refresh
 * reconnects to it (the server keeps the job and replays its numbered events). Entries expire
 * after a day; the server's own retention is longer.
 */
const KEY = 'homepilot_deep_jobs'
const MAX_AGE_MS = 24 * 60 * 60 * 1000

export type PendingDeepJob = { job_id: string; started_at: number; last_seq?: number }

function readAll(): Record<string, PendingDeepJob> {
  try {
    const raw = localStorage.getItem(KEY)
    const parsed = raw ? (JSON.parse(raw) as Record<string, PendingDeepJob>) : {}
    const now = Date.now()
    const fresh: Record<string, PendingDeepJob> = {}
    for (const [conv, job] of Object.entries(parsed || {})) {
      if (job && typeof job.job_id === 'string' && now - (job.started_at || 0) < MAX_AGE_MS) fresh[conv] = job
    }
    return fresh
  } catch {
    return {}
  }
}

function writeAll(all: Record<string, PendingDeepJob>): void {
  try {
    if (Object.keys(all).length) localStorage.setItem(KEY, JSON.stringify(all))
    else localStorage.removeItem(KEY)
  } catch {
    /* storage unavailable: the job still runs, it just will not be resumed from here */
  }
}

export function rememberDeepJob(conversationId: string, jobId: string): void {
  const all = readAll()
  all[conversationId] = { job_id: jobId, started_at: Date.now() }
  writeAll(all)
}

export function noteDeepSeq(conversationId: string, seq: number): void {
  const all = readAll()
  if (all[conversationId] && seq > (all[conversationId].last_seq ?? 0)) {
    all[conversationId].last_seq = seq
    writeAll(all)
  }
}

export function forgetDeepJob(conversationId: string): void {
  const all = readAll()
  if (conversationId in all) {
    delete all[conversationId]
    writeAll(all)
  }
}

export function pendingDeepJob(conversationId: string): PendingDeepJob | null {
  return readAll()[conversationId] ?? null
}

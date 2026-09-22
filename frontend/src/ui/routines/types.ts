export type RoutineActionType =
  | 'news_digest'
  | 'daily_briefing'
  | 'reminder'
  | 'assistant_prompt'

export type RoutineSchedule =
  | { type: 'daily'; time: string; days?: number[] }
  | { type: 'weekly'; time: string; days: number[] }
  | { type: 'once'; at: string; time?: string; days?: number[] }

export type RoutineTarget =
  | { type: 'assistant'; project_id?: undefined }
  | { type: 'persona'; project_id: string }
  | { type: 'project'; project_id: string }

export type RoutineDelivery = {
  /** Backwards-compatible v1 flag. */
  in_app: boolean
  /** Show the completed run in HomePilot's notification surface. */
  notification: boolean
  /** Persist routine output as a native conversation. */
  create_conversation: boolean
  /** Speak only when an optional companion is actively connected. */
  speak_if_active: boolean
  /** Run useful missed work after backend downtime. */
  catch_up: boolean
}

export type Routine = {
  id: string
  name: string
  enabled: boolean
  timezone: string
  schedule: RoutineSchedule
  target: RoutineTarget
  action: {
    type: RoutineActionType
    parameters: Record<string, unknown>
  }
  delivery: RoutineDelivery
  created_at: string
  updated_at: string
}

export type RoutineDraft = Omit<Routine, 'id' | 'created_at' | 'updated_at'>


export type RoutineRun = {
  id: string
  routine_id: string
  run_key: string
  scheduled_for: string
  started_at?: string | null
  completed_at?: string | null
  status: 'running' | 'success' | 'failed' | 'missed'
  project_id?: string | null
  conversation_id?: string | null
  result_preview?: string | null
  result?: {
    routine_id?: string
    routine_name?: string
    target?: RoutineTarget
    provider?: string
    notification?: boolean
    speak_if_active?: boolean
    presentation?: {
      speech_text?: string
      display_markdown?: string
      sources?: Array<{ name?: string; url?: string }>
      avatar?: { emotion?: string; intensity?: number }
    }
  }
  error?: string | null
  seen_at?: string | null
  opened_at?: string | null
  created_at: string
}

export type RoutineActionType =
  | 'news_digest'
  | 'daily_briefing'
  | 'reminder'
  | 'assistant_prompt'

export type RoutineSchedule =
  | { type: 'daily'; time: string; days?: number[] }
  | { type: 'weekly'; time: string; days: number[] }
  | { type: 'once'; at: string; time?: string; days?: number[] }

export type Routine = {
  id: string
  name: string
  enabled: boolean
  timezone: string
  schedule: RoutineSchedule
  action: {
    type: RoutineActionType
    parameters: Record<string, unknown>
  }
  delivery: {
    in_app: boolean
    speak_if_active: boolean
    catch_up: boolean
  }
  created_at: string
  updated_at: string
}

export type RoutineDraft = Omit<Routine, 'id' | 'created_at' | 'updated_at'>

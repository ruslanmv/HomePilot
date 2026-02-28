/** Hook for Teams room CRUD operations */

import { useState, useEffect, useCallback } from 'react'
import type { MeetingRoom } from './types'

type Args = {
  backendUrl: string
  apiKey?: string
}

/** LLM settings passed to /run-turn and /react so the backend uses the same
 *  provider the user configured in Enterprise Settings. */
export type TeamsLLMSettings = {
  provider?: string
  model?: string
  base_url?: string
  max_concurrent?: number
}

function headers(apiKey?: string): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (apiKey) h['x-api-key'] = apiKey
  return h
}

/** Read LLM settings from localStorage (same keys as SettingsPanel / App.tsx). */
function readLLMSettings(): TeamsLLMSettings {
  const provider = localStorage.getItem('homepilot_provider_chat') || undefined
  const model = localStorage.getItem('homepilot_model_chat') || undefined
  const base_url = localStorage.getItem('homepilot_base_url_chat') || undefined
  const concRaw = localStorage.getItem('homepilot_teams_concurrent_calls')
  const max_concurrent = concRaw ? parseInt(concRaw, 10) : undefined
  return { provider, model, base_url, max_concurrent }
}

export function useTeamsRooms({ backendUrl, apiKey }: Args) {
  const [rooms, setRooms] = useState<MeetingRoom[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchRooms = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${backendUrl}/v1/teams/rooms`, {
        headers: headers(apiKey),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setRooms(data)
    } catch (e: any) {
      setError(e.message || 'Failed to fetch rooms')
    } finally {
      setLoading(false)
    }
  }, [backendUrl, apiKey])

  useEffect(() => {
    fetchRooms()
  }, [fetchRooms])

  const createRoom = useCallback(
    async (params: {
      name: string
      description?: string
      participant_ids?: string[]
      turn_mode?: string
      agenda?: string[]
    }): Promise<MeetingRoom> => {
      const res = await fetch(`${backendUrl}/v1/teams/rooms`, {
        method: 'POST',
        headers: headers(apiKey),
        body: JSON.stringify(params),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
        throw new Error(err.detail || 'Failed to create room')
      }
      const room = await res.json()
      setRooms((prev) => [room, ...prev])
      return room
    },
    [backendUrl, apiKey],
  )

  const deleteRoom = useCallback(
    async (roomId: string) => {
      const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}`, {
        method: 'DELETE',
        headers: headers(apiKey),
      })
      if (!res.ok) throw new Error('Failed to delete room')
      setRooms((prev) => prev.filter((r) => r.id !== roomId))
    },
    [backendUrl, apiKey],
  )

  const addParticipant = useCallback(
    async (roomId: string, personaId: string): Promise<MeetingRoom> => {
      const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/participants`, {
        method: 'POST',
        headers: headers(apiKey),
        body: JSON.stringify({ persona_id: personaId }),
      })
      if (!res.ok) throw new Error('Failed to add participant')
      const room = await res.json()
      setRooms((prev) => prev.map((r) => (r.id === roomId ? room : r)))
      return room
    },
    [backendUrl, apiKey],
  )

  const removeParticipant = useCallback(
    async (roomId: string, personaId: string): Promise<MeetingRoom> => {
      const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/participants/${personaId}`, {
        method: 'DELETE',
        headers: headers(apiKey),
      })
      if (!res.ok) throw new Error('Failed to remove participant')
      const room = await res.json()
      setRooms((prev) => prev.map((r) => (r.id === roomId ? room : r)))
      return room
    },
    [backendUrl, apiKey],
  )

  const sendMessage = useCallback(
    async (roomId: string, content: string, senderName?: string): Promise<MeetingRoom> => {
      const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/message`, {
        method: 'POST',
        headers: headers(apiKey),
        body: JSON.stringify({ content, sender_name: senderName || 'You' }),
      })
      if (!res.ok) throw new Error('Failed to send message')
      const room = await res.json()
      setRooms((prev) => prev.map((r) => (r.id === roomId ? room : r)))
      return room
    },
    [backendUrl, apiKey],
  )

  const getRoom = useCallback(
    async (roomId: string): Promise<MeetingRoom> => {
      const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}`, {
        headers: headers(apiKey),
      })
      if (!res.ok) throw new Error('Room not found')
      return await res.json()
    },
    [backendUrl, apiKey],
  )

  /** Trigger persona turns after a human message was sent (round-robin legacy). */
  const runTurn = useCallback(
    async (roomId: string, humanName?: string): Promise<MeetingRoom> => {
      const llm = readLLMSettings()
      const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/run-turn`, {
        method: 'POST',
        headers: headers(apiKey),
        body: JSON.stringify({
          human_name: humanName || 'You',
          ...llm,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
        throw new Error(err.detail || 'Failed to run turn')
      }
      const data = await res.json()
      const room = data.room as MeetingRoom
      setRooms((prev) => prev.map((r) => (r.id === roomId ? room : r)))
      return room
    },
    [backendUrl, apiKey],
  )

  /** Reactive step: intent scoring + only relevant speakers respond. */
  const reactStep = useCallback(
    async (roomId: string): Promise<MeetingRoom> => {
      const llm = readLLMSettings()
      const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/react`, {
        method: 'POST',
        headers: headers(apiKey),
        body: JSON.stringify(llm),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
        throw new Error(err.detail || 'React step failed')
      }
      const data = await res.json()
      const room = data.room as MeetingRoom
      setRooms((prev) => prev.map((r) => (r.id === roomId ? room : r)))
      return room
    },
    [backendUrl, apiKey],
  )

  /** Call on a specific persona to speak next (moderated mode). */
  const callOn = useCallback(
    async (roomId: string, personaId: string): Promise<void> => {
      await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/moderation/call-on`, {
        method: 'POST',
        headers: headers(apiKey),
        body: JSON.stringify({ persona_id: personaId }),
      })
    },
    [backendUrl, apiKey],
  )

  /** Toggle hand-raise for a persona. */
  const toggleHandRaise = useCallback(
    async (roomId: string, personaId: string): Promise<void> => {
      await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/hand-raise/${personaId}`, {
        method: 'POST',
        headers: headers(apiKey),
      })
    },
    [backendUrl, apiKey],
  )

  /** Toggle mute for a persona (muted personas are skipped by orchestrator). */
  const toggleMute = useCallback(
    async (roomId: string, personaId: string): Promise<void> => {
      await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/mute/${personaId}`, {
        method: 'POST',
        headers: headers(apiKey),
      })
    },
    [backendUrl, apiKey],
  )

  return {
    rooms,
    loading,
    error,
    refresh: fetchRooms,
    createRoom,
    deleteRoom,
    addParticipant,
    removeParticipant,
    sendMessage,
    runTurn,
    reactStep,
    callOn,
    toggleHandRaise,
    toggleMute,
    getRoom,
  }
}

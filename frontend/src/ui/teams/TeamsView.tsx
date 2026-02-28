/**
 * TeamsView — Main orchestrator for the Teams tab.
 *
 * Manages three view modes (same pattern as AvatarStudio):
 *   1. Landing page (session grid)
 *   2. Creation wizard
 *   3. Active meeting room
 */

import React, { useState, useCallback, useEffect, useMemo } from 'react'
import type { MeetingRoom as MeetingRoomT, PersonaSummary } from './types'
import { useTeamsRooms } from './useTeamsRooms'
import { TeamsLandingPage } from './TeamsLandingPage'
import { CreateSessionWizard } from './CreateSessionWizard'
import { MeetingRoom } from './MeetingRoom'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface TeamsViewProps {
  backendUrl: string
  apiKey?: string
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TeamsView({ backendUrl, apiKey }: TeamsViewProps) {
  const [viewMode, setViewMode] = useState<'landing' | 'wizard' | 'room'>('landing')
  const [activeRoom, setActiveRoom] = useState<MeetingRoomT | null>(null)
  const [personas, setPersonas] = useState<PersonaSummary[]>([])

  const [runningTurn, setRunningTurn] = useState(false)

  const {
    rooms,
    loading,
    refresh,
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
  } = useTeamsRooms({ backendUrl, apiKey })

  // Fetch personas (projects of type 'persona')
  useEffect(() => {
    const fetchPersonas = async () => {
      try {
        const headers: Record<string, string> = {}
        if (apiKey) headers['x-api-key'] = apiKey
        const res = await fetch(`${backendUrl}/projects`, { headers })
        if (!res.ok) return
        const data = await res.json()
        const projects = Array.isArray(data) ? data : data.projects || []
        setPersonas(
          projects.filter((p: any) => p.project_type === 'persona'),
        )
      } catch {
        // non-critical
      }
    }
    fetchPersonas()
  }, [backendUrl, apiKey])

  // Open a room
  const handleOpenRoom = useCallback(async (room: MeetingRoomT) => {
    try {
      const fresh = await getRoom(room.id)
      setActiveRoom(fresh)
      setViewMode('room')
    } catch {
      setActiveRoom(room)
      setViewMode('room')
    }
  }, [getRoom])

  // Create session from wizard
  const handleCreate = useCallback(
    async (params: {
      name: string
      description: string
      participant_ids: string[]
      turn_mode: string
      agenda: string[]
    }) => {
      const room = await createRoom(params)
      setActiveRoom(room)
      setViewMode('room')
    },
    [createRoom],
  )

  // Send message in active room, then trigger persona turns
  const handleSendMessage = useCallback(
    async (content: string) => {
      if (!activeRoom) return
      // 1. Add the human message immediately
      const updated = await sendMessage(activeRoom.id, content)
      setActiveRoom(updated)

      // 2. Trigger persona responses — use reactive orchestrator (intent-based)
      //    for reactive/free-form/moderated modes, fall back to round-robin for legacy
      setRunningTurn(true)
      try {
        const mode = activeRoom.turn_mode || 'reactive'
        if (mode === 'round-robin') {
          const afterTurn = await runTurn(activeRoom.id, 'You')
          setActiveRoom(afterTurn)
        } else {
          const afterReact = await reactStep(activeRoom.id)
          setActiveRoom(afterReact)
        }
      } catch (e) {
        console.warn('Turn/react failed:', e)
      } finally {
        setRunningTurn(false)
      }
    },
    [activeRoom, sendMessage, runTurn, reactStep],
  )

  // Add participant to active room
  const handleAddParticipant = useCallback(
    async (personaId: string) => {
      if (!activeRoom) return
      const updated = await addParticipant(activeRoom.id, personaId)
      setActiveRoom(updated)
    },
    [activeRoom, addParticipant],
  )

  // Remove participant from active room
  const handleRemoveParticipant = useCallback(
    async (personaId: string) => {
      if (!activeRoom) return
      const updated = await removeParticipant(activeRoom.id, personaId)
      setActiveRoom(updated)
    },
    [activeRoom, removeParticipant],
  )

  // Call on a persona to speak (moderated / reactive)
  const handleCallOn = useCallback(
    async (personaId: string) => {
      if (!activeRoom) return
      await callOn(activeRoom.id, personaId)
      // Immediately trigger that persona to speak
      setRunningTurn(true)
      try {
        const after = await reactStep(activeRoom.id)
        setActiveRoom(after)
      } catch (e) {
        console.warn('callOn react failed:', e)
      } finally {
        setRunningTurn(false)
      }
    },
    [activeRoom, callOn, reactStep],
  )

  // Toggle hand raise
  const handleToggleHandRaise = useCallback(
    async (personaId: string) => {
      if (!activeRoom) return
      await toggleHandRaise(activeRoom.id, personaId)
      // Refresh room to get updated hand_raises
      try {
        const fresh = await getRoom(activeRoom.id)
        setActiveRoom(fresh)
      } catch { /* ignore */ }
    },
    [activeRoom, toggleHandRaise, getRoom],
  )

  // Toggle mute
  const handleToggleMute = useCallback(
    async (personaId: string) => {
      if (!activeRoom) return
      await toggleMute(activeRoom.id, personaId)
      // Refresh room to get updated muted list
      try {
        const fresh = await getRoom(activeRoom.id)
        setActiveRoom(fresh)
      } catch { /* ignore */ }
    },
    [activeRoom, toggleMute, getRoom],
  )

  // --- Render ---

  if (viewMode === 'wizard') {
    return (
      <CreateSessionWizard
        personas={personas}
        backendUrl={backendUrl}
        onCancel={() => setViewMode('landing')}
        onCreate={handleCreate}
      />
    )
  }

  if (viewMode === 'room' && activeRoom) {
    return (
      <MeetingRoom
        room={activeRoom}
        personas={personas}
        backendUrl={backendUrl}
        runningTurn={runningTurn}
        onBack={() => { setActiveRoom(null); setViewMode('landing'); refresh() }}
        onSendMessage={handleSendMessage}
        onAddParticipant={handleAddParticipant}
        onRemoveParticipant={handleRemoveParticipant}
        onCallOn={handleCallOn}
        onToggleHandRaise={handleToggleHandRaise}
        onToggleMute={handleToggleMute}
      />
    )
  }

  return (
    <TeamsLandingPage
      rooms={rooms}
      personas={personas}
      backendUrl={backendUrl}
      onNewSession={() => setViewMode('wizard')}
      onOpenRoom={handleOpenRoom}
      onDeleteRoom={deleteRoom}
    />
  )
}

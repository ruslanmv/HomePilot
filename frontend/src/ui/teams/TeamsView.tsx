/**
 * TeamsView — Main orchestrator for the Teams tab.
 *
 * Manages three view modes (same pattern as AvatarStudio):
 *   1. Landing page (session grid)
 *   2. Creation wizard
 *   3. Active meeting room
 */

import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import type { MeetingRoom as MeetingRoomT, PersonaSummary, PlayModeStyle } from './types'
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
    updateRoom,
    addParticipant,
    removeParticipant,
    sendMessage,
    runTurn,
    reactStep,
    previewTurn,
    callOn,
    toggleHandRaise,
    toggleMute,
    getRoom,
    // Play Mode
    startPlayMode,
    stopPlayMode,
    pausePlayMode,
    resumePlayMode,
    getPlayStatus,
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

      // 2. Trigger persona responses — branch by turn_mode
      setRunningTurn(true)
      try {
        const mode = updated.turn_mode || 'reactive'
        if (mode === 'round-robin') {
          // Initiative mode: deterministic turn via /run-turn
          const afterTurn = await runTurn(activeRoom.id, 'You')
          setActiveRoom(afterTurn)
        } else {
          // Reactive mode: intent-scored via /react
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

  // ── Initiative preview + "Run Turn (continue)" ──

  const handlePreviewTurn = useCallback(
    async () => {
      if (!activeRoom) return null
      return await previewTurn(activeRoom.id)
    },
    [activeRoom, previewTurn],
  )

  const handleRunTurnContinue = useCallback(
    async () => {
      if (!activeRoom) return
      setRunningTurn(true)
      try {
        const mode = activeRoom.turn_mode || 'reactive'
        if (mode === 'round-robin') {
          const after = await runTurn(activeRoom.id, 'You')
          setActiveRoom(after)
        } else {
          const after = await reactStep(activeRoom.id)
          setActiveRoom(after)
        }
      } catch (e) {
        console.warn('Run turn (continue) failed:', e)
      } finally {
        setRunningTurn(false)
      }
    },
    [activeRoom, runTurn, reactStep],
  )

  // ── Agenda / Topic editing ──

  const handleUpdateAgenda = useCallback(
    async (agenda: string[]) => {
      if (!activeRoom) return
      const updated = await updateRoom(activeRoom.id, { agenda })
      setActiveRoom(updated)
    },
    [activeRoom, updateRoom],
  )

  const handleUpdateTopic = useCallback(
    async (topic: string) => {
      if (!activeRoom) return
      const updated = await updateRoom(activeRoom.id, { topic })
      setActiveRoom(updated)
    },
    [activeRoom, updateRoom],
  )

  // ── Room settings handlers ──

  const handleChangeTurnMode = useCallback(
    async (turnMode: 'reactive' | 'round-robin') => {
      if (!activeRoom) return
      const updated = await updateRoom(activeRoom.id, { turn_mode: turnMode })
      setActiveRoom(updated)
    },
    [activeRoom, updateRoom],
  )

  const handleSavePolicy = useCallback(
    async (policy: any) => {
      if (!activeRoom) return
      const updated = await updateRoom(activeRoom.id, { policy })
      setActiveRoom(updated)
    },
    [activeRoom, updateRoom],
  )

  // ── Play Mode handlers ──

  const handleStartPlayMode = useCallback(
    async (opts: { style: PlayModeStyle; interval_ms: number; max_rounds: number }) => {
      if (!activeRoom) return
      await startPlayMode(activeRoom.id, opts)
      // Refresh to get play_mode state
      try {
        const fresh = await getRoom(activeRoom.id)
        setActiveRoom(fresh)
      } catch { /* ignore */ }
    },
    [activeRoom, startPlayMode, getRoom],
  )

  const handleStopPlayMode = useCallback(
    async () => {
      if (!activeRoom) return
      await stopPlayMode(activeRoom.id)
      try {
        const fresh = await getRoom(activeRoom.id)
        setActiveRoom(fresh)
      } catch { /* ignore */ }
    },
    [activeRoom, stopPlayMode, getRoom],
  )

  const handlePausePlayMode = useCallback(
    async () => {
      if (!activeRoom) return
      await pausePlayMode(activeRoom.id)
      try {
        const fresh = await getRoom(activeRoom.id)
        setActiveRoom(fresh)
      } catch { /* ignore */ }
    },
    [activeRoom, pausePlayMode, getRoom],
  )

  const handleResumePlayMode = useCallback(
    async () => {
      if (!activeRoom) return
      await resumePlayMode(activeRoom.id)
      try {
        const fresh = await getRoom(activeRoom.id)
        setActiveRoom(fresh)
      } catch { /* ignore */ }
    },
    [activeRoom, resumePlayMode, getRoom],
  )

  // Poll room state during active play mode (to see new messages + round count)
  useEffect(() => {
    if (!activeRoom?.play_mode?.enabled) return
    const interval = setInterval(async () => {
      try {
        const fresh = await getRoom(activeRoom.id)
        setActiveRoom(fresh)
        // Auto-stop polling if play mode ended
        if (!fresh.play_mode?.enabled) {
          clearInterval(interval)
        }
      } catch { /* ignore */ }
    }, 2000) // poll every 2s
    return () => clearInterval(interval)
  }, [activeRoom?.id, activeRoom?.play_mode?.enabled, getRoom])

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
        onPreviewTurn={handlePreviewTurn}
        onRunTurnContinue={handleRunTurnContinue}
        onUpdateAgenda={handleUpdateAgenda}
        onUpdateTopic={handleUpdateTopic}
        onStartPlayMode={handleStartPlayMode}
        onStopPlayMode={handleStopPlayMode}
        onPausePlayMode={handlePausePlayMode}
        onResumePlayMode={handleResumePlayMode}
        onChangeTurnMode={handleChangeTurnMode}
        onSavePolicy={handleSavePolicy}
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

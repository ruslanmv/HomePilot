/**
 * useBridge — React hook for Teams meeting bridge operations.
 *
 * Provides functions to:
 *   - Connect a room to a Teams meeting (paste join URL)
 *   - Disconnect
 *   - Poll bridge status
 *   - Toggle voice detection (STT)
 *   - Send persona messages to Teams chat
 */

import { useState, useCallback, useRef, useEffect, useMemo } from 'react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type BridgeStatus = {
  room_id: string
  connected: boolean
  status: 'not_connected' | 'connected' | 'active' | 'disconnected'
  bridge?: {
    provider: string
    join_url: string
    session_id: string | null
    chat_id: string | null
    connected: boolean
    voice_enabled: boolean
    poll_interval: number
    messages_seen: number
  }
  poller?: {
    running: boolean
    batch_delay: number
  }
}

export type VoiceStatus = {
  voice_enabled?: boolean
  error?: string
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

type Args = {
  backendUrl: string
  apiKey?: string
  roomId?: string
  /** Auto-poll status every N ms (0 = disabled) */
  statusPollInterval?: number
}

function headers(apiKey?: string): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (apiKey) h['x-api-key'] = apiKey
  return h
}

export function useBridge({ backendUrl, apiKey, roomId, statusPollInterval = 0 }: Args) {
  const [status, setStatus] = useState<BridgeStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── Fetch status ─────────────────────────────────────────────────────

  const fetchStatus = useCallback(async (rid?: string) => {
    const id = rid || roomId
    if (!id) return null
    try {
      const res = await fetch(`${backendUrl}/v1/teams/bridge/status/${id}`, {
        headers: headers(apiKey),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: BridgeStatus = await res.json()
      setStatus(data)
      return data
    } catch (e: any) {
      // Not connected is normal
      setStatus({ room_id: id, connected: false, status: 'not_connected' })
      return null
    }
  }, [backendUrl, apiKey, roomId])

  // ── Auto-poll status ─────────────────────────────────────────────────

  useEffect(() => {
    if (!roomId || !statusPollInterval) return
    fetchStatus()
    pollRef.current = setInterval(() => fetchStatus(), statusPollInterval)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [roomId, statusPollInterval, fetchStatus])

  // ── Connect ──────────────────────────────────────────────────────────

  const connect = useCallback(async (params: {
    room_id: string
    join_url: string
    mcp_base_url?: string
    poll_interval?: number
    voice_enabled?: boolean
  }): Promise<BridgeStatus> => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${backendUrl}/v1/teams/bridge/connect`, {
        method: 'POST',
        headers: headers(apiKey),
        body: JSON.stringify(params),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
        throw new Error(err.detail || 'Failed to connect')
      }
      const data: BridgeStatus = await res.json()
      setStatus(data)
      return data
    } catch (e: any) {
      setError(e.message)
      throw e
    } finally {
      setLoading(false)
    }
  }, [backendUrl, apiKey])

  // ── Disconnect ───────────────────────────────────────────────────────

  const disconnect = useCallback(async (rid?: string) => {
    const id = rid || roomId
    if (!id) return
    setLoading(true)
    try {
      await fetch(`${backendUrl}/v1/teams/bridge/disconnect/${id}`, {
        method: 'POST',
        headers: headers(apiKey),
      })
      setStatus({ room_id: id, connected: false, status: 'disconnected' })
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [backendUrl, apiKey, roomId])

  // ── Voice toggle ─────────────────────────────────────────────────────

  const toggleVoice = useCallback(async (enabled: boolean, rid?: string) => {
    const id = rid || roomId
    if (!id) return
    try {
      const res = await fetch(`${backendUrl}/v1/teams/bridge/voice/${id}`, {
        method: 'POST',
        headers: headers(apiKey),
        body: JSON.stringify({ enabled }),
      })
      if (!res.ok) throw new Error('Failed to toggle voice')
      // Refresh status
      await fetchStatus(id)
    } catch (e: any) {
      setError(e.message)
    }
  }, [backendUrl, apiKey, roomId, fetchStatus])

  // ── Send to Teams ────────────────────────────────────────────────────

  const sendToMeeting = useCallback(async (senderName: string, content: string, rid?: string) => {
    const id = rid || roomId
    if (!id) return
    try {
      await fetch(`${backendUrl}/v1/teams/bridge/send/${id}`, {
        method: 'POST',
        headers: headers(apiKey),
        body: JSON.stringify({ sender_name: senderName, content }),
      })
    } catch (e: any) {
      setError(e.message)
    }
  }, [backendUrl, apiKey, roomId])

  // ── Check MCP server availability ───────────────────────────────

  const checkMcpAvailable = useCallback(async (mcpBaseUrl = 'http://localhost:9106'): Promise<boolean> => {
    try {
      const res = await fetch(
        `${backendUrl}/v1/teams/bridge/health?mcp_base_url=${encodeURIComponent(mcpBaseUrl)}`,
        { headers: headers(apiKey) },
      )
      if (!res.ok) return false
      const data = await res.json()
      return !!data.available
    } catch {
      return false
    }
  }, [backendUrl, apiKey])

  return {
    status,
    loading,
    error,
    connect,
    disconnect,
    toggleVoice,
    sendToMeeting,
    fetchStatus,
    checkMcpAvailable,
  }
}


// ---------------------------------------------------------------------------
// Standalone hook: is the Teams MCP server available?
// ---------------------------------------------------------------------------

/**
 * useTeamsMcpAvailable — auto-detection for Teams MCP server.
 *
 * Probes the backend bridge health endpoint on mount.  If the server
 * is installed and healthy, `available` becomes true and the Teams tab
 * appears automatically — no manual toggle needed.
 *
 * A single check runs on mount; no periodic polling.
 */
export function useTeamsMcpAvailable(backendUrl: string, apiKey?: string) {
  const [available, setAvailable] = useState(false)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    let cancelled = false
    const check = async () => {
      try {
        const h: Record<string, string> = {}
        if (apiKey) h['x-api-key'] = apiKey
        const res = await fetch(
          `${backendUrl}/v1/teams/bridge/health`,
          { headers: h },
        )
        if (!res.ok) { if (!cancelled) setAvailable(false); return }
        const data = await res.json()
        if (!cancelled) setAvailable(!!data.available)
      } catch {
        if (!cancelled) setAvailable(false)
      } finally {
        if (!cancelled) setChecking(false)
      }
    }
    check()
    return () => { cancelled = true }
  }, [backendUrl, apiKey])

  return { available, checking }
}

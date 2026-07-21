/**
 * useRemoteChatTarget (Batch 5) — resolve where a chat completion should run.
 *
 * When the Account & Computers flag is on and the user has picked an ONLINE
 * remote computer (fixed selection), this returns the cloud-relay target for
 * that node's chat model — the SAME mechanism "Use for Chat" uses
 * (openai_compat @ {cloud}/ollama/v1, routed by model). Returns null in every
 * other case, so the local chat path is used unchanged.
 *
 * It only RESOLVES a target; the actual conditional swap happens in App's
 * `currentChatSelection()`. No execution, persistence, or provider mutation here.
 */
import { useEffect, useState } from 'react'

import { useAccount } from './HomePilotAccountProvider'
import { useComputer } from './ComputerContext'
import { mirrorClient } from './mirrorClient'
import type { MirrorStatus } from './types'

function cloudBase(status: MirrorStatus | null): string {
  try {
    const ls = localStorage.getItem('homepilot_cloud_url')
    if (ls) return ls.replace(/\/+$/, '')
  } catch { /* ignore */ }
  return (status?.cloud || '').replace(/\/+$/, '')
}

function currentModelChat(): string {
  try { return localStorage.getItem('homepilot_model_chat') || '' } catch { return '' }
}

interface ModelsListResult { chat_models?: Array<{ id?: string } | string> }

function pickChatModel(list: ModelsListResult | null, preferred: string): string {
  const ids: string[] = []
  for (const m of list?.chat_models || []) {
    const id = typeof m === 'string' ? m : m?.id
    if (id) ids.push(id)
  }
  if (preferred && ids.includes(preferred)) return preferred
  return ids[0] || ''
}

export interface RemoteChatTarget {
  baseUrl: string
  model: string
  nodeId: string
  nodeName: string
}

export function useRemoteChatTarget(): RemoteChatTarget | null {
  const { enabled, status } = useAccount()
  const { selectedComputer, selectionMode, presenceOf } = useComputer()
  const [model, setModel] = useState('')

  const nodeId = selectedComputer?.node_id || ''
  const online = nodeId ? presenceOf(nodeId) === 'online' : false
  // Only hijack routing on an explicit, online, fixed pick — never in automatic.
  const active = enabled && selectionMode === 'fixed' && !!nodeId && online

  useEffect(() => {
    if (!active || !nodeId) { setModel(''); return }
    let cancelled = false
    ;(async () => {
      try {
        const list = await mirrorClient.rpc<ModelsListResult>(nodeId, 'models.list', {})
        if (!cancelled) setModel(pickChatModel(list, currentModelChat()))
      } catch {
        // Relay routes by model name — fall back to the current chat model.
        if (!cancelled) setModel(currentModelChat())
      }
    })()
    return () => { cancelled = true }
  }, [active, nodeId])

  if (!active || !selectedComputer) return null
  const cloud = cloudBase(status)
  const resolved = model || currentModelChat()
  if (!cloud || !resolved) return null
  return {
    baseUrl: `${cloud}/ollama/v1`,
    model: resolved,
    nodeId,
    nodeName: selectedComputer.node_name || nodeId,
  }
}

/**
 * Batch 6: honest offline. When the user has PINNED a specific computer (fixed
 * selection) that is currently offline, return its identity so the UI can show
 * an offline state and BLOCK sends — never silently downgrade to Web CPU.
 * Returns null in automatic mode (which may pick another online computer) and
 * whenever the pinned computer is online.
 */
export function useSelectedOfflineNode(): { nodeId: string; nodeName: string } | null {
  const { enabled } = useAccount()
  const { selectedComputer, selectionMode, presenceOf } = useComputer()
  if (!enabled || selectionMode !== 'fixed' || !selectedComputer) return null
  if (presenceOf(selectedComputer.node_id) === 'online') return null
  return {
    nodeId: selectedComputer.node_id,
    nodeName: selectedComputer.node_name || selectedComputer.node_id,
  }
}

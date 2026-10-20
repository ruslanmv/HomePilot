/**
 * Model Management → Chat → OllaBridge: two stacked, independent cards.
 *
 *   OllaBridge Local — the user's own gateway (browser-direct, no sign-in)
 *   OllaBridge Cloud — the OllaBridge account and its synced machines
 *
 * Picking a model on either card routes chat to that connection (see
 * chatRoute.ts). Each card owns its connection; disconnecting one never
 * touches the other. This panel only holds the shared view of the current
 * chat route so each card can tell whether chat is using it.
 */
import React, { useCallback, useEffect, useState } from 'react'
import OllaBridgeCloudCard from './OllaBridgeCloudCard'
import OllaBridgeLocalCard from './OllaBridgeLocalCard'
import {
  LS_BASE_URL_CHAT, LS_MODEL_CHAT, LS_PROVIDER_CHAT, USE_GPU_NODE_EVENT, readChatSelection, routeChatTo,
  type ChatSelection,
} from './chatRoute'

export interface OllaBridgeChatPanelProps {
  backendUrl?: string
  backendApiKey?: string
}

export default function OllaBridgeChatPanel({ backendUrl, backendApiKey }: OllaBridgeChatPanelProps) {
  const [route, setRoute] = useState<ChatSelection>(readChatSelection)

  useEffect(() => {
    const reread = () => setRoute(readChatSelection())
    const onStorage = (e: StorageEvent) => {
      if (!e.key || e.key === LS_PROVIDER_CHAT || e.key === LS_MODEL_CHAT || e.key === LS_BASE_URL_CHAT) reread()
    }
    window.addEventListener('storage', onStorage)
    window.addEventListener(USE_GPU_NODE_EVENT, reread)
    return () => {
      window.removeEventListener('storage', onStorage)
      window.removeEventListener(USE_GPU_NODE_EVENT, reread)
    }
  }, [])

  const selectLocal = useCallback((baseUrl: string, model: string) => {
    routeChatTo('ollabridge-local', baseUrl, model)
    setRoute(readChatSelection())
  }, [])

  const selectCloud = useCallback((baseUrl: string, model: string) => {
    routeChatTo('ollabridge-cloud', baseUrl, model)
    setRoute(readChatSelection())
  }, [])

  return (
    <div className="flex flex-col gap-4" data-testid="ollabridge-chat-panel">
      <OllaBridgeLocalCard route={route} onSelect={selectLocal} backendUrl={backendUrl} backendApiKey={backendApiKey} />
      <OllaBridgeCloudCard route={route} onSelect={selectCloud} />
    </div>
  )
}

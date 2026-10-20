/**
 * Model Management → Chat (or Multimodal) → OllaBridge: two stacked, independent cards.
 *
 *   OllaBridge Local — the user's own gateway (browser-direct, no sign-in)
 *   OllaBridge Cloud — the OllaBridge account and its synced machines
 *
 * On Chat, picking a model routes chat to that connection (chatRoute.ts). On Multimodal
 * (`role="vision"`), it routes image analysis instead (visionRoute.ts) — only after the model
 * passed the vision check — and never touches chat. Each card owns its connection;
 * disconnecting one never touches the other. This panel only holds the shared view of the
 * current route so each card can tell whether it is the one in use.
 */
import React, { useCallback, useEffect, useState } from 'react'
import OllaBridgeCloudCard from './OllaBridgeCloudCard'
import OllaBridgeLocalCard from './OllaBridgeLocalCard'
import {
  LS_BASE_URL_CHAT, LS_MODEL_CHAT, LS_PROVIDER_CHAT, USE_GPU_NODE_EVENT, readChatSelection, routeChatTo,
  type ChatSelection,
} from './chatRoute'
import {
  LS_BASE_URL_VISION, LS_MODEL_VISION, LS_PROVIDER_VISION, USE_VISION_MODEL_EVENT, readVisionSelection, routeVisionTo,
} from './visionRoute'
import type { ShelfRole } from '../../lib/modelShelf'

export interface OllaBridgeChatPanelProps {
  backendUrl?: string
  backendApiKey?: string
  /** `vision` on Models → Multimodal. */
  role?: ShelfRole
}

export default function OllaBridgeChatPanel({ backendUrl, backendApiKey, role = 'chat' }: OllaBridgeChatPanelProps) {
  const vision = role === 'vision'
  const [route, setRoute] = useState<ChatSelection>(vision ? readVisionSelection : readChatSelection)

  useEffect(() => {
    const keys = vision
      ? [LS_PROVIDER_VISION, LS_MODEL_VISION, LS_BASE_URL_VISION]
      : [LS_PROVIDER_CHAT, LS_MODEL_CHAT, LS_BASE_URL_CHAT]
    const event = vision ? USE_VISION_MODEL_EVENT : USE_GPU_NODE_EVENT
    const reread = () => setRoute(vision ? readVisionSelection() : readChatSelection())
    const onStorage = (e: StorageEvent) => { if (!e.key || keys.includes(e.key)) reread() }
    reread()
    window.addEventListener('storage', onStorage)
    window.addEventListener(event, reread)
    return () => {
      window.removeEventListener('storage', onStorage)
      window.removeEventListener(event, reread)
    }
  }, [vision])

  const selectLocal = useCallback((baseUrl: string, model: string) => {
    if (vision) routeVisionTo(baseUrl, model)
    else routeChatTo('ollabridge-local', baseUrl, model)
    setRoute(vision ? readVisionSelection() : readChatSelection())
  }, [vision])

  const selectCloud = useCallback((baseUrl: string, model: string) => {
    if (vision) routeVisionTo(baseUrl, model)
    else routeChatTo('ollabridge-cloud', baseUrl, model)
    setRoute(vision ? readVisionSelection() : readChatSelection())
  }, [vision])

  return (
    <div className="flex flex-col gap-4" data-testid={vision ? 'ollabridge-vision-panel' : 'ollabridge-chat-panel'}>
      <OllaBridgeLocalCard
        route={route}
        onSelect={selectLocal}
        backendUrl={backendUrl}
        backendApiKey={backendApiKey}
        role={role}
      />
      <OllaBridgeCloudCard
        route={route}
        onSelect={selectCloud}
        role={role}
        backendUrl={backendUrl}
        backendApiKey={backendApiKey}
      />
    </div>
  )
}

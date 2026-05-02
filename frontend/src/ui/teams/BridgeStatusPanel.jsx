/**
 * BridgeStatusPanel — Shows the connection status of a Teams meeting bridge.
 *
 * Displays:
 *   - Connected/disconnected state with visual indicator
 *   - Meeting chat ID
 *   - Messages ingested count
 *   - Voice detection toggle (chat-only vs chat+voice)
 *   - Disconnect button
 *
 * This is a compact panel meant to sit inside the MeetingRoom right rail
 * or as an overlay badge.
 */
import React, { useState } from 'react';
import { Wifi, Mic, MessageSquare, Unplug, RefreshCw, ChevronDown, ChevronUp, } from 'lucide-react';
// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function BridgeStatusPanel({ status, onDisconnect, onToggleVoice, onRefresh, loading, }) {
    const [expanded, setExpanded] = useState(false);
    if (!status || !status.connected) {
        return null; // Don't render if not connected
    }
    const bridge = status.bridge;
    const voiceEnabled = bridge?.voice_enabled ?? false;
    const messagesSeen = bridge?.messages_seen ?? 0;
    const chatId = bridge?.chat_id || '(resolving...)';
    return (<div className="bg-gradient-to-r from-blue-500/10 to-purple-500/10 border border-blue-500/20 rounded-xl overflow-hidden">
      {/* Header — always visible */}
      <button onClick={() => setExpanded(!expanded)} className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/5 transition-colors">
        <div className="flex items-center gap-2.5">
          <div className="relative">
            <Wifi size={16} className="text-blue-400"/>
            <div className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-green-400 rounded-full animate-pulse"/>
          </div>
          <div className="text-left">
            <p className="text-xs font-medium text-white/80">Teams Bridge Active</p>
            <p className="text-[10px] text-white/40">
              {messagesSeen} message{messagesSeen !== 1 ? 's' : ''} ingested
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Voice indicator */}
          <div className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ${voiceEnabled
            ? 'bg-purple-500/20 text-purple-300'
            : 'bg-white/10 text-white/40'}`}>
            {voiceEnabled ? <Mic size={10}/> : <MessageSquare size={10}/>}
            {voiceEnabled ? 'Voice' : 'Chat'}
          </div>
          {expanded ? <ChevronUp size={14} className="text-white/40"/> : <ChevronDown size={14} className="text-white/40"/>}
        </div>
      </button>

      {/* Expanded details */}
      {expanded && (<div className="px-4 pb-3 space-y-3 border-t border-white/5">
          {/* Chat ID */}
          <div className="pt-3">
            <p className="text-[10px] text-white/30 uppercase tracking-wider mb-1">Meeting Chat</p>
            <p className="text-xs text-white/60 font-mono truncate">{chatId}</p>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 gap-2">
            <div className="p-2 bg-white/5 rounded-lg">
              <p className="text-[10px] text-white/30">Messages</p>
              <p className="text-sm font-semibold text-white">{messagesSeen}</p>
            </div>
            <div className="p-2 bg-white/5 rounded-lg">
              <p className="text-[10px] text-white/30">Poll Rate</p>
              <p className="text-sm font-semibold text-white">{bridge?.poll_interval || 5}s</p>
            </div>
          </div>

          {/* Voice toggle */}
          <div>
            <p className="text-[10px] text-white/30 uppercase tracking-wider mb-2">Input Mode</p>
            <div className="flex gap-2">
              <button onClick={() => onToggleVoice(false)} className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all ${!voiceEnabled
                ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                : 'bg-white/5 text-white/40 border border-white/10 hover:bg-white/10'}`}>
                <MessageSquare size={12}/>
                Chat
              </button>
              <button onClick={() => onToggleVoice(true)} className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all ${voiceEnabled
                ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
                : 'bg-white/5 text-white/40 border border-white/10 hover:bg-white/10'}`}>
                <Mic size={12}/>
                Voice
              </button>
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-2 pt-1">
            <button onClick={onRefresh} disabled={loading} className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-xs text-white/60 hover:bg-white/10 transition-colors disabled:opacity-40">
              <RefreshCw size={12} className={loading ? 'animate-spin' : ''}/>
              Refresh
            </button>
            <button onClick={onDisconnect} className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-red-500/10 border border-red-500/20 rounded-lg text-xs text-red-400 hover:bg-red-500/20 transition-colors">
              <Unplug size={12}/>
              Disconnect
            </button>
          </div>
        </div>)}
    </div>);
}
// ---------------------------------------------------------------------------
// Compact badge variant (for inline use in headers)
// ---------------------------------------------------------------------------
export function BridgeBadge({ status, onClick, }) {
    if (!status?.connected)
        return null;
    const voiceEnabled = status.bridge?.voice_enabled ?? false;
    const messagesSeen = status.bridge?.messages_seen ?? 0;
    return (<button onClick={onClick} className="flex items-center gap-1.5 px-2.5 py-1 bg-blue-500/15 border border-blue-500/20 rounded-full text-xs text-blue-300 hover:bg-blue-500/25 transition-colors" title="Teams Bridge connected">
      <div className="relative">
        <Wifi size={11}/>
        <div className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 bg-green-400 rounded-full"/>
      </div>
      <span>{messagesSeen}</span>
      {voiceEnabled && <Mic size={10} className="text-purple-300"/>}
    </button>);
}

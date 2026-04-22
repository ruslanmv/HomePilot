/**
 * JoinMeetingWizard — Wizard for connecting a HomePilot room to a live
 * Microsoft Teams meeting.
 *
 * Flow:
 *   Step 1: Paste the Teams meeting join URL
 *   Step 2: Select personas to bring to the meeting
 *   Step 3: Configure bridge settings (voice toggle, poll interval)
 *   → Creates a HomePilot room + connects bridge
 *
 * This is a new, additive component — it does NOT modify CreateSessionWizard.
 */
import React, { useState, useCallback } from 'react';
import { X, ChevronLeft, ChevronRight, Link2, Users, Mic, MessageSquare, Wifi, Check, AlertCircle, } from 'lucide-react';
// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function isValidTeamsUrl(url) {
    return (url.includes('teams.microsoft.com') ||
        url.includes('teams.live.com') ||
        url.includes('teamsjoin') ||
        url.includes('meetup-join'));
}
function resolveAvatarUrl(persona, backendUrl) {
    const thumb = persona.persona_appearance?.selected_thumb_filename;
    const main = persona.persona_appearance?.selected_filename;
    const file = thumb || main;
    if (!file)
        return null;
    return `${backendUrl}/projects/${persona.id}/files/${file}`;
}
// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function JoinMeetingWizard({ personas, backendUrl, onCancel, onJoin }) {
    const [step, setStep] = useState(1);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState(null);
    // Step 1: Meeting link
    const [joinUrl, setJoinUrl] = useState('');
    const [meetingName, setMeetingName] = useState('');
    // Step 2: Personas
    const [selectedIds, setSelectedIds] = useState([]);
    // Step 3: Settings
    const [voiceEnabled, setVoiceEnabled] = useState(false);
    const [pollInterval, setPollInterval] = useState(5);
    const [mcpBaseUrl, setMcpBaseUrl] = useState('http://localhost:9106');
    const urlValid = isValidTeamsUrl(joinUrl);
    const canNext = () => {
        if (step === 1)
            return urlValid && meetingName.trim().length > 0;
        if (step === 2)
            return selectedIds.length > 0;
        return true;
    };
    const togglePersona = useCallback((id) => {
        setSelectedIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]);
    }, []);
    const handleSubmit = useCallback(async () => {
        setSubmitting(true);
        setError(null);
        try {
            // Pre-check: verify Teams MCP server is reachable before attempting connect
            const healthRes = await fetch(`${backendUrl}/v1/teams/bridge/health?mcp_base_url=${encodeURIComponent(mcpBaseUrl)}`).catch(() => null);
            if (!healthRes || !healthRes.ok) {
                throw new Error(`Teams MCP server is not reachable at ${mcpBaseUrl}. ` +
                    'Please ensure teams-mcp-server is running and try again.');
            }
            const healthData = await healthRes.json();
            if (!healthData.available) {
                throw new Error(`Teams MCP server at ${mcpBaseUrl} is not responding. ` +
                    'Start the server with: cd teams-mcp-server && uvicorn teams_mcp.main:app');
            }
            await onJoin({
                name: meetingName.trim() || 'Teams Meeting',
                description: `Bridged from: ${joinUrl}`,
                participant_ids: selectedIds,
                join_url: joinUrl.trim(),
                voice_enabled: voiceEnabled,
                poll_interval: pollInterval,
                mcp_base_url: mcpBaseUrl,
            });
        }
        catch (e) {
            setError(e.message || 'Failed to join meeting');
        }
        finally {
            setSubmitting(false);
        }
    }, [meetingName, joinUrl, selectedIds, voiceEnabled, pollInterval, mcpBaseUrl, backendUrl, onJoin]);
    // ── Render ─────────────────────────────────────────────────────────
    return (<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="relative w-full max-w-2xl mx-4 bg-[#1a1a2e] border border-white/10 rounded-2xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-gradient-to-r from-blue-500/10 to-purple-500/10">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-500/20 rounded-lg">
              <Wifi size={20} className="text-blue-400"/>
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Join Teams Meeting</h2>
              <p className="text-xs text-white/50">Step {step} of 3</p>
            </div>
          </div>
          <button onClick={onCancel} className="p-2 hover:bg-white/10 rounded-lg transition-colors">
            <X size={18} className="text-white/60"/>
          </button>
        </div>

        {/* Progress bar */}
        <div className="h-1 bg-white/5">
          <div className="h-full bg-gradient-to-r from-blue-500 to-purple-500 transition-all duration-300" style={{ width: `${(step / 3) * 100}%` }}/>
        </div>

        {/* Content */}
        <div className="px-6 py-6 min-h-[360px]">
          {/* ── Step 1: Meeting Link ─────────────────────── */}
          {step === 1 && (<div className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-white/70 mb-2">
                  <Link2 size={14} className="inline mr-1.5"/>
                  Teams Meeting Link
                </label>
                <input type="url" value={joinUrl} onChange={(e) => setJoinUrl(e.target.value)} placeholder="https://teams.microsoft.com/l/meetup-join/..." className={`w-full px-4 py-3 bg-white/5 border rounded-xl text-white placeholder-white/30 focus:outline-none focus:ring-2 transition-all ${joinUrl && !urlValid
                ? 'border-red-500/50 focus:ring-red-500/30'
                : 'border-white/10 focus:ring-blue-500/30'}`} autoFocus/>
                {joinUrl && !urlValid && (<p className="mt-1.5 text-xs text-red-400 flex items-center gap-1">
                    <AlertCircle size={12}/>
                    Please paste a valid Microsoft Teams meeting link
                  </p>)}
                {joinUrl && urlValid && (<p className="mt-1.5 text-xs text-green-400 flex items-center gap-1">
                    <Check size={12}/>
                    Valid Teams meeting link detected
                  </p>)}
              </div>

              <div>
                <label className="block text-sm font-medium text-white/70 mb-2">
                  Meeting Name
                </label>
                <input type="text" value={meetingName} onChange={(e) => setMeetingName(e.target.value)} placeholder="e.g. Weekly Standup, Sprint Planning..." className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-white placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-blue-500/30 transition-all"/>
              </div>

              <div className="p-4 bg-blue-500/5 border border-blue-500/10 rounded-xl">
                <h4 className="text-sm font-medium text-blue-300 mb-2">How it works</h4>
                <ul className="text-xs text-white/50 space-y-1.5">
                  <li>1. Paste the Teams meeting join link above</li>
                  <li>2. Select which personas should attend</li>
                  <li>3. The bridge reads the meeting chat in real-time</li>
                  <li>4. Your personas analyze and respond to the conversation</li>
                  <li>5. Optionally enable voice detection for speech-to-text</li>
                </ul>
              </div>
            </div>)}

          {/* ── Step 2: Select Personas ─────────────────── */}
          {step === 2 && (<div className="space-y-4">
              <p className="text-sm text-white/60">
                Select the personas you want to bring to this Teams meeting.
                They will listen to the conversation and can respond.
              </p>

              <div className="grid grid-cols-2 gap-3 max-h-[280px] overflow-y-auto pr-1">
                {personas.map((p) => {
                const selected = selectedIds.includes(p.id);
                const avatarUrl = resolveAvatarUrl(p, backendUrl);
                return (<button key={p.id} onClick={() => togglePersona(p.id)} className={`flex items-center gap-3 p-3 rounded-xl border transition-all text-left ${selected
                        ? 'bg-blue-500/15 border-blue-500/30 ring-1 ring-blue-500/20'
                        : 'bg-white/5 border-white/10 hover:bg-white/10'}`}>
                      {avatarUrl ? (<img src={avatarUrl} alt={p.name} className="w-10 h-10 rounded-full object-cover border border-white/10"/>) : (<div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500/30 to-purple-500/30 flex items-center justify-center text-sm font-semibold text-white/70">
                          {p.name.charAt(0)}
                        </div>)}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-white truncate">{p.name}</p>
                        <p className="text-xs text-white/40 truncate">
                          {p.persona_agent?.role || p.persona_agent?.persona_class || 'Persona'}
                        </p>
                      </div>
                      {selected && (<Check size={16} className="text-blue-400 flex-shrink-0"/>)}
                    </button>);
            })}
              </div>

              {personas.length === 0 && (<div className="text-center py-8 text-white/40">
                  <Users size={32} className="mx-auto mb-2 opacity-50"/>
                  <p className="text-sm">No personas available. Create some first.</p>
                </div>)}

              <p className="text-xs text-white/40 text-center">
                {selectedIds.length} persona{selectedIds.length !== 1 ? 's' : ''} selected
              </p>
            </div>)}

          {/* ── Step 3: Bridge Settings ─────────────────── */}
          {step === 3 && (<div className="space-y-5">
              {/* Input Mode Toggle */}
              <div>
                <label className="block text-sm font-medium text-white/70 mb-3">
                  Input Mode
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <button onClick={() => setVoiceEnabled(false)} className={`p-4 rounded-xl border text-left transition-all ${!voiceEnabled
                ? 'bg-blue-500/15 border-blue-500/30'
                : 'bg-white/5 border-white/10 hover:bg-white/10'}`}>
                    <MessageSquare size={20} className={!voiceEnabled ? 'text-blue-400' : 'text-white/40'}/>
                    <p className="mt-2 text-sm font-medium text-white">Chat Only</p>
                    <p className="text-xs text-white/40 mt-1">
                      Read meeting chat messages via Graph API
                    </p>
                  </button>
                  <button onClick={() => setVoiceEnabled(true)} className={`p-4 rounded-xl border text-left transition-all ${voiceEnabled
                ? 'bg-purple-500/15 border-purple-500/30'
                : 'bg-white/5 border-white/10 hover:bg-white/10'}`}>
                    <Mic size={20} className={voiceEnabled ? 'text-purple-400' : 'text-white/40'}/>
                    <p className="mt-2 text-sm font-medium text-white">Chat + Voice</p>
                    <p className="text-xs text-white/40 mt-1">
                      Chat reading + speech-to-text transcription
                    </p>
                  </button>
                </div>
              </div>

              {/* Poll Interval */}
              <div>
                <label className="block text-sm font-medium text-white/70 mb-2">
                  Chat Poll Interval: {pollInterval}s
                </label>
                <input type="range" min={2} max={30} step={1} value={pollInterval} onChange={(e) => setPollInterval(Number(e.target.value))} className="w-full accent-blue-500"/>
                <div className="flex justify-between text-xs text-white/30 mt-1">
                  <span>2s (fast)</span>
                  <span>30s (slow)</span>
                </div>
              </div>

              {/* MCP Server URL */}
              <div>
                <label className="block text-sm font-medium text-white/70 mb-2">
                  Teams MCP Server URL
                </label>
                <input type="text" value={mcpBaseUrl} onChange={(e) => setMcpBaseUrl(e.target.value)} className="w-full px-4 py-2.5 bg-white/5 border border-white/10 rounded-xl text-white text-sm placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-blue-500/30"/>
                <p className="text-xs text-white/30 mt-1">
                  Default: http://localhost:9106 — must be authenticated first
                </p>
              </div>

              {error && (<div className="p-3 bg-red-500/10 border border-red-500/20 rounded-xl">
                  <p className="text-sm text-red-400">{error}</p>
                </div>)}
            </div>)}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-white/10 bg-white/[0.02]">
          <button onClick={step > 1 ? () => setStep(step - 1) : onCancel} className="flex items-center gap-1.5 px-4 py-2 text-sm text-white/60 hover:text-white/80 transition-colors">
            <ChevronLeft size={16}/>
            {step > 1 ? 'Back' : 'Cancel'}
          </button>

          {step < 3 ? (<button onClick={() => setStep(step + 1)} disabled={!canNext()} className="flex items-center gap-1.5 px-5 py-2.5 text-sm font-medium rounded-xl transition-all disabled:opacity-30 disabled:cursor-not-allowed bg-gradient-to-r from-blue-500 to-purple-500 text-white hover:brightness-110">
              Next
              <ChevronRight size={16}/>
            </button>) : (<button onClick={handleSubmit} disabled={submitting} className="flex items-center gap-2 px-5 py-2.5 text-sm font-medium rounded-xl transition-all disabled:opacity-50 bg-gradient-to-r from-green-500 to-emerald-500 text-white hover:brightness-110">
              {submitting ? (<>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/>
                  Connecting...
                </>) : (<>
                  <Wifi size={16}/>
                  Join Meeting
                </>)}
            </button>)}
        </div>
      </div>
    </div>);
}

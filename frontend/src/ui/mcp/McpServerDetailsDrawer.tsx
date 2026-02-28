/**
 * McpServerDetailsDrawer — info drawer for a catalog/registry server.
 *
 * Shows server metadata, auth type, transport, URL, tags, description,
 * documentation link, and an uninstall button for installed servers.
 * The endpoint URL is editable for installed servers so users can
 * customize the connection if needed.
 *
 * Phase 10+11 — fully additive, does not modify any existing component.
 */

import React, { useState } from 'react'
import {
  X,
  Globe,
  Lock,
  Key,
  Shield,
  ExternalLink,
  Tag,
  Server,
  Radio,
  Trash2,
  Edit3,
  Check,
  Copy,
  AlertCircle,
} from 'lucide-react'
import type { RegistryServer } from '../../agentic/types'
import { needsCredentialInput, needsOAuthFlow, isOpenAuth } from './setupInstructions'

type Props = {
  server: RegistryServer
  backendUrl?: string
  apiKey?: string
  onClose: () => void
  onSetup?: () => void
  onUninstall?: () => void
}

function authBadgeInfo(authType: string) {
  if (isOpenAuth(authType))
    return { icon: Shield, color: 'bg-emerald-500/20 text-emerald-300', label: 'Open — No auth needed' }
  if (needsOAuthFlow(authType))
    return { icon: Lock, color: 'bg-amber-500/20 text-amber-300', label: authType }
  if (needsCredentialInput(authType))
    return { icon: Key, color: 'bg-blue-500/20 text-blue-300', label: authType }
  return { icon: Shield, color: 'bg-white/10 text-white/50', label: authType || 'Unknown' }
}

function statusInfo(server: RegistryServer) {
  if (!server.is_registered) {
    return { dot: 'bg-white/30', label: 'Not installed', color: 'text-white/40' }
  }
  if (server.requires_oauth_config) {
    return { dot: 'bg-amber-400', label: 'Needs setup', color: 'text-amber-300' }
  }
  return { dot: 'bg-emerald-400', label: 'Active', color: 'text-emerald-300' }
}

export function McpServerDetailsDrawer({ server, backendUrl, apiKey, onClose, onSetup, onUninstall }: Props) {
  const auth = authBadgeInfo(server.auth_type)
  const status = statusInfo(server)
  const AuthIcon = auth.icon

  // Editable URL state
  const [editingUrl, setEditingUrl] = useState(false)
  const [urlValue, setUrlValue] = useState(server.url)
  const [urlSaving, setUrlSaving] = useState(false)
  const [urlSaved, setUrlSaved] = useState(false)
  const [urlError, setUrlError] = useState<string | null>(null)
  const [copiedUrl, setCopiedUrl] = useState(false)

  const handleCopyUrl = () => {
    navigator.clipboard.writeText(urlValue).catch(() => {})
    setCopiedUrl(true)
    setTimeout(() => setCopiedUrl(false), 2000)
  }

  const handleSaveUrl = async () => {
    if (!urlValue.trim() || urlValue === server.url) {
      setEditingUrl(false)
      return
    }
    setUrlSaving(true)
    setUrlError(null)
    try {
      // Re-register with updated URL — this updates the gateway
      if (backendUrl) {
        const headers: Record<string, string> = { 'Content-Type': 'application/json' }
        if (apiKey) headers['x-api-key'] = apiKey

        const res = await fetch(
          `${backendUrl}/v1/agentic/registry/${encodeURIComponent(server.id)}/register`,
          {
            method: 'POST',
            headers,
            body: JSON.stringify({ url: urlValue.trim() }),
          },
        )
        if (!res.ok) {
          const json = await res.json().catch(() => ({}))
          throw new Error(json.detail || json.message || `HTTP ${res.status}`)
        }
      }
      setUrlSaved(true)
      setEditingUrl(false)
      setTimeout(() => setUrlSaved(false), 3000)
    } catch (e: any) {
      setUrlError(e?.message || 'Failed to update URL')
    } finally {
      setUrlSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

      {/* Panel */}
      <div
        className="relative w-full max-w-md bg-[#0b0b12] border-l border-white/10 h-full overflow-y-auto animate-slide-in-right"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 bg-[#0b0b12]/95 backdrop-blur border-b border-white/10 px-6 py-4 flex items-center justify-between z-10">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 shrink-0 rounded-xl bg-gradient-to-br from-cyan-500/20 to-blue-500/20 border border-white/10 flex items-center justify-center text-cyan-400">
              <Globe size={18} strokeWidth={2} />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">{server.name}</h2>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-xs text-white/40">{server.provider}</span>
                <span className="text-white/20">·</span>
                <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${status.color}`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${status.dot}`} />
                  {status.label}
                </span>
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-xl transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-6 space-y-5">
          {/* Description */}
          <p className="text-sm text-white/60 leading-relaxed">{server.description}</p>

          {/* Info grid */}
          <div className="grid grid-cols-2 gap-3">
            <InfoCard label="Category" value={server.category} icon={<Tag size={14} />} />
            <InfoCard
              label="Auth Type"
              value={auth.label}
              icon={<AuthIcon size={14} />}
              badgeColor={auth.color}
            />
            <InfoCard
              label="Transport"
              value={server.transport || 'Auto-detect'}
              icon={<Radio size={14} />}
            />
            <InfoCard
              label="Security"
              value={server.secure ? 'Encrypted' : 'Standard'}
              icon={<Shield size={14} />}
            />
          </div>

          {/* Endpoint — editable for installed servers */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide">
                Endpoint
              </h3>
              <div className="flex items-center gap-1">
                {urlSaved && (
                  <span className="text-[10px] text-emerald-400 mr-1">Saved</span>
                )}
                <button
                  onClick={handleCopyUrl}
                  className="p-1 text-white/30 hover:text-white/60 transition-colors rounded"
                  title="Copy URL"
                >
                  {copiedUrl ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                </button>
                {server.is_registered && (
                  <button
                    onClick={() => {
                      if (editingUrl) {
                        setEditingUrl(false)
                        setUrlValue(server.url)
                        setUrlError(null)
                      } else {
                        setEditingUrl(true)
                      }
                    }}
                    className="p-1 text-white/30 hover:text-white/60 transition-colors rounded"
                    title={editingUrl ? 'Cancel edit' : 'Edit URL'}
                  >
                    {editingUrl ? <X size={12} /> : <Edit3 size={12} />}
                  </button>
                )}
              </div>
            </div>

            {editingUrl ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Server size={13} className="text-white/30 shrink-0" />
                  <input
                    type="text"
                    value={urlValue}
                    onChange={(e) => setUrlValue(e.target.value)}
                    className="flex-1 text-xs text-white bg-black/30 border border-cyan-500/30 rounded-lg px-3 py-2 font-mono focus:outline-none focus:border-cyan-500/50 transition-colors"
                    autoFocus
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleSaveUrl()
                      if (e.key === 'Escape') { setEditingUrl(false); setUrlValue(server.url) }
                    }}
                  />
                </div>
                {urlError && (
                  <div className="flex items-center gap-1 text-red-400 text-[11px]">
                    <AlertCircle size={10} />
                    {urlError}
                  </div>
                )}
                <div className="flex items-center gap-2 justify-end">
                  <button
                    onClick={() => { setEditingUrl(false); setUrlValue(server.url); setUrlError(null) }}
                    className="px-2.5 py-1 text-xs text-white/50 hover:text-white/70 bg-white/5 rounded-lg transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleSaveUrl}
                    disabled={urlSaving || !urlValue.trim()}
                    className="px-2.5 py-1 text-xs text-cyan-300 bg-cyan-500/20 hover:bg-cyan-500/30 rounded-lg transition-colors disabled:opacity-50"
                  >
                    {urlSaving ? 'Saving...' : 'Save URL'}
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <Server size={13} className="text-white/30 shrink-0" />
                <code className="text-xs text-white/50 bg-white/5 border border-white/10 rounded-lg px-3 py-2 block font-mono break-all flex-1">
                  {urlValue}
                </code>
              </div>
            )}
          </div>

          {/* Tags */}
          {server.tags.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide mb-2">
                Tags
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {server.tags.map((tag) => (
                  <span
                    key={tag}
                    className="text-xs px-2.5 py-1 rounded-full bg-white/5 text-white/50 border border-white/5"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Auth details */}
          <div>
            <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide mb-2">
              Authentication Details
            </h3>
            <div className="rounded-xl bg-white/5 border border-white/10 p-4 space-y-2">
              <div className="flex items-center gap-2">
                <span className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full font-medium ${auth.color}`}>
                  <AuthIcon size={10} />
                  {server.auth_type}
                </span>
              </div>
              <p className="text-xs text-white/40 leading-relaxed">
                {isOpenAuth(server.auth_type)
                  ? 'This server is publicly accessible and does not require any authentication credentials.'
                  : needsOAuthFlow(server.auth_type)
                    ? 'This server requires OAuth authorization. You will be redirected to the provider to grant access.'
                    : needsCredentialInput(server.auth_type)
                      ? 'This server requires an API key or token. You can obtain one from the provider\'s developer settings.'
                      : 'Check the provider\'s documentation for authentication requirements.'}
              </p>
            </div>
          </div>

          {/* Documentation link */}
          {server.documentation_url && (
            <a
              href={server.documentation_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 w-full px-4 py-3 text-sm font-medium text-cyan-300 bg-cyan-500/10 hover:bg-cyan-500/20 rounded-xl transition-colors border border-cyan-500/20"
            >
              <ExternalLink size={16} />
              View Documentation
            </a>
          )}

          {/* Setup button (if installed but needs config) */}
          {server.is_registered && server.requires_oauth_config && onSetup && (
            <button
              onClick={onSetup}
              className="flex items-center gap-2 w-full justify-center px-4 py-3 text-sm font-medium text-amber-200 bg-amber-500/20 hover:bg-amber-500/30 rounded-xl transition-colors border border-amber-500/30"
            >
              <Key size={16} />
              Complete Setup
            </button>
          )}

          {/* Uninstall button (if installed) */}
          {server.is_registered && onUninstall && (
            <div className="pt-3 border-t border-white/5">
              <button
                onClick={onUninstall}
                className="flex items-center gap-2 w-full justify-center px-4 py-2.5 text-sm font-medium text-red-300/70 hover:text-red-300 bg-transparent hover:bg-red-500/10 rounded-xl transition-colors"
              >
                <Trash2 size={14} />
                Uninstall Server
              </button>
            </div>
          )}
        </div>
      </div>

      <style>{`
        @keyframes slide-in-right {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
        .animate-slide-in-right {
          animation: slide-in-right 0.2s ease-out;
        }
      `}</style>
    </div>
  )
}

// ── Tiny info card ────────────────────────────────────────────────────

function InfoCard({
  label,
  value,
  icon,
  badgeColor,
}: {
  label: string
  value: string
  icon: React.ReactNode
  badgeColor?: string
}) {
  return (
    <div className="rounded-xl bg-white/5 border border-white/5 p-3">
      <div className="flex items-center gap-1.5 text-white/30 mb-1">
        {icon}
        <span className="text-[10px] uppercase tracking-wide font-semibold">{label}</span>
      </div>
      {badgeColor ? (
        <span className={`inline-flex items-center text-xs font-medium px-2 py-0.5 rounded-full ${badgeColor}`}>
          {value}
        </span>
      ) : (
        <span className="text-xs text-white/70 font-medium">{value}</span>
      )}
    </div>
  )
}

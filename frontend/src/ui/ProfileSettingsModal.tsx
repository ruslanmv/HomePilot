/**
 * ProfileSettingsModal — additive component (v1).
 *
 * Enterprise-style modal with 3 tabs:
 *   1. Profile  — identity, contact info, country/language/timezone
 *   2. Preferences — personalization, companion, content prefs, memory
 *   3. Integrations — secrets vault
 */
import React, { useEffect, useMemo, useState } from 'react'
import type { UserProfile, SecretListItem, MemoryItem } from './profileApi'
import {
  fetchProfile,
  saveProfile,
  listSecrets,
  upsertSecret,
  deleteSecret,
  fetchMemory,
  saveMemory,
  deleteMemoryItem,
} from './profileApi'
import AvatarUploader from './components/AvatarUploader'
import {
  COUNTRIES,
  LANGUAGES,
  getTimezonesForCountry,
  getSystemTimezone,
  formatTimezoneLabel,
} from './localeData'

type TabKey = 'profile' | 'prefs' | 'integrations'

const emptyProfile: UserProfile = {
  display_name: '',
  email: '',
  linkedin: '',
  website: '',
  company: '',
  role: '',
  country: '',
  locale: 'en',
  timezone: '',
  bio: '',

  personalization_enabled: true,
  likes: [],
  dislikes: [],
  favorite_persona_tags: [],
  preferred_tone: 'neutral',
  allow_usage_for_recommendations: true,

  companion_mode_enabled: false,
  affection_level: 'friendly',
  preferred_name: '',
  preferred_pronouns: '',
  preferred_terms_of_endearment: [],
  hard_boundaries: [],
  sensitive_topics: [],
  consent_notes: '',

  default_spicy_strength: 0.3,
  allowed_content_tags: [],
  blocked_content_tags: [],
}

function uid6() {
  return Math.random().toString(36).slice(2, 8)
}

// ---------------------------------------------------------------------------
// Reusable tag-input component
// ---------------------------------------------------------------------------

function TagInput({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string
  value: string[]
  onChange: (next: string[]) => void
  placeholder?: string
}) {
  const [draft, setDraft] = useState('')
  return (
    <div className="space-y-2">
      <div className="text-xs text-white/60">{label}</div>
      <div className="flex gap-2">
        <input
          className="flex-1 bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-white placeholder:text-white/30 outline-none focus:border-white/20"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              const t = draft.trim()
              if (!t) return
              onChange(Array.from(new Set([...value, t])))
              setDraft('')
            }
          }}
          placeholder={placeholder || 'Type and press Enter or Add'}
        />
        <button
          type="button"
          className="px-3 py-2 rounded-xl bg-white/10 hover:bg-white/15 border border-white/10 text-sm text-white/80"
          onClick={() => {
            const t = draft.trim()
            if (!t) return
            onChange(Array.from(new Set([...value, t])))
            setDraft('')
          }}
        >
          Add
        </button>
      </div>
      {value.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {value.map((t) => (
            <button
              key={t}
              type="button"
              className="text-xs px-2.5 py-1 rounded-full bg-white/5 border border-white/10 text-white/70 hover:text-white hover:bg-white/10"
              onClick={() => onChange(value.filter((x) => x !== t))}
              title="Remove"
            >
              {t} <span className="text-white/30">&times;</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function clamp01(n: number) {
  if (Number.isNaN(n)) return 0
  return Math.max(0, Math.min(1, n))
}

// ---------------------------------------------------------------------------
// Main modal
// ---------------------------------------------------------------------------

export default function ProfileSettingsModal({
  backendUrl,
  apiKey,
  nsfwMode,
  onClose,
  token: tokenProp,
}: {
  backendUrl: string
  apiKey: string
  nsfwMode: boolean
  onClose: () => void
  /** Optional Bearer token for per-user endpoints. Falls back to localStorage. */
  token?: string
}) {
  const [tab, setTab] = useState<TabKey>('profile')

  // Resolve auth token (prop > localStorage)
  const authToken = tokenProp || localStorage.getItem('homepilot_auth_token') || ''

  const [profile, setProfile] = useState<UserProfile>(emptyProfile)
  const [secrets, setSecrets] = useState<SecretListItem[]>([])
  const [memory, setMemory] = useState<MemoryItem[]>([])
  const [avatarUrl, setAvatarUrl] = useState('')

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [savedMsg, setSavedMsg] = useState(false)

  const [secretKey, setSecretKey] = useState('')
  const [secretVal, setSecretVal] = useState('')
  const [secretDesc, setSecretDesc] = useState('')

  const [memText, setMemText] = useState('')
  const [memCat, setMemCat] = useState<MemoryItem['category']>('general')
  const [memImportance, setMemImportance] = useState(3)
  const [memPinned, setMemPinned] = useState(false)

  const canUseBackend = useMemo(() => !!backendUrl, [backendUrl])

  async function refreshAll() {
    if (!canUseBackend) return
    setLoading(true)
    setErr(null)
    try {
      const p = await fetchProfile(backendUrl, apiKey)
      const merged = { ...emptyProfile, ...p }
      // Auto-detect system timezone if profile has none saved
      if (!merged.timezone) {
        merged.timezone = getSystemTimezone()
      }
      setProfile(merged)
      const s = await listSecrets(backendUrl, apiKey)
      setSecrets(s)
      const m = await fetchMemory(backendUrl, apiKey)
      setMemory(m)
      // Load avatar from stored user data (if available)
      try {
        const savedUser = localStorage.getItem('homepilot_auth_user')
        if (savedUser) {
          const u = JSON.parse(savedUser)
          if (u.avatar_url) setAvatarUrl(u.avatar_url)
        }
      } catch {}
    } catch (e: any) {
      setErr(e?.message || String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refreshAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function onSaveAll() {
    setSaving(true)
    setErr(null)
    setSavedMsg(false)
    try {
      await saveProfile(backendUrl, apiKey, {
        ...profile,
        default_spicy_strength: clamp01(profile.default_spicy_strength),
      })
      await saveMemory(backendUrl, apiKey, memory)
      setSavedMsg(true)
      setTimeout(() => setSavedMsg(false), 2500)
    } catch (e: any) {
      setErr(e?.message || String(e))
    } finally {
      setSaving(false)
    }
  }

  async function onAddSecret() {
    const k = secretKey.trim()
    const v = secretVal
    if (!k || !v) return
    setErr(null)
    try {
      await upsertSecret(backendUrl, apiKey, { key: k, value: v, description: secretDesc })
      setSecretKey('')
      setSecretVal('')
      setSecretDesc('')
      setSecrets(await listSecrets(backendUrl, apiKey))
    } catch (e: any) {
      setErr(e?.message || String(e))
    }
  }

  async function onDeleteSecret(key: string) {
    setErr(null)
    try {
      await deleteSecret(backendUrl, apiKey, key)
      setSecrets(await listSecrets(backendUrl, apiKey))
    } catch (e: any) {
      setErr(e?.message || String(e))
    }
  }

  function addMemory() {
    const t = memText.trim()
    if (!t) return
    const item: MemoryItem = {
      id: `mem_${uid6()}_${Date.now()}`,
      text: t,
      category: memCat,
      importance: Math.max(1, Math.min(5, memImportance)),
      pinned: memPinned,
      source: 'user',
    }
    setMemory([item, ...memory])
    setMemText('')
    setMemCat('general')
    setMemImportance(3)
    setMemPinned(false)
  }

  async function removeMemory(id: string) {
    setErr(null)
    try {
      await deleteMemoryItem(backendUrl, apiKey, id)
      setMemory(memory.filter((m) => m.id !== id))
    } catch (e: any) {
      setErr(e?.message || String(e))
    }
  }

  return (
    <div className="fixed inset-0 z-[200] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="w-full max-w-3xl rounded-3xl border border-white/10 bg-[#0b0b0b] shadow-2xl shadow-black/40 overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between">
          <div>
            <div className="text-white/90 font-semibold">Profile &amp; Integrations</div>
            <div className="text-xs text-white/40">
              Profile, preferences, memory, and integrations for personalization.
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-white/70"
          >
            Close
          </button>
        </div>

        {/* Tabs */}
        <div className="px-6 pt-4">
          <div className="inline-flex rounded-2xl bg-white/5 border border-white/10 p-1">
            {[
              { key: 'profile', label: 'Profile' },
              { key: 'prefs', label: 'Preferences' },
              { key: 'integrations', label: 'Integrations' },
            ].map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key as TabKey)}
                className={[
                  'px-4 py-2 rounded-2xl text-sm transition-all',
                  tab === t.key ? 'bg-white/10 text-white' : 'text-white/60 hover:text-white/80',
                ].join(' ')}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="px-6 py-5 max-h-[70vh] overflow-y-auto">
          {loading ? <div className="text-sm text-white/50">Loading...</div> : null}
          {err ? <div className="mb-4 text-sm text-red-400/80">{err}</div> : null}
          {savedMsg ? <div className="mb-4 text-sm text-green-400/80">Saved successfully.</div> : null}

          {/* ================================================================ */}
          {/* TAB 1 — Profile                                                  */}
          {/* ================================================================ */}
          {!loading && tab === 'profile' ? (
            <div className="space-y-5">
              {/* Avatar upload — multi-user identity */}
              {authToken && (
                <AvatarUploader
                  backendUrl={backendUrl}
                  token={authToken}
                  displayName={profile.display_name || 'User'}
                  avatarUrl={avatarUrl}
                  onAvatarChange={(url) => {
                    setAvatarUrl(url)
                    // Sync to localStorage user data
                    try {
                      const saved = localStorage.getItem('homepilot_auth_user')
                      if (saved) {
                        const u = JSON.parse(saved)
                        u.avatar_url = url
                        localStorage.setItem('homepilot_auth_user', JSON.stringify(u))
                      }
                    } catch {}
                  }}
                />
              )}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <input
                  className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                  placeholder="Display name"
                  value={profile.display_name}
                  onChange={(e) => setProfile({ ...profile, display_name: e.target.value })}
                />
                <input
                  className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                  placeholder="Email"
                  value={profile.email}
                  onChange={(e) => setProfile({ ...profile, email: e.target.value })}
                />
                <input
                  className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                  placeholder="LinkedIn URL"
                  value={profile.linkedin}
                  onChange={(e) => setProfile({ ...profile, linkedin: e.target.value })}
                />
                <input
                  className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                  placeholder="Website"
                  value={profile.website}
                  onChange={(e) => setProfile({ ...profile, website: e.target.value })}
                />
                <input
                  className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                  placeholder="Company"
                  value={profile.company}
                  onChange={(e) => setProfile({ ...profile, company: e.target.value })}
                />
                <input
                  className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                  placeholder="Role"
                  value={profile.role}
                  onChange={(e) => setProfile({ ...profile, role: e.target.value })}
                />
              </div>

              {/* Country, Language, Timezone */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="space-y-1.5">
                  <label className="text-[11px] uppercase tracking-wider text-white/40 font-semibold">Country</label>
                  <select
                    className="w-full bg-black border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                    value={profile.country}
                    onChange={(e) => {
                      const code = e.target.value
                      const tzs = getTimezonesForCountry(code)
                      // Auto-select first timezone for this country (or keep current if still valid)
                      const keepTz = tzs.includes(profile.timezone)
                      setProfile({
                        ...profile,
                        country: code,
                        timezone: keepTz ? profile.timezone : (tzs[0] || profile.timezone),
                      })
                    }}
                  >
                    <option value="">Select country...</option>
                    {COUNTRIES.map((c) => (
                      <option key={c.code} value={c.code}>{c.name}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label className="text-[11px] uppercase tracking-wider text-white/40 font-semibold">Language</label>
                  <select
                    className="w-full bg-black border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                    value={profile.locale}
                    onChange={(e) => setProfile({ ...profile, locale: e.target.value })}
                  >
                    <option value="">Select language...</option>
                    {LANGUAGES.map((l) => (
                      <option key={l.code} value={l.code}>{l.name} ({l.code})</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label className="text-[11px] uppercase tracking-wider text-white/40 font-semibold">Timezone</label>
                  <select
                    className="w-full bg-black border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                    value={profile.timezone}
                    onChange={(e) => setProfile({ ...profile, timezone: e.target.value })}
                  >
                    <option value="">Select timezone...</option>
                    {getTimezonesForCountry(profile.country).map((tz) => (
                      <option key={tz} value={tz}>{formatTimezoneLabel(tz)}</option>
                    ))}
                  </select>
                  {!profile.timezone && (
                    <div className="text-[10px] text-white/35">System detected: {getSystemTimezone() || 'unknown'}</div>
                  )}
                </div>
              </div>

              <textarea
                className="w-full bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20 min-h-[110px]"
                placeholder="Short bio (optional)"
                value={profile.bio}
                onChange={(e) => setProfile({ ...profile, bio: e.target.value })}
              />

              <div className="text-xs text-white/40">
                Saved locally on your HomePilot backend.
              </div>
            </div>
          ) : null}

          {/* ================================================================ */}
          {/* TAB 2 — Preferences                                              */}
          {/* ================================================================ */}
          {!loading && tab === 'prefs' ? (
            <div className="space-y-8">
              {/* Spicy mode status (read-only, synced from Global Settings) */}
              <div className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3 flex items-center justify-between">
                <div>
                  <div className="text-sm text-white/80">Spicy mode</div>
                  <div className="text-xs text-white/40">Controlled in Global Settings. Profile stores content preferences.</div>
                </div>
                <div className={[
                  "text-xs px-3 py-1.5 rounded-full border font-semibold",
                  nsfwMode
                    ? "border-red-500/30 bg-red-500/10 text-red-400"
                    : "border-white/10 bg-white/5 text-white/50",
                ].join(' ')}>
                  {nsfwMode ? 'ON' : 'OFF'}
                </div>
              </div>

              {/* Personalization */}
              <div className="flex items-center justify-between bg-white/5 border border-white/10 rounded-2xl px-4 py-3">
                <div>
                  <div className="text-sm text-white/80">Personalization</div>
                  <div className="text-xs text-white/40">Use your preferences and memory for recommendations.</div>
                </div>
                <input
                  type="checkbox"
                  checked={profile.personalization_enabled}
                  onChange={(e) => setProfile({ ...profile, personalization_enabled: e.target.checked })}
                  className="w-5 h-5"
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <div className="text-xs text-white/60">Preferred tone</div>
                  <select
                    className="w-full bg-black border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                    value={profile.preferred_tone}
                    onChange={(e) => setProfile({ ...profile, preferred_tone: e.target.value as any })}
                  >
                    <option value="neutral">Neutral</option>
                    <option value="friendly">Friendly</option>
                    <option value="formal">Formal</option>
                  </select>
                </div>

                <div className="flex items-center justify-between bg-white/5 border border-white/10 rounded-2xl px-4 py-3">
                  <div>
                    <div className="text-sm text-white/80">Allow recommendations</div>
                    <div className="text-xs text-white/40">Permit suggestions for personas/models/tools.</div>
                  </div>
                  <input
                    type="checkbox"
                    checked={profile.allow_usage_for_recommendations}
                    onChange={(e) => setProfile({ ...profile, allow_usage_for_recommendations: e.target.checked })}
                    className="w-5 h-5"
                  />
                </div>
              </div>

              {/* Spicy preference (only meaningful when global nsfwMode ON) */}
              <div className="bg-white/5 border border-white/10 rounded-2xl p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm text-white/80">Default spicy strength</div>
                    <div className="text-xs text-white/40">
                      Default intensity for spicy content when enabled.
                    </div>
                  </div>
                  <div className="text-xs text-white/60">{Math.round(profile.default_spicy_strength * 100)}%</div>
                </div>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.01}
                  value={profile.default_spicy_strength}
                  onChange={(e) => setProfile({ ...profile, default_spicy_strength: parseFloat(e.target.value) })}
                  className="w-full"
                />

                <TagInput
                  label="Allowed content tags (optional)"
                  value={profile.allowed_content_tags}
                  onChange={(allowed_content_tags) => setProfile({ ...profile, allowed_content_tags })}
                  placeholder="e.g. flirting, romance, teasing"
                />
                <TagInput
                  label="Blocked content tags (optional)"
                  value={profile.blocked_content_tags}
                  onChange={(blocked_content_tags) => setProfile({ ...profile, blocked_content_tags })}
                  placeholder="e.g. violence, non-consent"
                />
              </div>

              {/* Companion */}
              <div className="bg-white/5 border border-white/10 rounded-2xl p-4 space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm text-white/80">Companion mode</div>
                    <div className="text-xs text-white/40">Warm, consistent style based on your preferences.</div>
                  </div>
                  <input
                    type="checkbox"
                    checked={profile.companion_mode_enabled}
                    onChange={(e) => setProfile({ ...profile, companion_mode_enabled: e.target.checked })}
                    className="w-5 h-5"
                  />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <input
                    className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                    placeholder="Preferred name (what AI calls you)"
                    value={profile.preferred_name}
                    onChange={(e) => setProfile({ ...profile, preferred_name: e.target.value })}
                  />
                  <input
                    className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                    placeholder="Pronouns (optional)"
                    value={profile.preferred_pronouns}
                    onChange={(e) => setProfile({ ...profile, preferred_pronouns: e.target.value })}
                  />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
                  <div className="space-y-2">
                    <div className="text-xs text-white/60">Affection level</div>
                    <select
                      className="w-full bg-black border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                      value={profile.affection_level}
                      onChange={(e) => setProfile({ ...profile, affection_level: e.target.value as any })}
                    >
                      <option value="friendly">Friendly</option>
                      <option value="affectionate">Affectionate</option>
                      <option value="romantic">Romantic</option>
                    </select>
                  </div>

                  <TagInput
                    label="Preferred terms of endearment (optional)"
                    value={profile.preferred_terms_of_endearment}
                    onChange={(preferred_terms_of_endearment) =>
                      setProfile({ ...profile, preferred_terms_of_endearment })
                    }
                    placeholder="e.g. sweetheart, darling"
                  />
                </div>

                <TagInput
                  label="Hard boundaries"
                  value={profile.hard_boundaries}
                  onChange={(hard_boundaries) => setProfile({ ...profile, hard_boundaries })}
                  placeholder="e.g. no humiliation, no guilt-tripping"
                />
                <TagInput
                  label="Sensitive topics"
                  value={profile.sensitive_topics}
                  onChange={(sensitive_topics) => setProfile({ ...profile, sensitive_topics })}
                  placeholder="e.g. avoid trauma unless I ask"
                />

                <textarea
                  className="w-full bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20 min-h-[90px]"
                  placeholder="Consent notes / agreements (optional)"
                  value={profile.consent_notes}
                  onChange={(e) => setProfile({ ...profile, consent_notes: e.target.value })}
                />
              </div>

              {/* Tags */}
              <TagInput
                label="Likes (topics, styles, genres)"
                value={profile.likes}
                onChange={(likes) => setProfile({ ...profile, likes })}
                placeholder="e.g. cyberpunk, cozy talks, portraits"
              />
              <TagInput
                label="Dislikes (avoid recommendations)"
                value={profile.dislikes}
                onChange={(dislikes) => setProfile({ ...profile, dislikes })}
                placeholder="e.g. gore, politics"
              />
              <TagInput
                label="Favorite persona tags"
                value={profile.favorite_persona_tags}
                onChange={(favorite_persona_tags) => setProfile({ ...profile, favorite_persona_tags })}
                placeholder="e.g. girlfriend, coach, storyteller"
              />

              {/* Memory */}
              <div className="bg-white/5 border border-white/10 rounded-2xl p-4 space-y-4">
                <div>
                  <div className="text-sm text-white/80">Memory</div>
                  <div className="text-xs text-white/40">Add facts you want the AI to remember. You can forget anytime.</div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-6 gap-3 items-center">
                  <input
                    className="md:col-span-3 bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                    placeholder="Memory text (e.g. I like evening chats)"
                    value={memText}
                    onChange={(e) => setMemText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        addMemory()
                      }
                    }}
                  />
                  <select
                    className="md:col-span-1 bg-black border border-white/10 rounded-2xl px-3 py-3 text-sm text-white outline-none focus:border-white/20"
                    value={memCat}
                    onChange={(e) => setMemCat(e.target.value as any)}
                  >
                    <option value="general">general</option>
                    <option value="likes">likes</option>
                    <option value="dislikes">dislikes</option>
                    <option value="relationship">relationship</option>
                    <option value="work">work</option>
                    <option value="health">health</option>
                    <option value="other">other</option>
                  </select>
                  <select
                    className="md:col-span-1 bg-black border border-white/10 rounded-2xl px-3 py-3 text-sm text-white outline-none focus:border-white/20"
                    value={memImportance}
                    onChange={(e) => setMemImportance(parseInt(e.target.value, 10))}
                  >
                    {[1, 2, 3, 4, 5].map((n) => (
                      <option key={n} value={n}>
                        {n}*
                      </option>
                    ))}
                  </select>
                  <label className="md:col-span-1 flex items-center gap-2 text-xs text-white/60">
                    <input type="checkbox" checked={memPinned} onChange={(e) => setMemPinned(e.target.checked)} />
                    Pin
                  </label>
                </div>

                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={addMemory}
                    className="px-4 py-2 rounded-2xl bg-white/10 hover:bg-white/15 border border-white/10 text-sm text-white/90"
                  >
                    Add memory
                  </button>
                </div>

                {memory.length === 0 ? (
                  <div className="text-sm text-white/40">No memories saved yet.</div>
                ) : (
                  <div className="divide-y divide-white/10 rounded-2xl border border-white/10 bg-white/5 overflow-hidden">
                    {memory.map((m) => (
                      <div key={m.id} className="px-4 py-3 flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-sm text-white/85">{m.text}</div>
                          <div className="text-xs text-white/40">
                            {m.category} &middot; {m.importance}* {m.pinned ? '&middot; pinned' : ''}
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => removeMemory(m.id)}
                          className="px-3 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/70"
                        >
                          Forget
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : null}

          {/* ================================================================ */}
          {/* TAB 3 — Integrations                                             */}
          {/* ================================================================ */}
          {!loading && tab === 'integrations' ? (
            <div className="space-y-6">
              <div className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3">
                <div className="text-sm text-white/80">Secrets Vault</div>
                <div className="text-xs text-white/40">Optional keys for future integrations. Values are masked.</div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <input
                  className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                  placeholder="KEY_NAME (e.g. NOTION_TOKEN)"
                  value={secretKey}
                  onChange={(e) => setSecretKey(e.target.value)}
                />
                <input
                  className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                  placeholder="Value"
                  type="password"
                  value={secretVal}
                  onChange={(e) => setSecretVal(e.target.value)}
                />
                <input
                  className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/20"
                  placeholder="Description (optional)"
                  value={secretDesc}
                  onChange={(e) => setSecretDesc(e.target.value)}
                />
              </div>

              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={onAddSecret}
                  className="px-4 py-2 rounded-2xl bg-white/10 hover:bg-white/15 border border-white/10 text-sm text-white/90"
                >
                  Save Secret
                </button>
              </div>

              <div className="space-y-2">
                <div className="text-xs text-white/60">Stored keys</div>
                {secrets.length === 0 ? (
                  <div className="text-sm text-white/40">No secrets saved yet.</div>
                ) : (
                  <div className="divide-y divide-white/10 rounded-2xl border border-white/10 bg-white/5 overflow-hidden">
                    {secrets.map((s) => (
                      <div key={s.key} className="px-4 py-3 flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-sm text-white/85 truncate">{s.key}</div>
                          <div className="text-xs text-white/40 truncate">
                            {s.description || '\u2014'} &middot; <span className="text-white/50">{s.masked}</span>
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => onDeleteSecret(s.key)}
                          className="px-3 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/70"
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-white/10 flex items-center justify-between">
          <div className="text-xs text-white/35">
            Profile stores preferences, memory, and integrations.
          </div>
          <button
            type="button"
            onClick={onSaveAll}
            disabled={saving}
            className="px-4 py-2 rounded-2xl bg-blue-600 hover:bg-blue-500 border border-white/10 text-sm text-white font-semibold disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save All'}
          </button>
        </div>
      </div>
    </div>
  )
}

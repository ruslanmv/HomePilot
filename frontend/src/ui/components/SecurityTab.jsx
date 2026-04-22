/**
 * SecurityTab — account password + active sessions.
 *
 * Additive. Rendered inside ``ProfileSettingsModal`` under the
 * "Security" tab. Talks to the authenticated backend endpoints:
 *
 *   POST /v1/auth/change-password
 *   GET  /v1/auth/sessions
 *   POST /v1/auth/sessions/revoke-others
 *
 * Visual language intentionally matches the other tabs in the modal
 * (rounded inputs, white/10 borders, dark surfaces).
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Eye, EyeOff, KeyRound, Shield, ShieldCheck, LogOut, Check } from 'lucide-react';
import { resolveBackendUrl } from '../lib/backendUrl';
function scorePassword(value) {
    if (!value)
        return { score: 0, label: 'Empty', tone: 'text-white/30' };
    let score = 0;
    if (value.length >= 8)
        score++;
    if (value.length >= 12)
        score++;
    if (/[A-Z]/.test(value) && /[a-z]/.test(value))
        score++;
    if (/\d/.test(value) && /[^A-Za-z0-9]/.test(value))
        score++;
    const s = Math.min(score, 4);
    const meta = [
        { score: 0, label: 'Empty', tone: 'text-white/30' },
        { score: 1, label: 'Weak', tone: 'text-red-400' },
        { score: 2, label: 'Fair', tone: 'text-amber-400' },
        { score: 3, label: 'Good', tone: 'text-emerald-400' },
        { score: 4, label: 'Strong', tone: 'text-emerald-300' },
    ];
    return meta[s];
}
function formatDate(value) {
    if (!value)
        return '';
    try {
        const d = new Date(value.replace(' ', 'T') + 'Z');
        return d.toLocaleString();
    }
    catch {
        return value;
    }
}
const MIN_LEN = 8;
export default function SecurityTab({ backendUrl, token, onSaved }) {
    const base = useMemo(() => resolveBackendUrl(backendUrl), [backendUrl]);
    // ── Has-password detection (first-time set vs change flow) ───────────
    // Starts as ``null`` (unknown) until /v1/auth/me resolves. We render the
    // form only after we know the answer — this is what makes the "Set
    // password" flow just work on a fresh account (no current-password field
    // shown, no spurious validation).
    const [hasPassword, setHasPassword] = useState(null);
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const res = await fetch(`${base}/v1/auth/me`, {
                    headers: { Authorization: `Bearer ${token}` },
                });
                const payload = await res.json().catch(() => ({}));
                if (cancelled)
                    return;
                const hp = payload?.user?.has_password;
                // Default to ``true`` (change-mode) when the backend is older and
                // doesn't return the flag — safer than silently hiding the current
                // field on an account that actually has one.
                setHasPassword(typeof hp === 'boolean' ? hp : true);
            }
            catch {
                if (!cancelled)
                    setHasPassword(true);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [base, token]);
    // ── Password form state ───────────────────────────────────────────────
    const [current, setCurrent] = useState('');
    const [next, setNext] = useState('');
    const [confirm, setConfirm] = useState('');
    const [showCurrent, setShowCurrent] = useState(false);
    const [showNext, setShowNext] = useState(false);
    const [signOutOthers, setSignOutOthers] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [formErr, setFormErr] = useState(null);
    const [formOk, setFormOk] = useState(null);
    const strength = useMemo(() => scorePassword(next), [next]);
    const matches = confirm.length === 0 || next === confirm;
    const tooShort = next.length > 0 && next.length < MIN_LEN;
    // "Must differ from current" only applies when an account already has
    // a password. On first-time set, current is empty by design.
    const sameAsCurrent = hasPassword === true && next.length > 0 && next === current;
    const canSubmit = !submitting &&
        hasPassword !== null &&
        next.length >= MIN_LEN &&
        confirm.length >= MIN_LEN &&
        matches &&
        !sameAsCurrent;
    const submit = useCallback(async (event) => {
        event.preventDefault();
        if (!canSubmit)
            return;
        setSubmitting(true);
        setFormErr(null);
        setFormOk(null);
        try {
            const res = await fetch(`${base}/v1/auth/change-password`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({
                    current_password: current,
                    new_password: next,
                    sign_out_others: signOutOthers,
                }),
            });
            const payload = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(payload?.detail || `HTTP ${res.status}`);
            }
            const revoked = payload?.sessions_revoked ?? 0;
            const wasSetting = hasPassword === false;
            setCurrent('');
            setNext('');
            setConfirm('');
            setSignOutOthers(false);
            // Account now has a password — flip the UI into "Change" mode so
            // subsequent edits require the current value.
            setHasPassword(true);
            const baseMsg = wasSetting
                ? 'Password set successfully'
                : 'Password updated successfully';
            const msg = revoked > 0
                ? `${baseMsg} · ${revoked} other session${revoked === 1 ? '' : 's'} signed out`
                : baseMsg;
            setFormOk(msg);
            onSaved?.(msg);
            // Refresh sessions panel
            void loadSessions();
        }
        catch (err) {
            setFormErr(err?.message || 'Failed to update password');
        }
        finally {
            setSubmitting(false);
        }
    }, [base, token, current, next, signOutOthers, canSubmit, onSaved]);
    // ── Active sessions state ────────────────────────────────────────────
    const [sessions, setSessions] = useState([]);
    const [sessionsLoading, setSessionsLoading] = useState(true);
    const [sessionsErr, setSessionsErr] = useState(null);
    const [revoking, setRevoking] = useState(false);
    const loadSessions = useCallback(async () => {
        setSessionsLoading(true);
        setSessionsErr(null);
        try {
            const res = await fetch(`${base}/v1/auth/sessions`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            const payload = await res.json();
            if (!res.ok)
                throw new Error(payload?.detail || `HTTP ${res.status}`);
            setSessions(payload.sessions || []);
        }
        catch (err) {
            setSessionsErr(err?.message || 'Failed to load sessions');
        }
        finally {
            setSessionsLoading(false);
        }
    }, [base, token]);
    useEffect(() => {
        void loadSessions();
    }, [loadSessions]);
    const revokeOthers = useCallback(async () => {
        if (revoking)
            return;
        setRevoking(true);
        setSessionsErr(null);
        try {
            const res = await fetch(`${base}/v1/auth/sessions/revoke-others`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}` },
            });
            const payload = await res.json().catch(() => ({}));
            if (!res.ok)
                throw new Error(payload?.detail || `HTTP ${res.status}`);
            await loadSessions();
            const count = payload?.sessions_revoked ?? 0;
            onSaved?.(count > 0
                ? `${count} other session${count === 1 ? '' : 's'} signed out`
                : 'No other sessions to revoke');
        }
        catch (err) {
            setSessionsErr(err?.message || 'Failed to revoke sessions');
        }
        finally {
            setRevoking(false);
        }
    }, [base, token, revoking, loadSessions, onSaved]);
    const otherSessionsCount = sessions.filter((s) => !s.is_current).length;
    // ── Render ───────────────────────────────────────────────────────────
    return (<div className="space-y-8">
      {/* Password section */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <KeyRound size={14} className="text-white/60"/>
          <h3 className="text-white font-semibold text-sm">
            {hasPassword === false ? 'Set a password' : 'Password'}
          </h3>
        </div>
        <p className="text-xs text-white/50 mb-4">
          {hasPassword === false
            ? 'Your account does not have a password yet. Set one now to secure sign-in.'
            : 'Update the password you use to sign in to HomePilot.'}
        </p>

        <form onSubmit={submit} className="space-y-3">
          {/* Current password — only shown when the account has one. On
            first-time setup we hide it entirely to avoid the "field is
            empty, can't submit" confusion. */}
          {hasPassword === true ? (<PasswordField id="security-current" label="Current password" value={current} onChange={setCurrent} show={showCurrent} onToggleShow={() => setShowCurrent((v) => !v)} autoComplete="current-password" disabled={submitting}/>) : null}

          <div>
            <PasswordField id="security-new" label="New password" value={next} onChange={setNext} show={showNext} onToggleShow={() => setShowNext((v) => !v)} autoComplete="new-password" disabled={submitting}/>
            {next.length > 0 ? (<div className="mt-1.5 flex items-center gap-2 text-[11px]">
                <StrengthBar score={strength.score}/>
                <span className={strength.tone}>{strength.label}</span>
                {tooShort ? (<span className="text-white/40">· min {MIN_LEN} characters</span>) : null}
              </div>) : null}
          </div>

          <div>
            <PasswordField id="security-confirm" label="Confirm new password" value={confirm} onChange={setConfirm} show={showNext} onToggleShow={() => setShowNext((v) => !v)} autoComplete="new-password" disabled={submitting}/>
            {!matches ? (<div className="mt-1.5 text-[11px] text-red-400">
                Passwords don't match
              </div>) : null}
            {sameAsCurrent ? (<div className="mt-1.5 text-[11px] text-red-400">
                New password must differ from the current one
              </div>) : null}
          </div>

          {otherSessionsCount > 0 ? (<label className="flex items-center gap-2 text-xs text-white/70 pt-1">
              <input type="checkbox" checked={signOutOthers} onChange={(e) => setSignOutOthers(e.target.checked)} disabled={submitting} className="accent-emerald-500"/>
              Sign out {otherSessionsCount} other session
              {otherSessionsCount === 1 ? '' : 's'} after updating
            </label>) : null}

          {formErr ? (<div className="text-xs text-red-400/90" role="alert">
              {formErr}
            </div>) : null}
          {formOk ? (<div className="text-xs text-emerald-400/90 flex items-center gap-1.5">
              <Check size={12}/> {formOk}
            </div>) : null}

          <div className="pt-2">
            <button type="submit" disabled={!canSubmit} className="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/15 border border-white/10 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              {submitting
            ? (hasPassword === false ? 'Saving…' : 'Updating…')
            : (hasPassword === false ? 'Set password' : 'Update password')}
            </button>
            {hasPassword === null ? (<span className="ml-2 text-[11px] text-white/40">checking…</span>) : null}
          </div>
        </form>
      </section>

      {/* Divider */}
      <div className="border-t border-white/10"/>

      {/* Active sessions */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <Shield size={14} className="text-white/60"/>
          <h3 className="text-white font-semibold text-sm">Active sessions</h3>
        </div>
        <p className="text-xs text-white/50 mb-4">
          You're currently signed in on {sessions.length || 0} device
          {sessions.length === 1 ? '' : 's'}. Sign out anywhere you don't
          recognise.
        </p>

        {sessionsLoading ? (<div className="text-xs text-white/50">Loading sessions…</div>) : sessionsErr ? (<div className="text-xs text-red-400/90">{sessionsErr}</div>) : (<ul className="space-y-2">
            {sessions.map((s) => (<li key={s.id} className="flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2">
                <div className="flex items-center gap-3">
                  <ShieldCheck size={14} className={s.is_current ? 'text-emerald-400' : 'text-white/40'}/>
                  <div>
                    <div className="text-xs text-white font-medium">
                      Session {s.id}
                      {s.is_current ? (<span className="ml-2 text-[10px] text-emerald-400 font-semibold uppercase tracking-wider">
                          this device
                        </span>) : null}
                    </div>
                    <div className="text-[10px] text-white/40">
                      signed in {formatDate(s.created_at)} · expires{' '}
                      {formatDate(s.expires_at)}
                    </div>
                  </div>
                </div>
              </li>))}
          </ul>)}

        {otherSessionsCount > 0 ? (<div className="pt-3">
            <button type="button" onClick={revokeOthers} disabled={revoking} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/80 disabled:opacity-40">
              <LogOut size={12}/>
              {revoking
                ? 'Signing out…'
                : `Sign out ${otherSessionsCount} other session${otherSessionsCount === 1 ? '' : 's'}`}
            </button>
          </div>) : null}
      </section>

      {/* Hint for future 2FA */}
      <div className="text-[10px] text-white/30 pt-2">
        Two-factor authentication coming soon.
      </div>
    </div>);
}
// ─── Small presentational helpers ──────────────────────────────────────
function PasswordField({ id, label, value, onChange, show, onToggleShow, autoComplete, disabled, }) {
    return (<div>
      <label htmlFor={id} className="block text-[11px] font-medium text-white/60 mb-1">
        {label}
      </label>
      <div className="relative">
        <input id={id} type={show ? 'text' : 'password'} value={value} onChange={(e) => onChange(e.target.value)} autoComplete={autoComplete} disabled={disabled} className="w-full h-10 rounded-xl bg-white/5 border border-white/10 px-3 pr-10 text-sm text-white placeholder:text-white/30 focus:border-white/25 focus:outline-none disabled:opacity-50"/>
        <button type="button" onClick={onToggleShow} tabIndex={-1} aria-label={show ? 'Hide password' : 'Show password'} className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-white/40 hover:text-white/70">
          {show ? <EyeOff size={14}/> : <Eye size={14}/>}
        </button>
      </div>
    </div>);
}
function StrengthBar({ score }) {
    const colors = ['bg-white/10', 'bg-red-500/70', 'bg-amber-500/70', 'bg-emerald-500/70', 'bg-emerald-400'];
    return (<div className="flex gap-0.5 w-24">
      {[1, 2, 3, 4].map((i) => (<span key={i} className={`h-1 flex-1 rounded-full ${score >= i ? colors[score] : 'bg-white/10'}`}/>))}
    </div>);
}

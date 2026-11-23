/**
 * EcosystemPanel — the "My AI" tab (HomePilot One).
 *
 * One place that answers: what can I use right now, in what order will
 * HomePilot try it, and what may it cost me?
 *
 *   • Hugging Face        linked or not, who is billed
 *   • OllaBridge Cloud    reachable, account linked, catalog
 *   • Other providers     configured / free or paid / status
 *   • My computers        paired devices, online or offline
 *   • Routing             strategy, effective priority, paid switch, budgets
 *
 * Reads GET /v1/ecosystem/status (a non-blocking snapshot — a slow provider is
 * reported as unavailable, never awaited) and saves with PUT /v1/routing.
 * No secret ever reaches this component: accounts arrive as booleans.
 */
import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, Cloud, Cpu, Loader2, RefreshCw, Sparkles, Wallet } from "lucide-react";
import { resolveBackendUrl } from "../../lib/backendUrl";

type Provider = {
  id: string; name: string; tier: string; billing: string;
  configured: boolean; enabled: boolean; status: string;
};
type Device = { id: string; name?: string; online: boolean; gpu?: string; models: number };
type Status = {
  edition: string;
  huggingface: { linked: boolean; account?: string; usable: boolean; billed_to?: string | null; quota_status: string };
  ollabridge: { url?: string; reachable: boolean; account_linked: boolean; catalog: string; models: number };
  providers: Provider[];
  devices: { linked: boolean; items: Device[]; online: number; sharing: boolean };
  routing: { strategy: string; priority: string[]; allow_paid: boolean; paid_allowed_by_operator: boolean };
  usage: {
    paid_spent_today_usd: number; paid_spent_month_usd: number;
    daily_budget_usd: number | null; monthly_budget_usd: number | null; budget_exhausted: boolean;
  };
  storage?: { durable: boolean | null; warning: string | null };
};
type Prefs = {
  strategy: string; allow_paid: boolean; use_my_devices: boolean;
  max_request_cost_usd: number | null; daily_budget_usd: number | null; monthly_budget_usd: number | null;
};

export const STRATEGIES: { value: string; label: string; hint: string }[] = [
  { value: "hf_first", label: "Hugging Face first", hint: "Hugging Face, then other free services, then paid ones you allow, then your computers." },
  { value: "local_first", label: "My computers first", hint: "Use a paired computer when it is online; otherwise the cloud." },
  { value: "private_local", label: "Private — my computers only", hint: "Never sends anything to a hosted service. If your computer is offline, the request fails." },
  { value: "lowest_cost", label: "Lowest cost", hint: "Free options first, then the cheapest paid one you allow." },
  { value: "fastest", label: "Fastest", hint: "Whichever permitted service has been answering quickest." },
  { value: "quality_first", label: "Best quality", hint: "The strongest permitted model, within your spending limits." },
  { value: "pinned", label: "My model routes", hint: "Use the per-model routes set in the Routing tab." },
  { value: "legacy", label: "This installation's provider", hint: "Routing as it was before HomePilot One." },
];

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  try {
    const key = localStorage.getItem("homepilot_api_key");
    if (key) headers["X-API-Key"] = key;
    const token = localStorage.getItem("homepilot_auth_token");
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch {
    /* storage unavailable */
  }
  return headers;
}

/** "" → null (no limit); a number → that number; anything else → null. */
export function parseBudget(text: string): number | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const value = Number(trimmed);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

function Dot({ ok, warn }: { ok: boolean; warn?: boolean }) {
  const color = ok ? "bg-emerald-400" : warn ? "bg-amber-400" : "bg-white/25";
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} aria-hidden />;
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-white/10 bg-black/20 p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-medium text-white/90">{icon}{title}</div>
      <div className="space-y-1.5 text-xs text-white/60">{children}</div>
    </div>
  );
}

export default function EcosystemPanel({ backendUrl }: { backendUrl?: string }) {
  const base = resolveBackendUrl(backendUrl || "").replace(/\/+$/, "");
  const [status, setStatus] = useState<Status | null>(null);
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, r] = await Promise.all([
        fetch(`${base}/v1/ecosystem/status`, { headers: authHeaders(), credentials: "include" }),
        fetch(`${base}/v1/routing`, { headers: authHeaders(), credentials: "include" }),
      ]);
      if (s.status === 401 || r.status === 401) {
        setError("Sign in to see your AI resources.");
        return;
      }
      if (!s.ok || !r.ok) throw new Error(`HTTP ${s.ok ? r.status : s.status}`);
      setStatus(await s.json());
      setPrefs((await r.json()).prefs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load your AI resources.");
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => { void load(); }, [load]);

  const save = useCallback(async (changes: Partial<Prefs>) => {
    if (!prefs) return;
    const next = { ...prefs, ...changes };
    setPrefs(next);
    setSaving(true);
    setSaved(false);
    try {
      const res = await fetch(`${base}/v1/routing`, {
        method: "PUT", headers: authHeaders(), credentials: "include", body: JSON.stringify(changes),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSaved(true);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  }, [base, load, prefs]);

  if (loading && !status) {
    return <div className="flex items-center gap-2 text-xs text-white/50"><Loader2 size={14} className="animate-spin" /> Checking your AI resources…</div>;
  }
  if (error && !status) {
    return <div className="text-xs text-amber-300">{error}</div>;
  }
  if (!status || !prefs) return null;

  const strategy = STRATEGIES.find((s) => s.value === prefs.strategy);
  const otherProviders = status.providers.filter((p) => p.tier !== "huggingface");
  // Hugging Face can also be reached with the key OllaBridge holds, even when
  // nothing is linked on the HomePilot side.
  const hfViaGateway = status.providers.some((p) => p.tier === "huggingface" && p.configured && p.enabled);
  const hfUsable = status.huggingface.usable || hfViaGateway;
  const paidLocked = !status.routing.paid_allowed_by_operator;

  return (
    <div className="space-y-4">
      {status.storage?.durable === false && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-xs text-amber-200">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span>{status.storage.warning}</span>
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        <Section icon={<Sparkles size={14} />} title="Hugging Face">
          <div className="flex items-center gap-2">
            <Dot ok={hfUsable} />
            {status.huggingface.linked
              ? `Your account is connected${status.huggingface.account ? ` (${status.huggingface.account})` : ""}`
              : status.huggingface.usable ? "Using this site's shared access"
              : hfViaGateway ? "Available through OllaBridge Cloud" : "Not connected"}
          </div>
          {status.huggingface.billed_to && <div>Usage is billed to {status.huggingface.billed_to}.</div>}
          <div>Remaining credits: {status.huggingface.quota_status === "tracked" ? "tracked by HomePilot" : "not reported by Hugging Face"}</div>
          {!status.huggingface.linked && <div>Connect your own account in Settings → Connectors.</div>}
        </Section>

        <Section icon={<Cloud size={14} />} title="OllaBridge Cloud">
          <div className="flex items-center gap-2">
            <Dot ok={status.ollabridge.reachable} warn={!status.ollabridge.reachable} />
            {status.ollabridge.reachable ? "Connected" : "Not reachable right now"}
          </div>
          <div>{status.ollabridge.account_linked ? "Your account is linked" : "No account linked — your computers cannot be reached"}</div>
          <div>
            {status.ollabridge.catalog === "ready"
              ? `${status.ollabridge.models} models available`
              : "Model list not available"}
          </div>
        </Section>

        <Section icon={<Cloud size={14} />} title="Other providers">
          {otherProviders.length === 0 && <div>None reported.</div>}
          {otherProviders.map((p) => (
            <div key={p.id} className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2">
                <Dot ok={p.configured && p.enabled && p.status !== "unavailable"} />
                {p.name}
              </span>
              <span className="text-white/40">
                {p.billing === "paid" ? "paid" : "free"} · {p.configured ? p.status : "not set up"}
              </span>
            </div>
          ))}
        </Section>

        <Section icon={<Cpu size={14} />} title="My computers">
          {!status.devices.linked && <div>Link an OllaBridge account to use your own computer.</div>}
          {status.devices.linked && status.devices.items.length === 0 && <div>No computer paired yet.</div>}
          {status.devices.items.map((d) => (
            <div key={d.id} className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2"><Dot ok={d.online} />{d.name || d.id}</span>
              <span className="text-white/40">{d.online ? "online" : "offline"}{d.gpu ? ` · ${d.gpu}` : ""}</span>
            </div>
          ))}
          <label className="mt-2 flex items-center gap-2 text-white/70">
            <input
              type="checkbox"
              checked={prefs.use_my_devices}
              onChange={(e) => void save({ use_my_devices: e.target.checked })}
            />
            Let HomePilot use my paired computers
          </label>
        </Section>
      </div>

      <Section icon={<Wallet size={14} />} title="Routing and spending">
        <label className="block text-white/70">
          How should HomePilot choose?
          <select
            className="mt-1 block w-full rounded-lg border border-white/10 bg-black/40 px-2 py-2 text-xs text-white"
            value={prefs.strategy}
            onChange={(e) => void save({ strategy: e.target.value })}
          >
            {STRATEGIES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </label>
        {strategy && <div>{strategy.hint}</div>}
        <div className="text-white/80">
          Order now: {status.routing.priority.join(" → ")}
        </div>

        <label className={`mt-2 flex items-center gap-2 ${paidLocked ? "text-white/30" : "text-white/70"}`}>
          <input
            type="checkbox"
            disabled={paidLocked}
            checked={prefs.allow_paid && !paidLocked}
            onChange={(e) => void save({ allow_paid: e.target.checked })}
          />
          Allow paid services when free ones cannot answer
        </label>
        {paidLocked && <div>Paid services are turned off for this site.</div>}

        <div className="mt-2 grid gap-2 sm:grid-cols-3">
          {([
            ["max_request_cost_usd", "Most per request ($)"],
            ["daily_budget_usd", "Daily limit ($)"],
            ["monthly_budget_usd", "Monthly limit ($)"],
          ] as const).map(([key, label]) => (
            <label key={key} className="block text-white/70">
              {label}
              <input
                type="number" min="0" step="0.01" placeholder="no limit"
                className="mt-1 block w-full rounded-lg border border-white/10 bg-black/40 px-2 py-2 text-xs text-white"
                defaultValue={prefs[key] ?? ""}
                onBlur={(e) => {
                  const value = parseBudget(e.target.value);
                  if (value !== prefs[key]) void save({ [key]: value } as Partial<Prefs>);
                }}
              />
            </label>
          ))}
        </div>
        <div>
          Paid spend: ${status.usage.paid_spent_today_usd.toFixed(4)} today · ${status.usage.paid_spent_month_usd.toFixed(4)} this month
          {status.usage.budget_exhausted && <span className="ml-2 text-amber-300">A limit has been reached — paid services are paused.</span>}
        </div>
      </Section>

      <div className="flex items-center gap-3 text-xs text-white/50">
        <button
          onClick={() => void load()}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/10 px-3 hover:text-white"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
        {saving && <span className="inline-flex items-center gap-1"><Loader2 size={13} className="animate-spin" /> Saving…</span>}
        {saved && !saving && <span className="inline-flex items-center gap-1 text-emerald-300"><Check size={13} /> Saved</span>}
        {error && <span className="text-amber-300">{error}</span>}
      </div>
    </div>
  );
}

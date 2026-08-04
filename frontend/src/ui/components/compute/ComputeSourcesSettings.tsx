/**
 * ComputeSourcesSettings — the "Sources" tab.
 *
 * Connect, edit, and disconnect compute sources: local, an OllaBridge linked
 * device/relay, or a direct OpenAI-compatible endpoint. Credentials are
 * write-only — the field is send-once and never read back; the backend keeps the
 * secret server-side and returns only a credentialRef.
 */
import React, { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, Save, Trash2, Wifi } from "lucide-react";
import type { ComputeSource, SourceKind } from "@homepilot/types";
import { computeClient } from "../../api";

const KINDS: { value: SourceKind; label: string; wantsUrl: boolean; wantsCred: boolean }[] = [
  { value: "ollabridge", label: "OllaBridge linked device", wantsUrl: false, wantsCred: false },
  { value: "openai_compatible", label: "OpenAI-compatible endpoint", wantsUrl: true, wantsCred: true },
  { value: "comfyui", label: "Remote ComfyUI endpoint", wantsUrl: true, wantsCred: false },
  { value: "custom", label: "Custom", wantsUrl: true, wantsCred: true },
];

interface DraftSource {
  id: string;
  name: string;
  kind: SourceKind;
  baseUrl: string;
  credential: string;
  enabled: boolean;
}

const EMPTY: DraftSource = {
  id: "",
  name: "",
  kind: "openai_compatible",
  baseUrl: "",
  credential: "",
  enabled: true,
};

export default function ComputeSourcesSettings() {
  const [sources, setSources] = useState<ComputeSource[]>([]);
  const [draft, setDraft] = useState<DraftSource | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tested, setTested] = useState<Record<string, string>>({});
  const [testingId, setTestingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setSources(await computeClient.listComputeSources());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load sources");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = useCallback(async () => {
    if (!draft) return;
    if (!draft.id.trim()) {
      setError("An id is required (e.g. my-vllm).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await computeClient.upsertComputeSource({
        id: draft.id.trim(),
        name: draft.name.trim() || draft.id.trim(),
        kind: draft.kind,
        baseUrl: draft.baseUrl.trim() || undefined,
        enabled: draft.enabled,
        ...(draft.credential ? { credential: draft.credential } : {}),
      });
      setDraft(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }, [draft, load]);

  const toggle = useCallback(
    async (s: ComputeSource) => {
      await computeClient.upsertComputeSource({ id: s.id, kind: s.kind, enabled: !s.enabled });
      await load();
    },
    [load],
  );

  const remove = useCallback(
    async (id: string) => {
      await computeClient.deleteComputeSource(id);
      await load();
    },
    [load],
  );

  const test = useCallback(async (id: string) => {
    setTestingId(id);
    try {
      const r = await computeClient.testComputeSource(id);
      setTested((t) => ({ ...t, [id]: r.ok ? "✓ Reachable" : r.reason || "Unreachable" }));
    } catch (e) {
      setTested((t) => ({ ...t, [id]: e instanceof Error ? e.message : "Test failed" }));
    } finally {
      setTestingId(null);
    }
  }, []);

  const kindMeta = draft ? KINDS.find((k) => k.value === draft.kind) : undefined;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-white">Compute sources</h3>
          <p className="text-xs text-white/50">Where HomePilot may run models.</p>
        </div>
        <button
          onClick={() => setDraft({ ...EMPTY })}
          className="h-9 px-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/70 inline-flex items-center gap-1.5"
        >
          <Plus size={14} /> Connect source
        </button>
      </div>

      {error && (
        <div className="px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/20 text-red-300 text-xs">
          {error}
        </div>
      )}

      {loading && <Loader2 size={16} className="animate-spin text-white/40" />}

      <ul className="space-y-2">
        {sources.map((s) => (
          <li
            key={s.id}
            className="rounded-2xl border border-white/10 bg-white/[0.02] p-4 flex items-center justify-between"
          >
            <div>
              <div className="text-sm text-white">{s.name}</div>
              <div className="text-xs text-white/40">
                {s.kind}
                {s.baseUrl ? ` · ${s.baseUrl}` : ""}
                {s.credentialRef ? " · key set" : ""}
              </div>
              {tested[s.id] && <div className="text-[11px] text-white/50 mt-1">{tested[s.id]}</div>}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => void test(s.id)}
                disabled={testingId === s.id}
                className="h-8 px-2.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-[11px] text-white/70 inline-flex items-center gap-1"
              >
                {testingId === s.id ? <Loader2 size={12} className="animate-spin" /> : <Wifi size={12} />} Test
              </button>
              <button
                onClick={() => void toggle(s)}
                className={`text-[11px] px-2.5 py-1 rounded-full border ${
                  s.enabled
                    ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-300"
                    : "bg-white/5 border-white/10 text-white/40"
                }`}
              >
                {s.enabled ? "Enabled" : "Disabled"}
              </button>
              <button
                onClick={() => void remove(s.id)}
                aria-label={`Delete ${s.name}`}
                className="h-8 w-8 grid place-items-center rounded-xl bg-white/5 hover:bg-red-500/10 border border-white/10 text-white/50 hover:text-red-300"
              >
                <Trash2 size={14} />
              </button>
            </div>
          </li>
        ))}
        {!loading && sources.length === 0 && (
          <li className="text-xs text-white/40">No sources yet.</li>
        )}
      </ul>

      {draft && (
        <div className="rounded-2xl border border-white/10 bg-black/30 p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Id">
              <input
                value={draft.id}
                onChange={(e) => setDraft({ ...draft, id: e.target.value })}
                placeholder="my-vllm"
                className="w-full h-10 rounded-xl bg-black/40 border border-white/10 px-3 text-sm text-white placeholder:text-white/30 outline-none focus:border-cyan-400/50"
              />
            </Field>
            <Field label="Name">
              <input
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                placeholder="My vLLM"
                className="w-full h-10 rounded-xl bg-black/40 border border-white/10 px-3 text-sm text-white placeholder:text-white/30 outline-none focus:border-cyan-400/50"
              />
            </Field>
          </div>
          <Field label="Kind">
            <select
              value={draft.kind}
              onChange={(e) => setDraft({ ...draft, kind: e.target.value as SourceKind })}
              className="w-full h-10 rounded-xl bg-black/40 border border-white/10 px-3 text-sm text-white outline-none focus:border-cyan-400/50"
            >
              {KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
          </Field>
          {kindMeta?.wantsUrl && (
            <Field label="Base URL">
              <input
                value={draft.baseUrl}
                onChange={(e) => setDraft({ ...draft, baseUrl: e.target.value })}
                placeholder="https://host:port"
                className="w-full h-10 rounded-xl bg-black/40 border border-white/10 px-3 text-sm text-white placeholder:text-white/30 outline-none focus:border-cyan-400/50"
              />
            </Field>
          )}
          {kindMeta?.wantsCred && (
            <Field label="API key (write-only)">
              <input
                type="password"
                value={draft.credential}
                onChange={(e) => setDraft({ ...draft, credential: e.target.value })}
                placeholder="stored server-side, never shown again"
                className="w-full h-10 rounded-xl bg-black/40 border border-white/10 px-3 text-sm text-white placeholder:text-white/30 outline-none focus:border-cyan-400/50"
              />
            </Field>
          )}
          <div className="flex items-center gap-2 justify-end">
            <button
              onClick={() => setDraft(null)}
              className="h-9 px-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/60"
            >
              Cancel
            </button>
            <button
              onClick={() => void save()}
              disabled={busy}
              className="h-9 px-3 rounded-xl bg-cyan-500/20 hover:bg-cyan-500/30 border border-cyan-400/30 text-xs text-cyan-100 inline-flex items-center gap-1.5 disabled:opacity-50"
            >
              {busy ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} Save
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs text-white/50">{label}</span>
      {children}
    </label>
  );
}

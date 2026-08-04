/**
 * RoutingPolicyEditor — the "Routing" tab.
 *
 * Three layers, matching the resolver's precedence:
 *   1. Global compute mode (local / cloud / auto) — the ex-env flag, now a
 *      persisted setting.
 *   2. Per-model routes — explicit bindings that beat the defaults, each with a
 *      live "how this resolves" preview from /compute/admin/resolve.
 *   3. (Per-modality defaults are edited inline via the model routes' Auto.)
 */
import React, { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, Save, Trash2 } from "lucide-react";
import type {
  ComputeMode,
  ComputeSettings,
  ModelRoute,
  RouteCost,
  RouteResolution,
} from "@homepilot/types";
import { computeClient } from "../../api";
import { MODALITIES } from "./targets";

const MODES: { value: ComputeMode; label: string }[] = [
  { value: "local", label: "This PC only" },
  { value: "auto", label: "Auto (prefer local, burst to cloud)" },
  { value: "ollabridge_cloud", label: "OllaBridge Cloud" },
];

function costLabel(c: RouteCost): string {
  const price =
    c.estimatedUsd == null
      ? "cost unknown"
      : c.estimatedUsd === 0
        ? "free"
        : `$${c.estimatedUsd.toFixed(2)}/${c.perUnit || "request"}`;
  return `${c.target}: ${price}${c.overBudget ? " (over budget)" : ""}`;
}

export default function RoutingPolicyEditor() {
  const [settings, setSettings] = useState<ComputeSettings | null>(null);
  const [routes, setRoutes] = useState<ModelRoute[]>([]);
  const [resolutions, setResolutions] = useState<Record<string, RouteResolution>>({});
  const [draft, setDraft] = useState<{ modality: string; modelId: string; primaryTarget: string; fallback: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, r] = await Promise.all([
        computeClient.getComputeSettings(),
        computeClient.listRoutes(),
      ]);
      setSettings(s);
      setRoutes(r);
      const entries = await Promise.all(
        r.map(async (route) => {
          try {
            return [`${route.modality}:${route.modelId}`, await computeClient.resolveRoute(route.modality, route.modelId)] as const;
          } catch {
            return null;
          }
        }),
      );
      setResolutions(Object.fromEntries(entries.filter(Boolean) as [string, RouteResolution][]));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load routing");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const saveMode = useCallback(async (mode: ComputeMode) => {
    setBusy(true);
    try {
      setSettings(await computeClient.putComputeSettings({ computeMode: mode }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }, []);

  const saveBudget = useCallback(async (value: string) => {
    const parsed = value.trim() === "" ? null : Number(value);
    if (parsed != null && (Number.isNaN(parsed) || parsed < 0)) return;
    setBusy(true);
    try {
      setSettings(await computeClient.putComputeSettings({ maxCostUsdPerRequest: parsed }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }, []);

  const addRoute = useCallback(async () => {
    if (!draft) return;
    if (!draft.modelId.trim() || !draft.primaryTarget.trim()) {
      setError("Model id and primary target are required.");
      return;
    }
    setBusy(true);
    try {
      await computeClient.upsertRoute({
        modality: draft.modality as ModelRoute["modality"],
        modelId: draft.modelId.trim(),
        primaryTarget: draft.primaryTarget.trim(),
        fallbackTargets: draft.fallback.trim() ? [draft.fallback.trim()] : [],
        strategy: "pinned",
        privacy: "private_nodes",
      });
      setDraft(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }, [draft, load]);

  const removeRoute = useCallback(
    async (route: ModelRoute) => {
      await computeClient.deleteRoute(route.modality, route.modelId);
      await load();
    },
    [load],
  );

  if (loading) return <Loader2 size={16} className="animate-spin text-white/40" />;

  return (
    <div className="space-y-5">
      {error && (
        <div className="px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/20 text-red-300 text-xs">
          {error}
        </div>
      )}

      {/* Global default */}
      <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4 space-y-2">
        <div className="text-sm font-semibold text-white">Default compute</div>
        <p className="text-xs text-white/50">Used when a model has no explicit route.</p>
        <div className="flex flex-wrap gap-2 pt-1">
          {MODES.map((m) => (
            <button
              key={m.value}
              disabled={busy}
              onClick={() => void saveMode(m.value)}
              className={`h-9 px-3 rounded-xl border text-xs ${
                settings?.computeMode === m.value
                  ? "bg-cyan-500/20 border-cyan-400/30 text-cyan-100"
                  : "bg-white/5 border-white/10 text-white/60 hover:bg-white/10"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 pt-2 text-xs text-white/60">
          <span>Budget per request (USD)</span>
          <input
            type="number"
            min={0}
            step="0.01"
            defaultValue={settings?.maxCostUsdPerRequest ?? ""}
            placeholder="no cap"
            onBlur={(e) => void saveBudget(e.target.value)}
            className="h-8 w-28 rounded-lg bg-black/40 border border-white/10 px-2 text-xs text-white outline-none focus:border-cyan-400/50"
          />
          <span className="text-white/30">hosted options over budget are skipped</span>
        </label>
      </div>

      {/* Per-model routes */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold text-white">Per-model routes</div>
          <button
            onClick={() => setDraft({ modality: "chat", modelId: "", primaryTarget: "local", fallback: "" })}
            className="h-9 px-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/70 inline-flex items-center gap-1.5"
          >
            <Plus size={14} /> Add route
          </button>
        </div>

        <ul className="space-y-2">
          {routes.map((r) => {
            const res = resolutions[`${r.modality}:${r.modelId}`];
            return (
              <li key={`${r.modality}:${r.modelId}`} className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm text-white">
                      {r.modelId} <span className="text-white/40">· {r.modality}</span>
                    </div>
                    <div className="text-xs text-white/50">
                      {r.primaryTarget}
                      {r.fallbackTargets.length ? ` → ${r.fallbackTargets.join(" → ")}` : ""}
                      <span className="text-white/30"> · {r.strategy}</span>
                    </div>
                    {res && (
                      <div className="text-[11px] text-white/40 mt-1">
                        Resolves to: {res.targets.join(" → ")}
                        {res.costs?.length ? (
                          <span className="block text-white/30">
                            {res.costs.map(costLabel).join(" · ")}
                          </span>
                        ) : null}
                      </div>
                    )}
                  </div>
                  <button
                    onClick={() => void removeRoute(r)}
                    aria-label={`Delete route for ${r.modelId}`}
                    className="h-8 w-8 grid place-items-center rounded-xl bg-white/5 hover:bg-red-500/10 border border-white/10 text-white/50 hover:text-red-300"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </li>
            );
          })}
          {routes.length === 0 && <li className="text-xs text-white/40">No per-model routes.</li>}
        </ul>

        {draft && (
          <div className="rounded-2xl border border-white/10 bg-black/30 p-4 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <label className="block space-y-1">
                <span className="text-xs text-white/50">Modality</span>
                <select
                  value={draft.modality}
                  onChange={(e) => setDraft({ ...draft, modality: e.target.value })}
                  className="w-full h-10 rounded-xl bg-black/40 border border-white/10 px-3 text-sm text-white outline-none focus:border-cyan-400/50"
                >
                  {MODALITIES.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block space-y-1">
                <span className="text-xs text-white/50">Model id</span>
                <input
                  value={draft.modelId}
                  onChange={(e) => setDraft({ ...draft, modelId: e.target.value })}
                  placeholder="deepseek-r1:latest"
                  className="w-full h-10 rounded-xl bg-black/40 border border-white/10 px-3 text-sm text-white placeholder:text-white/30 outline-none focus:border-cyan-400/50"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs text-white/50">Primary target</span>
                <input
                  value={draft.primaryTarget}
                  onChange={(e) => setDraft({ ...draft, primaryTarget: e.target.value })}
                  placeholder="local · device:colab · source:my-vllm"
                  className="w-full h-10 rounded-xl bg-black/40 border border-white/10 px-3 text-sm text-white placeholder:text-white/30 outline-none focus:border-cyan-400/50"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs text-white/50">Fallback (optional)</span>
                <input
                  value={draft.fallback}
                  onChange={(e) => setDraft({ ...draft, fallback: e.target.value })}
                  placeholder="local"
                  className="w-full h-10 rounded-xl bg-black/40 border border-white/10 px-3 text-sm text-white placeholder:text-white/30 outline-none focus:border-cyan-400/50"
                />
              </label>
            </div>
            <div className="flex items-center gap-2 justify-end">
              <button
                onClick={() => setDraft(null)}
                className="h-9 px-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/60"
              >
                Cancel
              </button>
              <button
                onClick={() => void addRoute()}
                disabled={busy}
                className="h-9 px-3 rounded-xl bg-cyan-500/20 hover:bg-cyan-500/30 border border-cyan-400/30 text-xs text-cyan-100 inline-flex items-center gap-1.5 disabled:opacity-50"
              >
                {busy ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} Save
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

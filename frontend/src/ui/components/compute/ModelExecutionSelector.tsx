/**
 * ModelExecutionSelector — the per-model "Runs on / Fallback" control.
 *
 * Drop this beside any model (Models tab, persona model picker) to bind where it
 * executes. "Auto" clears the binding (the routing policy decides); anything else
 * pins a ModelRoute. Options that can't serve the model are shown but disabled
 * with the reason ("Offline", "Requires 20 GB VRAM", …).
 *
 * Self-contained: fetches sources/devices/manifests and the model's current
 * route on mount, and persists changes via the compute admin API.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import type {
  ComputeDevice,
  ComputeSource,
  Modality,
  ModelManifest,
  ModelRoute,
} from "@homepilot/types";
import { computeClient } from "../../api";
import { buildTargetOptions, targetLabel, type TargetOption } from "./targets";

interface Props {
  modelId: string;
  modality?: Modality;
  onChange?: (route: ModelRoute | null) => void;
}

export default function ModelExecutionSelector({ modelId, modality = "chat", onChange }: Props) {
  const [sources, setSources] = useState<ComputeSource[]>([]);
  const [devices, setDevices] = useState<ComputeDevice[]>([]);
  const [manifests, setManifests] = useState<ModelManifest[]>([]);
  const [route, setRoute] = useState<ModelRoute | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [srcs, devs, mans, routes] = await Promise.all([
        computeClient.listComputeSources(),
        computeClient.listComputeDevices(),
        computeClient.listModelManifests().catch(() => []),
        computeClient.listRoutes().catch(() => []),
      ]);
      setSources(srcs);
      setDevices(devs);
      setManifests(mans);
      setRoute(routes.find((r) => r.modelId === modelId && r.modality === modality) ?? null);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [modelId, modality]);

  useEffect(() => {
    void load();
  }, [load]);

  const options: TargetOption[] = useMemo(
    () => buildTargetOptions({ modality, modelId, sources, devices, manifests }),
    [modality, modelId, sources, devices, manifests],
  );
  // Fallback list = concrete targets only (no "Auto").
  const fallbackOptions = options.filter((o) => o.target !== "");

  const primary = route?.primaryTarget ?? "";
  const fallback = route?.fallbackTargets?.[0] ?? "";

  // Live status for the currently-bound target.
  function statusFor(target: string): { text: string; ok: boolean | null } {
    if (!target) return { text: "Auto — routing policy decides", ok: null };
    if (target === "local") return { text: "This PC", ok: null };
    if (target.startsWith("device:")) {
      const d = devices.find((x) => `device:${x.id}` === target);
      const online = d ? (d.onlineEffective ?? d.online) : false;
      return { text: `${targetLabel(target, sources, devices)} ${online ? "online" : "offline"}`, ok: online };
    }
    if (target.startsWith("source:")) {
      const s = sources.find((x) => `source:${x.id}` === target);
      return { text: `${targetLabel(target, sources, devices)} ${s?.enabled ? "enabled" : "disabled"}`, ok: !!s?.enabled };
    }
    return { text: targetLabel(target, sources, devices), ok: null };
  }
  const status = statusFor(primary);

  const persist = useCallback(
    async (nextPrimary: string, nextFallback: string) => {
      setBusy(true);
      setError(null);
      try {
        if (!nextPrimary) {
          // Auto → clear the binding.
          if (route) await computeClient.deleteRoute(modality, modelId);
          setRoute(null);
          onChange?.(null);
        } else {
          const saved = await computeClient.upsertRoute({
            modality,
            modelId,
            primaryTarget: nextPrimary,
            fallbackTargets: nextFallback ? [nextFallback] : [],
            strategy: "pinned",
            privacy: "private_nodes",
          });
          setRoute(saved);
          onChange?.(saved);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Save failed");
      } finally {
        setBusy(false);
      }
    },
    [route, modality, modelId, onChange],
  );

  if (loading) return <Loader2 size={14} className="animate-spin text-white/40" />;

  return (
    <div className="flex flex-col gap-2 text-xs">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-white/50">Runs on</span>
        <Select
          value={primary}
          disabled={busy}
          options={options}
          onChange={(v) => void persist(v, fallback)}
        />
        <span className="text-white/50">Fallback</span>
        <Select
          value={fallback}
          disabled={busy || !primary}
          options={[{ target: "", label: "None" }, ...fallbackOptions.filter((o) => o.target !== primary)]}
          onChange={(v) => void persist(primary, v)}
        />
        {busy && <Loader2 size={12} className="animate-spin text-white/40" />}
      </div>
      <div className="flex items-center gap-1.5 text-[11px]">
        <span className="text-white/40">Status:</span>
        <span
          className={
            status.ok === true ? "text-emerald-300" : status.ok === false ? "text-amber-300" : "text-white/50"
          }
        >
          {status.text}
        </span>
      </div>
      {error && <span className="text-red-300">{error}</span>}
    </div>
  );
}

function Select(props: {
  value: string;
  options: TargetOption[];
  disabled?: boolean;
  onChange: (v: string) => void;
}) {
  const { value, options, disabled, onChange } = props;
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      className="h-8 rounded-lg bg-black/40 border border-white/10 px-2 text-xs text-white outline-none focus:border-cyan-400/50 disabled:opacity-50"
    >
      {options.map((o) => (
        <option key={o.target || "auto"} value={o.target} disabled={o.disabled}>
          {o.label}
          {o.disabled && o.reason ? ` — ${o.reason}` : ""}
        </option>
      ))}
    </select>
  );
}

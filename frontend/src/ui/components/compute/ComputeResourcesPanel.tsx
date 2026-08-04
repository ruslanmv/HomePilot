/**
 * ComputeResourcesPanel — the "Resources" tab.
 *
 * One glance at everything that can run a request:
 *   • This PC — live CPU / RAM / per-GPU VRAM meters (multi-GPU aware).
 *   • Remote sources — each with its devices, status badges (Online / Busy /
 *     Offline / Ephemeral), GPU/VRAM, model count and heartbeat age, plus
 *     per-source actions (Test · Sync · Disconnect).
 *   • A global "Use remote resources" default that never overrides an explicit
 *     per-model route.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  Cloud, Cpu, Loader2, MemoryStick, Plug, RefreshCw, Trash2, Wifi, WifiOff, Zap,
} from "lucide-react";
import type {
  ComputeDevice, ComputeSource, ComputeStatus, LocalResources, ModelManifest,
} from "@homepilot/types";
import { computeClient } from "../../api";

function heartbeat(d: ComputeDevice): string {
  if (d.heartbeatAgeS == null) return "—";
  const s = Math.max(0, Math.round(d.heartbeatAgeS));
  return s < 60 ? `${s}s ago` : `${Math.round(s / 60)}m ago`;
}

function deviceBadge(d: ComputeDevice): { label: string; cls: string } {
  const online = d.onlineEffective ?? d.online;
  if (!online) return { label: "Offline", cls: "bg-white/5 border-white/10 text-white/40" };
  if (d.capacity > 0 && d.activeJobs >= d.capacity)
    return { label: "Busy", cls: "bg-amber-500/10 border-amber-500/20 text-amber-300" };
  return { label: "Online", cls: "bg-emerald-500/10 border-emerald-500/20 text-emerald-300" };
}

function Meter({ label, percent, tone = "cyan" }: { label: string; percent?: number | null; tone?: string }) {
  const p = Math.max(0, Math.min(100, Math.round(percent ?? 0)));
  const bar =
    tone === "violet" ? "bg-violet-400/70" : tone === "emerald" ? "bg-emerald-400/70" : "bg-cyan-400/70";
  return (
    <div className="min-w-[92px]">
      <div className="flex justify-between text-[10px] text-white/40 mb-0.5">
        <span>{label}</span>
        <span>{percent == null ? "—" : `${p}%`}</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
        <div className={`h-full ${bar}`} style={{ width: `${p}%` }} />
      </div>
    </div>
  );
}

export default function ComputeResourcesPanel({
  onConnectSource,
}: {
  onConnectSource?: () => void;
}) {
  const [status, setStatus] = useState<ComputeStatus | null>(null);
  const [local, setLocal] = useState<LocalResources | null>(null);
  const [sources, setSources] = useState<ComputeSource[]>([]);
  const [devices, setDevices] = useState<ComputeDevice[]>([]);
  const [manifests, setManifests] = useState<ModelManifest[]>([]);
  const [remoteDefault, setRemoteDefault] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [tested, setTested] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [st, res, srcs, devs, mans, settings] = await Promise.all([
        computeClient.getComputeStatus().catch(() => null),
        computeClient.getLocalResources().catch(() => null),
        computeClient.listComputeSources(),
        computeClient.listComputeDevices(),
        computeClient.listModelManifests().catch(() => []),
        computeClient.getComputeSettings().catch(() => null),
      ]);
      setStatus(st);
      setLocal(res);
      setSources(srcs);
      setDevices(devs);
      setManifests(mans);
      setRemoteDefault(settings?.computeMode === "auto" || settings?.computeMode === "ollabridge_cloud");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load resources");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const modelsFor = (deviceId: string) =>
    manifests.filter((m) => m.deviceIds.includes(deviceId)).length;

  const toggleRemoteDefault = useCallback(async () => {
    const next = !remoteDefault;
    setRemoteDefault(next);
    try {
      await computeClient.putComputeSettings({ computeMode: next ? "auto" : "local" });
    } catch {
      setRemoteDefault(!next); // revert on failure
    }
  }, [remoteDefault]);

  const testSource = useCallback(async (id: string) => {
    setBusyId(id);
    try {
      const r = await computeClient.testComputeSource(id);
      setTested((t) => ({ ...t, [id]: r.ok ? "✓ Reachable" : r.reason || "Unreachable" }));
    } catch (e) {
      setTested((t) => ({ ...t, [id]: e instanceof Error ? e.message : "Test failed" }));
    } finally {
      setBusyId(null);
    }
  }, []);

  const syncFromCloud = useCallback(async () => {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const r = await computeClient.syncFromCloud();
      if (!r.linked) {
        setSyncMsg(r.reason || "Link your OllaBridge account to sync devices.");
      } else {
        setSyncMsg(`Synced ${r.devices} device${r.devices === 1 ? "" : "s"} · ${r.models} model${r.models === 1 ? "" : "s"} from OllaBridge Cloud.`);
        await load();
      }
    } catch (e) {
      setSyncMsg(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }, [load]);

  const disconnect = useCallback(async (id: string) => {
    setBusyId(id);
    try {
      await computeClient.deleteComputeSource(id);
      await load();
    } finally {
      setBusyId(null);
    }
  }, [load]);

  const gpus = local?.gpus?.length ? local.gpus : local?.gpu?.available ? [local.gpu] : [];
  const localOnline = status?.localGpuAvailable ?? (gpus.length > 0);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-white">Resources</h3>
          <p className="text-xs text-white/50">Live capacity across this PC and connected sources.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void syncFromCloud()}
            disabled={syncing}
            className="h-9 px-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/70 inline-flex items-center gap-1.5"
          >
            {syncing ? <Loader2 size={14} className="animate-spin" /> : <Cloud size={14} />}
            Sync from Cloud
          </button>
          {onConnectSource && (
            <button
              onClick={onConnectSource}
              className="h-9 px-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/70 inline-flex items-center gap-1.5"
            >
              <Plug size={14} /> Connect source
            </button>
          )}
          <button
            onClick={() => void load()}
            className="h-9 px-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/70 inline-flex items-center gap-1.5"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            Refresh
          </button>
        </div>
      </div>

      {status && (
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4 flex items-center gap-3">
          <Zap size={16} className="text-cyan-300 shrink-0" />
          <div className="text-sm text-white/80">{status.message}</div>
        </div>
      )}
      {error && (
        <div className="px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/20 text-red-300 text-xs">
          {error}
        </div>
      )}
      {syncMsg && (
        <div className="px-3 py-2 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-200 text-xs">
          {syncMsg}
        </div>
      )}

      {/* This PC */}
      <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="text-sm font-medium text-white">This PC</div>
          <span className={`text-[11px] px-2.5 py-1 rounded-full border ${
            localOnline ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-300" : "bg-white/5 border-white/10 text-white/40"
          }`}>
            {localOnline ? "Online" : "Offline"}
          </span>
        </div>
        <div className="space-y-2">
          {local?.cpu?.name && (
            <div className="flex items-center justify-between gap-4">
              <span className="flex items-center gap-2 text-xs text-white/70">
                <Cpu size={14} className="text-white/40" />
                {local.cpu.name}
                {local.cpu.logicalCores ? <span className="text-white/40">· {local.cpu.logicalCores} threads</span> : null}
              </span>
              <div className="flex items-center gap-3">
                <Meter label="CPU" percent={local.cpu.percent} tone="violet" />
                {local.ram?.percent != null && <Meter label="RAM" percent={local.ram.percent} tone="emerald" />}
              </div>
            </div>
          )}
          {gpus.map((g, i) => (
            <div key={i} className="flex items-center justify-between gap-4">
              <span className="flex items-center gap-2 text-xs text-white/70">
                <MemoryStick size={14} className="text-white/40" />
                {g.name || `GPU ${g.index ?? i}`}
                {g.vramTotalMb ? <span className="text-white/40">· {Math.round(g.vramTotalMb / 1024)} GB</span> : null}
              </span>
              <div className="flex items-center gap-3">
                <Meter label="VRAM" percent={g.usedPercent} />
                {g.utilizationPercent != null && <Meter label="GPU" percent={g.utilizationPercent} tone="violet" />}
              </div>
            </div>
          ))}
          {gpus.length === 0 && (
            <div className="text-xs text-white/40">No local GPU detected — Ollama/ComfyUI may run on CPU.</div>
          )}
        </div>
      </div>

      {/* Global default */}
      <label className="rounded-2xl border border-white/10 bg-white/[0.02] p-4 flex items-center justify-between cursor-pointer">
        <div>
          <div className="text-sm text-white">Use remote resources for complex tasks</div>
          <div className="text-xs text-white/40">A soft default — explicit per-model routes always win.</div>
        </div>
        <input type="checkbox" checked={remoteDefault} onChange={() => void toggleRemoteDefault()} className="sr-only peer" />
        <span className="w-10 h-6 rounded-full bg-white/10 peer-checked:bg-cyan-500/60 relative transition-colors">
          <span className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white transition-transform ${remoteDefault ? "translate-x-4" : ""}`} />
        </span>
      </label>

      {/* Remote sources */}
      {sources.filter((s) => s.kind !== "local").map((s) => {
        const devs = devices.filter((d) => d.sourceId === s.id);
        return (
          <div key={s.id} className="rounded-2xl border border-white/10 bg-white/[0.02] p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium text-white">{s.name}</div>
                <div className="text-xs text-white/40">{s.kind}{s.baseUrl ? ` · ${s.baseUrl}` : ""}</div>
              </div>
              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => void testSource(s.id)}
                  disabled={busyId === s.id}
                  className="h-8 px-2.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-[11px] text-white/70 inline-flex items-center gap-1"
                >
                  {busyId === s.id ? <Loader2 size={12} className="animate-spin" /> : <Wifi size={12} />} Test
                </button>
                <button
                  onClick={() => void load()}
                  className="h-8 px-2.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-[11px] text-white/70 inline-flex items-center gap-1"
                >
                  <RefreshCw size={12} /> Sync
                </button>
                <button
                  onClick={() => void disconnect(s.id)}
                  aria-label={`Disconnect ${s.name}`}
                  className="h-8 w-8 grid place-items-center rounded-lg bg-white/5 hover:bg-red-500/10 border border-white/10 text-white/50 hover:text-red-300"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            </div>
            {tested[s.id] && <div className="text-[11px] text-white/50">{tested[s.id]}</div>}
            {devs.length === 0 ? (
              <div className="text-xs text-white/40">No devices reported yet.</div>
            ) : (
              <ul className="space-y-2">
                {devs.map((d) => {
                  const badge = deviceBadge(d);
                  return (
                    <li key={d.id} className="flex items-center justify-between text-xs">
                      <span className="flex items-center gap-2 text-white/80">
                        <Cpu size={14} className="text-white/40" />
                        {d.name || d.id}
                        {d.ephemeral && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/20">
                            Ephemeral
                          </span>
                        )}
                      </span>
                      <span className="flex items-center gap-3 text-white/50">
                        {d.gpuName && <span>{d.gpuName}</span>}
                        {d.vramMb != null && <span>{Math.round(d.vramMb / 1024)} GB</span>}
                        <span>{modelsFor(d.id)} models</span>
                        <span>{heartbeat(d)}</span>
                        {(d.onlineEffective ?? d.online) ? (
                          <Wifi size={14} className="text-emerald-400" />
                        ) : (
                          <WifiOff size={14} className="text-white/30" />
                        )}
                        <span className={`text-[10px] px-2 py-0.5 rounded-full border ${badge.cls}`}>{badge.label}</span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        );
      })}

      {!loading && sources.filter((s) => s.kind !== "local").length === 0 && (
        <div className="text-xs text-white/40">
          No remote compute sources connected yet.
        </div>
      )}
    </div>
  );
}

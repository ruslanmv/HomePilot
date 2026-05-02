/**
 * SystemResourcesCard — Machine Capacity section for the System Status dashboard.
 *
 * Shows GPU VRAM, RAM, CPU, and disk with thin progress bars and status pills.
 * Gracefully handles GPU unavailability (renders muted placeholder).
 */
import React, { useEffect, useState } from 'react';
import { Cpu, HardDrive, Gauge, CircuitBoard } from 'lucide-react';
import { fetchSystemResources } from './systemResourcesApi';
/* ── status helpers ────────────────────────────────── */
function pillTone(status) {
    if (status === 'critical' || status === 'tight')
        return 'bg-red-500/8 text-red-300/80 border-red-400/15';
    if (status === 'warning')
        return 'bg-amber-500/8 text-amber-300/80 border-amber-400/15';
    if (status === 'unavailable')
        return 'bg-white/[0.04] text-white/35 border-white/[0.06]';
    return 'bg-emerald-500/8 text-emerald-300/80 border-emerald-500/15';
}
function barColor(status) {
    if (status === 'critical' || status === 'tight')
        return 'bg-red-400/80';
    if (status === 'warning')
        return 'bg-amber-400/80';
    return 'bg-emerald-400/80';
}
function clamp(v) {
    if (v == null)
        return 0;
    return Math.max(0, Math.min(100, v));
}
/* ── main card ─────────────────────────────────────── */
export default function SystemResourcesCard({ backendUrl, apiKey, }) {
    const [data, setData] = useState(null);
    useEffect(() => {
        let mounted = true;
        (async () => {
            try {
                const res = await fetchSystemResources(backendUrl, apiKey);
                if (mounted)
                    setData(res);
            }
            catch {
                if (mounted)
                    setData(null);
            }
        })();
        return () => { mounted = false; };
    }, [backendUrl, apiKey]);
    if (!data)
        return null;
    return (<div className="rounded-3xl border border-white/[0.07] bg-white/[0.02] p-6 mb-7" style={{ animation: 'statusCardIn 350ms ease-out 240ms both' }}>
      <div className="text-sm font-semibold text-white/90 mb-4">Machine Capacity</div>

      <div className="grid grid-cols-2 gap-4">
        {/* GPU VRAM */}
        <ResourceItem icon={<Gauge size={15}/>} title="GPU VRAM" subtitle={data.gpu.available ? (data.gpu.name || 'NVIDIA GPU') : 'GPU unavailable'} value={data.gpu.available
            ? `${((data.gpu.vram_used_mb ?? 0) / 1024).toFixed(1)} / ${((data.gpu.vram_total_mb ?? 0) / 1024).toFixed(1)} GB`
            : '\u2014'} percent={data.gpu.used_percent ?? 0} status={data.gpu.status} extra={data.gpu.available ? `${data.gpu.utilization_percent ?? 0}% GPU load` : 'No nvidia-smi detected'}/>

        {/* System RAM */}
        <ResourceItem icon={<CircuitBoard size={15}/>} title="System RAM" subtitle="Memory usage" value={`${(data.ram.used_mb / 1024).toFixed(1)} / ${(data.ram.total_mb / 1024).toFixed(1)} GB`} percent={data.ram.percent} status={data.ram.status} extra={`${(data.ram.available_mb / 1024).toFixed(1)} GB available`}/>

        {/* CPU */}
        <ResourceItem icon={<Cpu size={15}/>} title="CPU" subtitle={data.cpu.name || 'Processor'} value={`${data.cpu.percent}% load`} percent={data.cpu.percent} status={data.cpu.status} extra={`${data.cpu.logical_cores} logical cores`}/>

        {/* Disk */}
        <ResourceItem icon={<HardDrive size={15}/>} title="Disk" subtitle={data.disk.path} value={`${data.disk.free_gb} GB free`} percent={data.disk.percent} status={data.disk.status} extra={`${data.disk.used_gb} / ${data.disk.total_gb} GB used`}/>
      </div>
    </div>);
}
/* ── sub-component ─────────────────────────────────── */
function ResourceItem({ icon, title, subtitle, value, percent, status, extra, }) {
    return (<div className="rounded-2xl border border-white/[0.04] bg-black/20 p-4">
      {/* Header row */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2.5">
          <div className="h-8 w-8 rounded-xl bg-white/[0.04] border border-white/[0.04] grid place-items-center text-white/50">
            {icon}
          </div>
          <div className="min-w-0">
            <div className="text-[13px] font-medium text-white/90">{title}</div>
            <div className="text-[10px] text-white/25 truncate max-w-[140px]">{subtitle}</div>
          </div>
        </div>
        <div className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold shrink-0 ${pillTone(status)}`}>
          {status}
        </div>
      </div>

      {/* Value */}
      <div className="text-xl font-bold text-white mb-2.5">{value}</div>

      {/* Progress bar */}
      <div className="h-1.5 rounded-full bg-white/[0.05] overflow-hidden mb-2">
        <div className={`h-full rounded-full transition-all duration-500 ${barColor(status)}`} style={{ width: `${clamp(percent)}%` }}/>
      </div>

      {/* Extra label */}
      <div className="text-[11px] text-white/30">{extra}</div>
    </div>);
}

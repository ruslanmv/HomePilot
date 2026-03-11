/**
 * SystemStatusDialog — live health dashboard for HomePilot services.
 *
 * Shows a donut chart (pure CSS conic-gradient), service health cards,
 * and architecture overview.  No chart library needed.
 */
import React, { useEffect, useMemo, useState } from 'react'
import { X, Activity, Database, Cpu, Server, Bot, PlugZap } from 'lucide-react'
import { fetchSystemOverview, type SystemOverviewResponse } from './systemApi'
import SystemResourcesCard from './SystemResourcesCard'

/* ── helpers ───────────────────────────────────────────── */

function formatUptime(sec: number) {
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return `${h}h ${m}m`
}

function statusTone(ok?: boolean) {
  if (ok) return 'text-emerald-300/90 border-emerald-500/15 bg-emerald-500/8'
  return 'text-red-300/80 border-red-400/15 bg-red-500/6'
}

const SERVICE_LABELS: Record<string, string> = {
  backend: 'Backend',
  ollama: 'Ollama',
  llm: 'LLM',
  comfyui: 'ComfyUI',
  forge: 'ContextForge',
  sqlite: 'SQLite',
}

/* ── main component ────────────────────────────────────── */

export default function SystemStatusDialog({
  backendUrl,
  apiKey,
  onClose,
}: {
  backendUrl: string
  apiKey?: string
  onClose: () => void
}) {
  const [data, setData] = useState<SystemOverviewResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  /* Escape to close */
  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onEsc)
    return () => document.removeEventListener('keydown', onEsc)
  }, [onClose])

  /* Fetch data */
  useEffect(() => {
    let mounted = true
    ;(async () => {
      try {
        setLoading(true)
        const result = await fetchSystemOverview(backendUrl, apiKey)
        if (mounted) setData(result)
      } catch (e: any) {
        if (mounted) setError(e?.message || 'Failed to load system status')
      } finally {
        if (mounted) setLoading(false)
      }
    })()
    return () => { mounted = false }
  }, [backendUrl, apiKey])

  /* Donut gradient — glow only on the green arc */
  const healthyPct = data
    ? Math.round((data.overview.healthy_services / Math.max(data.overview.total_services, 1)) * 100)
    : 0
  const donut = useMemo(() => {
    if (!data) return 'conic-gradient(#374151 0% 100%)'
    return `conic-gradient(#34d399 0% ${healthyPct}%, rgba(255,255,255,0.06) ${healthyPct}% 100%)`
  }, [data, healthyPct])

  const handleBackdrop = (e: React.MouseEvent) => { if (e.target === e.currentTarget) onClose() }

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={handleBackdrop}
      style={{ animation: 'statusFadeIn 200ms ease-out' }}
    >
      <div
        className="relative w-[960px] max-w-[96vw] max-h-[92vh] overflow-hidden rounded-3xl border border-white/[0.07] bg-[#0c0c18] shadow-2xl"
        style={{ animation: 'statusSlideUp 250ms ease-out' }}
      >
        {/* Close — smaller, subtler, brighter on hover */}
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 z-10 h-7 w-7 rounded-full grid place-items-center text-white/25 hover:text-white/80 hover:bg-white/8 transition-colors"
        >
          <X size={14} />
        </button>

        {/* Accent bar */}
        <div className="h-1 w-full bg-gradient-to-r from-emerald-500 via-cyan-500 to-blue-500" />

        <div className="px-8 pt-7 pb-8 overflow-y-auto max-h-[calc(92vh-4px)]">
          {/* Header */}
          <div className="flex items-start justify-between gap-6 mb-7">
            <div>
              <div className="text-[10px] uppercase tracking-[0.25em] text-white/25 mb-2">System Overview</div>
              <h2 className="text-3xl font-bold text-white tracking-tight">HomePilot Runtime</h2>
              <p className="text-sm text-white/40 mt-1.5">Live health dashboard for your backend, models, and services.</p>
            </div>
            {data && (
              <div className="px-3 py-1 rounded-full text-xs font-semibold border text-emerald-300/80 border-emerald-500/15 bg-emerald-500/8">
                v{data.overview.version}
              </div>
            )}
          </div>

          {loading ? (
            <div className="text-white/50 text-sm py-12 text-center">Loading system status...</div>
          ) : error ? (
            <div className="text-red-300/80 text-sm py-12 text-center">{error}</div>
          ) : data ? (
            <>
              {/* Top metrics — dimmer labels, more spacing */}
              <div className="grid grid-cols-4 gap-4 mb-7">
                <MetricCard label="Uptime" value={formatUptime(data.overview.uptime_seconds)} delay={0} />
                <MetricCard label="Healthy Services" value={`${data.overview.healthy_services}/${data.overview.total_services}`} delay={60} />
                <MetricCard label="Avg Latency" value={`${data.overview.avg_latency_ms}ms`} delay={120} />
                <MetricCard label="Active Entities" value={`${data.overview.active_entities}`} delay={180} />
              </div>

              {/* Machine Capacity — additive, fails gracefully */}
              <SystemResourcesCard backendUrl={backendUrl} apiKey={apiKey} />

              {/* Donut + Architecture */}
              <div className="grid grid-cols-[280px_1fr] gap-6 mb-7">
                {/* Donut chart — flat card, no nested box */}
                <div className="rounded-3xl border border-white/[0.07] bg-white/[0.02] px-6 pt-5 pb-6 flex flex-col items-center">
                  <div className="text-sm font-semibold text-white/90 self-start mb-5">Service Stability</div>

                  {/* Donut: thinner stroke, more center room */}
                  <div className="relative h-40 w-40 mb-1">
                    {/* Green arc glow (behind the donut) */}
                    <div
                      className="absolute inset-[-4px] rounded-full blur-md opacity-30 donut-ring"
                      style={{ background: `conic-gradient(rgba(52,211,153,0.5) 0% ${healthyPct}%, transparent ${healthyPct}% 100%)` }}
                    />
                    {/* Donut track */}
                    <div className="absolute inset-0 rounded-full donut-ring" style={{ background: donut }} />
                    {/* Thick cutout — thinner ring (inset-[14px] → thinner stroke) */}
                    <div className="absolute inset-[14px] rounded-full bg-[#0c0c18]" />
                    {/* Center text */}
                    <div className="absolute inset-0 grid place-items-center">
                      <div className="text-center">
                        <div className="text-3xl font-bold text-white tracking-tight">{healthyPct}%</div>
                        <div className="text-[11px] text-white/30 mt-0.5">healthy</div>
                        <div className="text-[10px] text-white/20 mt-0.5">
                          {data.overview.healthy_services} of {data.overview.total_services} online
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Legend — smaller, dimmer, more spacing from donut */}
                  <div className="flex items-center gap-5 mt-5 text-[11px]">
                    <Legend color="bg-emerald-400/80" label="Running" />
                    <Legend color="bg-white/15" label="Down" />
                  </div>
                </div>

                {/* Architecture flow — more gap, padding, dimmer descriptions */}
                <div className="rounded-3xl border border-white/[0.07] bg-white/[0.02] p-6">
                  <div className="text-sm font-semibold text-white/90 mb-5">Architecture Flow</div>
                  <div className="grid grid-cols-4 gap-5 text-sm">
                    <FlowCard
                      title="Inputs"
                      icon={<PlugZap size={14} />}
                      items={[`${data.architecture.inputs.virtual_servers_active}/${data.architecture.inputs.virtual_servers_total} virtual servers`]}
                    />
                    <FlowCard
                      title="Gateway"
                      icon={<Activity size={14} />}
                      items={[`ContextForge ${data.architecture.gateway.contextforge_ok ? 'online' : 'offline'}`]}
                    />
                    <FlowCard
                      title="Infrastructure"
                      icon={<Database size={14} />}
                      items={[data.architecture.infrastructure.database, data.architecture.infrastructure.memory_mode]}
                    />
                    <FlowCard
                      title="Outputs"
                      icon={<Bot size={14} />}
                      items={[
                        `${data.architecture.outputs.mcp_servers_active}/${data.architecture.outputs.mcp_servers_total} MCP`,
                        `${data.architecture.outputs.a2a_agents_active}/${data.architecture.outputs.a2a_agents_total} A2A`,
                        `${data.architecture.outputs.tools_active}/${data.architecture.outputs.tools_total} Tools`,
                      ]}
                    />
                  </div>
                </div>
              </div>

              {/* Services + Inventory */}
              <div className="grid grid-cols-2 gap-6">
                <div className="rounded-3xl border border-white/[0.07] bg-white/[0.02] p-6">
                  <div className="text-sm font-semibold text-white/90 mb-4">Services</div>
                  <div className="space-y-2.5">
                    {Object.entries(data.services).map(([key, svc]) => (
                      <div key={key} className="status-card flex items-center justify-between rounded-2xl border border-white/[0.04] bg-black/20 px-4 py-3">
                        <div className="flex items-center gap-3">
                          <div className="h-9 w-9 rounded-xl bg-white/[0.04] border border-white/[0.04] grid place-items-center text-white/50">
                            {key === 'sqlite' ? <Database size={15} /> :
                             key === 'backend' ? <Server size={15} /> :
                             key === 'llm' ? <Cpu size={15} /> :
                             <Activity size={15} />}
                          </div>
                          <div>
                            <div className="text-[13px] font-medium text-white/90">{SERVICE_LABELS[key] || key}</div>
                            <div className="text-[11px] text-white/25 truncate max-w-[160px]">
                              {svc.url || svc.base_url || svc.service || 'internal'}
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-3">
                          <div className="text-[11px] text-white/35">
                            {svc.latency_ms != null ? `${svc.latency_ms}ms` : '\u2014'}
                          </div>
                          <div className={`px-2.5 py-1 rounded-full border text-[11px] font-semibold ${statusTone(svc.ok)}`}>
                            {svc.ok ? 'Healthy' : 'Offline'}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="rounded-3xl border border-white/[0.07] bg-white/[0.02] p-6">
                  <div className="text-sm font-semibold text-white/90 mb-4">Inventory</div>
                  <div className="grid grid-cols-2 gap-3.5">
                    <SmallCount label="Virtual Servers" value={data.architecture.inputs.virtual_servers_active} sub={`${data.architecture.inputs.virtual_servers_total} total`} />
                    <SmallCount label="MCP Servers" value={data.architecture.outputs.mcp_servers_active} sub={`${data.architecture.outputs.mcp_servers_total} total`} />
                    <SmallCount label="A2A Agents" value={data.architecture.outputs.a2a_agents_active} sub={`${data.architecture.outputs.a2a_agents_total} total`} />
                    <SmallCount label="Tools" value={data.architecture.outputs.tools_active} sub={`${data.architecture.outputs.tools_total} total`} />
                    <SmallCount label="Prompts" value={data.architecture.outputs.prompts_active} sub={`${data.architecture.outputs.prompts_total} total`} />
                    <SmallCount label="Resources" value={data.architecture.outputs.resources_active} sub={`${data.architecture.outputs.resources_total} total`} />
                  </div>
                </div>
              </div>
            </>
          ) : null}
        </div>
      </div>

      <style>{`
        @keyframes statusFadeIn { from { opacity: 0 } to { opacity: 1 } }
        @keyframes statusSlideUp { from { opacity: 0; transform: translateY(16px) scale(0.97) } to { opacity: 1; transform: translateY(0) scale(1) } }
        @keyframes statusCardIn { from { opacity: 0; transform: translateY(12px) } to { opacity: 1; transform: translateY(0) } }
        @keyframes donutSpin { from { transform: rotate(-90deg) } to { transform: rotate(0deg) } }
        .status-card { animation: statusCardIn 350ms ease-out both }
        .status-card:nth-child(1) { animation-delay: 60ms }
        .status-card:nth-child(2) { animation-delay: 120ms }
        .status-card:nth-child(3) { animation-delay: 180ms }
        .status-card:nth-child(4) { animation-delay: 240ms }
        .status-card:nth-child(5) { animation-delay: 300ms }
        .status-card:nth-child(6) { animation-delay: 360ms }
        .donut-ring { animation: donutSpin 800ms cubic-bezier(0.34,1.56,0.64,1) both; animation-delay: 200ms }
      `}</style>
    </div>
  )
}

/* ── sub-components ────────────────────────────────────── */

function MetricCard({ label, value, delay = 0 }: { label: string; value: string; delay?: number }) {
  return (
    <div
      className="rounded-2xl border border-white/[0.07] bg-white/[0.02] px-4 py-4"
      style={{ animation: `statusCardIn 350ms ease-out ${delay}ms both` }}
    >
      <div className="text-[10px] uppercase tracking-wider text-white/25 mb-2">{label}</div>
      <div className="text-2xl font-bold text-white">{value}</div>
    </div>
  )
}

function SmallCount({ label, value, sub }: { label: string; value: number; sub: string }) {
  return (
    <div className="rounded-2xl border border-white/[0.04] bg-black/20 px-4 py-4">
      <div className="text-[10px] uppercase tracking-wider text-white/25 mb-2">{label}</div>
      <div className="text-2xl font-bold text-white">{value}</div>
      <div className="text-[11px] text-white/25 mt-1">{sub}</div>
    </div>
  )
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5 text-white/35">
      <div className={`h-2 w-2 rounded-full ${color}`} />
      <span>{label}</span>
    </div>
  )
}

function FlowCard({ title, icon, items }: { title: string; icon: React.ReactNode; items: string[] }) {
  return (
    <div className="rounded-2xl border border-white/[0.04] bg-black/20 p-4">
      <div className="flex items-center gap-2 text-white/70 font-medium text-[13px] mb-3">
        {icon}
        {title}
      </div>
      <div className="space-y-2">
        {items.map((item) => (
          <div key={item} className="text-[11px] text-white/35">{item}</div>
        ))}
      </div>
    </div>
  )
}

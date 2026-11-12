/**
 * ComputeSettingsTabs — segmented navigation for the Compute section.
 *
 * "My AI" is the simple view: everything the user can reach and how HomePilot
 * chooses between it. The other three tabs are the advanced controls —
 * inventory (Resources), connections (Sources), and per-model policy (Routing). "Connect source" on the Resources tab deep-links to Sources.
 */
import React, { useState } from "react";
import { Cpu, Server, SlidersHorizontal, Sparkles } from "lucide-react";
import EcosystemPanel from "./EcosystemPanel";
import ComputeResourcesPanel from "./ComputeResourcesPanel";
import ComputeSourcesSettings from "./ComputeSourcesSettings";
import RoutingPolicyEditor from "./RoutingPolicyEditor";

type Tab = "ecosystem" | "resources" | "sources" | "routing";

const TABS: { id: Tab; label: string; Icon: typeof Cpu }[] = [
  { id: "ecosystem", label: "My AI", Icon: Sparkles },
  { id: "resources", label: "Resources", Icon: Cpu },
  { id: "sources", label: "Sources", Icon: Server },
  { id: "routing", label: "Routing", Icon: SlidersHorizontal },
];

export default function ComputeSettingsTabs() {
  const [tab, setTab] = useState<Tab>("ecosystem");

  return (
    <div className="space-y-4">
      <div className="inline-flex max-w-full flex-wrap rounded-xl border border-white/10 bg-black/30 p-1">
        {TABS.map(({ id, label, Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`h-9 px-4 rounded-lg text-xs font-medium inline-flex items-center gap-1.5 transition-colors ${
              tab === id ? "bg-white/10 text-white" : "text-white/50 hover:text-white/80"
            }`}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {tab === "ecosystem" && <EcosystemPanel />}
      {tab === "resources" && <ComputeResourcesPanel onConnectSource={() => setTab("sources")} />}
      {tab === "sources" && <ComputeSourcesSettings />}
      {tab === "routing" && <RoutingPolicyEditor />}
    </div>
  );
}

/**
 * ComputeSettingsTabs — segmented navigation for the Compute section.
 *
 * Splits the feature into the three concerns the design separates — inventory
 * (Resources), connections (Sources), and policy (Routing) — instead of one
 * long scroll. "Connect source" on the Resources tab deep-links to Sources.
 */
import React, { useState } from "react";
import { Cpu, Server, SlidersHorizontal } from "lucide-react";
import ComputeResourcesPanel from "./ComputeResourcesPanel";
import ComputeSourcesSettings from "./ComputeSourcesSettings";
import RoutingPolicyEditor from "./RoutingPolicyEditor";

type Tab = "resources" | "sources" | "routing";

const TABS: { id: Tab; label: string; Icon: typeof Cpu }[] = [
  { id: "resources", label: "Resources", Icon: Cpu },
  { id: "sources", label: "Sources", Icon: Server },
  { id: "routing", label: "Routing", Icon: SlidersHorizontal },
];

export default function ComputeSettingsTabs() {
  const [tab, setTab] = useState<Tab>("resources");

  return (
    <div className="space-y-4">
      <div className="inline-flex rounded-xl border border-white/10 bg-black/30 p-1">
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

      {tab === "resources" && <ComputeResourcesPanel onConnectSource={() => setTab("sources")} />}
      {tab === "sources" && <ComputeSourcesSettings />}
      {tab === "routing" && <RoutingPolicyEditor />}
    </div>
  );
}

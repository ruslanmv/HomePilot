/**
 * GraphPanel — read-only DAG view for an experience.
 *
 * First cut: no canvas / no drag-to-reposition — just a
 * kind-grouped list of nodes with their outbound transitions
 * rendered as chips. That covers the 80 % need (verify the
 * planner built a sensible graph) while keeping the editor shell
 * shippable in a single batch.
 *
 * Data shape:
 *   - Fetches nodes + edges in parallel via Promise.all inside
 *     one useAsyncResource, so reload / error / loading stay in
 *     sync.
 *   - Nodes grouped by `kind` (scene → decision → merge →
 *     assessment → remediation → ending) so the structural
 *     skeleton is easy to eyeball.
 *   - Outbound edges are resolved to target node titles with an
 *     O(1) id map — no N² lookups.
 */

import React, { useMemo } from "react";
import { ArrowRight, GitBranch } from "lucide-react";
import type { InteractiveApi } from "./api";
import type { EdgeItem, NodeItem } from "./types";
import {
  EmptyState,
  ErrorBanner,
  Panel,
  SkeletonRow,
  useAsyncResource,
} from "./ui";

export interface GraphPanelProps {
  api: InteractiveApi;
  projectId: string;
}

const KIND_ORDER: NodeItem["kind"][] = [
  "scene", "decision", "merge", "assessment", "remediation", "ending",
];

const KIND_BADGE: Record<NodeItem["kind"], string> = {
  scene: "bg-[#3ea6ff]/10 text-[#3ea6ff] border-[#3ea6ff]/40",
  decision: "bg-amber-500/10 text-amber-300 border-amber-500/40",
  merge: "bg-purple-500/10 text-purple-300 border-purple-500/40",
  assessment: "bg-emerald-500/10 text-emerald-300 border-emerald-500/40",
  remediation: "bg-orange-500/10 text-orange-300 border-orange-500/40",
  ending: "bg-[#aaa]/10 text-[#aaa] border-white/10",
};

export function GraphPanel({ api, projectId }: GraphPanelProps) {
  const resource = useAsyncResource<{ nodes: NodeItem[]; edges: EdgeItem[] }>(
    async (signal) => {
      const [nodes, edges] = await Promise.all([
        api.listNodes(projectId, signal),
        api.listEdges(projectId, signal),
      ]);
      return { nodes, edges };
    },
    [api, projectId],
  );

  const { grouped, titleById, outboundByFrom } = useMemo(() => {
    const nodes = resource.data?.nodes || [];
    const edges = resource.data?.edges || [];
    const titleById = new Map<string, string>();
    nodes.forEach((n) => titleById.set(n.id, n.title || "(untitled)"));

    const outboundByFrom = new Map<string, EdgeItem[]>();
    edges.forEach((e) => {
      const list = outboundByFrom.get(e.from_node_id) || [];
      list.push(e);
      outboundByFrom.set(e.from_node_id, list);
    });

    const grouped: Record<string, NodeItem[]> = {};
    for (const n of nodes) {
      const bucket = grouped[n.kind] || (grouped[n.kind] = []);
      bucket.push(n);
    }
    return { grouped, titleById, outboundByFrom };
  }, [resource.data]);

  return (
    <Panel
      title="Scene graph"
      subtitle="Read-only view of nodes + transitions. Editing lands in a future batch."
    >
      {resource.error ? (
        <ErrorBanner
          title="Couldn't load the graph"
          message={resource.error}
          onRetry={resource.reload}
        />
      ) : resource.loading && !resource.data ? (
        <div className="flex flex-col gap-2" aria-busy="true">
          {Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} />)}
        </div>
      ) : (resource.data?.nodes || []).length === 0 ? (
        <EmptyState
          icon={<GitBranch className="w-12 h-12" aria-hidden />}
          title="No nodes yet"
          description="The planner didn't seed a graph, or the seeding step was skipped. Re-run the wizard or add nodes directly once editing ships."
        />
      ) : (
        <div className="flex flex-col gap-5">
          {KIND_ORDER.map((kind) => {
            const bucket = grouped[kind];
            if (!bucket || bucket.length === 0) return null;
            return (
              <section key={kind}>
                <header className="flex items-center gap-2 mb-2">
                  <span
                    className={[
                      "text-[10px] uppercase tracking-wide px-2 py-0.5 rounded border",
                      KIND_BADGE[kind],
                    ].join(" ")}
                  >
                    {kind}
                  </span>
                  <span className="text-xs text-[#777]">{bucket.length} {bucket.length === 1 ? "node" : "nodes"}</span>
                </header>
                <ul className="flex flex-col gap-2">
                  {bucket.map((node) => (
                    <NodeRow
                      key={node.id}
                      node={node}
                      outbound={outboundByFrom.get(node.id) || []}
                      titleById={titleById}
                    />
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

function NodeRow({
  node, outbound, titleById,
}: {
  node: NodeItem;
  outbound: EdgeItem[];
  titleById: Map<string, string>;
}) {
  return (
    <li className="bg-[#121212] border border-[#3f3f3f] rounded-md p-3 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium text-[#f1f1f1] truncate">
            {node.title || "(untitled)"}
          </div>
          {node.narration && (
            <p className="text-xs text-[#aaa] mt-0.5 line-clamp-2">{node.narration}</p>
          )}
        </div>
        <code className="text-[10px] text-[#777] shrink-0">{node.id}</code>
      </div>

      {outbound.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <ArrowRight className="w-3.5 h-3.5 text-[#777]" aria-hidden />
          {outbound
            .slice()
            .sort((a, b) => (a.ordinal || 0) - (b.ordinal || 0))
            .map((edge) => (
              <span
                key={edge.id}
                className="text-[11px] bg-[#1f1f1f] border border-[#3f3f3f] rounded px-2 py-0.5 text-[#cfd8dc]"
                title={`edge ${edge.id} · ${edge.trigger_kind}`}
              >
                <span className="text-[#777] mr-1">{edge.trigger_kind}</span>
                {titleById.get(edge.to_node_id) || edge.to_node_id}
              </span>
            ))}
        </div>
      )}
    </li>
  );
}

/**
 * GraphPanel — the authoring cockpit for a project's scene graph.
 *
 * Evolved from the read-only DAG view into the post-creation
 * authoring surface the user loads right after the wizard
 * finishes. Every row supports:
 *   - **Edit** (EDIT-2): click-to-edit title + narration +
 *     image prompt. Saves via PATCH /nodes/{id}.
 *   - **Regenerate** (EDIT-3): re-render this scene's asset. Hits
 *     POST /experiences/{eid}/nodes/{nid}/render and updates the
 *     preview inline.
 *   - **Preview** (EDIT-4): open the rendered image/video (or a
 *     placeholder if nothing rendered yet) in a modal.
 *
 * Panel header adds a "Regenerate all missing" action that streams
 * through /generate-all/stream with the bulk modal, so users who
 * created a project with the render flag off can flip the flag
 * and one-click to catch every empty scene up.
 *
 * Nodes are grouped by kind (scene → decision → merge → ending)
 * so the structural skeleton stays legible even in a 20-scene
 * experience. Outbound edges render as chips with target-title
 * labels; O(1) lookup via a titleById map.
 */

import React, { useCallback, useMemo, useState } from "react";
import {
  ArrowRight, Check, GitBranch, Image as ImageIcon, Loader2,
  Pencil, Play, RotateCw, X,
} from "lucide-react";
import type { InteractiveApi } from "./api";
import type { EdgeItem, NodeItem } from "./types";
import { InteractiveApiError } from "./types";
import { GeneratingPanel } from "./GeneratingPanel";
import {
  EmptyState,
  ErrorBanner,
  Panel,
  PrimaryButton,
  SecondaryButton,
  SkeletonRow,
  useAsyncResource,
  useToast,
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

// Kinds that carry a visual asset the Preview modal can show.
// Endings + merges are usually structural-only so we skip the
// render/preview affordances on them.
const RENDERABLE_KINDS = new Set<NodeItem["kind"]>([
  "scene", "decision", "assessment", "remediation",
]);

export function GraphPanel({ api, projectId }: GraphPanelProps) {
  const toast = useToast();
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

  const missingAssetCount = useMemo(() => {
    const nodes = resource.data?.nodes || [];
    return nodes.filter(
      (n) => RENDERABLE_KINDS.has(n.kind) && (n.asset_ids || []).length === 0,
    ).length;
  }, [resource.data]);

  // ── Bulk "Regenerate all missing" via /generate-all/stream ──

  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkTotal, setBulkTotal] = useState(0);
  const [bulkDone, setBulkDone] = useState(0);
  const [bulkTitle, setBulkTitle] = useState("");

  const regenerateAllMissing = useCallback(async () => {
    setBulkOpen(true);
    setBulkTotal(0);
    setBulkDone(0);
    setBulkTitle("");
    try {
      await api.generateAllStream(projectId, {
        onEvent: (ev) => {
          if (ev.type === "rendering_started") {
            const total = Number((ev.payload as any)?.total || 0);
            setBulkTotal(total);
          }
          if (ev.type === "rendering_scene") {
            const title = String((ev.payload as any)?.title || "");
            if (title) setBulkTitle(title);
          }
          if (
            ev.type === "scene_rendered"
            || ev.type === "scene_skipped"
            || ev.type === "scene_render_failed"
          ) {
            setBulkDone((prev) => prev + 1);
          }
        },
      });
      toast.toast({
        variant: "success",
        title: "Regeneration complete",
        message: "Your scenes are up to date.",
      });
      resource.reload();
    } catch (err) {
      const e = err as InteractiveApiError;
      toast.toast({
        variant: "error",
        title: "Regeneration failed",
        message: e.message || "Try again, or regenerate scenes one by one.",
      });
    } finally {
      setBulkOpen(false);
    }
  }, [api, projectId, resource, toast]);

  // ── Per-row handlers shared with every NodeRow ────────────────

  const handleSavePatch = useCallback(
    async (nodeId: string, patch: { title?: string; narration?: string; image_prompt?: string }) => {
      try {
        await api.patchNode(nodeId, patch);
        toast.toast({ variant: "success", title: "Scene saved" });
        resource.reload();
      } catch (err) {
        const e = err as InteractiveApiError;
        toast.toast({
          variant: "error",
          title: "Save failed",
          message: e.message || "Check your input and retry.",
        });
        throw err;
      }
    },
    [api, resource, toast],
  );

  const handleRegenerate = useCallback(
    async (nodeId: string) => {
      try {
        const res = await api.renderSingleScene(projectId, nodeId);
        if (res.status === "rendered") {
          toast.toast({
            variant: "success",
            title: "Scene regenerated",
            message: "Refreshing the graph…",
          });
          resource.reload();
        } else if (res.status === "skipped") {
          toast.toast({
            variant: "warning",
            title: "Rendering is disabled",
            message: "Enable INTERACTIVE_PLAYBACK_RENDER or pick a different model in Settings.",
          });
        } else if (res.status === "failed") {
          toast.toast({
            variant: "error",
            title: "Render failed",
            message: res.reason || "Try again in a moment.",
          });
        } else {
          toast.toast({
            variant: "info",
            title: "Rendered but not attached",
            message: "The asset exists; refresh to see it.",
          });
          resource.reload();
        }
      } catch (err) {
        const e = err as InteractiveApiError;
        toast.toast({
          variant: "error",
          title: "Couldn't regenerate this scene",
          message: e.message || "Try again.",
        });
      }
    },
    [api, projectId, resource, toast],
  );

  // ── Preview modal ────────────────────────────────────────────

  const [previewNode, setPreviewNode] = useState<NodeItem | null>(null);

  return (
    <Panel
      title="Scene graph"
      subtitle="Edit, regenerate, or preview any scene. Changes save as you go."
      actions={
        missingAssetCount > 0 ? (
          <PrimaryButton
            onClick={regenerateAllMissing}
            icon={<RotateCw className="w-3.5 h-3.5" aria-hidden />}
            size="sm"
          >
            Regenerate all ({missingAssetCount} missing)
          </PrimaryButton>
        ) : undefined
      }
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
          description="The planner didn't seed a graph. Re-run the wizard, or open the Catalog tab to add scenes manually."
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
                      onSave={handleSavePatch}
                      onRegenerate={handleRegenerate}
                      onPreview={() => setPreviewNode(node)}
                    />
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}

      {bulkOpen && (
        <GeneratingPanel
          title={bulkTotal > 0
            ? `Regenerating scenes · ${bulkDone} of ${bulkTotal}`
            : "Regenerating scenes"}
          description={bulkTitle ? `Now rendering: ${bulkTitle}` : "Starting the render pipeline…"}
          spinnerSize="large"
          accentClassName="text-[#c4b5fd]"
          progress={bulkTotal > 0 ? Math.round((bulkDone / bulkTotal) * 100) : undefined}
          progressLabel={bulkTotal > 0 ? `${bulkDone} / ${bulkTotal} scenes` : undefined}
        />
      )}

      {previewNode && (
        <PreviewModal
          api={api}
          node={previewNode}
          onClose={() => setPreviewNode(null)}
          onRegenerate={() => {
            setPreviewNode(null);
            handleRegenerate(previewNode.id);
          }}
        />
      )}
    </Panel>
  );
}


// ── NodeRow with edit + regenerate + preview ──────────────────

function NodeRow({
  node, outbound, titleById, onSave, onRegenerate, onPreview,
}: {
  node: NodeItem;
  outbound: EdgeItem[];
  titleById: Map<string, string>;
  onSave: (nodeId: string, patch: { title?: string; narration?: string; image_prompt?: string }) => Promise<void>;
  onRegenerate: (nodeId: string) => void;
  onPreview: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [draftTitle, setDraftTitle] = useState(node.title || "");
  const [draftNarration, setDraftNarration] = useState(node.narration || "");
  const [draftImagePrompt, setDraftImagePrompt] = useState(node.image_prompt || "");

  const hasAsset = (node.asset_ids || []).length > 0;
  const canRender = RENDERABLE_KINDS.has(node.kind);

  const openEdit = () => {
    setDraftTitle(node.title || "");
    setDraftNarration(node.narration || "");
    setDraftImagePrompt(node.image_prompt || "");
    setEditing(true);
  };

  const saveEdit = async () => {
    const patch: { title?: string; narration?: string; image_prompt?: string } = {};
    if (draftTitle !== (node.title || "")) patch.title = draftTitle;
    if (draftNarration !== (node.narration || "")) patch.narration = draftNarration;
    if (draftImagePrompt !== (node.image_prompt || "")) patch.image_prompt = draftImagePrompt;
    if (Object.keys(patch).length === 0) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(node.id, patch);
      setEditing(false);
    } catch {
      // toast already shown by parent; stay in edit mode.
    } finally {
      setSaving(false);
    }
  };

  const kickRegenerate = async () => {
    setRegenerating(true);
    try {
      await onRegenerate(node.id);
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <li className="bg-[#121212] border border-[#3f3f3f] rounded-md p-3 flex flex-col gap-2">
      {editing ? (
        <div className="flex flex-col gap-2">
          <FieldRow label="Title">
            <input
              type="text"
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
              className="w-full bg-[#0f0f0f] border border-[#3f3f3f] rounded-md px-2.5 py-1.5 text-sm outline-none focus:border-[#3ea6ff]"
              autoFocus
            />
          </FieldRow>
          <FieldRow label="Narration">
            <textarea
              value={draftNarration}
              onChange={(e) => setDraftNarration(e.target.value)}
              rows={3}
              className="w-full bg-[#0f0f0f] border border-[#3f3f3f] rounded-md px-2.5 py-1.5 text-sm outline-none focus:border-[#3ea6ff] resize-y"
            />
          </FieldRow>
          <FieldRow label="Image prompt">
            <textarea
              value={draftImagePrompt}
              onChange={(e) => setDraftImagePrompt(e.target.value)}
              rows={2}
              placeholder="Optional visual direction for the renderer"
              className="w-full bg-[#0f0f0f] border border-[#3f3f3f] rounded-md px-2.5 py-1.5 text-sm outline-none focus:border-[#3ea6ff] resize-y"
            />
          </FieldRow>
          <div className="flex items-center justify-end gap-2 mt-1">
            <SecondaryButton
              onClick={() => setEditing(false)}
              size="sm"
              disabled={saving}
            >
              Cancel
            </SecondaryButton>
            <PrimaryButton
              onClick={saveEdit}
              size="sm"
              icon={saving
                ? <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />
                : <Check className="w-3.5 h-3.5" aria-hidden />}
              disabled={saving}
            >
              Save
            </PrimaryButton>
          </div>
        </div>
      ) : (
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-[#f1f1f1] truncate">
              {node.title || "(untitled)"}
            </div>
            {node.narration && (
              <p className="text-xs text-[#aaa] mt-0.5 line-clamp-2">{node.narration}</p>
            )}
            {!hasAsset && canRender && (
              <div className="text-[11px] text-amber-300/90 mt-1 inline-flex items-center gap-1">
                <ImageIcon className="w-3 h-3" aria-hidden />
                No asset rendered yet
              </div>
            )}
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {canRender && (
              <>
                <IconAction label="Preview" onClick={onPreview}>
                  <Play className="w-3.5 h-3.5 fill-current" aria-hidden />
                </IconAction>
                <IconAction
                  label={regenerating ? "Regenerating…" : "Regenerate"}
                  onClick={kickRegenerate}
                  disabled={regenerating}
                >
                  {regenerating
                    ? <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />
                    : <RotateCw className="w-3.5 h-3.5" aria-hidden />}
                </IconAction>
              </>
            )}
            <IconAction label="Edit" onClick={openEdit}>
              <Pencil className="w-3.5 h-3.5" aria-hidden />
            </IconAction>
          </div>
          <code className="text-[10px] text-[#555] shrink-0 self-start mt-0.5">{node.id.slice(-6)}</code>
        </div>
      )}

      {outbound.length > 0 && !editing && (
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


// ── Small UI helpers ──────────────────────────────────────────

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-[#777]">{label}</span>
      {children}
    </label>
  );
}


function IconAction({
  children, label, onClick, disabled,
}: {
  children: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      disabled={disabled}
      className="w-7 h-7 rounded-md hover:bg-white/10 text-[#aaa] hover:text-[#f1f1f1] flex items-center justify-center transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {children}
    </button>
  );
}


// ── Preview modal (EDIT-4) ────────────────────────────────────

function PreviewModal({
  api, node, onClose, onRegenerate,
}: {
  api: InteractiveApi;
  node: NodeItem;
  onClose: () => void;
  onRegenerate: () => void;
}) {
  const assetId = (node.asset_ids || [])[0] || "";
  // Resolve the player URL via the backend's registry so we
  // don't duplicate the asset-id → storage-key logic client-side.
  // Stubs (ixa_stub_*) + unknown ids resolve to null; the modal
  // then shows the "no asset yet" empty state with a Regenerate
  // CTA, instead of a broken image icon.
  const urlRes = useAsyncResource<string | null>(
    (signal) => assetId ? api.resolveAssetUrl(assetId, signal) : Promise.resolve(null),
    [api, assetId],
  );
  const src = urlRes.data || "";
  const looksLikeVideo = /\.(mp4|webm|mov|mkv|m4v)(\?|$)/i.test(src);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Preview: ${node.title}`}
      className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-black/75 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-xl bg-[#0f0f0f] border border-[#3f3f3f] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between gap-4 px-4 py-3 border-b border-[#2a2a2a]">
          <div className="min-w-0">
            <div className="text-sm font-semibold truncate">{node.title || "(untitled)"}</div>
            <div className="text-[11px] text-[#777]">{node.kind} · preview</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close preview"
            className="w-8 h-8 rounded-md hover:bg-white/10 flex items-center justify-center"
          >
            <X className="w-4 h-4" aria-hidden />
          </button>
        </header>
        <div className="aspect-video bg-black flex items-center justify-center">
          {urlRes.loading ? (
            <Loader2 className="w-6 h-6 text-[#555] animate-spin" aria-hidden />
          ) : !src ? (
            <div className="text-center p-8">
              <ImageIcon className="w-12 h-12 text-[#555] mx-auto mb-3" aria-hidden />
              <div className="text-sm text-[#aaa]">
                {assetId ? "Asset not resolvable yet." : "No asset rendered yet."}
              </div>
              <div className="text-[11px] text-[#777] mt-1">
                Click Regenerate below to produce one.
              </div>
            </div>
          ) : looksLikeVideo ? (
            <video
              src={src}
              controls
              autoPlay
              className="max-w-full max-h-full"
            />
          ) : (
            <img src={src} alt={node.title} className="max-w-full max-h-full object-contain" />
          )}
        </div>
        {node.narration && (
          <div className="px-4 py-3 border-t border-[#2a2a2a] text-sm text-[#cfd8dc]">
            {node.narration}
          </div>
        )}
        <footer className="flex items-center justify-end gap-2 px-4 py-3 border-t border-[#2a2a2a]">
          <SecondaryButton onClick={onClose} size="sm">
            Close
          </SecondaryButton>
          <PrimaryButton
            onClick={onRegenerate}
            size="sm"
            icon={<RotateCw className="w-3.5 h-3.5" aria-hidden />}
          >
            Regenerate
          </PrimaryButton>
        </footer>
      </div>
    </div>
  );
}

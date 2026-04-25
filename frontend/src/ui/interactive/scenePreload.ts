/**
 * Scene preload + transition helpers for the Standard Interactive
 * player.
 *
 * The player used to bind directly to ``api.resolveTurn`` and let
 * the network round-trip + ComfyUI render gate every scene change —
 * the user saw a black flash between scenes while the next image
 * loaded fresh from disk every time. The cinematic-engine spec
 * called this out explicitly: assets must be preloaded so transitions
 * feel premium, not laggy.
 *
 * Two pieces here:
 *
 *   * ``useScenePreload`` — fetches the experience's node graph
 *     once, walks the edges from the current scene, and runs
 *     ``new Image().src = …`` on every reachable next-scene's
 *     ``asset_ids[0]``. Browsers cache the bytes; when the player
 *     navigates the next scene mounts from cache.
 *
 *   * ``fadeKey`` — small helper that yields a stable transition
 *     key for a scene id so React's key-based remount triggers
 *     the CSS opacity transition cleanly.
 *
 * Both are pure wrappers around the existing api / DOM primitives —
 * no new dependencies.
 */
import { useEffect, useMemo, useState } from "react";

import type { InteractiveApi } from "./api";
import type { EdgeItem, NodeItem } from "./types";


/**
 * Resolve a node's primary asset URL via the same path the player
 * itself uses. Falls back through:
 *   1. Direct ``http(s)://`` or ``/files/`` URL stored in asset_ids
 *      (legacy authoring stamps these directly)
 *   2. ``GET /v1/interactive/assets/{id}/url`` for registry ids
 *      (the canonical Phase 4 link target).
 *
 * Returns "" when no usable URL can be found — callers skip preload
 * for those nodes, which is fine: the scene will load on demand
 * when navigation lands.
 */
async function _resolveNodeUrl(
  node: NodeItem,
  api: InteractiveApi,
  signal?: AbortSignal,
): Promise<string> {
  const ids = Array.isArray(node.asset_ids) ? node.asset_ids : [];
  const first = String(ids[0] || "").trim();
  if (!first) return "";

  if (first.startsWith("http://") || first.startsWith("https://")) {
    return first;
  }
  if (first.startsWith("/files/") || first.startsWith("/")) {
    return first;
  }

  // Registry id — round-trip the resolve endpoint.
  try {
    const r = await api.resolveAssetUrl(first, signal);
    return r || "";
  } catch {
    return "";
  }
}


/**
 * Preload upcoming scene assets so transitions feel instant.
 *
 * Strategy:
 *   1. Fetch nodes + edges for this experience once on mount.
 *   2. Whenever ``currentNodeId`` changes, walk forward edges from
 *      that node up to ``depth`` hops and preload every reachable
 *      scene's asset.
 *   3. Use ``new Image()`` (not ``fetch``) so the browser puts the
 *      bytes in the regular HTTP cache that ``<img>`` later uses —
 *      ``fetch`` cache and ``<img>`` cache are NOT the same on every
 *      browser.
 *
 * Returns nothing — fire-and-forget. Callers don't need to know
 * which preloads succeeded; on a miss the navigation just stalls
 * for the network roundtrip the same as before.
 */
export function useScenePreload(
  api: InteractiveApi,
  experienceId: string,
  currentNodeId: string,
  depth: number = 2,
): void {
  // Graph is fetched once per experience. AbortController lets the
  // effect cancel stale fetches on remount.
  const [graph, setGraph] = useState<{ nodes: NodeItem[]; edges: EdgeItem[] } | null>(null);

  useEffect(() => {
    if (!experienceId) return;
    const ctrl = new AbortController();
    Promise.all([
      api.listNodes(experienceId, ctrl.signal).catch(() => [] as NodeItem[]),
      api.listEdges(experienceId, ctrl.signal).catch(() => [] as EdgeItem[]),
    ]).then(([nodes, edges]) => {
      if (ctrl.signal.aborted) return;
      setGraph({ nodes, edges });
    });
    return () => ctrl.abort();
  }, [api, experienceId]);

  useEffect(() => {
    if (!graph || !currentNodeId) return;
    const ctrl = new AbortController();

    const adj = new Map<string, string[]>();
    for (const e of graph.edges) {
      const list = adj.get(e.from_node_id) ?? [];
      list.push(e.to_node_id);
      adj.set(e.from_node_id, list);
    }
    const byId = new Map(graph.nodes.map((n) => [n.id, n] as const));

    // BFS bounded by ``depth`` so we don't hammer storage on large
    // graphs. depth=2 means "next + one further" — covers the
    // immediate Continue + every choice's first step.
    const queue: Array<[string, number]> = [[currentNodeId, 0]];
    const seen = new Set<string>([currentNodeId]);
    const targets: NodeItem[] = [];
    while (queue.length) {
      const [id, d] = queue.shift()!;
      if (d >= depth) continue;
      for (const next of adj.get(id) ?? []) {
        if (seen.has(next)) continue;
        seen.add(next);
        const node = byId.get(next);
        if (node) targets.push(node);
        queue.push([next, d + 1]);
      }
    }

    // Resolve URLs in parallel — cap concurrency so we don't open
    // a hundred sockets on a wide branching graph.
    void (async () => {
      const PAR = 4;
      const queueRef = [...targets];
      async function _worker() {
        while (queueRef.length) {
          if (ctrl.signal.aborted) return;
          const node = queueRef.shift();
          if (!node) return;
          const url = await _resolveNodeUrl(node, api, ctrl.signal);
          if (!url || ctrl.signal.aborted) continue;
          // Browser-cache warm. The Image object is GC'd once the
          // request resolves; bytes stay in HTTP cache for the
          // <img> mount the player will do next.
          try {
            const img = new Image();
            img.src = url;
          } catch { /* ignore — browser-side */ }
        }
      }
      await Promise.all(Array.from({ length: PAR }, _worker));
    })();

    return () => ctrl.abort();
  }, [api, graph, currentNodeId, depth]);
}


/**
 * Stable key for the fade-transition wrapper.
 *
 * Using ``scene?.id ?? "no-scene"`` directly as a React key is fine,
 * but this helper lets the player unify what counts as a "new
 * scene" for the purpose of triggering the fade — e.g. a status
 * change from pending → ready on the SAME node should NOT count
 * (still the same scene, just newly resolved), while a navigation
 * to a different node SHOULD.
 */
export function fadeKey(sceneId: string | undefined, assetUrl: string): string {
  // Scene id alone misses the edge case where the asset_url changes
  // (e.g. a regenerate-scene fired in the editor mid-play). Including
  // both means "fade when EITHER changes."
  return `${sceneId || "none"}::${assetUrl || "no-asset"}`;
}


/**
 * Use ``fadeKey`` + a short ``isFading`` window so React can
 * dispatch fade-out → swap → fade-in on scene change. The hook
 * surfaces an ``opacity`` value (0..1) the player applies to the
 * media wrapper's style.
 *
 * Implementation: when the key changes, drop opacity to 0 for a
 * frame, then ramp back to 1 after a brief microtask delay so the
 * CSS transition catches the change.
 */
export function useFadeOnSceneChange(key: string, durationMs: number = 280): {
  opacity: number;
  transitionMs: number;
} {
  const [phase, setPhase] = useState<"in" | "out">("in");
  // ``useMemo`` keeps the transition duration stable across renders
  // (and lets the caller hardcode the same value in their CSS for
  // maximum sync).
  const transitionMs = useMemo(() => durationMs, [durationMs]);

  useEffect(() => {
    setPhase("out");
    const t = window.setTimeout(() => setPhase("in"), 16); // one frame
    return () => window.clearTimeout(t);
  }, [key]);

  return {
    opacity: phase === "out" ? 0 : 1,
    transitionMs,
  };
}

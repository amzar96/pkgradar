import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import ELK from "elkjs/lib/elk-api.js";
import ElkWorker from "elkjs/lib/elk-worker.min.js?worker";
import { Maximize2, Network, SlidersHorizontal } from "lucide-react";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import GraphNode, { type GraphNodeData } from "../components/GraphNode";
import { EmptyState } from "../components/primitives";
import { HEALTH_COLOR } from "../lib/health";
import { prefersReducedMotion } from "../lib/theme";
import { useActiveProject, useApp } from "../store";
import type { PackageEdge, PackageNode, Project } from "../types";

const elk = new ELK({ workerFactory: () => new ElkWorker() });
const MAX_ELK_NODES = 300;
const NODE_W = 172;
const NODE_H = 58;

const nodeTypes = { pkg: GraphNode };

const LAYOUT_OPTIONS: Record<string, Record<string, string>> = {
  layered: {
    "elk.algorithm": "layered",
    "elk.direction": "DOWN",
    "elk.layered.spacing.nodeNodeBetweenLayers": "92",
    "elk.spacing.nodeNode": "28",
    "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
    "elk.edgeRouting": "ORTHOGONAL",
  },
};

function compactPositions(
  nodes: PackageNode[],
): Record<string, { x: number; y: number }> {
  const sorted = [...nodes].sort((a, b) => {
    if (a.group !== b.group) {
      if (a.group === "main") return -1;
      if (b.group === "main") return 1;
      return a.group.localeCompare(b.group);
    }
    return a.name.localeCompare(b.name);
  });
  const count = Math.max(sorted.length, 1);
  const cellW = NODE_W + 22;
  const cellH = NODE_H + 18;
  const rootGap = cellH + 64;
  const targetAspect = 1.35;
  let cols = Math.min(Math.max(count, 1), 4);
  let best = Number.POSITIVE_INFINITY;
  for (let candidate = 1; candidate <= Math.min(count, 14); candidate += 1) {
    const rows = Math.ceil(count / candidate);
    const width = candidate * cellW - 22;
    const height = rows * cellH - 18 + rootGap;
    const score = Math.abs(Math.log(width / height / targetAspect));
    if (score < best) {
      best = score;
      cols = candidate;
    }
  }
  const width = cols * cellW - 22;
  const out: Record<string, { x: number; y: number }> = {};
  sorted.forEach((node, index) => {
    const col = index % cols;
    const row = Math.floor(index / cols);
    out[node.id] = { x: col * cellW, y: row * cellH };
  });
  out["root"] = { x: width / 2 - NODE_W / 2, y: -rootGap };
  return out;
}

function radialPositions(
  nodes: PackageNode[],
  edges: PackageEdge[],
): Record<string, { x: number; y: number }> {
  const adjacency = new Map<string, string[]>();
  for (const edge of edges) {
    const list = adjacency.get(edge.source) ?? [];
    list.push(edge.target);
    adjacency.set(edge.source, list);
  }
  const children = new Map<string, string[]>();
  const seen = new Set(["root"]);
  const order = ["root"];
  for (let index = 0; index < order.length; index += 1) {
    const current = order[index];
    children.set(current, []);
    for (const child of adjacency.get(current) ?? []) {
      if (seen.has(child)) continue;
      seen.add(child);
      children.get(current)!.push(child);
      order.push(child);
    }
  }

  const leaves = new Map<string, number>();
  const countLeaves = (id: string): number => {
    const kids = children.get(id) ?? [];
    if (kids.length === 0) {
      leaves.set(id, 1);
      return 1;
    }
    let total = 0;
    for (const kid of kids) total += countLeaves(kid);
    leaves.set(id, total);
    return total;
  };
  countLeaves("root");

  const depthOf = new Map(nodes.map((node) => [node.id, node.depth]));
  const perDepth = new Map<number, number>();
  for (const id of order) {
    const depth = depthOf.get(id) ?? 2;
    perDepth.set(depth, (perDepth.get(depth) ?? 0) + 1);
  }
  const radii = new Map<number, number>();
  let previous = 0;
  const maxDepth = Math.max(0, ...perDepth.keys());
  for (let depth = 1; depth <= maxDepth; depth += 1) {
    const count = perDepth.get(depth) ?? 1;
    const needed = (count * (NODE_W + 26)) / (2 * Math.PI);
    const step = Math.max(330, Math.min(needed, 1150));
    previous += step;
    radii.set(depth, previous);
  }

  const positions = new Map<string, { x: number; y: number }>();
  const place = (id: string, start: number, end: number, depth: number) => {
    const radius = radii.get(depth) ?? 0;
    const angle = (start + end) / 2;
    positions.set(id, {
      x: Math.cos(angle) * radius - NODE_W / 2,
      y: Math.sin(angle) * radius - NODE_H / 2,
    });
    const kids = children.get(id) ?? [];
    const total = kids.reduce((sum, kid) => sum + (leaves.get(kid) ?? 1), 0) || 1;
    let cursor = start;
    for (const kid of kids) {
      const span = ((end - start) * (leaves.get(kid) ?? 1)) / total;
      place(kid, cursor, cursor + span, depth + 1);
      cursor += span;
    }
  };
  place("root", -Math.PI / 2, 1.5 * Math.PI, 0);
  return Object.fromEntries(positions);
}

function ancestors(project: Project, nodeId: string | null): Set<string> {
  if (!nodeId) return new Set();
  const incoming = new Map<string, PackageEdge[]>();
  for (const edge of project.edges) {
    const list = incoming.get(edge.target) ?? [];
    list.push(edge);
    incoming.set(edge.target, list);
  }
  const seen = new Set<string>([nodeId]);
  const queue = [nodeId];
  while (queue.length) {
    const current = queue.shift()!;
    if (current === "root") continue;
    for (const edge of incoming.get(current) ?? []) {
      if (!seen.has(edge.source)) {
        seen.add(edge.source);
        queue.push(edge.source);
      }
    }
  }
  return seen;
}

function TopologyInner() {
  const project = useActiveProject();
  const theme = useApp((state) => state.theme);
  const selectedNode = useApp((state) => state.selectedNode);
  const selectNode = useApp((state) => state.selectNode);
  const search = useApp((state) => state.search);
  const layoutKind = useApp((state) => state.layout);
  const setLayout = useApp((state) => state.setLayout);
  const depthLimit = useApp((state) => state.depthLimit);
  const setDepthLimit = useApp((state) => state.setDepthLimit);
  const group = useApp((state) => state.group);
  const setGroup = useApp((state) => state.setGroup);
  const onlyOutdated = useApp((state) => state.onlyOutdated);
  const onlyAdvisories = useApp((state) => state.onlyAdvisories);
  const toggleOutdated = useApp((state) => state.toggleOutdated);
  const toggleAdvisories = useApp((state) => state.toggleAdvisories);

  const { fitView } = useReactFlow();
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [layouting, setLayouting] = useState(false);
  const [layoutNote, setLayoutNote] = useState<string | null>(null);
  const nodeDataCache = useRef(new Map<string, GraphNodeData>());
  const deferredSearch = useDeferredValue(search);
  const reducedMotion = prefersReducedMotion();

  const nodesById = useMemo(
    () => new Map((project?.nodes ?? []).map((node) => [node.id, node])),
    [project],
  );

  const visibleIds = useMemo(() => {
    if (!project) return new Set<string>();
    const ids = new Set<string>(["root"]);
    for (const node of project.nodes) {
      if (depthLimit < 99 && node.depth > depthLimit) continue;
      if (group && node.group !== group) continue;
      if (onlyAdvisories && node.advisories.length === 0) continue;
      if (
        onlyOutdated &&
        !node.advisories.length &&
        (node.delta === "none" || node.delta === "unknown")
      )
        continue;
      ids.add(node.id);
    }
    return ids;
  }, [project, depthLimit, group, onlyAdvisories, onlyOutdated]);

  const visibleEdges = useMemo(() => {
    if (!project) return [];
    return project.edges.filter(
      (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target),
    );
  }, [project, visibleIds]);

  const fit = (padding: number, minZoom: number, maxZoom: number) => {
    fitView({
      padding,
      duration: reducedMotion || visibleIds.size > 150 ? 0 : 320,
      minZoom,
      maxZoom,
    });
  };

  const signature = useMemo(
    () => `${[...visibleIds].sort().join("|")}::${layoutKind}`,
    [visibleIds, layoutKind],
  );

  const effectiveLayout = useMemo(() => {
    if (layoutKind !== "auto") return layoutKind;
    return visibleIds.size > 26 ? "compact" : "radial";
  }, [layoutKind, visibleIds]);

  useEffect(() => {
    if (!project || visibleIds.size === 0) return;
    setLayoutNote(null);
    if (effectiveLayout === "radial") {
      const visible = [...visibleIds]
        .map((id) => nodesById.get(id))
        .filter((node): node is PackageNode => Boolean(node));
      setPositions(radialPositions(visible, visibleEdges));
      setLayouting(false);
      const timer = window.setTimeout(() => fit(0.1, 0.34, 1.05), 40);
      return () => window.clearTimeout(timer);
    }
    if (effectiveLayout === "compact") {
      const visible = [...visibleIds]
        .map((id) => nodesById.get(id))
        .filter((node): node is PackageNode => Boolean(node));
      setPositions(compactPositions(visible));
      setLayouting(false);
      const timer = window.setTimeout(() => fit(0.08, 0.18, 0.95), 40);
      return () => window.clearTimeout(timer);
    }
    // ELK is layout-heavy. Above the cap, use the cheap grid so filters and
    // selection stay responsive instead of freezing the browser.
    if (visibleIds.size > MAX_ELK_NODES) {
      const visible = [...visibleIds]
        .map((id) => nodesById.get(id))
        .filter((node): node is PackageNode => Boolean(node));
      setPositions(compactPositions(visible));
      setLayouting(false);
      setLayoutNote(`compact layout for ${visible.length} nodes`);
      const timer = window.setTimeout(() => fit(0.08, 0.16, 0.9), 40);
      return () => window.clearTimeout(timer);
    }
    let cancelled = false;
    setLayouting(true);
    const children = [...visibleIds].map((id) => ({
      id,
      width: NODE_W,
      height: NODE_H,
    }));
    const elkEdges = visibleEdges.map((edge) => ({
      id: edge.id,
      sources: [edge.source],
      targets: [edge.target],
    }));
    elk
      .layout({
        id: "root",
        layoutOptions: LAYOUT_OPTIONS[layoutKind] ?? LAYOUT_OPTIONS.layered,
        children,
        edges: elkEdges,
      } as never)
      .then((result: { children?: { id: string; x?: number; y?: number }[] }) => {
        if (cancelled) return;
        const map: Record<string, { x: number; y: number }> = {};
        for (const child of result.children ?? []) {
          map[child.id] = { x: child.x ?? 0, y: child.y ?? 0 };
        }
        setPositions(map);
        setLayouting(false);
        window.setTimeout(() => fit(0.12, 0.34, 0.95), 40);
      })
      .catch(() => {
        if (cancelled) return;
        const visible = [...visibleIds]
          .map((id) => nodesById.get(id))
          .filter((node): node is PackageNode => Boolean(node));
        setPositions(compactPositions(visible));
        setLayoutNote("worker unavailable — compact layout");
        setLayouting(false);
      });
    return () => {
      cancelled = true;
    };
  }, [signature, visibleEdges, project, visibleIds, layoutKind, effectiveLayout, nodesById, fitView]);

  const path = useMemo(
    () => (project ? ancestors(project, selectedNode) : new Set<string>()),
    [project, selectedNode],
  );

  const searchTerm = deferredSearch.trim().toLowerCase();
  const searching = searchTerm.length >= 2;

  const hiddenByDepth = useMemo(() => {
    if (!project || depthLimit >= 99) return 0;
    return project.nodes.filter((node) => !node.root && node.depth > depthLimit).length;
  }, [project, depthLimit]);

  const flowNodes = useMemo<Node[]>(() => {
    if (!project) return [];
    const result: Node[] = [];
    for (const id of visibleIds) {
      const pkg = nodesById.get(id);
      if (!pkg) continue;
      const highlighted = path.has(id);
      const dimmed = searching && !pkg.name.toLowerCase().includes(searchTerm);
      const cached = nodeDataCache.current.get(id);
      const data: GraphNodeData =
        cached && cached.pkg === pkg && cached.highlighted === highlighted && cached.dimmed === dimmed
          ? cached
          : { pkg, highlighted, dimmed };
      nodeDataCache.current.set(id, data);
      result.push({
        id,
        type: "pkg",
        position: positions[id] ?? { x: 0, y: 0 },
        data,
        draggable: false,
        selectable: true,
      });
    }
    return result;
  }, [project, visibleIds, nodesById, positions, path, searching, searchTerm]);

  const flowEdges = useMemo<Edge[]>(() => {
    return visibleEdges.map((edge) => {
      const onPath = path.has(edge.source) && path.has(edge.target);
      const dev = edge.kind === "dev";
      const optional = edge.kind === "optional";
      const inferred = edge.kind === "inferred";
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: effectiveLayout === "radial" ? "straight" : "smoothstep",
        style: {
          stroke: onPath
            ? "var(--color-accent)"
            : dev
              ? "var(--edge-dev)"
              : inferred
                ? "var(--edge-inferred)"
                : "var(--edge)",
          strokeWidth: onPath ? 1.8 : 1,
          strokeDasharray: dev || inferred ? "3 3" : undefined,
          opacity: searching ? 0.25 : 1,
        },
        animated: false,
      };
    });
  }, [visibleEdges, path, searching, effectiveLayout]);

  if (!project) {
    return (
      <div className="p-6">
        <EmptyState
          title="No project selected"
          detail="Pick a project in the sidebar, or run a scan."
          icon={<Network size={28} />}
        />
      </div>
    );
  }

  const groups = Array.from(new Set(project.nodes.map((node) => node.group)));

  return (
    <div className="flex h-full w-full flex-col">
      <div className="border-b border-line bg-panel">
        <div className="flex flex-wrap items-center gap-2 px-3 py-2">
          <div className="mr-1 flex items-center gap-1.5">
            <SlidersHorizontal size={12} className="text-dim" />
            <span className="max-w-[180px] truncate font-mono text-[10.5px] text-fg">
              {project.id === "." ? project.name : project.id}
            </span>
          </div>

          <div className="flex overflow-hidden rounded border border-line">
            {(["auto", "radial", "compact", "layered"] as const).map((kind) => (
              <button
                key={kind}
                onClick={() => setLayout(kind)}
                className={`px-2 py-1 text-[10px] transition-colors ${
                  layoutKind === kind
                    ? "bg-accent/15 text-accent"
                    : "text-dim hover:bg-panel2 hover:text-muted"
                }`}
              >
                {kind}
              </button>
            ))}
          </div>

          <label className="flex items-center gap-1.5 text-[10px] text-dim">
            depth
            <select
              aria-label="Dependency depth"
              value={depthLimit}
              onChange={(event) => setDepthLimit(Number(event.target.value))}
              className="rounded border border-line bg-panel2 px-1 py-1 font-mono text-[10px] text-muted outline-none"
            >
              <option value={1}>1</option>
              <option value={2}>2</option>
              <option value={3}>3</option>
              <option value={4}>4</option>
              <option value={6}>6</option>
              <option value={99}>all</option>
            </select>
          </label>

          <label className="flex items-center gap-1.5 text-[10px] text-dim">
            group
            <select
              aria-label="Dependency group"
              value={group ?? ""}
              onChange={(event) => setGroup(event.target.value || null)}
              className="rounded border border-line bg-panel2 px-1 py-1 font-mono text-[10px] text-muted outline-none"
            >
              <option value="">all</option>
              {groups.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>

          <button
            onClick={toggleOutdated}
            className={`rounded border px-2 py-1 text-[10px] transition-colors ${
              onlyOutdated
                ? "border-minor/40 bg-minor/10 text-minor"
                : "border-line text-dim hover:text-muted"
            }`}
          >
            outdated
          </button>
          <button
            onClick={toggleAdvisories}
            className={`rounded border px-2 py-1 text-[10px] transition-colors ${
              onlyAdvisories
                ? "border-cve/40 bg-cve/10 text-cve"
                : "border-line text-dim hover:text-muted"
            }`}
          >
            advisories
          </button>

          <button
            onClick={() => fit(0.12, 0.3, 1)}
            className="rounded border border-line p-1 text-dim transition-colors hover:text-fg"
            title="Fit view"
            aria-label="Fit graph to view"
          >
            <Maximize2 size={11} />
          </button>

          {hiddenByDepth > 0 ? (
            <button
              onClick={() => setDepthLimit(99)}
              title="Expand every package at every depth"
              className="ml-auto rounded border border-accent/30 bg-accent/10 px-2 py-1 font-mono text-[9.5px] text-accent transition-colors hover:bg-accent/20"
            >
              +{hiddenByDepth} hidden
            </button>
          ) : null}

          <span className={`font-mono text-[9.5px] text-dim ${hiddenByDepth > 0 ? "" : "ml-auto"}`}>
            {flowNodes.length} nodes · {flowEdges.length} edges
          </span>
        </div>
      </div>

      {project.venv.broken ? (
        <div className="border-b border-major/30 bg-major/10 px-3 py-1 text-[10px] text-major">
          broken venv — no interpreter at {project.venv.path}
        </div>
      ) : null}

      <div className="dot-grid relative min-h-0 flex-1">
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={nodeTypes}
          onNodeClick={(_, node) => selectNode(node.id)}
          onPaneClick={() => selectNode(null)}
          minZoom={0.12}
          maxZoom={2}
          fitView
          proOptions={{ hideAttribution: true }}
          nodesConnectable={false}
          nodesDraggable={false}
          onlyRenderVisibleElements
          elevateEdgesOnSelect
          colorMode={theme}
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={22}
            size={1}
            color="var(--grid-dot)"
          />
          <Controls showInteractive={false} position="bottom-right" />
        </ReactFlow>

        <div className="pointer-events-none absolute bottom-3 left-3 rounded-md border border-line bg-panel/90 px-2.5 py-1.5">
        <div className="flex items-center gap-3 text-[9px] text-dim">
          {(["ok", "patch", "minor", "major", "cve"] as const).map((state) => (
            <span key={state} className="flex items-center gap-1">
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: HEALTH_COLOR[state] }}
              />
              {state}
            </span>
          ))}
          <span className="text-line2">·</span>
          <span>solid = runtime</span>
          <span>dashed = dev/optional</span>
        </div>
      </div>

      {layouting ? (
        <div className="absolute top-3 right-3 rounded border border-line bg-panel px-2 py-1 font-mono text-[9.5px] text-dim">
          laying out…
        </div>
      ) : layoutNote ? (
        <div className="absolute top-3 right-3 rounded border border-line bg-panel px-2 py-1 font-mono text-[9.5px] text-dim">
          {layoutNote}
        </div>
      ) : null}
      </div>
    </div>
  );
}

export default function Topology() {
  return (
    <ReactFlowProvider>
      <TopologyInner />
    </ReactFlowProvider>
  );
}

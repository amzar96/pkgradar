import { ArrowDown, ArrowUp, PackageSearch, Search } from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";

import { DeltaBadge, EmptyState, HealthDot, Pill } from "../components/primitives";
import { HEALTH_COLOR, health, humanAge } from "../lib/health";
import { useActiveProject, useApp } from "../store";
import type { PackageNode } from "../types";

type SortKey = "name" | "version" | "delta" | "risk" | "advisories" | "dependents" | "depth";

const DELTA_RANK: Record<string, number> = {
  major: 5,
  minor: 4,
  patch: 3,
  other: 2,
  unknown: 1,
  none: 0,
};

function compareVersions(a: string, b: string): number {
  const split = (value: string) =>
    value.split(/[.+-]/).map((part) => {
      const number = Number.parseInt(part, 10);
      return Number.isNaN(number) ? 0 : number;
    });
  const left = split(a);
  const right = split(b);
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    const diff = (left[index] ?? 0) - (right[index] ?? 0);
    if (diff !== 0) return diff;
  }
  return a.localeCompare(b);
}

export default function Packages() {
  const project = useActiveProject();
  const selectedNode = useApp((state) => state.selectedNode);
  const selectNode = useApp((state) => state.selectNode);

  const [term, setTerm] = useState("");
  const [sort, setSort] = useState<SortKey>("risk");
  const [asc, setAsc] = useState(false);
  const [onlyOutdated, setOnlyOutdated] = useState(false);
  const [onlyDirect, setOnlyDirect] = useState(false);
  const [limit, setLimit] = useState(80);
  const deferredTerm = useDeferredValue(term);

  const rows = useMemo(() => {
    if (!project) return [];
    const needle = deferredTerm.trim().toLowerCase();
    const filtered = project.nodes.filter((node) => {
      if (node.root) return false;
      if (needle && !node.name.includes(needle) && !(node.latest ?? "").includes(needle))
        return false;
      if (onlyOutdated && (node.delta === "none" || node.delta === "unknown")) return false;
      if (onlyDirect && !node.direct) return false;
      return true;
    });
    const direction = asc ? 1 : -1;
    return filtered.sort((a, b) => {
      switch (sort) {
        case "name":
          return a.name.localeCompare(b.name) * direction;
        case "version":
          return compareVersions(a.version, b.version) * direction;
        case "delta":
          return ((DELTA_RANK[a.delta] ?? 0) - (DELTA_RANK[b.delta] ?? 0)) * direction;
        case "advisories":
          return (a.advisories.length - b.advisories.length) * direction;
        case "dependents":
          return (a.dependents - b.dependents) * direction;
        case "depth":
          return (a.depth - b.depth) * direction;
        default:
          return (a.risk - b.risk) * direction;
      }
    });
  }, [project, deferredTerm, sort, asc, onlyOutdated, onlyDirect]);

  if (!project) {
    return (
      <div className="p-6">
        <EmptyState title="No project selected" icon={<PackageSearch size={28} />} />
      </div>
    );
  }

  const header = (key: SortKey, label: string, className = "") => (
    <button
      onClick={() => {
        if (sort === key) setAsc(!asc);
        else {
          setSort(key);
          setAsc(key === "name");
        }
      }}
      className={`flex items-center gap-1 text-left text-[9px] font-medium tracking-[0.14em] uppercase transition-colors hover:text-fg ${
        sort === key ? "text-fg" : "text-dim"
      } ${className}`}
    >
      {label}
      {sort === key ? (
        asc ? (
          <ArrowUp size={9} />
        ) : (
          <ArrowDown size={9} />
        )
      ) : null}
    </button>
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
        <div>
          <div className="text-[13px] font-medium text-fg">{project.name}</div>
          <div className="font-mono text-[9.5px] text-dim">
            {project.stats.packages} packages · {project.stats.outdated} outdated ·{" "}
            {project.stats.advisories} advisories
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <div className="flex items-center gap-1.5 rounded-md border border-line bg-panel px-2 py-1.5">
            <Search size={12} className="text-dim" />
            <input
              aria-label="Filter packages"
              value={term}
              onChange={(event) => setTerm(event.target.value)}
              placeholder="filter packages"
              className="w-[180px] bg-transparent text-[11px] text-fg placeholder:text-dim focus:outline-none"
            />
          </div>
          <button
            onClick={() => setOnlyOutdated(!onlyOutdated)}
            className={`rounded border px-2 py-1.5 text-[10px] transition-colors ${
              onlyOutdated
                ? "border-minor/40 bg-minor/10 text-minor"
                : "border-line text-dim hover:text-muted"
            }`}
          >
            outdated
          </button>
          <button
            onClick={() => setOnlyDirect(!onlyDirect)}
            className={`rounded border px-2 py-1.5 text-[10px] transition-colors ${
              onlyDirect
                ? "border-accent/40 bg-accent/10 text-accent"
                : "border-line text-dim hover:text-muted"
            }`}
          >
            direct only
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse text-left">
          <thead className="sticky top-0 z-10 bg-table-head">
            <tr className="border-b border-line">
              <th className="py-2 pr-3 pl-5">{header("name", "package")}</th>
              <th className="px-3 py-2">{header("version", "locked")}</th>
              <th className="px-3 py-2 text-[9px] tracking-[0.14em] text-dim uppercase">latest</th>
              <th className="px-3 py-2">{header("delta", "delta")}</th>
              <th className="px-3 py-2">{header("advisories", "cve")}</th>
              <th className="px-3 py-2">{header("risk", "risk")}</th>
              <th className="px-3 py-2">{header("dependents", "used by")}</th>
              <th className="px-3 py-2 text-[9px] tracking-[0.14em] text-dim uppercase">installed</th>
              <th className="px-3 py-2">{header("depth", "depth")}</th>
              <th className="py-2 pr-5 pl-3 text-[9px] tracking-[0.14em] text-dim uppercase">group</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, limit).map((node) => (
              <Row
                key={node.id}
                node={node}
                active={selectedNode === node.id}
                onClick={() => selectNode(node.id)}
              />
            ))}
          </tbody>
        </table>
        {rows.length === 0 ? (
          <div className="p-6">
            <EmptyState title="No packages match" detail="Try clearing the filters." />
          </div>
        ) : null}
        {rows.length > limit ? (
          <div className="flex justify-center py-4">
            <button
              onClick={() => setLimit(limit + 200)}
              className="rounded border border-line px-3 py-1.5 text-[10px] text-muted hover:text-fg"
            >
              show more ({rows.length - limit} remaining)
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Row({
  node,
  active,
  onClick,
}: {
  node: PackageNode;
  active: boolean;
  onClick: () => void;
}) {
  const state = health(node);
  const color = HEALTH_COLOR[state];
  return (
    <tr
      onClick={onClick}
      className={`group cursor-pointer border-b border-line/50 transition-colors hover:bg-panel2/60 ${
        active ? "bg-panel2" : ""
      }`}
    >
      <td className="py-1.5 pr-3 pl-5">
        <div className="flex items-center gap-2">
          <HealthDot health={state} size={6} />
          <span className="max-w-[220px] truncate font-mono text-[11px] text-fg">{node.name}</span>
          {node.direct ? <Pill color="var(--color-accent)">direct</Pill> : null}
          {node.yanked ? <Pill color="var(--color-major)">yanked</Pill> : null}
          {node.index && node.index !== "PyPI" ? (
            <Pill color="var(--color-accent)" className="max-w-[120px] truncate">
              {node.index}
            </Pill>
          ) : null}
        </div>
      </td>
      <td className="px-3 py-1.5 font-mono text-[10.5px] text-muted">{node.version || "?"}</td>
      <td className="px-3 py-1.5 font-mono text-[10.5px]">
        {node.latest && node.latest !== node.version ? (
          <span style={{ color }}>{node.latest}</span>
        ) : (
          <span className="text-dim">—</span>
        )}
        {node.latest_upload ? (
          <span className="ml-1.5 text-[9.5px] text-dim">{humanAge(node.latest_upload)}</span>
        ) : null}
      </td>
      <td className="px-3 py-1.5">
        <DeltaBadge node={node} compact />
        {node.breaking ? <span className="ml-1 text-[9px] text-major">!</span> : null}
      </td>
      <td className="px-3 py-1.5">
        {node.advisories.length ? (
          <span className="font-mono text-[10px] text-cve">{node.advisories.length}</span>
        ) : (
          <span className="text-[10px] text-dim">—</span>
        )}
      </td>
      <td className="px-3 py-1.5">
        <div className="flex items-center gap-1.5">
          <div className="h-1 w-12 overflow-hidden rounded-full bg-line">
            <div
              className="h-full rounded-full"
              style={{ width: `${Math.round(node.risk * 100)}%`, background: color }}
            />
          </div>
          <span className="font-mono text-[9px] text-dim">{node.risk.toFixed(2)}</span>
        </div>
      </td>
      <td className="px-3 py-1.5 font-mono text-[10px] text-muted">{node.dependents}</td>
      <td className="px-3 py-1.5 font-mono text-[10px]">
        {node.installed_version ? (
          <span
            className={
              node.drift === "version" ? "text-minor" : "text-dim"
            }
          >
            {node.installed_version}
            {node.drift === "version" ? " ≠" : ""}
          </span>
        ) : node.drift === "missing" ? (
          <span className="text-major/70">missing</span>
        ) : (
          <span className="text-dim">—</span>
        )}
      </td>
      <td className="px-3 py-1.5 font-mono text-[10px] text-dim">{node.depth}</td>
      <td className="py-1.5 pr-5 pl-3">
        <span className="rounded bg-line px-1.5 py-px font-mono text-[9px] text-dim">
          {node.group}
        </span>
      </td>
    </tr>
  );
}

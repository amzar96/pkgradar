import {
  ArrowUpRight,
  CircleAlert,
  ExternalLink,
  GitBranch,
  Package,
  ShieldAlert,
  X,
} from "lucide-react";
import { useMemo } from "react";

import {
  HEALTH_COLOR,
  HEALTH_LABEL,
  formatDate,
  health,
  humanAge,
  severityColor,
} from "../lib/health";
import { useActiveProject, useApp } from "../store";
import type { PackageEdge, PackageNode, Project } from "../types";
import { CopyButton, DeltaBadge, HealthDot, Pill } from "./primitives";

function pathToRoot(project: Project, nodeId: string): PackageNode[] {
  const byId = new Map(project.nodes.map((node) => [node.id, node]));
  const outgoing = new Map<string, PackageEdge[]>();
  for (const edge of project.edges) {
    const list = outgoing.get(edge.source) ?? [];
    list.push(edge);
    outgoing.set(edge.source, list);
  }
  // Walk from the root so `parent` points towards the root; walking backwards
  // from the node only records predecessors and produces a one-node chain.
  const parent = new Map<string, string | null>([["root", null]]);
  const queue = ["root"];
  while (queue.length) {
    const current = queue.shift()!;
    if (current === nodeId) break;
    for (const edge of outgoing.get(current) ?? []) {
      if (!parent.has(edge.target)) {
        parent.set(edge.target, current);
        queue.push(edge.target);
      }
    }
  }
  if (!parent.has(nodeId)) return [];
  const chain: PackageNode[] = [];
  let cursor: string | null = nodeId;
  while (cursor) {
    const node = byId.get(cursor);
    if (node) chain.push(node);
    cursor = parent.get(cursor) ?? null;
  }
  return chain.reverse();
}

function advisoryHref(url: string | null | undefined): string {
  if (!url) return "#";
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : "#";
  } catch {
    return "#";
  }
}

export default function Inspector() {
  const project = useActiveProject();
  const selectedNode = useApp((state) => state.selectedNode);
  const closeInspector = useApp((state) => state.closeInspector);

  const node = useMemo(
    () => project?.nodes.find((item) => item.id === selectedNode) ?? null,
    [project, selectedNode],
  );
  const incoming = useMemo(
    () => (project && node ? project.edges.filter((edge) => edge.target === node.id) : []),
    [project, node],
  );
  const chain = useMemo(
    () => (project && node ? pathToRoot(project, node.id) : []),
    [project, node],
  );

  if (!project || !node) return null;

  const state = health(node);
  const color = HEALTH_COLOR[state];
  const upgradeVersion = node.fixed_in || node.latest;
  const upgradeCommand =
    upgradeVersion && upgradeVersion !== node.version
      ? `uv add "${node.name}>=${upgradeVersion}"`
      : null;

  return (
    <aside className="slide-in flex w-[382px] shrink-0 flex-col border-l border-line bg-[#0a0d12]">
      <div className="flex items-start justify-between border-b border-line px-4 py-3.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <HealthDot health={state} size={9} />
            <span className="truncate font-mono text-[13px] font-semibold text-fg">{node.name}</span>
          </div>
          <div className="mt-1 flex items-center gap-1.5">
            <span className="font-mono text-[11px] text-muted">{node.version || "?"}</span>
            {node.latest && node.latest !== node.version ? (
              <>
                <ArrowUpRight size={11} className="text-dim" />
                <span className="font-mono text-[11px]" style={{ color }}>
                  {node.latest}
                </span>
              </>
            ) : null}
            <DeltaBadge node={node} />
            <span className="text-[10px] text-dim">{HEALTH_LABEL[state]}</span>
          </div>
        </div>
        <button
          onClick={closeInspector}
          className="rounded p-1 text-dim transition hover:bg-panel2 hover:text-fg"
        >
          <X size={14} />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {upgradeCommand ? (
          <Section title="Upgrade">
            <div className="flex items-center justify-between gap-2 rounded-md border border-line bg-panel px-2.5 py-2">
              <code className="truncate font-mono text-[10.5px] text-accent">{upgradeCommand}</code>
              <CopyButton value={upgradeCommand} label="" />
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-dim">
              {node.releases_behind !== null ? (
                <Pill color="#8b98a9">{node.releases_behind} releases newer</Pill>
              ) : null}
              {node.latest_upload ? <Pill>{humanAge(node.latest_upload)}</Pill> : null}
              {node.breaking ? <Pill color="#f87171">breaking change</Pill> : null}
              {node.yanked ? <Pill color="#f87171">yanked</Pill> : null}
            </div>
          </Section>
        ) : null}

        {node.risk_factors.length ? (
          <Section title="Risk">
            <div className="flex items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${Math.round(node.risk * 100)}%`, background: color }}
                />
              </div>
              <span className="font-mono text-[10px] text-muted">{node.risk.toFixed(2)}</span>
            </div>
            <div className="mt-2 space-y-1">
              {node.risk_factors.map((factor, index) => (
                <div key={index} className="flex items-start gap-2 text-[10.5px]">
                  <span className="mt-[5px] h-1 w-1 shrink-0 rounded-full bg-dim" />
                  <span className="flex-1 text-muted">{factor.label}</span>
                  <span className="font-mono text-dim">+{factor.weight.toFixed(2)}</span>
                </div>
              ))}
            </div>
          </Section>
        ) : null}

        {node.advisories.length ? (
          <Section
            title={`Advisories · ${node.advisories.length}`}
            icon={<ShieldAlert size={11} className="text-cve" />}
          >
            <div className="space-y-1.5">
              {node.advisories.slice(0, 25).map((advisory) => (
                <a
                  key={advisory.id}
                  href={advisoryHref(advisory.url)}
                  onClick={(event) => {
                    if (advisoryHref(advisory.url) === "#") event.preventDefault();
                  }}
                  target="_blank"
                  rel="noreferrer"
                  className="block rounded-md border border-line bg-panel px-2.5 py-2 transition hover:border-line2"
                >
                  <div className="flex items-center gap-1.5">
                    <span
                      className="rounded px-1 font-mono text-[8.5px] tracking-wide"
                      style={{
                        color: severityColor(advisory.severity),
                        border: `1px solid ${severityColor(advisory.severity)}44`,
                        background: `${severityColor(advisory.severity)}12`,
                      }}
                    >
                      {(advisory.severity || "UNKNOWN").toUpperCase()}
                    </span>
                    <span className="truncate font-mono text-[9.5px] text-dim">
                      {advisory.aliases.find((alias) => alias.startsWith("CVE")) || advisory.id}
                    </span>
                    <ExternalLink size={9} className="ml-auto shrink-0 text-dim" />
                  </div>
                  <div className="mt-1 line-clamp-2 text-[10.5px] leading-snug text-muted">
                    {advisory.summary}
                  </div>
                  {advisory.fixed.length ? (
                    <div className="mt-1 font-mono text-[9px] text-dim">
                      fixed in {advisory.fixed[0]}
                    </div>
                  ) : null}
                </a>
              ))}
              {node.advisories.length > 25 ? (
                <div className="text-[10px] text-dim">
                  +{node.advisories.length - 25} more advisories
                </div>
              ) : null}
            </div>
          </Section>
        ) : null}

        {chain.length > 1 ? (
          <Section title="Path to root" icon={<GitBranch size={11} className="text-dim" />}>
            <div className="space-y-0.5">
              {chain.map((item, index) => (
                <div key={item.id} className="flex items-center gap-1.5">
                  <span className="w-3 text-right font-mono text-[9px] text-dim">{index}</span>
                  <span
                    className={`truncate rounded px-1.5 py-0.5 font-mono text-[10px] ${
                      item.id === node.id
                        ? "bg-accent/10 text-accent"
                        : "text-muted"
                    }`}
                  >
                    {item.name}
                  </span>
                  {index < chain.length - 1 ? (
                    <span className="text-[9px] text-dim">→</span>
                  ) : null}
                </div>
              ))}
            </div>
          </Section>
        ) : null}

        <Section title={`Required by · ${incoming.length}`} icon={<Package size={11} className="text-dim" />}>
          {incoming.length === 0 ? (
            <div className="text-[10.5px] text-dim">No incoming edges recorded.</div>
          ) : (
            <div className="space-y-1">
              {incoming.slice(0, 30).map((edge) => {
                const parent = project.nodes.find((item) => item.id === edge.source);
                return (
                  <div
                    key={edge.id}
                    className="flex items-center gap-2 rounded border border-line/70 px-2 py-1"
                  >
                    <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-muted">
                      {parent?.name ?? edge.source}
                    </span>
                    <Pill color={edge.kind === "dev" ? "#a78bfa" : edge.kind === "optional" ? "#fbbf24" : "#8b98a9"}>
                      {edge.kind}
                    </Pill>
                    <span className="font-mono text-[9.5px] text-dim">{edge.spec || "resolved"}</span>
                  </div>
                );
              })}
            </div>
          )}
        </Section>

        <Section title="Environment">
          <Row
            label="Installed"
            value={
              node.installed_version ??
              (node.drift === "missing" ? "missing from venv" : "not scanned")
            }
            mono
          />
          <Row
            label="Locked"
            value={node.version}
            mono
          />
          <Row
            label="Drift"
            value={node.drift ? node.drift : "unknown"}
            colour={
              node.drift === "version"
                ? "#fbbf24"
                : node.drift === "missing"
                  ? "#f87171"
                  : "#8b98a9"
            }
          />
          <Row label="Group" value={node.group} />
          <Row label="Depth" value={String(node.depth)} />
          <Row label="Dependents" value={String(node.dependents)} />
          <Row label="Source" value={node.source} />
          <Row label="License" value={node.license || "—"} />
          <Row label="Latest release" value={formatDate(node.latest_upload)} />
          {node.deprecated ? <Row label="Upstream" value="inactive" colour="#fbbf24" /> : null}
        </Section>

        {node.summary ? (
          <Section title="About">
            <p className="text-[10.5px] leading-relaxed text-muted">{node.summary}</p>
          </Section>
        ) : null}

        {node.marker ? (
          <Section title="Marker">
            <code className="block break-all rounded border border-line bg-panel px-2 py-1.5 font-mono text-[9.5px] text-dim">
              {node.marker}
            </code>
          </Section>
        ) : null}

        <div className="px-4 py-3 text-[9.5px] leading-relaxed text-dim">
          <CircleAlert size={10} className="mr-1 inline" />
          Read-only view. pkgradar never runs a mutating uv command.
        </div>
      </div>
    </aside>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="border-b border-line/70 px-4 py-3.5">
      <div className="mb-2 flex items-center gap-1.5">
        {icon}
        <span className="text-[9px] font-medium tracking-[0.14em] text-dim uppercase">{title}</span>
      </div>
      {children}
    </div>
  );
}

function Row({
  label,
  value,
  mono,
  colour,
}: {
  label: string;
  value: string;
  mono?: boolean;
  colour?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-0.5">
      <span className="text-[10px] text-dim">{label}</span>
      <span
        className={`truncate text-[10.5px] ${mono ? "font-mono" : ""}`}
        style={{ color: colour ?? "#b6c2d1" }}
        title={value}
      >
        {value}
      </span>
    </div>
  );
}

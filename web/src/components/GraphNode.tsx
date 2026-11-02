import { Handle, Position, type NodeProps } from "@xyflow/react";
import { memo } from "react";

import { HEALTH_COLOR, alpha, health } from "../lib/health";
import type { PackageNode } from "../types";
import { DeltaBadge } from "./primitives";

export interface GraphNodeData extends Record<string, unknown> {
  pkg: PackageNode;
  highlighted: boolean;
  dimmed: boolean;
}

function GraphNodeView({ data, selected }: NodeProps) {
  const { pkg, highlighted, dimmed } = data as GraphNodeData;
  const state = health(pkg);
  const color = HEALTH_COLOR[state];
  const advisories = pkg.advisories.length;

  return (
    <div
      style={{
        borderColor: selected || highlighted ? alpha(color, 67) : undefined,
        boxShadow: selected
          ? `0 0 0 1px ${alpha(color, 40)}, var(--shadow)`
          : highlighted
            ? `0 0 0 1px ${alpha(color, 27)}`
            : undefined,
        opacity: dimmed ? 0.28 : 1,
        background: pkg.root
          ? "linear-gradient(180deg, var(--root-from), var(--root-to))"
          : undefined,
      }}
      className={`relative flex h-[58px] w-[172px] flex-col justify-center overflow-hidden rounded-lg border px-2.5 py-1.5 transition-[border-color,box-shadow,opacity,background-color] duration-150 ${
        pkg.root ? "border-accent/40" : "border-line bg-panel hover:border-line2"
      }`}
    >
      <span
        className="absolute top-0 bottom-0 left-0 w-[2px]"
        style={{
          background: pkg.root ? "var(--color-accent)" : color,
          opacity: pkg.root ? 0.9 : 0.75,
        }}
      />
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-1.5">
        <span className="min-w-0 flex-1 truncate text-[11.5px] font-medium tracking-tight text-fg">
          {pkg.name}
        </span>
        {advisories > 0 ? (
          <span
            className="rounded px-1 font-mono text-[9px] leading-4"
            style={{
              color: "var(--color-cve)",
              background: alpha("var(--color-cve)", 10),
              border: `1px solid ${alpha("var(--color-cve)", 25)}`,
            }}
            title={`${advisories} advisories`}
          >
            {advisories} CVE
          </span>
        ) : (
          <DeltaBadge node={pkg} compact />
        )}
      </div>
      <div className="mt-0.5 flex items-center gap-1.5 font-mono text-[10px]">
        <span className="text-muted">{pkg.version || "?"}</span>
        {pkg.latest && pkg.latest !== pkg.version ? (
          <>
            <span className="text-dim">→</span>
            <span style={{ color }}>{pkg.latest}</span>
          </>
        ) : null}
        {pkg.extras.length ? (
          <span className="truncate text-dim">[{pkg.extras.join(",")}]</span>
        ) : null}
      </div>
      <div className="mt-0.5 flex items-center gap-1.5">
        <span className="text-[9px] text-dim">
          {pkg.root
            ? "project root"
            : pkg.direct
              ? "direct"
              : `${pkg.dependents} dependent${pkg.dependents === 1 ? "" : "s"}`}
        </span>
        {pkg.group !== "main" && !pkg.root ? (
          <span className="rounded bg-line px-1 text-[9px] text-dim">{pkg.group}</span>
        ) : null}
        {pkg.drift === "missing" ? (
          <span className="text-[9px] text-dim">not installed</span>
        ) : pkg.drift === "version" ? (
          <span className="text-[9px] text-minor">drift</span>
        ) : null}
        {pkg.yanked ? <span className="text-[9px] text-major">yanked</span> : null}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

export default memo(GraphNodeView);

import { Check, Copy } from "lucide-react";
import { useState, type ReactNode } from "react";

import { HEALTH_COLOR, HEALTH_LABEL, deltaLabel, type Health } from "../lib/health";
import type { PackageNode } from "../types";

export function HealthDot({ health, size = 8 }: { health: Health; size?: number }) {
  return (
    <span
      title={HEALTH_LABEL[health]}
      style={{
        width: size,
        height: size,
        background: HEALTH_COLOR[health],
        boxShadow: `0 0 10px ${HEALTH_COLOR[health]}55`,
      }}
      className="inline-block shrink-0 rounded-full"
    />
  );
}

export function DeltaBadge({ node, compact = false }: { node: PackageNode; compact?: boolean }) {
  const health = node.advisories.length
    ? "cve"
    : node.delta === "major" || node.breaking
      ? "major"
      : node.delta === "minor"
        ? "minor"
        : node.delta === "patch" || node.delta === "other"
          ? "patch"
          : "ok";
  const color = HEALTH_COLOR[health];
  if (node.delta === "none") return null;
  if (node.delta === "unknown" && !node.latest) return null;
  return (
    <span
      className="rounded border px-1.5 py-px font-mono text-[10px] leading-4 tracking-tight whitespace-nowrap"
      style={{ color, borderColor: `${color}44`, background: `${color}12` }}
    >
      {compact ? deltaLabel(node) : `${node.delta === "unknown" ? "?" : deltaLabel(node)}`}
      {node.breaking && !compact ? "!" : ""}
    </span>
  );
}

export function Pill({
  children,
  color = "#8b98a9",
  className = "",
  title,
}: {
  children: ReactNode;
  color?: string;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`rounded border px-1.5 py-px font-mono text-[10px] leading-4 whitespace-nowrap ${className}`}
      style={{ color, borderColor: `${color}3d`, background: `${color}10` }}
    >
      {children}
    </span>
  );
}

export function CopyButton({ value, label = "copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="inline-flex items-center gap-1 rounded border border-line bg-panel2 px-2 py-1 font-mono text-[10px] text-muted transition hover:border-line2 hover:text-fg"
      onClick={(event) => {
        event.stopPropagation();
        navigator.clipboard.writeText(value).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1200);
        });
      }}
      title={value}
    >
      {copied ? <Check size={11} className="text-good" /> : <Copy size={11} />}
      {copied ? "copied" : label}
    </button>
  );
}

export function StatTile({
  label,
  value,
  hint,
  color = "#e7edf4",
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  color?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="relative overflow-hidden rounded-lg border border-line bg-panel px-4 py-3">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-medium tracking-[0.14em] text-dim uppercase">{label}</span>
        <span style={{ color }} className="opacity-70">
          {icon}
        </span>
      </div>
      <div className="mt-1.5 font-mono text-2xl leading-none font-semibold" style={{ color }}>
        {value}
      </div>
      {hint ? <div className="mt-1 text-[11px] text-dim">{hint}</div> : null}
    </div>
  );
}

export function Meter({
  segments,
  height = 6,
}: {
  segments: { value: number; color: string }[];
  height?: number;
}) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0) || 1;
  return (
    <div className="flex w-full overflow-hidden rounded-full bg-line" style={{ height }}>
      {segments.map((segment, index) =>
        segment.value > 0 ? (
          <div
            key={index}
            style={{
              width: `${(segment.value / total) * 100}%`,
              background: segment.color,
            }}
          />
        ) : null,
      )}
    </div>
  );
}

export function EmptyState({
  title,
  detail,
  icon,
}: {
  title: string;
  detail?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-line px-6 py-16 text-center">
      <div className="mb-3 text-dim">{icon}</div>
      <div className="text-sm font-medium text-fg">{title}</div>
      {detail ? <div className="mt-1 max-w-md text-xs leading-relaxed text-dim">{detail}</div> : null}
    </div>
  );
}

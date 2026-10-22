import type { PackageNode } from "../types";

export type Health = "ok" | "patch" | "minor" | "major" | "cve" | "unknown";

export function health(node: PackageNode): Health {
  if (node.root) return "ok";
  if (node.advisories.length > 0) return "cve";
  if (node.drift === "missing") return "unknown";
  if (!node.available) return "unknown";
  if (node.delta === "major" || node.breaking) return "major";
  if (node.delta === "minor") return "minor";
  if (node.delta === "patch" || node.delta === "other") return "patch";
  if (node.delta === "none") return "ok";
  return "unknown";
}

export const HEALTH_COLOR: Record<Health, string> = {
  ok: "#34d399",
  patch: "#a3e635",
  minor: "#fbbf24",
  major: "#f87171",
  cve: "#e879f9",
  unknown: "#64748b",
};

export const HEALTH_LABEL: Record<Health, string> = {
  ok: "Up to date",
  patch: "Patch behind",
  minor: "Minor behind",
  major: "Major / breaking",
  cve: "Advisories",
  unknown: "Unknown",
};

export function deltaLabel(node: PackageNode): string {
  if (node.delta === "major") return "major";
  if (node.breaking) return "breaking";
  if (node.delta === "minor") return "minor";
  if (node.delta === "patch") return "patch";
  if (node.delta === "other") return "other";
  if (node.delta === "none") return "latest";
  return "?";
}

export function pct(value: number, total: number): number {
  if (!total) return 0;
  return Math.round((value / total) * 100);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function ageDays(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return Math.max(0, Math.round((Date.now() - date.getTime()) / 86_400_000));
}

export function humanAge(iso: string | null | undefined): string {
  const days = ageDays(iso);
  if (days === null) return "—";
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.round(days / 30)}mo ago`;
  const years = Math.floor(days / 365);
  const months = Math.round((days % 365) / 30);
  return months ? `${years}y ${months}mo ago` : `${years}y ago`;
}

export function shortNumber(value: number): string {
  if (value < 1000) return String(value);
  return `${(value / 1000).toFixed(1)}k`;
}

export function severityColor(severity: string | null | undefined): string {
  switch ((severity || "").toUpperCase()) {
    case "CRITICAL":
      return "#f43f5e";
    case "HIGH":
      return "#fb7185";
    case "MODERATE":
    case "MEDIUM":
      return "#fbbf24";
    case "LOW":
      return "#60a5fa";
    default:
      return "#94a3b8";
  }
}

export function projectHealth(project: {
  stats: { packages: number; major: number; outdated: number; advisories: number; conflicts: number };
}): Health {
  if (project.stats.advisories > 0) return "cve";
  if (project.stats.major > 0) return "major";
  if (project.stats.conflicts > 0) return "major";
  if (project.stats.outdated > 0) return "minor";
  return "ok";
}

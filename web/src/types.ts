export type DeltaKind = "major" | "minor" | "patch" | "other" | "none" | "unknown";
export type DriftKind = "same" | "version" | "missing" | "extra" | null;

export interface Advisory {
  id: string;
  aliases: string[];
  summary: string | null;
  severity: string | null;
  fixed: string[];
  url: string | null;
}

export interface RiskFactor {
  label: string;
  weight: number;
}

export interface PackageNode {
  id: string;
  name: string;
  version: string;
  group: string;
  depth: number;
  direct: boolean;
  root: boolean;
  extras: string[];
  marker: string | null;
  source: string;
  available: boolean;
  latest: string | null;
  latest_upload: string | null;
  delta: DeltaKind;
  breaking: boolean;
  releases_behind: number | null;
  license: string | null;
  summary: string | null;
  yanked: boolean;
  deprecated: string | null;
  installed_version: string | null;
  drift: DriftKind;
  index: string | null;
  advisories: Advisory[];
  fixed_in: string | null;
  dependents: number;
  risk: number;
  risk_factors: RiskFactor[];
}

export interface PackageEdge {
  id: string;
  source: string;
  target: string;
  spec: string | null;
  kind: string;
  group: string | null;
  extra: string | null;
  marker: string | null;
  resolved: boolean;
}

export interface ConstraintView {
  parent: string;
  parent_id: string;
  spec: string;
  resolved: string | null;
  depth: number;
}

export interface Conflict {
  id: string;
  project_id: string;
  package: string;
  kind: "constraint" | "env" | "resolver" | "declared" | "drift";
  severity: "high" | "medium" | "low";
  title: string;
  detail: string;
  blame: ConstraintView[];
  raw: string | null;
  suggestion: string | null;
}

export interface LockInfo {
  exists: boolean;
  path: string | null;
  packages: number;
  requires_python: string | null;
  stale: boolean | null;
  error: string | null;
}

export interface VenvInfo {
  exists: boolean;
  path: string | null;
  python: string | null;
  installed: number;
  broken: boolean;
  compatible: boolean;
  check: string;
  check_output: string | null;
}

export interface DriftPlan {
  would_install: string[];
  would_uninstall: string[];
  raw: string | null;
}

export interface Drift {
  lock_only: string[];
  venv_only: string[];
  version_mismatch: { name: string; locked: string; installed: string }[];
  plan: DriftPlan;
}

export interface Stats {
  packages: number;
  direct: number;
  outdated: number;
  major: number;
  advisories: number;
  conflicts: number;
  drift: number;
  max_depth: number;
  duplicate_versions: number;
  cycles: number;
}

export interface Project {
  id: string;
  name: string;
  version: string;
  path: string;
  rel_path: string;
  python_requires: string | null;
  groups: string[];
  lock: LockInfo;
  venv: VenvInfo;
  nodes: PackageNode[];
  edges: PackageEdge[];
  conflicts: Conflict[];
  drift: Drift;
  stats: Stats;
}

export interface SkewRow {
  name: string;
  latest: string | null;
  versions: Record<string, string>;
  spread: number;
  newest: string | null;
  oldest: string | null;
}

export interface ScanStats {
  projects: number;
  packages: number;
  unique_packages: number;
  outdated: number;
  advisories: number;
  conflicts: number;
  drifted_projects: number;
  duration_ms: number;
}

export interface IndexRef {
  name: string;
  url: string;
  source: "default" | "cli" | "env" | "project";
  primary: boolean;
}

export interface ScanResult {
  root: string;
  generated_at: string;
  offline: boolean;
  indexes: IndexRef[];
  projects: Project[];
  skew: SkewRow[];
  conflicts: Conflict[];
  stats: ScanStats;
  warnings: string[];
}

export type View = "fleet" | "topology" | "packages" | "conflicts" | "skew";

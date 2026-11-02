from __future__ import annotations

import re
from dataclasses import dataclass, field

from packaging.specifiers import InvalidSpecifier, Specifier, SpecifierSet
from packaging.version import Version

from .models import (
    Conflict,
    ConstraintView,
    PackageNode,
    Project,
    RiskFactor,
    SkewRow,
    Stats,
)
from .pypi import PackageInfo
from .utils import best_satisfying, classify_delta, normalize_name, parse_version, releases_behind

SEVERITY_WEIGHT = {
    "CRITICAL": 0.55,
    "HIGH": 0.42,
    "MODERATE": 0.28,
    "MEDIUM": 0.28,
    "LOW": 0.14,
    "UNKNOWN": 0.1,
}
DELTA_WEIGHT = {"major": 0.38, "minor": 0.16, "patch": 0.03, "other": 0.05}


@dataclass(frozen=True)
class Interval:
    lo: Version | None = None
    lo_inc: bool = True
    hi: Version | None = None
    hi_inc: bool = True
    excl: frozenset[Version] = field(default_factory=frozenset)

    @property
    def empty(self) -> bool:
        if self.lo is not None and self.hi is not None:
            if self.lo > self.hi:
                return True
            if self.lo == self.hi:
                if not (self.lo_inc and self.hi_inc):
                    return True
                if self.lo in self.excl:
                    return True
        return False


def _bump(parts: list[int]) -> Version:
    parts = list(parts)
    parts[-1] += 1
    return Version(".".join(str(p) for p in parts))


def _prefix(text: str) -> list[int]:
    return [int(p) for p in text.split(".") if p.isdigit()] or [0]


def _from_spec(spec: Specifier) -> Interval | None:
    op, raw = spec.operator, spec.version
    if op == "==" and raw.endswith(".*"):
        base = raw[:-2]
        lo = parse_version(base)
        if lo is None:
            return None
        return Interval(lo=lo, hi=_bump(_prefix(base)), hi_inc=False)
    value = parse_version(raw)
    if value is None:
        return None
    if op == ">=":
        return Interval(lo=value)
    if op == ">":
        return Interval(lo=value, lo_inc=False)
    if op == "<=":
        return Interval(hi=value)
    if op == "<":
        return Interval(hi=value, hi_inc=False)
    if op == "==":
        return Interval(lo=value, hi=value)
    if op == "!=":
        return Interval(excl=frozenset({value}))
    if op == "~=":
        parts = _prefix(raw)
        prefix = parts[:-1] or parts
        return Interval(lo=value, hi=_bump(prefix), hi_inc=False)
    return None


def spec_interval(spec: str) -> Interval | None:
    try:
        specset = SpecifierSet(spec)
    except InvalidSpecifier:
        return None
    mega = Interval()
    found = False
    for single in specset:
        piece = _from_spec(single)
        if piece is None:
            continue
        found = True
        mega = intersect(mega, piece)
    return mega if found else None


def intersect(a: Interval, b: Interval) -> Interval:
    lo, lo_inc = a.lo, a.lo_inc
    if b.lo is not None and (lo is None or b.lo > lo):
        lo, lo_inc = b.lo, b.lo_inc
    elif b.lo is not None and lo is not None and b.lo == lo:
        lo_inc = a.lo_inc and b.lo_inc
    hi, hi_inc = a.hi, a.hi_inc
    if b.hi is not None and (hi is None or b.hi < hi):
        hi, hi_inc = b.hi, b.hi_inc
    elif b.hi is not None and hi is not None and b.hi == hi:
        hi_inc = a.hi_inc and b.hi_inc
    return Interval(lo=lo, lo_inc=lo_inc, hi=hi, hi_inc=hi_inc, excl=a.excl | b.excl)


def _fmt_interval(iv: Interval) -> str:
    parts = []
    if iv.lo is not None:
        parts.append(f"{'>=' if iv.lo_inc else '>'}{iv.lo}")
    if iv.hi is not None:
        parts.append(f"{'<=' if iv.hi_inc else '<'}{iv.hi}")
    for v in sorted(iv.excl):
        parts.append(f"!={v}")
    return ",".join(parts) or "any"


def _constraints_for(project: Project) -> dict[str, list[tuple[str, str, PackageNode]]]:
    """target node id -> [(parent_id, spec, parent_node)]"""
    by_id = {n.id: n for n in project.nodes}
    out: dict[str, list[tuple[str, str, PackageNode]]] = {}
    for edge in project.edges:
        if not edge.spec or edge.source == edge.target:
            continue
        parent = by_id.get(edge.source)
        target = by_id.get(edge.target)
        if not parent or not target:
            continue
        out.setdefault(target.id, []).append((parent.id, edge.spec, parent))
    return out


def constraint_conflicts(project: Project, versions: dict[str, list[str]]) -> list[Conflict]:
    conflicts: list[Conflict] = []
    by_id = {n.id: n for n in project.nodes}
    for target_id, rows in _constraints_for(project).items():
        if len(rows) < 2:
            continue
        node = by_id[target_id]
        pairs = []
        intervals = []
        for parent_id, spec, parent in rows:
            iv = spec_interval(spec)
            intervals.append((parent, spec, iv))
            pairs.append((spec, iv))
        intervals = [(p, s, i) for p, s, i in intervals if i is not None]
        if len(intervals) < 2:
            continue
        if node.version == "?":
            # declared-only project: no resolved version to validate
            continue

        worst_pair = None
        worst_score = -1
        for i in range(len(intervals)):
            for j in range(i + 1, len(intervals)):
                merged = intersect(intervals[i][2], intervals[j][2])
                if merged.empty:
                    score = len(intervals[i][1]) + len(intervals[j][1])
                    if score > worst_score:
                        worst_score = score
                        worst_pair = (intervals[i], intervals[j])

        combined = Interval()
        for _, _, iv in intervals:
            combined = intersect(combined, iv)

        blame = [
            ConstraintView(
                parent=parent.name,
                parent_id=parent.id,
                spec=spec,
                resolved=node.version,
                depth=parent.depth,
            )
            for parent, spec, _ in sorted(intervals, key=lambda row: row[0].depth)
        ]

        if worst_pair is not None:
            left, right = worst_pair
            suggestion = best_satisfying([left[1], right[1]], versions.get(node.name, []))
            conflicts.append(
                Conflict(
                    id=f"{project.id}:constraint:{node.id}",
                    project_id=project.id,
                    package=node.name,
                    kind="constraint",
                    severity="high",
                    title=f"{node.name} has no version satisfying every parent",
                    detail=(
                        f"{left[0].name} needs {left[1] or 'any'}, but "
                        f"{right[0].name} needs {right[1] or 'any'}. "
                        f"Intersection is empty (resolved: {node.version})."
                        + (f" Nearest workable release: {suggestion}." if suggestion else "")
                    ),
                    blame=blame,
                    suggestion=(
                        f"Relax {left[0].name} or {right[0].name}; their ranges cannot overlap."
                    ),
                )
            )
        elif combined.empty:
            conflicts.append(
                Conflict(
                    id=f"{project.id}:constraint:{node.id}",
                    project_id=project.id,
                    package=node.name,
                    kind="constraint",
                    severity="high",
                    title=f"{node.name} constraints cannot overlap",
                    detail=f"Combined range is empty: {_fmt_interval(combined)}",
                    blame=blame,
                )
            )
        else:
            # Resolution outside a declared range means the lock is stale.
            violating = []
            for parent, spec, _ in intervals:
                try:
                    if node.version not in SpecifierSet(spec):
                        violating.append((parent, spec))
                except InvalidSpecifier:
                    continue
            if violating:
                parent, spec = violating[0]
                conflicts.append(
                    Conflict(
                        id=f"{project.id}:declared:{node.id}",
                        project_id=project.id,
                        package=node.name,
                        kind="declared",
                        severity="medium",
                        title=f"{node.name} {node.version} is outside {parent.name}'s range",
                        detail=(
                            f"{parent.name} declares {spec}, but the lock resolved "
                            f"{node.version}. The lockfile is stale or hand-edited."
                        ),
                        blame=blame,
                        suggestion="Run `uv lock` to re-resolve.",
                    )
                )
    return conflicts


_ENV_PATTERNS = [
    re.compile(r"^(?P<pkg>[\w.\-]+) (?P<ver>[\w.\-+]+) requires (?P<req>.+?), but (?P<what>.+)$"),
    re.compile(r"^(?P<pkg>[\w.\-]+) (?P<ver>[\w.\-+]+) depends on (?P<req>.+), but (?P<what>.+)$"),
    re.compile(r"^(?P<pkg>[\w.\-]+) (?P<ver>[\w.\-+]+) requires (?P<req>.+)$"),
]


def env_conflicts(project: Project) -> list[Conflict]:
    output = project.venv.check_output
    if not output:
        return []
    conflicts: list[Conflict] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("checked "):
            continue
        matched = None
        for pattern in _ENV_PATTERNS:
            matched = pattern.match(line)
            if matched:
                break
        if matched:
            groups = matched.groupdict()
            conflicts.append(
                Conflict(
                    id=f"{project.id}:env:{groups.get('pkg')}:{len(conflicts)}",
                    project_id=project.id,
                    package=normalize_name(groups.get("pkg") or ""),
                    kind="env",
                    severity="high",
                    title=line,
                    detail=(
                        f"Installed environment is inconsistent: {groups.get('req')} is required, "
                        f"but {groups.get('what') or 'nothing matching'} is present."
                    ),
                    raw=line,
                    suggestion="Run `uv sync` to repair the environment.",
                )
            )
        else:
            conflicts.append(
                Conflict(
                    id=f"{project.id}:env:line{len(conflicts)}",
                    project_id=project.id,
                    package="environment",
                    kind="env",
                    severity="medium",
                    title=line[:140],
                    detail="uv pip check reported a problem in this environment.",
                    raw=line,
                )
            )
    return conflicts


def drift_conflict(project: Project) -> list[Conflict]:
    drift = project.drift
    total = len(drift.lock_only) + len(drift.venv_only) + len(drift.version_mismatch)
    if total == 0:
        return []
    detail_bits = []
    if drift.venv_only:
        detail_bits.append(f"{len(drift.venv_only)} installed but not locked")
    if drift.lock_only:
        detail_bits.append(f"{len(drift.lock_only)} locked but not installed")
    if drift.version_mismatch:
        detail_bits.append(f"{len(drift.version_mismatch)} at a different version")
    plan = drift.plan
    suggestion = None
    if plan.would_install or plan.would_uninstall:
        suggestion = (
            f"`uv sync` would install {len(plan.would_install)} and "
            f"uninstall {len(plan.would_uninstall)} package(s)."
        )
    return [
        Conflict(
            id=f"{project.id}:drift",
            project_id=project.id,
            package="environment",
            kind="drift",
            severity="medium" if drift.version_mismatch else "low",
            title=f"Environment drift: {total} package(s)",
            detail=", ".join(detail_bits) + ".",
            suggestion=suggestion,
        )
    ]


def resolver_conflict(project: Project, raw: str | None) -> list[Conflict]:
    if not raw:
        return []
    first = next((line for line in raw.splitlines() if line.strip()), raw[:200])
    return [
        Conflict(
            id=f"{project.id}:resolver",
            project_id=project.id,
            package="resolution",
            kind="resolver",
            severity="high",
            title="uv could not resolve the project",
            detail=first.strip()[:300],
            raw=raw,
            suggestion="Read the resolver chain in the raw output; a parent range must be relaxed.",
        )
    ]


def apply_enrichment(
    project: Project,
    infos: dict[str, PackageInfo],
    advisories: dict[tuple[str, str], list],
) -> None:
    for node in project.nodes:
        if node.root:
            continue
        info = infos.get(node.name)
        if info is not None:
            node.available = info.available
            if info.index:
                node.index = info.index
            if info.available:
                node.latest = info.latest
                node.latest_upload = info.latest_upload
                node.license = info.license or node.license
                node.summary = node.summary or info.summary
                node.yanked = info.yanked
                node.deprecated = info.deprecated
                node.delta, node.breaking = classify_delta(node.version, info.latest)
                node.releases_behind = releases_behind(node.version, info.versions)
        found = advisories.get((node.name, node.version), [])
        node.advisories = found
        fixed = []
        current = parse_version(node.version)
        for advisory in found:
            for candidate in advisory.fixed:
                version = parse_version(candidate)
                if version and current and version > current:
                    fixed.append(version)
        node.fixed_in = str(min(fixed)) if fixed else None


def score_risk(node: PackageNode) -> None:
    if node.root:
        node.risk = 0.0
        node.risk_factors = []
        return
    factors: list[RiskFactor] = []
    weight = DELTA_WEIGHT.get(node.delta, 0.0)
    if weight:
        label = f"{node.delta} outdated ({node.version} -> {node.latest})"
        if node.breaking:
            weight += 0.08
            label += " (breaking)"
        factors.append(RiskFactor(label=label, weight=round(weight, 3)))

    if node.advisories:
        severity = (node.advisories[0].severity or "UNKNOWN").upper()
        base = SEVERITY_WEIGHT.get(severity, 0.1)
        extra = min(0.15, 0.02 * (len(node.advisories) - 1))
        factors.append(
            RiskFactor(
                label=f"{len(node.advisories)} advisor{'y' if len(node.advisories) == 1 else 'ies'}"
                f" (worst: {severity.title()})",
                weight=round(base + extra, 3),
            )
        )
    if node.yanked:
        factors.append(RiskFactor(label="current version is yanked", weight=0.2))
    if node.deprecated:
        factors.append(RiskFactor(label="upstream marked inactive", weight=0.08))
    if node.drift == "version":
        factors.append(RiskFactor(label="installed differs from lock", weight=0.08))
    elif node.drift == "missing":
        factors.append(RiskFactor(label="locked but not installed", weight=0.03))

    node.risk = round(min(1.0, sum(f.weight for f in factors)), 3)
    node.risk_factors = factors


def recompute_stats(project: Project) -> None:
    nodes = [n for n in project.nodes if not n.root]
    project.stats.packages = len(nodes)
    project.stats.direct = sum(1 for n in nodes if n.direct)
    project.stats.outdated = sum(
        1 for n in nodes if n.delta in {"major", "minor", "patch", "other"}
    )
    project.stats.major = sum(1 for n in nodes if n.delta == "major" or n.breaking)
    project.stats.advisories = sum(len(n.advisories) for n in nodes)
    project.stats.conflicts = len(project.conflicts)
    project.stats.drift = (
        len(project.drift.lock_only)
        + len(project.drift.venv_only)
        + len(project.drift.version_mismatch)
    )


def compute_skew(projects: list[Project], infos: dict[str, PackageInfo]) -> list[SkewRow]:
    per_name: dict[str, dict[str, set[str]]] = {}
    for project in projects:
        for node in project.nodes:
            if node.root:
                continue
            per_name.setdefault(node.name, {}).setdefault(project.id, set()).add(node.version)

    rows: list[SkewRow] = []
    for name, by_project in per_name.items():
        all_versions = {v for versions in by_project.values() for v in versions}
        if len(all_versions) < 2 or len(by_project) < 1:
            continue
        ordered = sorted(all_versions, key=lambda v: parse_version(v) or parse_version("0"))
        info = infos.get(name)
        rows.append(
            SkewRow(
                name=name,
                latest=info.latest if info and info.available else None,
                versions={
                    pid: ", ".join(
                        sorted(versions, key=lambda v: parse_version(v) or parse_version("0"))
                    )
                    for pid, versions in by_project.items()
                },
                spread=len(all_versions),
                oldest=ordered[0],
                newest=ordered[-1],
            )
        )
    rows.sort(key=lambda row: (-row.spread, row.name))
    return rows


def collect_conflicts(project: Project, versions: dict[str, list[str]], resolver_raw: str | None) -> None:
    conflicts = []
    conflicts.extend(constraint_conflicts(project, versions))
    conflicts.extend(env_conflicts(project))
    conflicts.extend(resolver_conflict(project, resolver_raw))
    conflicts.extend(drift_conflict(project))
    seen: set[str] = set()
    unique = []
    for conflict in conflicts:
        if conflict.id in seen:
            continue
        seen.add(conflict.id)
        unique.append(conflict)
    project.conflicts = unique

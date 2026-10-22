from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DriftKind = Literal["same", "version", "missing", "extra"]
DeltaKind = Literal["major", "minor", "patch", "other", "none", "unknown"]


class Advisory(BaseModel):
    id: str
    aliases: list[str] = Field(default_factory=list)
    summary: str | None = None
    severity: str | None = None
    fixed: list[str] = Field(default_factory=list)
    url: str | None = None


class RiskFactor(BaseModel):
    label: str
    weight: float


class PackageNode(BaseModel):
    id: str
    name: str
    version: str
    group: str = "main"
    depth: int = 0
    direct: bool = False
    root: bool = False
    extras: list[str] = Field(default_factory=list)
    marker: str | None = None
    source: str = "registry"

    # PyPI enrichment
    available: bool = True
    latest: str | None = None
    latest_upload: str | None = None
    delta: DeltaKind = "unknown"
    breaking: bool = False
    releases_behind: int | None = None
    license: str | None = None
    summary: str | None = None
    yanked: bool = False
    deprecated: str | None = None

    # environment truth
    installed_version: str | None = None
    drift: DriftKind | None = None

    advisories: list[Advisory] = Field(default_factory=list)
    fixed_in: str | None = None

    dependents: int = 0
    risk: float = 0.0
    risk_factors: list[RiskFactor] = Field(default_factory=list)


class PackageEdge(BaseModel):
    id: str
    source: str
    target: str
    spec: str | None = None
    kind: str = "runtime"  # runtime | dev | optional | inferred
    group: str | None = None
    extra: str | None = None
    marker: str | None = None
    resolved: bool = True


class ConstraintView(BaseModel):
    parent: str
    parent_id: str
    spec: str
    resolved: str | None = None
    depth: int = 0


class Conflict(BaseModel):
    id: str
    project_id: str
    package: str
    kind: Literal["constraint", "env", "resolver", "declared", "drift"]
    severity: Literal["high", "medium", "low"]
    title: str
    detail: str
    blame: list[ConstraintView] = Field(default_factory=list)
    raw: str | None = None
    suggestion: str | None = None


class LockInfo(BaseModel):
    exists: bool = False
    path: str | None = None
    packages: int = 0
    requires_python: str | None = None
    stale: bool | None = None
    error: str | None = None


class VenvInfo(BaseModel):
    exists: bool = False
    path: str | None = None
    python: str | None = None
    installed: int = 0
    broken: bool = False
    compatible: bool = True
    check: str = "unknown"  # ok | incompatible | unknown
    check_output: str | None = None


class DriftPlan(BaseModel):
    would_install: list[str] = Field(default_factory=list)
    would_uninstall: list[str] = Field(default_factory=list)
    raw: str | None = None


class Drift(BaseModel):
    lock_only: list[str] = Field(default_factory=list)
    venv_only: list[str] = Field(default_factory=list)
    version_mismatch: list[dict] = Field(default_factory=list)
    plan: DriftPlan = Field(default_factory=DriftPlan)


class Stats(BaseModel):
    packages: int = 0
    direct: int = 0
    outdated: int = 0
    major: int = 0
    advisories: int = 0
    conflicts: int = 0
    drift: int = 0
    max_depth: int = 0
    duplicate_versions: int = 0
    cycles: int = 0


class Project(BaseModel):
    id: str
    name: str
    version: str = "0.0.0"
    path: str
    rel_path: str
    python_requires: str | None = None
    groups: list[str] = Field(default_factory=list)
    lock: LockInfo = Field(default_factory=LockInfo)
    venv: VenvInfo = Field(default_factory=VenvInfo)
    nodes: list[PackageNode] = Field(default_factory=list)
    edges: list[PackageEdge] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    drift: Drift = Field(default_factory=Drift)
    stats: Stats = Field(default_factory=Stats)


class SkewRow(BaseModel):
    name: str
    latest: str | None = None
    versions: dict[str, str] = Field(default_factory=dict)
    spread: int = 0
    newest: str | None = None
    oldest: str | None = None


class ScanStats(BaseModel):
    projects: int = 0
    packages: int = 0
    unique_packages: int = 0
    outdated: int = 0
    advisories: int = 0
    conflicts: int = 0
    drifted_projects: int = 0
    duration_ms: int = 0


class ScanResult(BaseModel):
    root: str
    generated_at: str
    offline: bool = False
    projects: list[Project] = Field(default_factory=list)
    skew: list[SkewRow] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    stats: ScanStats = Field(default_factory=ScanStats)
    warnings: list[str] = Field(default_factory=list)

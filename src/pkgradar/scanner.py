from __future__ import annotations

import asyncio
import inspect
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from .analyze import (
    apply_enrichment,
    collect_conflicts,
    compute_skew,
    recompute_stats,
    score_risk,
)
from .discover import DiscoveredProject, discover
from .graph import GraphBuilder
from .locks import load_lock
from .models import (
    Drift,
    DriftPlan,
    LockInfo,
    Project,
    ScanResult,
    ScanStats,
    VenvInfo,
)
from .osv import fetch_advisories
from .pypi import PackageInfo, PyPIClient
from .utils import normalize_name, parse_requirement
from .venvs import (
    build_venv_graph,
    compute_drift,
    enrich_edge_specs,
    lock_check,
    reconcile_drift,
    scan_venv,
    sync_plan,
)

EventFn = Callable[[str, dict], Awaitable[None] | None]


def _read_toml(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except Exception:
        return {}


async def _emit(on_event: EventFn | None, event: str, data: dict) -> None:
    if on_event is None:
        return
    result = on_event(event, data)
    if inspect.isawaitable(result):
        await result


def _declared_graph(project_name: str, version: str, pyproject: dict):
    builder = GraphBuilder(project_name, version)
    project_tbl = pyproject.get("project", {}) or {}

    def wire(requirements, kind: str, group: str, extra: str | None = None) -> None:
        for raw in requirements or []:
            req = parse_requirement(str(raw))
            if req is None:
                continue
            node_id = builder.add_node(req.name, "?", source="declared")
            builder.add_edge(
                builder.root_id,
                node_id,
                spec=str(req.specifier) or None,
                kind=kind,
                group=group,
                extra=extra,
                marker=str(req.marker) if req.marker else None,
            )
            if req.extras:
                builder._extras[node_id].update(req.extras)

    wire(project_tbl.get("dependencies"), "runtime", "main")
    for extra_name, reqs in (project_tbl.get("optional-dependencies") or {}).items():
        wire(reqs, "optional", "main", extra=str(extra_name))
    dep_groups = pyproject.get("dependency-groups")
    if dep_groups is None:
        dep_groups = (pyproject.get("tool", {}).get("uv", {}) or {}).get("dependency-groups")
    for group_name, reqs in (dep_groups or {}).items():
        wire([r for r in (reqs or []) if isinstance(r, str)], "dev", str(group_name))

    nodes, edges, stats = builder.finalize()
    for node in nodes:
        if not node.root:
            node.available = False
    return nodes, edges, stats


def _build_project(discovered: DiscoveredProject, deep: bool) -> Project:
    pyproject_path = discovered.pyproject
    pyproject = _read_toml(pyproject_path)
    project = Project(
        id=discovered.id,
        name=discovered.name,
        version=discovered.version,
        path=str(discovered.path),
        rel_path=discovered.rel_path,
        python_requires=discovered.python_requires,
        groups=discovered.groups or ["main"],
    )

    if discovered.lock:
        nodes, edges, stats, lock_info = load_lock(
            discovered.lock, discovered.name, discovered.version, pyproject
        )
        project.nodes, project.edges, project.stats = nodes, edges, stats
        project.lock = lock_info
        if deep:
            # A stale lock is not a resolver failure: `uv lock --check` only
            # says the lock needs regenerating, so it must not become a
            # high-severity "cannot resolve" conflict.
            project.lock.stale, _ = lock_check(discovered.path)
    elif discovered.pyproject:
        nodes, edges, stats = _declared_graph(discovered.name, discovered.version, pyproject)
        project.nodes, project.edges, project.stats = nodes, edges, stats
        project.lock = LockInfo(exists=False)

    if discovered.venv:
        if discovered.venv_broken:
            project.venv = VenvInfo(exists=True, path=str(discovered.venv), broken=True)
        else:
            state = scan_venv(discovered.venv)
            project.venv = state.info
            if discovered.lock and project.nodes:
                project.drift, _ = compute_drift(project.nodes, state, project.id)
                enrich_edge_specs(project.nodes, project.edges, state)
                reconcile_drift(project, DriftPlan())
                if deep:
                    project.drift.plan, plan_raw = sync_plan(
                        discovered.path, discovered.venv
                    )
                    if plan_raw and not project.drift.plan.raw:
                        project.drift.plan.raw = plan_raw
                    reconcile_drift(project, project.drift.plan)
            elif not discovered.lock:
                project.drift = Drift()

    collect_conflicts(project, {}, None)
    return project


async def scan(
    root: Path,
    *,
    offline: bool = False,
    enrich: bool = True,
    advisories: bool = True,
    deep: bool = True,
    on_event: EventFn | None = None,
) -> ScanResult:
    started = time.time()
    root = root.expanduser().resolve()
    await _emit(on_event, "progress", {"phase": "discover", "message": f"Scanning {root}", "done": 0, "total": 1})

    discovered, warnings = discover(root)
    await _emit(
        on_event,
        "progress",
        {
            "phase": "discover",
            "message": f"Found {len(discovered)} project(s)",
            "done": 1,
            "total": max(1, len(discovered)),
        },
    )

    projects: list[Project] = []
    for index, item in enumerate(discovered):
        await _emit(
            on_event,
            "progress",
            {
                "phase": "parse",
                "message": f"Reading {item.rel_path}",
                "done": index,
                "total": len(discovered) + 1,
            },
        )
        try:
            project = await asyncio.to_thread(_build_project, item, deep)
        except Exception as exc:  # pragma: no cover - defensive
            warnings.append(f"{item.rel_path}: {exc}")
            continue
        projects.append(project)
        await _emit(on_event, "project", {"project": project.model_dump(mode="json")})

    # Enrichment
    infos: dict[str, PackageInfo] = {}
    advisory_map: dict = {}
    if enrich:
        names = sorted(
            {
                node.name
                for project in projects
                for node in project.nodes
                if not node.root and node.version != "?"
            }
        )
        total = len(names)
        await _emit(
            on_event,
            "progress",
            {"phase": "pypi", "message": f"Querying PyPI for {total} packages", "done": 0, "total": total},
        )
        client = PyPIClient(offline=offline)

        async def pypi_progress(done: int, count: int) -> None:
            if done == count or done % 5 == 0 or done == 1:
                await _emit(
                    on_event,
                    "enrich",
                    {
                        "phase": "pypi",
                        "message": f"PyPI {done}/{count}",
                        "done": done,
                        "total": count,
                    },
                )

        infos = await client.fetch_many(names, progress=pypi_progress)

        if advisories and not offline:
            pairs = sorted(
                {
                    (node.name, node.version)
                    for project in projects
                    for node in project.nodes
                    if not node.root and node.version != "?"
                }
            )
            await _emit(
                on_event,
                "progress",
                {
                    "phase": "osv",
                    "message": f"Checking {len(pairs)} package versions against OSV",
                    "done": 0,
                    "total": len(pairs),
                },
            )
            advisory_map = await fetch_advisories(pairs, offline=offline)

    for project in projects:
        apply_enrichment(project, infos, advisory_map)
        collect_conflicts(
            project,
            {name: info.versions for name, info in infos.items()},
            resolver_raw=None,
        )
        for node in project.nodes:
            score_risk(node)
        recompute_stats(project)

    skew = compute_skew(projects, infos) if enrich else []
    all_conflicts = [conflict for project in projects for conflict in project.conflicts]

    unique_names = {
        node.name for project in projects for node in project.nodes if not node.root
    }
    duration = int((time.time() - started) * 1000)
    result = ScanResult(
        root=str(root),
        generated_at=datetime.now(timezone.utc).isoformat(),
        offline=offline,
        projects=projects,
        skew=skew,
        conflicts=all_conflicts,
        warnings=warnings,
        stats=ScanStats(
            projects=len(projects),
            packages=sum(p.stats.packages for p in projects),
            unique_packages=len(unique_names),
            outdated=sum(p.stats.outdated for p in projects),
            advisories=sum(p.stats.advisories for p in projects),
            conflicts=len(all_conflicts),
            drifted_projects=sum(
                1
                for p in projects
                if p.drift.lock_only or p.drift.venv_only or p.drift.version_mismatch
            ),
            duration_ms=duration,
        ),
    )
    await _emit(on_event, "done", {"result": result.model_dump(mode="json")})
    return result


def scan_sync(root: Path, **kwargs) -> ScanResult:
    return asyncio.run(scan(root, **kwargs))

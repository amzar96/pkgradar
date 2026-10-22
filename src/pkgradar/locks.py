from __future__ import annotations

import tomllib
from collections import defaultdict
from pathlib import Path

from .graph import GraphBuilder
from .models import LockInfo, PackageEdge, PackageNode, Stats
from .utils import normalize_name, parse_version

try:  # Python 3.11+
    from packaging.specifiers import SpecifierSet
except Exception:  # pragma: no cover
    SpecifierSet = None  # type: ignore


def _source_kind(source: dict) -> str:
    if not source:
        return "unknown"
    if "registry" in source:
        return "registry"
    if "git" in source:
        return "git"
    if "editable" in source or "directory" in source or "path" in source:
        return "local"
    return "unknown"


def _pick(candidates: list[dict], spec: str | None, version: str | None = None) -> dict | None:
    if not candidates:
        return None
    if version:
        for cand in candidates:
            if cand.get("version") == version:
                return cand
    filtered = candidates
    if spec and SpecifierSet is not None:
        try:
            specset = SpecifierSet(spec)
            matching = [c for c in candidates if (parse_version(c.get("version")) in specset)]
            if matching:
                filtered = matching
        except Exception:
            pass
    ranked = sorted(
        filtered,
        key=lambda c: (
            not bool(parse_version(c.get("version")) and parse_version(c.get("version")).is_prerelease),
            parse_version(c.get("version")) or parse_version("0"),
        ),
        reverse=True,
    )
    return ranked[0]


def load_lock(
    lock_path: Path,
    project_name: str,
    project_version: str,
    pyproject: dict,
) -> tuple[list[PackageNode], list[PackageEdge], Stats, LockInfo]:
    with lock_path.open("rb") as fh:
        data = tomllib.load(fh)

    packages: list[dict] = data.get("package", []) or []
    # uv.lock includes the project itself (editable/local source); it is the
    # root of the graph, not a dependency.
    root_norm = normalize_name(project_name)
    packages = [
        pkg
        for pkg in packages
        if not (
            normalize_name(str(pkg.get("name", ""))) == root_norm
            and _source_kind(pkg.get("source", {})) in {"local", "unknown"}
        )
    ]
    by_name: dict[str, list[dict]] = defaultdict(list)
    for pkg in packages:
        by_name[normalize_name(str(pkg.get("name", "")))].append(pkg)

    builder = GraphBuilder(project_name, project_version)
    for pkg in packages:
        builder.add_node(
            str(pkg.get("name", "")),
            str(pkg.get("version", "")),
            source=_source_kind(pkg.get("source", {})),
        )

    def wire(src_id: str, deps: list[dict], *, kind: str, group: str | None, extra: str | None = None) -> None:
        for dep in deps or []:
            dep_name = normalize_name(str(dep.get("name", "")))
            if not dep_name:
                continue
            target = _pick(by_name.get(dep_name, []), None, dep.get("version"))
            if target is None:
                continue
            target_id = f"{dep_name}@{target.get('version', '')}"
            if target_id not in builder.nodes:
                continue
            dep_extra = dep.get("extra")
            if isinstance(dep_extra, list):
                dep_extra = dep_extra[0] if dep_extra else None
            if dep_extra is not None:
                dep_extra = str(dep_extra)
            builder.add_edge(
                src_id,
                target_id,
                spec=dep.get("specifier"),
                kind="optional" if dep_extra and kind == "runtime" else kind,
                group=group,
                extra=dep_extra or extra,
                marker=dep.get("marker"),
            )

    for pkg in packages:
        norm = normalize_name(str(pkg.get("name", "")))
        src_id = f"{norm}@{pkg.get('version', '')}"
        if src_id not in builder.nodes:
            continue
        wire(src_id, pkg.get("dependencies", []), kind="runtime", group=None)
        for extra_name, deps in (pkg.get("optional-dependencies") or {}).items():
            wire(src_id, deps, kind="optional", group=None, extra=str(extra_name))
        for group_name, deps in (pkg.get("dev-dependencies") or {}).items():
            wire(src_id, deps, kind="dev", group=str(group_name))

    # Root edges come from pyproject: lock stores resolved versions, pyproject
    # stores the human-declared ranges we want to show on the edges.
    project_tbl = pyproject.get("project", {}) or {}
    for raw in project_tbl.get("dependencies", []) or []:
        _wire_root_requirement(builder, by_name, str(raw), kind="runtime", group="main")
    for extra_name, reqs in (project_tbl.get("optional-dependencies") or {}).items():
        for raw in reqs or []:
            _wire_root_requirement(
                builder, by_name, str(raw), kind="optional", group="main", extra=str(extra_name)
            )

    dep_groups = pyproject.get("dependency-groups")
    if dep_groups is None:
        dep_groups = (pyproject.get("tool", {}).get("uv", {}) or {}).get("dependency-groups")
    if dep_groups is None:
        legacy = (pyproject.get("tool", {}).get("uv", {}) or {}).get("dev-dependencies")
        if legacy:
            dep_groups = {"dev": legacy}
    for group_name, reqs in (dep_groups or {}).items():
        for raw in reqs or []:
            if isinstance(raw, dict):
                continue  # PEP 735 include-group
            _wire_root_requirement(
                builder, by_name, str(raw), kind="dev", group=str(group_name)
            )

    nodes, edges, stats = builder.finalize()
    info = LockInfo(
        exists=True,
        path=str(lock_path),
        packages=len(packages),
        requires_python=data.get("requires-python"),
    )
    return nodes, edges, stats, info


def _wire_root_requirement(
    builder: GraphBuilder,
    by_name: dict[str, list[dict]],
    raw: str,
    *,
    kind: str,
    group: str,
    extra: str | None = None,
) -> None:
    from .utils import parse_requirement

    req = parse_requirement(raw)
    if req is None:
        return
    name = normalize_name(req.name)
    target = _pick(by_name.get(name, []), str(req.specifier) or None)
    if target is None:
        return
    target_id = f"{name}@{target.get('version', '')}"
    if target_id not in builder.nodes:
        return
    builder.add_edge(
        builder.root_id,
        target_id,
        spec=str(req.specifier) or None,
        kind=kind,
        group=group,
        extra=extra,
        marker=str(req.marker) if req.marker else None,
    )
    if req.extras:
        builder._extras[target_id].update(req.extras)

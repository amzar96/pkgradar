from __future__ import annotations

import re
import tempfile
import uuid
from dataclasses import dataclass, field
from email.parser import Parser
from pathlib import Path

from packaging.markers import Marker, default_environment
from packaging.requirements import Requirement
from packaging.version import Version

from .graph import GraphBuilder
from .models import Drift, DriftPlan, PackageEdge, PackageNode, Stats, VenvInfo
from .proc import run, uv_bin
from .utils import normalize_name, parse_version

_EXTRA_RE = re.compile(r"""extra\s*==\s*["']([^"']+)["']""")


def _marker_env(python_version: str | None) -> dict:
    env = default_environment()
    if python_version:
        try:
            version = Version(python_version)
            env["python_version"] = f"{version.major}.{version.minor}"
            env["python_full_version"] = str(version)
        except Exception:
            pass
    return env


def _choose_requirement(
    requirements: list[Requirement],
    python_version: str | None,
    extra: str | None = None,
) -> Requirement | None:
    """A package can declare the same dependency twice under different markers
    (e.g. urllib3 via python_version < 3.10 / >= 3.10). Pick the branch that is
    actually live for this interpreter."""
    env_base = _marker_env(python_version)
    for req in requirements:
        if req.marker is None:
            return req
        match = _EXTRA_RE.search(str(req.marker))
        env = dict(env_base)
        env["extra"] = match.group(1) if match else (extra or "")
        try:
            if req.marker.evaluate(env):
                return req
        except Exception:
            continue
    return None


@dataclass
class InstalledPackage:
    name: str
    version: str
    requires: list[Requirement] = field(default_factory=list)
    license: str | None = None
    summary: str | None = None


@dataclass
class VenvState:
    info: VenvInfo
    installed: list[InstalledPackage] = field(default_factory=list)
    by_name: dict[str, InstalledPackage] = field(default_factory=dict)


def venv_python(venv: Path) -> Path | None:
    for candidate in (venv / "bin" / "python", venv / "Scripts" / "python.exe"):
        if candidate.exists():
            return candidate
    return None


def safe_python(venv: Path) -> Path | None:
    """Return the interpreter only when it is safe to execute.

    uv queries the project interpreter for `lock --check` and `sync --dry-run`,
    so a cloned repository that ships an executable at `.venv/bin/python` can
    run arbitrary code as the user. A real POSIX venv uses a symlink to an
    interpreter outside the project; only that layout is trusted. Windows venvs
    copy python.exe into the venv, so they are treated as untrusted.
    """
    candidate = venv / "bin" / "python"
    if not candidate.is_symlink():
        return None
    try:
        target = candidate.resolve(strict=True)
        project = venv.parent.resolve(strict=True)
    except OSError:
        return None
    try:
        target.relative_to(project)
    except ValueError:
        return target if target.is_file() else None
    return None


def site_packages(venv: Path) -> Path | None:
    matches = sorted(venv.glob("lib/python*/site-packages"))
    if matches:
        return matches[-1]
    win = venv / "Lib" / "site-packages"
    if win.exists():
        return win
    return None


def _python_version(venv: Path) -> str | None:
    """Read the version from pyvenv.cfg; never execute the project interpreter."""
    cfg = venv / "pyvenv.cfg"
    if cfg.exists():
        try:
            for line in cfg.read_text(errors="replace").splitlines():
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if key.strip() in {"version", "version_info"}:
                    return value.strip()
        except Exception:
            pass
    return None


def _headers(path: Path) -> Parser:
    raw = path.read_text(encoding="utf-8", errors="replace")
    head = raw.split("\n\n", 1)[0]
    return Parser().parsestr(head)


def read_installed(site: Path) -> list[InstalledPackage]:
    packages: list[InstalledPackage] = []
    seen: set[tuple[str, str]] = set()
    for meta in sorted(site.glob("*.dist-info/METADATA")):
        try:
            msg = _headers(meta)
        except Exception:
            continue
        name = msg.get("Name")
        version = msg.get("Version")
        if not name or not version:
            continue
        key = (normalize_name(name), version)
        if key in seen:
            continue
        seen.add(key)
        requires: list[Requirement] = []
        for raw in msg.get_all("Requires-Dist") or []:
            try:
                requires.append(Requirement(raw))
            except Exception:
                continue
        license_value = msg.get("License-Expression") or msg.get("License")
        if license_value and len(license_value) > 80:
            license_value = None
        packages.append(
            InstalledPackage(
                name=normalize_name(name),
                version=str(version),
                requires=requires,
                license=license_value,
                summary=(msg.get("Summary") or None),
            )
        )
    return packages


def scan_venv(venv: Path) -> VenvState:
    python = venv_python(venv)
    info = VenvInfo(path=str(venv))
    if python is None:
        info.broken = True
        info.exists = True
        return VenvState(info=info)

    info.exists = True
    info.python = _python_version(venv)

    site = site_packages(venv)
    installed: list[InstalledPackage] = read_installed(site) if site else []

    info.installed = len(installed)
    # `uv pip list` / `uv pip check` execute the project interpreter, which is
    # attacker-controlled when scanning a cloned repo. dist-info is authoritative
    # for versions, so we deliberately do not run them. Compatibility is unknown.
    info.check = "unknown"

    return VenvState(
        info=info,
        installed=installed,
        by_name={p.name: p for p in installed},
    )


def build_venv_graph(
    project_name: str,
    project_version: str,
    state: VenvState,
) -> tuple[list[PackageNode], list[PackageEdge], Stats]:
    builder = GraphBuilder(project_name, project_version)
    for pkg in state.installed:
        builder.add_node(pkg.name, pkg.version)
    python_version = state.info.python
    for pkg in state.installed:
        src = f"{pkg.name}@{pkg.version}"
        grouped: dict[str, list[Requirement]] = {}
        for req in pkg.requires:
            target = state.by_name.get(normalize_name(req.name))
            if target is None:
                continue
            grouped.setdefault(target.name, []).append(req)
        for target_name, reqs in grouped.items():
            chosen = _choose_requirement(reqs, python_version)
            if chosen is None:
                continue
            target = state.by_name[target_name]
            marker = str(chosen.marker) if chosen.marker else None
            extra_match = _EXTRA_RE.search(marker or "")
            builder.add_edge(
                src,
                f"{target.name}@{target.version}",
                spec=str(chosen.specifier) or None,
                kind="optional" if extra_match else "runtime",
                extra=extra_match.group(1) if extra_match else None,
                marker=marker,
            )
    nodes, edges, stats = builder.finalize()
    for node in nodes:
        if not node.root:
            node.installed_version = node.version
            node.drift = "same"
    return nodes, edges, stats


def compute_drift(
    nodes: list[PackageNode],
    state: VenvState,
    project_id: str,
) -> tuple[Drift, list]:
    """Attach installed versions to lock nodes and return project-level drift."""
    installed = state.by_name
    lock_by_name: dict[str, PackageNode] = {}
    for node in nodes:
        if node.root:
            continue
        lock_by_name.setdefault(node.name, node)

    lock_only: list[str] = []
    version_mismatch: list[dict] = []
    for name, node in lock_by_name.items():
        pkg = installed.get(name)
        if pkg is None:
            node.drift = "missing"
            lock_only.append(name)
            continue
        node.installed_version = pkg.version
        if parse_version(pkg.version) != parse_version(node.version):
            node.drift = "version"
            version_mismatch.append(
                {"name": name, "locked": node.version, "installed": pkg.version}
            )
        else:
            node.drift = "same"

    venv_only = sorted(n for n in installed if n not in lock_by_name)
    return (
        Drift(
            lock_only=sorted(lock_only),
            venv_only=venv_only,
            version_mismatch=version_mismatch,
        ),
        venv_only,
    )


def enrich_edge_specs(nodes: list[PackageNode], edges: list[PackageEdge], state: VenvState) -> None:
    """uv.lock edges carry resolved versions but not ranges. Installed METADATA
    does carry the ranges, so borrow them when the installed version matches the
    locked one."""
    by_name = state.by_name
    versions = {node.id: node.version for node in nodes}
    python_version = state.info.python
    for edge in edges:
        if edge.spec:
            continue
        if edge.source == "root":
            continue
        src_name = edge.source.split("@", 1)[0]
        tgt_name = edge.target.split("@", 1)[0]
        pkg = by_name.get(src_name)
        if pkg is None or versions.get(edge.source) != pkg.version:
            continue
        candidates = [r for r in pkg.requires if normalize_name(r.name) == tgt_name]
        if not candidates:
            continue
        chosen = _choose_requirement(candidates, python_version, edge.extra)
        if chosen is None:
            continue
        edge.spec = str(chosen.specifier) or None
        if not edge.marker and chosen.marker:
            edge.marker = str(chosen.marker)


def sync_plan(project_dir: Path, venv: Path | None = None) -> tuple[DriftPlan, str | None]:
    """`uv sync --dry-run` is read-only and tells us the real delta.

    uv queries the project interpreter while syncing. Skip the plan when the
    venv does not have the trusted symlink layout, so a cloned repo cannot get
    us to execute its `.venv/bin/python`. dist-info drift is still reported.
    """
    if venv is not None and safe_python(venv) is None:
        return DriftPlan(), None

    res = run([uv_bin(), "sync", "--dry-run"], cwd=project_dir, timeout=120)
    text = res.text
    if res.code != 0:
        return DriftPlan(), text[:4000] or None

    counts = {m.group(1): int(m.group(2)) for m in re.finditer(
        r"Would (install|uninstall) (\d+) package", text
    )}
    bullets = [
        line.strip()[1:].strip()
        for line in text.splitlines()
        if line.strip().startswith("-")
    ]
    plan = DriftPlan(raw=text[:8000])
    uninstall_count = counts.get("uninstall", 0)
    install_count = counts.get("install", 0)
    if bullets and len(bullets) == uninstall_count and uninstall_count:
        plan.would_uninstall = bullets
    elif bullets and len(bullets) == install_count and install_count:
        plan.would_install = bullets
    elif bullets and uninstall_count == 0 and install_count:
        plan.would_install = bullets
    elif bullets:
        # Ambiguous: keep them as uninstalls (the usual drift case).
        plan.would_uninstall = bullets
    return plan, None


def _marker_applies(edge: PackageEdge, python_version: str | None) -> bool:
    if not edge.marker:
        return True
    env = _marker_env(python_version)
    match = _EXTRA_RE.search(edge.marker)
    env["extra"] = match.group(1) if match else (edge.extra or "")
    try:
        return bool(Marker(edge.marker).evaluate(env))
    except Exception:
        return True


def reconcile_drift(project, plan: DriftPlan) -> None:
    """`uv sync --dry-run` knows whether anything would actually change; marker
    gating explains lock packages that are not meant for this platform."""
    drift = project.drift
    if plan.raw and "would make no changes" in plan.raw.lower():
        drift.lock_only = []
        drift.venv_only = []
        drift.version_mismatch = []
        for node in project.nodes:
            if node.root:
                continue
            node.drift = "same" if node.installed_version else None
        return

    python_version = project.venv.python
    lock_only = set(drift.lock_only)
    applicable: set[str] = set()
    for edge in project.edges:
        if edge.target in lock_only and _marker_applies(edge, python_version):
            applicable.add(edge.target)
    applicable_names = {
        node.name for node in project.nodes if node.id in applicable
    }
    drift.lock_only = [name for name in drift.lock_only if name in applicable_names]
    own = normalize_name(project.name)
    drift.venv_only = [n for n in drift.venv_only if n != own]
    drift.version_mismatch = [
        row for row in drift.version_mismatch if row["name"] != own
    ]
    plan.would_uninstall = [
        item for item in plan.would_uninstall
        if item.split("==")[0].strip() != own
    ]
    plan.would_install = [
        item for item in plan.would_install
        if item.split("==")[0].strip() != own
    ]

    missing = set(drift.lock_only)
    mismatched = {row["name"] for row in drift.version_mismatch}
    for node in project.nodes:
        if node.root:
            continue
        if node.name in missing:
            node.drift = "missing"
        elif node.name in mismatched:
            node.drift = "version"
        elif node.installed_version:
            node.drift = "same"
        else:
            node.drift = None


def lock_check(project_dir: Path) -> tuple[bool | None, str | None]:
    # `uv lock --check` queries the project's `.venv` interpreter if it exists.
    # Redirect uv's project environment to a throwaway path outside the project
    # so a cloned repo cannot execute `.venv/bin/python`.
    env = str(Path(tempfile.gettempdir()) / f"pkgradar-lock-{uuid.uuid4().hex}")
    res = run(
        [uv_bin(), "lock", "--check"],
        cwd=project_dir,
        timeout=120,
        extra_env={"UV_PROJECT_ENVIRONMENT": env},
    )
    if res.code == 0:
        return True, None
    if res.code == 127:
        return None, None
    return False, res.text[:4000]

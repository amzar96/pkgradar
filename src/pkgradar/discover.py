from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "site-packages",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".cache",
    ".next",
    ".turbo",
    ".parcel-cache",
    "dist",
    "build",
    "target",
    "vendor",
    "htmlcov",
    ".idea",
    ".vscode",
    ".DS_Store",
    "webdist",
    ".eggs",
}

MAX_DEPTH = 7


@dataclass
class DiscoveredProject:
    path: Path
    rel_path: str
    name: str
    version: str = "0.0.0"
    python_requires: str | None = None
    pyproject: Path | None = None
    lock: Path | None = None
    venv: Path | None = None
    venv_broken: bool = False
    groups: list[str] = field(default_factory=list)
    workspace_members: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.rel_path.replace(os.sep, "/") or "."


def _read_pyproject(path: Path) -> dict:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except Exception:
        return {}


def _venv_python(venv: Path) -> Path | None:
    for candidate in (venv / "bin" / "python", venv / "Scripts" / "python.exe"):
        if candidate.exists():
            return candidate
    return None


def _looks_like_venv(path: Path) -> bool:
    return (path / "pyvenv.cfg").exists() or (path / "bin" / "python").exists() or (
        path / "Scripts" / "python.exe"
    ).exists()


def discover(root: Path, max_depth: int = MAX_DEPTH) -> tuple[list[DiscoveredProject], list[str]]:
    """Walk *root* and find uv projects plus .venv directories.

    Returns (projects, warnings). Broken venvs are surfaced, never raised.
    """
    root = root.expanduser().resolve()
    warnings: list[str] = []
    found: dict[Path, DiscoveredProject] = {}

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        try:
            depth = len(current.relative_to(root).parts)
        except ValueError:
            dirnames[:] = []
            continue

        # Collect venv directories before pruning them.
        for d in list(dirnames):
            if d in {".venv", "venv"}:
                vpath = current / d
                if not _looks_like_venv(vpath):
                    continue
                proj = found.get(current)
                if proj is None:
                    proj = DiscoveredProject(path=current, rel_path=_rel(current, root), name=current.name)
                    found[current] = proj
                if proj.venv is None:
                    proj.venv = vpath
                    proj.venv_broken = _venv_python(vpath) is None

        dirnames[:] = [
            d
            for d in dirnames
            if d not in IGNORE_DIRS and not d.endswith(".egg-info") and not d.startswith(".")
        ]

        if depth >= max_depth:
            dirnames[:] = []

        if "pyproject.toml" in filenames:
            pj = current / "pyproject.toml"
            data = _read_pyproject(pj)
            project_tbl = data.get("project", {}) or {}
            uv_tbl = data.get("tool", {}).get("uv", {}) or {}
            name = project_tbl.get("name") or current.name
            proj = found.get(current) or DiscoveredProject(
                path=current, rel_path=_rel(current, root), name=name
            )
            proj.name = name
            proj.version = str(project_tbl.get("version") or "0.0.0")
            proj.python_requires = project_tbl.get("requires-python")
            proj.pyproject = pj
            groups = list((project_tbl.get("optional-dependencies") or {}).keys())
            dep_groups = ((data.get("dependency-groups") or {}) if "dependency-groups" in data else {})
            if not dep_groups:
                dep_groups = (uv_tbl.get("dependency-groups") or {})
            groups.extend(list(dep_groups.keys()))
            proj.groups = ["main", *groups]
            ws = uv_tbl.get("workspace") or {}
            proj.workspace_members = list(ws.get("members") or [])
            lock = current / "uv.lock"
            if lock.exists():
                proj.lock = lock
            found[current] = proj

    # Attach a parent lock to workspace members that do not have their own.
    with_lock = {p.path for p in found.values() if p.lock}
    for proj in found.values():
        if proj.lock or not proj.pyproject:
            continue
        parent = proj.path.parent
        while parent != root and parent != parent.parent:
            if parent in with_lock:
                proj.lock = parent / "uv.lock"
                break
            parent = parent.parent

    projects = sorted(found.values(), key=lambda p: (p.rel_path.count("/"), p.rel_path))
    for proj in projects:
        if proj.venv and proj.venv_broken:
            warnings.append(f"Broken virtualenv (no interpreter): {proj.venv}")
        if proj.venv and not proj.pyproject and not proj.lock:
            warnings.append(f"VenV without pyproject/uv.lock: {proj.venv}")
    return projects, warnings


def _rel(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return str(path)
    return str(rel) if str(rel) != "." else "."

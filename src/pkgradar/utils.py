from __future__ import annotations

import re
from typing import Iterable

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

_NORM_RE = re.compile(r"[-_.]+")


def normalize_name(name: str) -> str:
    return _NORM_RE.sub("-", name).strip().lower()


def parse_version(value: str | None) -> Version | None:
    if not value:
        return None
    try:
        return Version(value)
    except InvalidVersion:
        return None


def parse_requirement(text: str) -> Requirement | None:
    try:
        return Requirement(text)
    except InvalidRequirement:
        return None


def classify_delta(current: str | None, latest: str | None) -> tuple[str, bool]:
    """Return (delta, breaking) for current -> latest."""
    cur, new = parse_version(current), parse_version(latest)
    if not cur or not new:
        return "unknown", False
    if new <= cur:
        return "none", False
    a, b = cur.release, new.release
    if a == b:
        return "other", False
    for idx in range(max(len(a), len(b))):
        x = a[idx] if idx < len(a) else 0
        y = b[idx] if idx < len(b) else 0
        if x != y:
            if idx == 0:
                return "major", True
            if idx == 1:
                # 0.x minor bumps are breaking in practice
                return "minor", a[0] == 0
            return "patch", False
    return "other", False


def releases_behind(current: str | None, versions: Iterable[str]) -> int | None:
    cur = parse_version(current)
    if not cur:
        return None
    count = 0
    for raw in versions:
        v = parse_version(raw)
        if not v or v.is_prerelease:
            continue
        if v > cur:
            count += 1
    return count


def best_satisfying(specifiers: list[str], versions: Iterable[str]) -> str | None:
    """Highest stable release satisfying every specifier string."""
    from packaging.specifiers import InvalidSpecifier, SpecifierSet

    sets = []
    for spec in specifiers:
        try:
            sets.append(SpecifierSet(spec))
        except InvalidSpecifier:
            continue
    if not sets:
        return None
    candidates = []
    for raw in versions:
        v = parse_version(raw)
        if not v or v.is_prerelease:
            continue
        if all(v in s for s in sets):
            candidates.append(v)
    if not candidates:
        return None
    return str(max(candidates))


def truncate(value: str, length: int = 90) -> str:
    value = " ".join(value.split())
    return value if len(value) <= length else value[: length - 1] + "…"

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx

from .models import Advisory
from .pypi import CACHE_ROOT, UA
from .utils import normalize_name, parse_version

OSV_TTL = 7 * 86400
SEVERITY_ORDER = {"CRITICAL": 4, "HIGH": 3, "MODERATE": 2, "MEDIUM": 2, "LOW": 1}


def _detail_path(vuln_id: str) -> Path:
    safe = vuln_id.replace("/", "_")
    return CACHE_ROOT / "osv" / f"{safe}.json"


def _load_detail(vuln_id: str) -> dict | None:
    path = _detail_path(vuln_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    if time.time() - payload.get("fetched", 0) > OSV_TTL:
        return None
    return payload.get("data")


def _save_detail(vuln_id: str, data: dict) -> None:
    path = _detail_path(vuln_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps({"fetched": time.time(), "data": data}))
    except Exception:
        pass


def _severity(vuln: dict) -> str | None:
    for affected in vuln.get("affected") or []:
        eco = affected.get("ecosystem_specific") or {}
        if eco.get("severity"):
            return str(eco["severity"]).upper()
    db = vuln.get("database_specific") or {}
    if db.get("severity"):
        return str(db["severity"]).upper()
    for sev in vuln.get("severity") or []:
        if sev.get("type") == "CVSS_V4" or sev.get("type") == "CVSS_V3":
            return "UNKNOWN"
    return None


def _fixed(vuln: dict, name: str) -> list[str]:
    fixed: list[str] = []
    for affected in vuln.get("affected") or []:
        pkg = affected.get("package") or {}
        if (pkg.get("ecosystem") or "").lower() != "pypi":
            continue
        if normalize_name(str(pkg.get("name", ""))) != name:
            continue
        for rng in affected.get("ranges") or []:
            for event in rng.get("events") or []:
                if event.get("fixed"):
                    fixed.append(str(event["fixed"]))
    return sorted({f for f in fixed if parse_version(f)}, key=lambda v: parse_version(v))


def parse_advisory(vuln: dict, name: str) -> Advisory:
    vuln_id = str(vuln.get("id", ""))
    aliases = [str(a) for a in (vuln.get("aliases") or [])]
    if vuln_id.startswith("GHSA"):
        url = f"https://github.com/advisories/{vuln_id}"
    else:
        url = f"https://osv.dev/vulnerability/{vuln_id}"
    return Advisory(
        id=vuln_id,
        aliases=aliases,
        summary=vuln.get("summary") or vuln.get("details", "")[:200] or None,
        severity=_severity(vuln),
        fixed=_fixed(vuln, name),
        url=url,
    )


async def fetch_advisories(
    packages: list[tuple[str, str]],
    offline: bool = False,
    progress=None,
) -> dict[tuple[str, str], list[Advisory]]:
    """packages: [(normalized_name, version)] -> advisories keyed by (name, version)."""
    out: dict[tuple[str, str], list[Advisory]] = {}
    if not packages:
        return out
    if offline:
        return out

    unique = sorted({(normalize_name(n), v) for n, v in packages if v and v != "?"})
    vuln_ids: set[str] = set()
    hits: dict[tuple[str, str], list[str]] = {}
    headers = {"User-Agent": UA, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
        for start in range(0, len(unique), 400):
            chunk = unique[start : start + 400]
            body = {
                "queries": [
                    {"package": {"name": name, "ecosystem": "PyPI"}, "version": version}
                    for name, version in chunk
                ]
            }
            try:
                res = await client.post("https://api.osv.dev/v1/querybatch", json=body)
                res.raise_for_status()
                results = res.json().get("results") or []
            except Exception:
                continue
            for (name, version), result in zip(chunk, results):
                ids = [str(v.get("id")) for v in (result.get("vulns") or []) if v.get("id")]
                if not ids:
                    continue
                hits[(name, version)] = ids
                vuln_ids.update(ids)

        if not vuln_ids:
            return out

        details: dict[str, dict] = {}
        to_fetch: list[str] = []
        for vuln_id in vuln_ids:
            cached = _load_detail(vuln_id)
            if cached is not None:
                details[vuln_id] = cached
            else:
                to_fetch.append(vuln_id)

        sem = asyncio.Semaphore(10)
        done = 0

        async def one(vuln_id: str) -> None:
            nonlocal done
            async with sem:
                try:
                    res = await client.get(f"https://api.osv.dev/v1/vulns/{vuln_id}")
                    if res.status_code == 200:
                        data = res.json()
                        details[vuln_id] = data
                        _save_detail(vuln_id, data)
                except Exception:
                    pass
                finally:
                    done += 1
                    if progress:
                        progress(done, len(to_fetch))

        await asyncio.gather(*(one(v) for v in to_fetch))

    for key, ids in hits.items():
        name = key[0]
        advisories = [parse_advisory(details[i], name) for i in ids if i in details]
        advisories.sort(
            key=lambda a: SEVERITY_ORDER.get((a.severity or "").upper(), 0), reverse=True
        )
        out[key] = advisories
    return out


def worst_severity(advisories: list[Advisory]) -> str | None:
    if not advisories:
        return None
    ranked = sorted(
        advisories, key=lambda a: SEVERITY_ORDER.get((a.severity or "").upper(), 0), reverse=True
    )
    return ranked[0].severity

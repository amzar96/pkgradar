from __future__ import annotations

import asyncio
import inspect
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .utils import normalize_name, parse_version

CACHE_ROOT = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "pkgradar"
PYPI_TTL = 24 * 3600
UA = "pkgradar/0.1 (+https://github.com/local/pkgradar)"


@dataclass
class PackageInfo:
    name: str
    available: bool = True
    latest: str | None = None
    latest_upload: str | None = None
    license: str | None = None
    summary: str | None = None
    yanked: bool = False
    requires_python: str | None = None
    deprecated: str | None = None
    homepage: str | None = None
    versions: list[str] = field(default_factory=list)
    offline: bool = False


def _cache_path(name: str) -> Path:
    safe = normalize_name(name).replace("/", "_")
    return CACHE_ROOT / "pypi" / f"{safe}.json"


def _load_cache(name: str, ttl: int | None) -> PackageInfo | None:
    path = _cache_path(name)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    fetched = payload.get("fetched", 0)
    if ttl is not None and time.time() - fetched > ttl:
        return None
    data = payload.get("data")
    if not data:
        return None
    return PackageInfo(**{**data, "versions": data.get("versions", [])})


def _save_cache(name: str, info: PackageInfo) -> None:
    path = _cache_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetched": time.time(), "data": info.__dict__}
    try:
        path.write_text(json.dumps(payload))
    except Exception:
        pass


def _license(info: dict) -> str | None:
    for key in ("license_expression", "license"):
        value = info.get(key)
        if value and 0 < len(value) <= 80 and value.lower() not in {"unknown", "none"}:
            return value
    for classifier in info.get("classifiers") or []:
        if classifier.startswith("License ::"):
            return classifier.split("::")[-1].strip()
    return None


def _deprecated(info: dict) -> str | None:
    for classifier in info.get("classifiers") or []:
        if classifier.strip() == "Development Status :: 7 - Inactive":
            return "Development Status :: 7 - Inactive"
    return None


def parse_pypi(name: str, payload: dict) -> PackageInfo:
    info = payload.get("info") or {}
    latest = info.get("version")
    releases = payload.get("releases") or {}
    urls = payload.get("urls") or []
    upload = None
    if urls:
        upload = urls[0].get("upload_time_iso_8601") or urls[0].get("upload_time")
    if not upload and latest and releases.get(latest):
        files = releases[latest]
        if files:
            upload = files[0].get("upload_time_iso_8601") or files[0].get("upload_time")
    versions = list(releases.keys())
    versions.sort(key=lambda v: (parse_version(v) or parse_version("0")), reverse=True)
    yanked = False
    if latest and releases.get(latest):
        yanked = all(bool(f.get("yanked")) for f in releases[latest])
    return PackageInfo(
        name=normalize_name(name),
        available=True,
        latest=latest,
        latest_upload=upload,
        license=_license(info),
        summary=(info.get("summary") or None),
        yanked=yanked,
        requires_python=info.get("requires_python"),
        deprecated=_deprecated(info),
        homepage=info.get("home_page") or (info.get("project_urls") or {}).get("Homepage"),
        versions=versions[:1000],
    )


async def _report(progress, done: int, total: int) -> None:
    if progress is None:
        return
    result = progress(done, total)
    if inspect.isawaitable(result):
        await result


class PyPIClient:
    def __init__(self, offline: bool = False, ttl: int = PYPI_TTL, concurrency: int = 12) -> None:
        self.offline = offline
        self.ttl = ttl
        self._sem = asyncio.Semaphore(concurrency)

    async def fetch_many(
        self,
        names: list[str],
        progress=None,
    ) -> dict[str, PackageInfo]:
        unique = sorted({normalize_name(n) for n in names})
        results: dict[str, PackageInfo] = {}
        pending: list[str] = []
        for name in unique:
            cached = _load_cache(name, None if self.offline else self.ttl)
            if cached is not None:
                cached.offline = self.offline and not cached.available
                results[name] = cached
            elif self.offline:
                results[name] = PackageInfo(name=name, available=False, offline=True)
            else:
                pending.append(name)
        if not pending:
            await _report(progress, len(results), len(results))
            return results

        headers = {"User-Agent": UA, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=25, headers=headers, follow_redirects=True) as client:
            done = len(results)

            async def one(name: str) -> None:
                nonlocal done
                info = await self._fetch(client, name)
                results[name] = info
                done += 1
                await _report(progress, done, len(unique))

            await asyncio.gather(*(one(name) for name in pending))
        return results

    async def _fetch(self, client: httpx.AsyncClient, name: str) -> PackageInfo:
        async with self._sem:
            for attempt in range(3):
                try:
                    res = await client.get(f"https://pypi.org/pypi/{name}/json")
                    if res.status_code == 404:
                        info = PackageInfo(name=name, available=False)
                        _save_cache(name, info)
                        return info
                    if res.status_code == 429:
                        await asyncio.sleep(2 * (attempt + 1))
                        continue
                    res.raise_for_status()
                    info = parse_pypi(name, res.json())
                    _save_cache(name, info)
                    return info
                except Exception:
                    if attempt == 2:
                        return PackageInfo(name=name, available=False)
                    await asyncio.sleep(0.6 * (attempt + 1))
        return PackageInfo(name=name, available=False)

from __future__ import annotations

import asyncio
import html
import inspect
import json
import os
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

import httpx
from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    parse_sdist_filename,
    parse_wheel_filename,
)

from .indexes import IndexConfig, default_indexes
from .utils import normalize_name, parse_version, safe_filename

CACHE_ROOT = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "pkgradar"
PYPI_TTL = 24 * 3600
UA = "pkgradar/0.1 (+https://github.com/local/pkgradar)"
MAX_BODY_BYTES = 32 * 1024 * 1024
MAX_VERSIONS = 1000


class _IndexSecurityError(Exception):
    """A redirect or URL that must not be followed."""


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
    index: str | None = None
    public: bool = True
    error: str | None = None


def _cache_path(index: IndexConfig, name: str) -> Path:
    safe = safe_filename(normalize_name(name), lower=True)
    if index.public:
        # Keep the historical PyPI path so existing caches keep working.
        return CACHE_ROOT / "pypi" / f"{safe}.json"
    return CACHE_ROOT / "indexes" / index.key / f"{safe}.json"


def _load_cache(index: IndexConfig, name: str, ttl: int | None) -> PackageInfo | None:
    path = _cache_path(index, name)
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
    if not isinstance(data, dict):
        return None
    try:
        info = PackageInfo(**{**data, "versions": data.get("versions", [])})
    except TypeError:
        return None
    info.index = index.name
    info.public = index.public
    return info


def _save_cache(index: IndexConfig, name: str, info: PackageInfo) -> None:
    path = _cache_path(index, name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
        payload = {
            "schema": 2,
            "index": index.redacted,
            "fetched": time.time(),
            "data": info.__dict__,
        }
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload))
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        os.replace(temp, path)
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


def parse_pypi(
    name: str,
    payload: dict,
    *,
    index: IndexConfig | None = None,
    public: bool | None = None,
) -> PackageInfo:
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
    is_public = index.public if public is None and index is not None else (public is not False)
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
        versions=versions[:MAX_VERSIONS],
        index=index.name if index else None,
        public=is_public,
    )


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, dict[str, str]]] = []
        self._attrs: dict[str, str] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag.lower() == "a":
            self._attrs = {key.lower(): value or "" for key, value in attrs}
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._attrs is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._attrs is not None:
            self.links.append(("".join(self._text).strip(), self._attrs))
            self._attrs = None
            self._text = []


def _version_from_filename(filename: str, name: str) -> str | None:
    lowered = filename.lower()
    try:
        if lowered.endswith(".whl"):
            parsed_name, version, _, _ = parse_wheel_filename(filename)
        elif lowered.endswith((".tar.gz", ".zip")):
            parsed_name, version = parse_sdist_filename(filename)
        else:
            return None
    except (InvalidWheelFilename, InvalidSdistFilename, ValueError):
        parsed_name = None
        version = None
    if parsed_name is not None and normalize_name(str(parsed_name)) != normalize_name(name):
        return None
    if version is not None:
        return str(version)
    # Fallback for sdists that packaging does not recognize (e.g. .tar.bz2).
    escaped = re.escape(normalize_name(name))
    match = re.match(
        rf"^{escaped}-(?P<version>[^-]+)\.(?:tar\.gz|tar\.bz2|zip)$",
        lowered,
    )
    return match.group("version") if match else None


def _sort_versions(versions: list[str]) -> list[str]:
    versions.sort(key=lambda value: (parse_version(value) or parse_version("0")), reverse=True)
    return versions[:MAX_VERSIONS]


def _simple_info(
    name: str,
    index: IndexConfig,
    versions: dict[str, list[dict]],
) -> PackageInfo:
    if not versions:
        return PackageInfo(name=normalize_name(name), available=False, index=index.name, public=index.public)

    ordered = _sort_versions(list(versions))
    latest = None
    # Prefer the newest stable, non-yanked release; fall back to a prerelease
    # only when the index has nothing else.
    for candidate in ordered:
        parsed = parse_version(candidate)
        if parsed is not None and parsed.is_prerelease:
            continue
        files = versions.get(candidate) or []
        if files and not all(bool(item.get("yanked")) for item in files):
            latest = candidate
            break
    if latest is None:
        for candidate in ordered:
            files = versions.get(candidate) or []
            if files and not all(bool(item.get("yanked")) for item in files):
                latest = candidate
                break
    if latest is None:
        latest = ordered[0]
    files = versions.get(latest) or []
    yanked = bool(files) and all(bool(item.get("yanked")) for item in files)
    requires_python = next(
        (item.get("requires_python") for item in files if item.get("requires_python")),
        None,
    )
    upload = next((item.get("upload_time") for item in files if item.get("upload_time")), None)
    return PackageInfo(
        name=normalize_name(name),
        available=True,
        latest=latest,
        latest_upload=upload,
        yanked=yanked,
        requires_python=requires_python,
        versions=ordered,
        index=index.name,
        public=index.public,
    )


def parse_simple_json(name: str, payload: dict, index: IndexConfig) -> PackageInfo:
    files = payload.get("files") or []
    versions: dict[str, list[dict]] = {}
    for item in files:
        if not isinstance(item, dict):
            continue
        filename = item.get("filename")
        if not isinstance(filename, str):
            continue
        version = _version_from_filename(filename, name)
        if version is None:
            continue
        versions.setdefault(version, []).append(
            {
                "yanked": bool(item.get("yanked")),
                "requires_python": item.get("requires-python"),
                "upload_time": item.get("upload-time"),
            }
        )
    return _simple_info(name, index, versions)


def parse_simple_html(
    name: str,
    body: str,
    index: IndexConfig,
    *,
    base_url: str | None = None,
) -> PackageInfo:
    parser = _LinkParser()
    try:
        parser.feed(body)
    except Exception:
        return PackageInfo(name=normalize_name(name), available=False, index=index.name, public=index.public)
    versions: dict[str, list[dict]] = {}
    for _text, attrs in parser.links:
        href = attrs.get("href")
        if not href:
            continue
        filename = urlsplit(urljoin(base_url or index.url, href)).path.rsplit("/", 1)[-1]
        filename = unquote(html.unescape(filename))
        version = _version_from_filename(filename, name)
        if version is None:
            continue
        yanked = "data-yanked" in attrs
        versions.setdefault(version, []).append(
            {
                "yanked": yanked,
                "requires_python": attrs.get("data-requires-python"),
                "upload_time": None,
            }
        )
    return _simple_info(name, index, versions)


async def _report(progress, done: int, total: int) -> None:
    if progress is None:
        return
    result = progress(done, total)
    if inspect.isawaitable(result):
        await result


class IndexClient:
    """Query one or more package indexes for release metadata.

    PyPI's legacy JSON API is preferred where available. Private indexes that
    only serve a PEP 503/691 simple endpoint are parsed from the simple index.
    """

    def __init__(
        self,
        indexes: list[IndexConfig] | None = None,
        *,
        offline: bool = False,
        ttl: int = PYPI_TTL,
        concurrency: int = 12,
        api: str = "auto",
        ca_bundle: str | None = None,
        timeout: float = 25.0,
    ) -> None:
        self.indexes = indexes or default_indexes(api=api, ca_bundle=ca_bundle)
        self.offline = offline
        self.ttl = ttl
        self.timeout = timeout
        self.ca_bundle = ca_bundle
        self._sem = asyncio.Semaphore(max(1, concurrency))
        self._clients: dict[bool | str, httpx.AsyncClient] = {}
        self.errors: dict[str, str] = {}

    def _client(self, index: IndexConfig) -> httpx.AsyncClient:
        verify: bool | str = index.ca_bundle or self.ca_bundle or True
        key: bool | str = verify
        client = self._clients.get(key)
        if client is None:
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                headers={"User-Agent": UA},
                follow_redirects=False,
                verify=verify,
            )
            self._clients[key] = client
        return client

    async def close(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()

    async def fetch_many(
        self,
        requests: list[tuple[IndexConfig, str]] | list[str],
        progress=None,
    ) -> dict[tuple[str, str], PackageInfo]:
        if requests and isinstance(requests[0], str):
            primary = self.indexes[0]
            requests = [(primary, name) for name in requests]  # type: ignore[list-item]
        unique: dict[tuple[str, str], tuple[IndexConfig, str]] = {}
        for index, name in requests:  # type: ignore[misc]
            normalized = normalize_name(name)
            unique[(index.key, normalized)] = (index, normalized)

        results: dict[tuple[str, str], PackageInfo] = {}
        pending: list[tuple[IndexConfig, str]] = []
        for (key, name), (index, _) in unique.items():
            cached = _load_cache(index, name, None if self.offline else self.ttl)
            if cached is not None:
                cached.offline = self.offline and not cached.available
                results[(key, name)] = cached
            elif self.offline:
                results[(key, name)] = PackageInfo(
                    name=name,
                    available=False,
                    offline=True,
                    index=index.name,
                    public=index.public,
                )
            else:
                pending.append((index, name))

        if not pending:
            await _report(progress, len(results), len(results))
            return results

        done = len(results)
        total = len(unique)

        async def one(index: IndexConfig, name: str) -> None:
            nonlocal done
            try:
                info = await self._fetch(index, name)
            except Exception as exc:  # pragma: no cover - defensive
                message = str(exc).replace(index.url, index.redacted)[:200]
                self.errors[index.name] = f"request failed: {message}"
                info = PackageInfo(
                    name=name,
                    available=False,
                    index=index.name,
                    public=index.public,
                    error=message,
                )
            results[(index.key, name)] = info
            done += 1
            await _report(progress, done, total)

        try:
            await asyncio.gather(*(one(index, name) for index, name in pending))
        finally:
            await self.close()
        return results

    def _json_url(self, index: IndexConfig, name: str) -> str:
        base = index.url.rstrip("/")
        if base.endswith("/simple"):
            base = base[: -len("/simple")]
        return f"{base}/pypi/{quote(name, safe='')}/json"

    def _simple_urls(self, index: IndexConfig, name: str) -> list[str]:
        base = index.url.rstrip("/")
        quoted = quote(normalize_name(name), safe="")
        candidates: list[str] = []
        if base.endswith("/simple"):
            candidates.append(f"{base}/{quoted}/")
        else:
            # Users often pass a repository root; try the conventional simple
            # suffix first, then the URL as-is.
            candidates.append(f"{base}/simple/{quoted}/")
            candidates.append(f"{base}/{quoted}/")
        return candidates

    async def _fetch(self, index: IndexConfig, name: str) -> PackageInfo:
        async with self._sem:
            if index.api != "simple" and (index.public or index.api == "json"):
                status, content_type, body = await self._request(
                    index,
                    self._json_url(index, name),
                    accept="application/json",
                )
                if status == 404 and index.api == "auto":
                    return await self._fetch_simple(index, name)
                if status in (401, 403):
                    return self._auth_error(index, name, status)
                if status == 200:
                    try:
                        payload = json.loads(body)
                        return parse_pypi(name, payload, index=index)
                    except Exception:
                        if index.api == "json":
                            self.errors[index.name] = "invalid JSON response"
                            return PackageInfo(
                                name=normalize_name(name),
                                available=False,
                                index=index.name,
                                public=index.public,
                                error="invalid JSON response",
                            )
                elif index.api == "json":
                    self.errors[index.name] = f"HTTP {status}"
                    return PackageInfo(
                        name=normalize_name(name),
                        available=False,
                        index=index.name,
                        public=index.public,
                        error=f"HTTP {status}",
                    )
            return await self._fetch_simple(index, name)

    async def _fetch_simple(self, index: IndexConfig, name: str) -> PackageInfo:
        last_error = None
        for url in self._simple_urls(index, name):
            status, content_type, body = await self._request(
                index,
                url,
                accept="application/vnd.pypi.simple.v1+json, text/html;q=0.9",
            )
            if status in (401, 403):
                return self._auth_error(index, name, status)
            if status == 404:
                continue
            if status != 200:
                last_error = f"HTTP {status}"
                continue
            try:
                if "json" in content_type:
                    payload = json.loads(body)
                    info = parse_simple_json(name, payload, index)
                else:
                    info = parse_simple_html(name, body, index, base_url=url)
            except Exception:
                last_error = "invalid simple index response"
                continue
            if info.available:
                return info
        info = PackageInfo(
            name=normalize_name(name),
            available=False,
            index=index.name,
            public=index.public,
            error=last_error,
        )
        if last_error:
            self.errors[index.name] = last_error
        else:
            # A 404 is a stable "not on this index" answer; cache it so a
            # repeated scan does not hammer the index for missing names.
            _save_cache(index, name, info)
        return info

    def _auth_error(self, index: IndexConfig, name: str, status: int) -> PackageInfo:
        message = f"authentication failed (HTTP {status})"
        self.errors[index.name] = message
        return PackageInfo(
            name=normalize_name(name),
            available=False,
            index=index.name,
            public=index.public,
            error=message,
        )

    async def _request(
        self,
        index: IndexConfig,
        url: str,
        *,
        accept: str,
    ) -> tuple[int, str, str]:
        client = self._client(index)
        auth = (
            httpx.BasicAuth(index.username, index.password or "")
            if index.username
            else None
        )
        origin = urlsplit(url).netloc
        current = url
        for _ in range(3):
            for attempt in range(3):
                try:
                    async with client.stream(
                        "GET",
                        current,
                        headers={"Accept": accept},
                        auth=auth,
                        follow_redirects=False,
                    ) as response:
                        if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                            retry = response.headers.get("retry-after")
                            delay = min(8.0, float(retry)) if retry and retry.isdigit() else 0.8 * (attempt + 1)
                            await asyncio.sleep(delay)
                            continue
                        if response.status_code in (301, 302, 303, 307, 308):
                            location = response.headers.get("location")
                            if not location:
                                return response.status_code, "", ""
                            target = urljoin(current, location)
                            target_parts = urlsplit(target)
                            if (
                                urlsplit(current).scheme == "https"
                                and target_parts.scheme != "https"
                            ):
                                raise _IndexSecurityError("refusing HTTPS downgrade")
                            if target_parts.netloc != origin:
                                raise _IndexSecurityError(
                                    "refusing cross-host redirect for package index"
                                )
                            current = target
                            break
                        content_type = response.headers.get("content-type", "")
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_BODY_BYTES:
                                raise ValueError("index response too large")
                            chunks.append(chunk)
                        return response.status_code, content_type, b"".join(chunks).decode("utf-8", "replace")
                except asyncio.CancelledError:
                    raise
                except _IndexSecurityError as exc:
                    self.errors[index.name] = str(exc)
                    return 0, "", ""
                except Exception as exc:
                    if attempt == 2:
                        message = str(exc).replace(index.url, index.redacted)[:200]
                        self.errors[index.name] = f"request failed: {message}"
                        return 0, "", ""
                    await asyncio.sleep(0.6 * (attempt + 1))
        return 0, "", ""


# Backwards-compatible name for callers that imported PyPIClient.
PyPIClient = IndexClient

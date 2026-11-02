from __future__ import annotations

import hashlib
import ipaddress
import netrc
import os
import re
import socket
from dataclasses import dataclass, field, replace
from urllib.parse import unquote, urlsplit, urlunsplit

from .models import IndexRef

DEFAULT_INDEX_URL = "https://pypi.org/simple/"
PUBLIC_INDEX_HOSTS = {"pypi.org"}
_INDEX_NAME_RE = re.compile(r"[^A-Za-z0-9]+")


@dataclass(frozen=True)
class IndexConfig:
    """A package index the scanner may query.

    ``url`` never contains credentials; they are kept separately so they cannot
    leak into logs, JSON, cache keys or the web UI.
    """

    name: str
    url: str
    source: str = "default"  # default | cli | env | project
    primary: bool = False
    explicit: bool = False
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    api: str = "auto"  # auto | json | simple
    ca_bundle: str | None = None

    @property
    def key(self) -> str:
        return index_key(self.url)

    @property
    def host(self) -> str:
        return (urlsplit(self.url).hostname or "").lower()

    @property
    def redacted(self) -> str:
        return redact_url(self.url)

    @property
    def public(self) -> bool:
        return self.host in PUBLIC_INDEX_HOSTS

    def to_ref(self) -> IndexRef:
        return IndexRef(
            name=self.name,
            url=self.redacted,
            source=self.source,  # type: ignore[arg-type]
            primary=self.primary,
        )


def _split_credentials(url: str) -> tuple[str, str | None, str | None]:
    parsed = urlsplit(url)
    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    clean = urlunsplit((parsed.scheme, host, parsed.path, parsed.query, ""))
    return clean, username, password


def normalize_index_url(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError("empty index URL")
    if "://" not in text:
        text = f"https://{text}"
    parsed = urlsplit(text)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError(f"unsupported index scheme: {scheme}")
    if not parsed.hostname:
        raise ValueError("index URL has no hostname")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    path = parsed.path or "/"
    if host == "pypi.org" and path in {"", "/", "/pypi", "/pypi/"}:
        path = "/simple/"
    if not path.endswith("/"):
        path = f"{path}/"
    return urlunsplit((scheme, host, path, parsed.query, ""))


def index_key(url: str) -> str:
    """Stable cache namespace for an index URL (credentials never included)."""
    canonical = normalize_index_url(url)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def redact_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "invalid-index-url"
    host = parsed.hostname or "unknown"
    if ":" in host:
        host = f"[{host}]"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    path = parsed.path or "/"
    query = "redacted" if parsed.query else ""
    return urlunsplit((parsed.scheme or "https", host, path, query, ""))


def _env_name(name: str) -> str:
    return _INDEX_NAME_RE.sub("_", name).strip("_").upper()


def _env_credentials(name: str, *, primary: bool) -> tuple[str | None, str | None]:
    keys = [f"UV_INDEX_{_env_name(name)}_USERNAME", f"PKGRADAR_INDEX_{_env_name(name)}_USERNAME"]
    passwords = [
        f"UV_INDEX_{_env_name(name)}_PASSWORD",
        f"PKGRADAR_INDEX_{_env_name(name)}_PASSWORD",
    ]
    if primary:
        keys += ["UV_INDEX_USERNAME", "PKGRADAR_INDEX_USERNAME"]
        passwords += ["UV_INDEX_PASSWORD", "PKGRADAR_INDEX_PASSWORD"]
    username = next((os.environ[key] for key in keys if os.environ.get(key)), None)
    password = next((os.environ[key] for key in passwords if os.environ.get(key)), None)
    return username, password


def _netrc_credentials(host: str) -> tuple[str | None, str | None]:
    try:
        auth = netrc.netrc().authenticators(host)
    except Exception:
        return None, None
    if not auth:
        return None, None
    login, _, password = auth
    return login or None, password or None


def _looks_private(host: str) -> bool:
    lowered = host.lower().rstrip(".")
    if lowered in {"localhost", "metadata.google.internal"} or lowered.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    )


def validate_untrusted_index(url: str) -> None:
    """Reject obvious SSRF targets in index URLs taken from a scanned repo."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if _looks_private(host):
        raise ValueError(f"refusing private/loopback index host: {host}")
    # A resolved hostname can still point at link-local metadata. This is only a
    # best-effort guard; the real protection is that project indexes are opt-in.
    try:
        for info in socket.getaddrinfo(host, None):
            address = ipaddress.ip_address(info[4][0])
            if address.is_link_local or address.is_loopback:
                raise ValueError(f"index host resolves to a local address: {host}")
    except (socket.gaierror, UnicodeError, ValueError) as exc:
        if isinstance(exc, ValueError):
            raise
        # Unresolvable hosts fail later with a normal network warning.


def _make_index(
    *,
    name: str,
    url: str,
    source: str,
    primary: bool,
    explicit: bool = False,
    api: str = "auto",
    ca_bundle: str | None = None,
    username: str | None = None,
    password: str | None = None,
) -> IndexConfig:
    clean, url_user, url_password = _split_credentials(url)
    normalized = normalize_index_url(clean)
    credential_name = name or (urlsplit(normalized).hostname or "")
    user = username or url_user
    secret = password or url_password
    if not user or not secret:
        env_user, env_password = _env_credentials(credential_name, primary=primary)
        user = user or env_user
        secret = secret or env_password
    if not user or not secret:
        netrc_user, netrc_password = _netrc_credentials(urlsplit(normalized).hostname or "")
        user = user or netrc_user
        secret = secret or netrc_password
    return IndexConfig(
        name=name or (urlsplit(normalized).hostname or "index"),
        url=normalized,
        source=source,
        primary=primary,
        explicit=explicit,
        username=user,
        password=secret,
        api=api,
        ca_bundle=ca_bundle,
    )


def _split_env_urls(value: str | None) -> list[str]:
    if not value:
        return []
    return [part for part in re.split(r"[\s,]+", value.strip()) if part]


def default_indexes(*, api: str = "auto", ca_bundle: str | None = None) -> list[IndexConfig]:
    return [
        _make_index(
            name="PyPI",
            url=DEFAULT_INDEX_URL,
            source="default",
            primary=True,
            api=api,
            ca_bundle=ca_bundle,
        )
    ]


def resolve_indexes(
    primary: str | None = None,
    extras: list[str] | None = None,
    *,
    api: str = "auto",
    ca_bundle: str | None = None,
) -> list[IndexConfig]:
    """Resolve CLI/env indexes. Project-local indexes are handled separately."""
    raw_primary = (
        primary
        or os.environ.get("PKGRADAR_INDEX_URL")
        or os.environ.get("UV_INDEX_URL")
    )
    cli_extras = list(extras or [])
    env_extras = _split_env_urls(
        os.environ.get("PKGRADAR_EXTRA_INDEX_URL") or os.environ.get("UV_EXTRA_INDEX_URL")
    )

    if not raw_primary:
        indexes = default_indexes(api=api, ca_bundle=ca_bundle)
    else:
        source = "cli" if primary else "env"
        indexes = [
            _make_index(
                name="",
                url=raw_primary,
                source=source,
                primary=True,
                api=api,
                ca_bundle=ca_bundle,
            )
        ]

    seen = {index.key for index in indexes}
    for raw, source in [(item, "cli") for item in cli_extras] + [
        (item, "env") for item in env_extras
    ]:
        if not raw:
            continue
        try:
            config = _make_index(
                name="",
                url=raw,
                source=source,
                primary=False,
                api=api,
                ca_bundle=ca_bundle,
            )
        except ValueError:
            continue
        if config.key in seen:
            continue
        seen.add(config.key)
        indexes.append(config)

    if not indexes:
        indexes = default_indexes(api=api, ca_bundle=ca_bundle)
    return _name_indexes(indexes)


def _name_indexes(indexes: list[IndexConfig]) -> list[IndexConfig]:
    used: set[str] = set()
    named: list[IndexConfig] = []
    for index in indexes:
        name = index.name
        if not name or name == "index" or (index.public and name == index.host):
            name = "PyPI" if index.public else (index.host or "index")
        base = name
        counter = 2
        while name.lower() in used:
            name = f"{base} ({counter})"
            counter += 1
        used.add(name.lower())
        named.append(replace(index, name=name))
    return named


def project_indexes(
    pyproject: dict,
    *,
    api: str = "auto",
    ca_bundle: str | None = None,
) -> tuple[list[IndexConfig], list[str]]:
    """Read opt-in ``[[tool.uv.index]]`` entries from a scanned pyproject."""
    uv = (pyproject.get("tool") or {}).get("uv") or {}
    entries = uv.get("index") or []
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return [], []

    warnings: list[str] = []
    configs: list[IndexConfig] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        name = str(entry.get("name") or "")
        if entry.get("explicit"):
            warnings.append(
                f"ignored explicit project index {redact_url(url)}: "
                "package sources are not resolved"
            )
            continue
        try:
            clean, _, _ = _split_credentials(url)
            validate_untrusted_index(clean)
            config = _make_index(
                name=name,
                url=url,
                source="project",
                primary=bool(entry.get("default")),
                explicit=bool(entry.get("explicit")),
                api=api,
                ca_bundle=ca_bundle,
            )
        except ValueError as exc:
            warnings.append(f"ignored project index {redact_url(url)}: {exc}")
            continue
        configs.append(config)

    if configs and not any(config.primary for config in configs):
        configs[0] = replace(configs[0], primary=True)
    return configs, warnings


def plan_for_project(
    local: list[IndexConfig], globals_: list[IndexConfig]
) -> list[IndexConfig]:
    """Project indexes take priority, then the configured global indexes."""
    if not local:
        return list(globals_)
    ordered: list[IndexConfig] = []
    seen: set[str] = set()
    for index in local:
        if index.key not in seen:
            seen.add(index.key)
            ordered.append(index)
    for index in globals_:
        if index.key not in seen:
            seen.add(index.key)
            ordered.append(index)
    # Exactly one primary per project.
    promoted = False
    final: list[IndexConfig] = []
    for index in ordered:
        primary = index.primary and not promoted
        if primary:
            promoted = True
        final.append(replace(index, primary=primary))
    if final and not promoted:
        final[0] = replace(final[0], primary=True)
    return final


def index_refs(indexes: list[IndexConfig]) -> list[IndexRef]:
    seen: set[str] = set()
    refs: list[IndexRef] = []
    primary_seen = False
    for index in indexes:
        if index.key in seen:
            continue
        seen.add(index.key)
        ref = index.to_ref()
        if ref.primary and primary_seen:
            ref = ref.model_copy(update={"primary": False})
        elif ref.primary:
            primary_seen = True
        refs.append(ref)
    return refs

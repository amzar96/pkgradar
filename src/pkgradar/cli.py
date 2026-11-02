from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__
from .indexes import resolve_indexes


def _add_index_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--index-url",
        default=None,
        help="primary package index (simple API root; default: PyPI)",
    )
    parser.add_argument(
        "--extra-index-url",
        action="append",
        default=[],
        metavar="URL",
        help="additional package index; may be repeated",
    )
    parser.add_argument(
        "--index-api",
        choices=["auto", "json", "simple"],
        default="auto",
        help="index protocol: legacy JSON where available, else PEP 503 simple",
    )
    parser.add_argument(
        "--trust-project-indexes",
        action="store_true",
        help="honor [[tool.uv.index]] from scanned pyproject.toml files",
    )
    parser.add_argument(
        "--index-ca-bundle",
        default=None,
        metavar="PATH",
        help="CA bundle for private package indexes",
    )
    parser.add_argument(
        "--index-timeout",
        type=float,
        default=25.0,
        metavar="SECONDS",
        help="per-request index timeout (default: 25)",
    )
    parser.add_argument(
        "--index-concurrency",
        type=int,
        default=12,
        metavar="N",
        help="concurrent index requests (default: 12)",
    )
    parser.add_argument(
        "--osv-include-private",
        action="store_true",
        help="send private-index package names to OSV (off by default)",
    )


def _add_scan_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("root", nargs="?", default=None, help="directory to scan (default: cwd)")
    parser.add_argument("--offline", action="store_true", help="use cached PyPI data only")
    parser.add_argument("--no-enrich", action="store_true", help="skip PyPI lookups")
    parser.add_argument("--no-advisories", action="store_true", help="skip OSV lookups")
    parser.add_argument("--fast", action="store_true", help="skip uv lock check / sync dry-run")
    _add_index_flags(parser)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pkgradar",
        description="Dependency radar for uv projects: graph, drift, conflicts, advisories.",
    )
    parser.add_argument("--version", action="version", version=f"pkgradar {__version__}")
    sub = parser.add_subparsers(dest="command")

    scan_parser = sub.add_parser("scan", help="scan once and print a report")
    _add_scan_flags(scan_parser)
    scan_parser.add_argument("--json", dest="json_out", help="write full result JSON to a file")
    scan_parser.add_argument("--quiet", action="store_true", help="only print the JSON")

    serve_parser = sub.add_parser("serve", help="start the web UI")
    serve_parser.add_argument("root", nargs="?", default=None, help="directory to scan (default: cwd)")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=6767)
    serve_parser.add_argument("--open", action="store_true", help="open a browser")
    serve_parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="allow binding a non-loopback host (exposes the UI to your network)",
    )
    _add_index_flags(serve_parser)

    tui_parser = sub.add_parser("tui", help="start the terminal UI")
    _add_scan_flags(tui_parser)
    tui_parser.add_argument(
        "--theme",
        choices=["dark", "light"],
        default=None,
        help="TUI theme (default: dark, or PKGRADAR_THEME)",
    )

    args = parser.parse_args(argv)

    if args.command in (None, "serve"):
        if args.command is None:
            # Re-parse as serve so `pkgradar` alone just works.
            args = parser.parse_args(["serve", *(argv or sys.argv[1:])])
        return _serve(args)
    if args.command == "scan":
        return _scan(args)
    if args.command == "tui":
        return _tui(args)
    parser.print_help()
    return 1


def _root(value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else Path.cwd().resolve()


def _indexes(args: argparse.Namespace):
    try:
        return resolve_indexes(
            args.index_url,
            args.extra_index_url,
            api=args.index_api,
            ca_bundle=args.index_ca_bundle,
        )
    except ValueError as exc:
        print(f"pkgradar: invalid index configuration: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


def _scan(args: argparse.Namespace) -> int:
    from rich.console import Console
    from rich.markup import escape

    from .scanner import scan_sync

    console = Console()
    root = _root(args.root)
    if not args.quiet:
        console.print(f"[bold]pkgradar[/bold] scanning [cyan]{escape(str(root))}[/cyan]")
    indexes = _indexes(args)
    result = scan_sync(
        root,
        offline=args.offline,
        enrich=not args.no_enrich,
        advisories=not args.no_advisories,
        deep=not args.fast,
        indexes=indexes,
        trust_project_indexes=args.trust_project_indexes,
        index_api=args.index_api,
        index_ca_bundle=args.index_ca_bundle,
        index_timeout=args.index_timeout,
        index_concurrency=args.index_concurrency,
        osv_include_private=args.osv_include_private,
    )

    if args.json_out:
        Path(args.json_out).expanduser().write_text(
            json.dumps(result.model_dump(mode="json"), indent=2)
        )
        if not args.quiet:
            console.print(f"wrote [cyan]{escape(args.json_out)}[/cyan]")

    if not args.quiet:
        _print_report(console, result)
    elif args.json_out is None:
        print(json.dumps(result.model_dump(mode="json"), indent=2))
    return 0


def _print_report(console, result) -> None:
    from rich.markup import escape
    from rich.table import Table

    stats = result.stats
    console.print(
        f"\n[bold]{stats.projects}[/bold] projects · [bold]{stats.packages}[/bold] packages "
        f"([bold]{stats.unique_packages}[/bold] unique) · [yellow]{stats.outdated}[/yellow] outdated · "
        f"[red]{stats.advisories}[/red] advisories · [magenta]{stats.conflicts}[/magenta] conflicts · "
        f"[cyan]{stats.drifted_projects}[/cyan] drifted · {stats.duration_ms} ms\n"
    )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("project", style="cyan", no_wrap=True)
    table.add_column("pkgs", justify="right")
    table.add_column("outdated", justify="right", style="yellow")
    table.add_column("major", justify="right", style="red")
    table.add_column("adv", justify="right", style="red")
    table.add_column("drift", justify="right", style="magenta")
    table.add_column("venv")
    table.add_column("lock")
    for project in result.projects:
        venv = (
            "broken"
            if project.venv.broken
            else (project.venv.python or "none")
        )
        if not project.lock.exists:
            lock = "none"
        elif project.lock.stale is True:
            lock = "ok"
        elif project.lock.stale is False:
            lock = "stale"
        else:
            lock = "?"
        table.add_row(
            escape(project.rel_path),
            str(project.stats.packages),
            str(project.stats.outdated),
            str(project.stats.major),
            str(project.stats.advisories),
            str(project.stats.drift),
            escape(venv),
            lock,
        )
    console.print(table)

    if result.skew:
        console.print("\n[bold]Version skew across projects[/bold]")
        for row in result.skew[:8]:
            versions = ", ".join(
                f"{escape(pid)}={escape(v)}" for pid, v in list(row.versions.items())[:4]
            )
            console.print(
                f"  [cyan]{escape(row.name)}[/cyan] ({row.spread} versions) {versions}"
            )

    if result.conflicts:
        console.print("\n[bold]Conflicts[/bold]")
        for conflict in result.conflicts[:12]:
            colour = {"high": "red", "medium": "yellow", "low": "cyan"}.get(
                conflict.severity, "white"
            )
            console.print(
                f"  [{colour}]{conflict.severity:<6}[/{colour}] "
                f"[cyan]{escape(conflict.project_id)}[/cyan] {escape(conflict.title)}"
            )
            for blame in conflict.blame[:4]:
                console.print(
                    f"           {escape(blame.parent)} requires "
                    f"{escape(blame.spec or 'any')} "
                    f"(resolved {escape(blame.resolved or '?')})"
                )


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app

    loopback = args.host in {"127.0.0.1", "localhost", "::1"}
    if not loopback and not args.allow_remote:
        print(
            f"refusing to bind {args.host}: pass --allow-remote to expose pkgradar "
            "on a non-loopback interface",
            file=sys.stderr,
        )
        return 2
    if not loopback:
        print(
            f"warning: binding {args.host} exposes an unauthenticated, read-only "
            "dependency scanner to your network",
            file=sys.stderr,
        )

    root = _root(args.root)
    indexes = _indexes(args)
    app = create_app(
        root,
        allow_remote=not loopback,
        indexes=indexes,
        trust_project_indexes=args.trust_project_indexes,
        index_api=args.index_api,
        index_ca_bundle=args.index_ca_bundle,
        index_timeout=args.index_timeout,
        index_concurrency=args.index_concurrency,
        osv_include_private=args.osv_include_private,
    )
    url = f"http://{args.host}:{args.port}"
    print(f"pkgradar {__version__} -> {url}  (root: {root})")
    if args.open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _tui(args: argparse.Namespace) -> int:
    from .tui import run_tui

    indexes = _indexes(args)
    return run_tui(
        _root(args.root),
        offline=args.offline,
        enrich=not args.no_enrich,
        advisories=not args.no_advisories,
        deep=not args.fast,
        theme=args.theme,
        indexes=indexes,
        trust_project_indexes=args.trust_project_indexes,
        index_api=args.index_api,
        index_ca_bundle=args.index_ca_bundle,
        index_timeout=args.index_timeout,
        index_concurrency=args.index_concurrency,
        osv_include_private=args.osv_include_private,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.markup import escape
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)

from .models import PackageNode, Project, ScanResult
from .scanner import scan_sync

SEVERITY = {"high": "red", "medium": "yellow", "low": "cyan"}
DELTA = {
    "major": "red",
    "minor": "yellow",
    "patch": "green",
    "other": "cyan",
    "none": "green",
    "unknown": "dim",
}


def _ref(node: PackageNode) -> str:
    return f"{escape(node.name)}@{node.version}"


def _node_label(node: PackageNode) -> str:
    bits = [f"[bold]{escape(node.name)}[/bold]", f"[dim]{node.version}[/dim]"]
    if node.root:
        bits.append("[cyan]project[/cyan]")
    elif node.delta in ("major", "minor", "patch", "other"):
        bits.append(f"[{DELTA[node.delta]}]{node.delta}[/]")
    if node.advisories:
        bits.append(f"[red]{len(node.advisories)} cve[/red]")
    if node.drift and node.drift not in ("same", None):
        bits.append(f"[magenta]{node.drift}[/magenta]")
    if node.direct and not node.root:
        bits.append("[dim]direct[/dim]")
    if node.group not in ("main", None):
        bits.append(f"[dim]{escape(node.group)}[/dim]")
    return "  ".join(bits)


def _bar(value: float, width: int = 12) -> str:
    filled = max(0, min(width, round(value * width)))
    colour = "red" if value >= 0.75 else "yellow" if value >= 0.45 else "green"
    return f"[{colour}]{'━' * filled}[/{colour}][dim]{'━' * (width - filled)}[/dim]"


class PkgRadarApp(App):
    """Terminal twin of the pkgradar web UI."""

    TITLE = "pkgradar"
    SUB_TITLE = "dependency radar"

    CSS = """
    Screen { background: #07080b; color: #d6dde6; }
    Header { background: #0b0f14; color: #d6dde6; }
    Footer { background: #0b0f14; color: #6b7785; }
    TabbedContent { background: #07080b; }
    ContentSwitcher { background: #07080b; }
    DataTable { height: 1fr; background: #07080b; }
    DataTable > .datatable--header { background: #0b0f14; color: #8b98a5; }
    DataTable > .datatable--cursor { background: #16202b; color: #e6edf3; }
    Tree { width: 58%; height: 1fr; background: #07080b; padding: 0 1; }
    Tree > .tree--cursor { background: #16202b; color: #e6edf3; }
    #inspector-scroll { width: 42%; height: 1fr; border-left: solid #1c2633;
                        background: #090c10; }
    #inspector { padding: 1 2; }
    #status { height: 1; background: #0b0f14; color: #6b7785; padding: 0 1; }
    .summary { height: auto; padding: 1 2; color: #8b98a5; }
    .empty { padding: 2; color: #6b7785; }
    """

    BINDINGS = [
        Binding("1", "show_tab('fleet')", "Fleet", priority=True),
        Binding("2", "show_tab('topology')", "Topology", priority=True),
        Binding("3", "show_tab('conflicts')", "Conflicts", priority=True),
        Binding("4", "show_tab('skew')", "Skew", priority=True),
        Binding("r", "rescan", "Rescan"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        root: Path,
        *,
        offline: bool = False,
        enrich: bool = True,
        advisories: bool = True,
        deep: bool = True,
    ) -> None:
        super().__init__()
        self.root = root
        self.offline = offline
        self.enrich = enrich
        self.advisories = advisories
        self.deep = deep
        self.result: ScanResult | None = None
        self._incoming: dict[str, dict[str, list[Any]]] = {}
        self._tree_budget = 0

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="fleet"):
            with TabPane("Fleet", id="fleet"):
                yield Static("loading…", id="fleet-summary", classes="summary")
                yield DataTable(id="fleet-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Topology", id="topology"):
                with Horizontal():
                    yield Tree("projects", id="tree")
                    with VerticalScroll(id="inspector-scroll"):
                        yield Static("select a package", id="inspector")
            with TabPane("Conflicts", id="conflicts"):
                yield Static("loading…", id="conflict-summary", classes="summary")
                yield DataTable(id="conflict-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Skew", id="skew"):
                yield Static("loading…", id="skew-summary", classes="summary")
                yield DataTable(id="skew-table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#fleet-table", DataTable).add_columns(
            "project", "pkgs", "outdated", "major", "adv", "drift", "venv", "lock"
        )
        self.query_one("#conflict-table", DataTable).add_columns(
            "sev", "project", "kind", "conflict", "blame"
        )
        self.query_one("#skew-table", DataTable).add_columns(
            "package", "latest", "spread", "versions"
        )
        self.scan()

    # ------------------------------------------------------------------- scan
    @work(thread=True, exclusive=True)
    def scan(self) -> None:
        self.call_from_thread(self._set_status, f"scanning {self.root} …")

        def progress(event: str, data: dict[str, Any]) -> None:
            if event != "progress":
                return
            message = data.get("message") or data.get("phase") or ""
            done, total = data.get("done"), data.get("total")
            suffix = f"  {done}/{total}" if total else ""
            self.call_from_thread(self._set_status, f"{message}{suffix}")

        try:
            result = scan_sync(
                self.root,
                offline=self.offline,
                enrich=self.enrich,
                advisories=self.advisories,
                deep=self.deep,
                on_event=progress,
            )
        except Exception as error:  # pragma: no cover - surfaced in the UI
            self.call_from_thread(self._fail, error)
            return
        self.call_from_thread(self._apply, result)

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(escape(text))

    def _fail(self, error: Exception) -> None:
        self._set_status(f"scan failed: {error}")
        self.notify(str(error), severity="error", timeout=8)

    def _apply(self, result: ScanResult) -> None:
        self.result = result
        stats = result.stats
        self._set_status(
            f"{stats.projects} projects · {stats.packages} packages · "
            f"{stats.outdated} outdated · {stats.advisories} advisories · "
            f"{stats.conflicts} conflicts · {stats.duration_ms} ms"
        )
        self._fill_fleet(result)
        self._fill_conflicts(result)
        self._fill_skew(result)
        self._fill_tree(result)

    # ------------------------------------------------------------------- fleet
    def _fill_fleet(self, result: ScanResult) -> None:
        stats = result.stats
        self.query_one("#fleet-summary", Static).update(
            f"[bold]{stats.projects}[/bold] projects · "
            f"[bold]{stats.packages}[/bold] packages "
            f"([bold]{stats.unique_packages}[/bold] unique) · "
            f"[yellow]{stats.outdated}[/yellow] outdated · "
            f"[red]{stats.advisories}[/red] advisories · "
            f"[magenta]{stats.conflicts}[/magenta] conflicts · "
            f"[cyan]{stats.drifted_projects}[/cyan] drifted"
        )
        table = self.query_one("#fleet-table", DataTable)
        table.clear()
        for project in result.projects:
            lock = "—"
            if project.lock.exists:
                lock = "ok" if project.lock.stale is not False else (
                    "stale" if project.lock.stale is False else "?"
                )
            venv = "broken" if project.venv.broken else (project.venv.python or "none")
            table.add_row(
                project.rel_path,
                str(project.stats.packages),
                str(project.stats.outdated),
                f"[red]{project.stats.major}[/red]" if project.stats.major else "0",
                f"[red]{project.stats.advisories}[/red]" if project.stats.advisories else "0",
                f"[magenta]{project.stats.drift}[/magenta]" if project.stats.drift else "0",
                venv,
                lock,
                key=project.id,
            )

    # --------------------------------------------------------------- conflicts
    def _fill_conflicts(self, result: ScanResult) -> None:
        drift = sum(1 for conflict in result.conflicts if conflict.kind == "drift")
        self.query_one("#conflict-summary", Static).update(
            f"[bold]{len(result.conflicts)}[/bold] conflicts · "
            f"[magenta]{drift}[/magenta] drift · "
            f"[yellow]{len(result.conflicts) - drift}[/yellow] solver/constraint"
        )
        table = self.query_one("#conflict-table", DataTable)
        table.clear()
        for conflict in result.conflicts:
            blame = " · ".join(
                f"{escape(item.parent)} {escape(item.spec or '')}".strip()
                for item in conflict.blame[:3]
            )
            table.add_row(
                f"[{SEVERITY.get(conflict.severity, 'white')}]{conflict.severity}[/]",
                escape(conflict.project_id),
                conflict.kind,
                escape(conflict.title),
                escape(blame or conflict.detail),
                key=conflict.id,
            )

    # -------------------------------------------------------------------- skew
    def _fill_skew(self, result: ScanResult) -> None:
        self.query_one("#skew-summary", Static).update(
            f"[bold]{len(result.skew)}[/bold] packages resolve to more than one version "
            f"across {result.stats.projects} projects"
        )
        table = self.query_one("#skew-table", DataTable)
        table.clear()
        for row in result.skew:
            items = list(row.versions.items())
            versions = "  ".join(
                f"[cyan]{escape(pid)}[/cyan]={version}" for pid, version in items[:4]
            )
            if len(items) > 4:
                versions += f"  [dim]+{len(items) - 4} more[/dim]"
            table.add_row(
                escape(row.name),
                escape(row.latest or "?"),
                f"[yellow]{row.spread}[/yellow]",
                versions,
                key=row.name,
            )

    # ---------------------------------------------------------------- topology
    def _fill_tree(self, result: ScanResult) -> None:
        tree = self.query_one("#tree", Tree)
        tree.clear()
        if not result.projects:
            self.query_one("#inspector", Static).update("no projects found")
            return
        for project in result.projects:
            incoming: dict[str, list[Any]] = {}
            for edge in project.edges:
                incoming.setdefault(edge.target, []).append(edge)
            self._incoming[project.id] = incoming
            project_node = tree.root.add(
                f"[bold]{escape(project.rel_path)}[/bold] "
                f"[dim]{project.version} · {project.stats.packages} pkgs[/dim]",
                data={"project": project, "node": None},
                expand=project is result.projects[0],
            )
            nodes = {node.id: node for node in project.nodes}
            self._tree_budget = 2000
            self._add_children(project_node, project, nodes, "root", set(), 0)
            if self._tree_budget <= 0:
                project_node.add(
                    "[dim](tree truncated — open the web UI for the full graph)[/dim]"
                )
        tree.root.expand()
        first = result.projects[0]
        self._show_project(first)

    def _add_children(
        self,
        parent,
        project: Project,
        nodes: dict[str, PackageNode],
        source_id: str,
        seen: set[str],
        depth: int,
    ) -> None:
        if depth > 10 or self._tree_budget <= 0:
            return
        for edge in project.edges:
            if edge.source != source_id:
                continue
            child = nodes.get(edge.target)
            if child is None or child.id in seen or child.root:
                continue
            self._tree_budget -= 1
            branch = seen | {child.id}
            branch_node = parent.add(
                _node_label(child),
                data={"project": project, "node": child},
                expand=False,
            )
            self._add_children(branch_node, project, nodes, child.id, branch, depth + 1)

    # --------------------------------------------------------------- inspector
    @on(Tree.NodeHighlighted, "#tree")
    def _on_tree_highlight(self, event: Tree.NodeHighlighted) -> None:
        data = event.node.data or {}
        project: Project | None = data.get("project")
        node: PackageNode | None = data.get("node")
        if project is None:
            return
        if node is None:
            self._show_project(project)
        else:
            self._show_node(project, node)

    def _show_project(self, project: Project) -> None:
        stats = project.stats
        lines = [
            f"[bold]{escape(project.rel_path)}[/bold]  [dim]{project.version}[/dim]",
            f"[dim]{escape(project.path)}[/dim]",
            "",
            f"[bold]{stats.packages}[/bold] packages · [bold]{stats.direct}[/bold] direct · "
            f"depth {stats.max_depth}",
            f"[yellow]{stats.outdated}[/yellow] outdated · [red]{stats.major}[/red] major · "
            f"[red]{stats.advisories}[/red] advisories",
            f"[magenta]{stats.drift}[/magenta] drift · "
            f"[cyan]{stats.conflicts}[/cyan] conflicts",
            "",
            f"venv  [dim]{escape(project.venv.python or 'none')}[/dim]"
            f"  ({project.venv.installed} installed)",
            f"lock  [dim]{'present' if project.lock.exists else 'missing'}[/dim]"
            f"  ({project.lock.packages} packages"
            f"{', stale' if project.lock.stale is False else ''})",
        ]
        if project.venv.broken:
            lines.append("[red]venv interpreter is broken[/red]")
        self.query_one("#inspector", Static).update("\n".join(lines))

    def _show_node(self, project: Project, node: PackageNode) -> None:
        delta = DELTA.get(node.delta, "dim")
        lines = [
            f"[bold]{escape(node.name)}[/bold]  [dim]{node.version}[/dim]",
            f"[dim]{escape(project.rel_path)} · {escape(node.group)} · "
            f"depth {node.depth}{' · direct' if node.direct else ''}[/dim]",
            "",
        ]
        if node.latest:
            change = f"[{delta}]{node.delta}[/]" if node.delta not in ("none", "unknown") else "[green]current[/green]"
            behind = f" · {node.releases_behind} behind" if node.releases_behind else ""
            lines.append(f"latest   [bold]{node.latest}[/bold]  {change}{behind}")
        else:
            lines.append("latest   [dim]unknown[/dim]")
        if node.installed_version:
            lines.append(
                f"installed [bold]{node.installed_version}[/bold]  "
                f"[magenta]{node.drift or 'same'}[/magenta]"
            )
        lines.append(f"weight   {_bar(node.risk)}  {node.risk:.2f} · {node.dependents} dependents")
        if node.license:
            lines.append(f"license  [dim]{escape(node.license)}[/dim]")
        if node.yanked:
            lines.append("[red]yanked release[/red]")
        if node.deprecated:
            lines.append(f"[red]deprecated: {escape(node.deprecated)}[/red]")

        if node.risk_factors:
            lines.append("")
            lines.append("[bold]risk[/bold]")
            for factor in node.risk_factors[:6]:
                lines.append(f"  · {escape(factor.label)}  [dim]+{factor.weight:.2f}[/dim]")

        if node.advisories:
            lines.append("")
            lines.append(f"[bold red]{len(node.advisories)} advisories[/bold red]")
            for advisory in node.advisories[:6]:
                severity = advisory.severity or "?"
                colour = "red" if severity.lower() in ("high", "critical") else "yellow"
                summary = advisory.summary or advisory.id
                lines.append(
                    f"  [{colour}]{escape(advisory.id)}[/{colour}] "
                    f"[dim]{escape(severity)} · {escape(summary)[:70]}[/dim]"
                )
            if len(node.advisories) > 6:
                lines.append(f"  [dim]+{len(node.advisories) - 6} more[/dim]")
            if node.fixed_in:
                lines.append(f"  [green]fixed in {node.fixed_in}[/green]")

        incoming = self._incoming.get(project.id, {}).get(node.id, [])
        if incoming:
            lines.append("")
            lines.append("[bold]required by[/bold]")
            for edge in incoming[:10]:
                parent = next(
                    (item for item in project.nodes if item.id == edge.source), None
                )
                name = parent.name if parent else edge.source
                lines.append(
                    f"  [cyan]{escape(name)}[/cyan] "
                    f"[dim]{escape(edge.spec or 'any')}[/dim]"
                    f"  [dim]{edge.kind}[/dim]"
                )
            if len(incoming) > 10:
                lines.append(f"  [dim]+{len(incoming) - 10} more[/dim]")

        if node.summary:
            lines.append("")
            lines.append(f"[dim]{escape(node.summary)}[/dim]")

        self.query_one("#inspector", Static).update("\n".join(lines))

    # ------------------------------------------------------------------ actions
    def action_show_tab(self, name: str) -> None:
        if self.focused is not None:
            # TabbedContent re-activates the pane that owns the focused widget,
            # so release focus before switching away from it.
            self.focused.blur()
        self.query_one(TabbedContent).active = name
        self.call_after_refresh(self._focus_pane, name)

    def _focus_pane(self, name: str) -> None:
        try:
            pane = self.query_one(TabbedContent).get_pane(name)
        except Exception:  # pragma: no cover - defensive
            return
        for widget in pane.query("*"):
            if widget.focusable:
                widget.focus()
                return

    def action_rescan(self) -> None:
        for table_id in ("#fleet-table", "#conflict-table", "#skew-table"):
            self.query_one(table_id, DataTable).clear()
        self.query_one("#tree", Tree).clear()
        self.scan()


def run_tui(
    root: Path,
    *,
    offline: bool = False,
    enrich: bool = True,
    advisories: bool = True,
    deep: bool = True,
) -> int:
    app = PkgRadarApp(
        root, offline=offline, enrich=enrich, advisories=advisories, deep=deep
    )
    app.run()
    return 0

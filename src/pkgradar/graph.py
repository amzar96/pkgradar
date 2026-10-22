from __future__ import annotations

from collections import defaultdict

from .models import PackageEdge, PackageNode, Stats
from .utils import normalize_name


class GraphBuilder:
    def __init__(self, project_name: str, project_version: str = "0.0.0") -> None:
        self.nodes: dict[str, PackageNode] = {}
        self.edges: list[PackageEdge] = []
        self._edge_keys: set[tuple] = set()
        self.root_name = project_name
        self.root_id = "root"
        self.nodes[self.root_id] = PackageNode(
            id=self.root_id,
            name=project_name,
            version=project_version,
            root=True,
            depth=0,
            direct=True,
            group="main",
        )
        self._extras: dict[str, set[str]] = defaultdict(set)

    def add_node(
        self,
        name: str,
        version: str,
        *,
        group: str = "main",
        source: str = "registry",
        marker: str | None = None,
    ) -> str:
        norm = normalize_name(name)
        node_id = f"{norm}@{version}" if version else norm
        node = self.nodes.get(node_id)
        if node is None:
            node = PackageNode(
                id=node_id,
                name=norm,
                version=version,
                group=group,
                source=source,
                marker=marker,
            )
            self.nodes[node_id] = node
        return node_id

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        *,
        spec: str | None = None,
        kind: str = "runtime",
        group: str | None = None,
        extra: str | None = None,
        marker: str | None = None,
        resolved: bool = True,
    ) -> None:
        if source_id == target_id or target_id not in self.nodes:
            return
        key = (source_id, target_id, kind, extra, spec)
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self.edges.append(
            PackageEdge(
                id=f"e{len(self.edges)}",
                source=source_id,
                target=target_id,
                spec=spec or None,
                kind=kind,
                group=group,
                extra=extra,
                marker=marker,
                resolved=resolved,
            )
        )
        if extra:
            self._extras[target_id].add(extra)

    def finalize(self) -> tuple[list[PackageNode], list[PackageEdge], Stats]:
        adjacency: dict[str, list[PackageEdge]] = defaultdict(list)
        for edge in self.edges:
            adjacency[edge.source].append(edge)

        depth: dict[str, int] = {self.root_id: 0}
        group: dict[str, str] = {self.root_id: "main"}
        queue = [self.root_id]
        while queue:
            current = queue.pop(0)
            for edge in adjacency.get(current, []):
                child = edge.target
                if child in depth:
                    if depth[current] + 1 < depth[child]:
                        depth[child] = depth[current] + 1
                    continue
                depth[child] = depth[current] + 1
                group[child] = edge.group or ("dev" if edge.kind == "dev" else group[current])
                queue.append(child)

        # Orphans (present in lock but unreachable from the root) hang off root
        # so the rendered graph never floats apart.
        for node_id in list(self.nodes):
            if node_id != self.root_id and node_id not in depth:
                self.add_edge(self.root_id, node_id, kind="inferred", resolved=False)
                depth[node_id] = 1
                group[node_id] = "main"

        incoming: dict[str, int] = defaultdict(int)
        for edge in self.edges:
            incoming[edge.target] += 1

        for node_id, node in self.nodes.items():
            node.depth = depth.get(node_id, 99)
            if node_id != self.root_id:
                node.group = group.get(node_id, node.group)
            node.direct = node.root or any(
                e.source == self.root_id for e in self.edges if e.target == node_id
            )
            node.extras = sorted(self._extras.get(node_id, set()))
            node.dependents = incoming.get(node_id, 0)

        adjacency = defaultdict(list)
        for edge in self.edges:
            adjacency[edge.source].append(edge)

        color: dict[str, int] = {}
        cycles = 0

        def dfs(node_id: str) -> None:
            nonlocal cycles
            color[node_id] = 1
            for edge in adjacency.get(node_id, []):
                state = color.get(edge.target, 0)
                if state == 1:
                    cycles += 1
                elif state == 0:
                    dfs(edge.target)
            color[node_id] = 2

        for node_id in self.nodes:
            if color.get(node_id, 0) == 0:
                dfs(node_id)

        by_name: dict[str, set[str]] = defaultdict(set)
        for node in self.nodes.values():
            if not node.root:
                by_name[node.name].add(node.version)
        duplicates = sum(1 for versions in by_name.values() if len(versions) > 1)

        stats = Stats(
            packages=len(self.nodes) - 1,
            direct=sum(1 for n in self.nodes.values() if n.direct and not n.root),
            max_depth=max((n.depth for n in self.nodes.values() if n.depth < 99), default=0),
            duplicate_versions=duplicates,
            cycles=cycles,
        )

        nodes = sorted(self.nodes.values(), key=lambda n: (n.depth, n.name))
        return nodes, self.edges, stats

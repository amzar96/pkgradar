import {
  ChevronDown,
  FolderOpen,
  Gauge,
  Moon,
  RefreshCw,
  Search,
  Server,
  Sun,
  WifiOff,
  X,
} from "lucide-react";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import { useApp } from "../store";
import type { IndexRef, PackageNode, Project } from "../types";
import { HealthDot, Pill } from "./primitives";

interface Props {
  onRescan: (root?: string) => void;
}

const EMPTY_INDEXES: IndexRef[] = [];

export default function TopBar({ onRescan }: Props) {
  const root = useApp((state) => state.root);
  const status = useApp((state) => state.status);
  const progress = useApp((state) => state.progress);
  const projects = useApp((state) => state.projects);
  const result = useApp((state) => state.result);
  const offline = useApp((state) => state.offline);
  const deep = useApp((state) => state.deep);
  const theme = useApp((state) => state.theme);
  const toggleTheme = useApp((state) => state.toggleTheme);
  const search = useApp((state) => state.search);
  const setSearch = useApp((state) => state.setSearch);
  const setOffline = useApp((state) => state.setOffline);
  const setDeep = useApp((state) => state.setDeep);
  const resultIndexes = useApp((state) => state.result?.indexes);
  const indexes = resultIndexes ?? EMPTY_INDEXES;
  const primaryIndex = indexes.find((index) => index.primary) ?? indexes[0];
  const selectProject = useApp((state) => state.selectProject);
  const selectNode = useApp((state) => state.selectNode);
  const setView = useApp((state) => state.setView);

  const [editingRoot, setEditingRoot] = useState(false);
  const [rootDraft, setRootDraft] = useState(root);
  const [focused, setFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
      }
      if (event.key === "Escape") {
        setSearch("");
        inputRef.current?.blur();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  useEffect(() => setRootDraft(root), [root]);

  const deferredSearch = useDeferredValue(search);

  const matches = useMemo(() => {
    const term = deferredSearch.trim().toLowerCase();
    if (term.length < 2) return [];
    const hits: { project: Project; node: PackageNode }[] = [];
    for (const project of projects) {
      for (const node of project.nodes) {
        if (node.name.toLowerCase().includes(term)) {
          hits.push({ project, node });
        }
      }
    }
    return hits.sort((a, b) => a.node.depth - b.node.depth).slice(0, 9);
  }, [deferredSearch, projects]);

  const scanning = status === "scanning";
  const pct = progress.total ? Math.min(100, (progress.done / progress.total) * 100) : 0;

  return (
    <header className="relative z-30 flex h-[54px] shrink-0 items-center gap-3 border-b border-line bg-header px-4 backdrop-blur">
      <div className="relative flex items-center">
        {editingRoot ? (
          <div className="flex items-center gap-1.5 rounded-md border border-accent/40 bg-panel2 px-2 py-1">
            <FolderOpen size={13} className="text-accent" />
            <input
              autoFocus
              aria-label="Scan root"
              value={rootDraft}
              onChange={(event) => setRootDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  setEditingRoot(false);
                  onRescan(rootDraft);
                }
                if (event.key === "Escape") setEditingRoot(false);
              }}
              className="w-[360px] bg-transparent font-mono text-[11px] text-fg outline-none"
            />
            <button className="text-dim hover:text-fg" onClick={() => setEditingRoot(false)}>
              <X size={12} />
            </button>
          </div>
        ) : (
          <button
            onClick={() => setEditingRoot(true)}
            title="Change scan root"
            className="group flex max-w-[430px] items-center gap-2 rounded-md border border-line bg-panel px-2.5 py-1.5 transition-colors hover:border-line2"
          >
            <FolderOpen size={13} className="shrink-0 text-dim group-hover:text-accent" />
            <span className="truncate font-mono text-[11px] text-muted">{root || "scanning…"}</span>
            <ChevronDown size={12} className="shrink-0 text-dim" />
          </button>
        )}
      </div>

      <div className="relative flex-1" style={{ maxWidth: 420 }}>
        <div
          className={`flex items-center gap-2 rounded-md border bg-panel px-2.5 py-1.5 transition-colors ${
            focused ? "border-accent/40" : "border-line"
          }`}
        >
          <Search size={13} className="text-dim" />
          <input
            ref={inputRef}
            aria-label="Search packages across projects"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => window.setTimeout(() => setFocused(false), 150)}
            placeholder="Search packages across projects"
            className="w-full bg-transparent text-[11.5px] text-fg placeholder:text-dim focus:outline-none"
          />
          <span className="rounded border border-line px-1.5 py-px font-mono text-[9px] text-dim">⌘K</span>
        </div>
        {focused && matches.length > 0 ? (
          <div className="absolute top-full right-0 left-0 mt-1.5 overflow-hidden rounded-lg border border-line bg-panel shadow-2xl">
            {matches.map(({ project, node }) => (
              <button
                key={`${project.id}:${node.id}`}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  selectProject(project.id);
                  selectNode(node.id);
                  setView("topology");
                  setSearch("");
                }}
                className="flex w-full items-center gap-2.5 border-b border-line/60 px-3 py-2 text-left last:border-0 hover:bg-panel2"
              >
                <HealthDot
                  health={
                    node.advisories.length
                      ? "cve"
                      : node.delta === "major"
                        ? "major"
                        : node.delta === "minor"
                          ? "minor"
                          : "ok"
                  }
                  size={7}
                />
                <span className="flex-1 truncate font-mono text-[11px] text-fg">{node.name}</span>
                <span className="font-mono text-[10px] text-dim">{node.version}</span>
                <Pill>{project.id === "." ? project.name : project.id}</Pill>
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <div className="ml-auto flex items-center gap-2">
        {primaryIndex ? (
          <span
            className="hidden max-w-[180px] items-center gap-1 truncate rounded-md border border-line bg-panel px-2 py-1.5 font-mono text-[10px] text-dim lg:flex"
            title={`${primaryIndex.name} · ${primaryIndex.url}`}
          >
            <Server size={11} className="shrink-0" />
            <span className="truncate">{primaryIndex.name}</span>
          </span>
        ) : null}
        <button
          onClick={toggleTheme}
          title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          aria-pressed={theme === "light"}
          className="flex items-center rounded-md border border-line bg-panel px-2 py-1.5 text-dim transition-colors hover:text-fg"
        >
          {theme === "dark" ? <Sun size={12} /> : <Moon size={12} />}
        </button>
        <button
          onClick={() => setOffline(!offline)}
          title="Offline: use cached PyPI metadata only"
          aria-pressed={offline}
          className={`flex items-center gap-1 rounded-md border px-2 py-1.5 text-[10px] transition-colors ${
            offline
              ? "border-accent/40 bg-accent/10 text-accent"
              : "border-line bg-panel text-dim hover:text-muted"
          }`}
        >
          <WifiOff size={12} />
          offline
        </button>
        <button
          onClick={() => setDeep(!deep)}
          title="Deep: run uv lock --check and uv sync --dry-run (read-only)"
          aria-pressed={deep}
          className={`flex items-center gap-1 rounded-md border px-2 py-1.5 text-[10px] transition-colors ${
            deep
              ? "border-accent/40 bg-accent/10 text-accent"
              : "border-line bg-panel text-dim hover:text-muted"
          }`}
        >
          <Gauge size={12} />
          deep
        </button>

        <div className="mx-1 h-5 w-px bg-line" />

        {scanning ? (
          <div className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-accent pulse-soft" />
            <span className="max-w-[180px] truncate font-mono text-[10px] text-muted">
              {progress.message || "scanning"}
            </span>
          </div>
        ) : (
          <span className="font-mono text-[10px] text-dim">
            {result ? `${result.stats.projects} projects · ${result.stats.packages} pkgs` : ""}
          </span>
        )}

        <button
          onClick={() => onRescan()}
          disabled={scanning}
          aria-label="Rescan projects"
          className="flex items-center gap-1.5 rounded-md border border-line bg-panel px-2.5 py-1.5 text-[11px] text-muted transition-colors hover:border-line2 hover:text-fg disabled:opacity-40"
        >
          <RefreshCw size={12} className={scanning ? "animate-spin" : ""} />
          rescan
        </button>
      </div>

      {scanning ? (
        <div className="absolute right-0 bottom-0 left-0 h-px bg-line">
          <div
            className="h-full bg-accent transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
      ) : null}
    </header>
  );
}

import {
  Boxes,
  GitCompareArrows,
  Network,
  Package,
  Radar,
  TriangleAlert,
} from "lucide-react";

import { projectHealth } from "../lib/health";
import { useApp } from "../store";
import type { View } from "../types";
import { HealthDot } from "./primitives";

const NAV: { id: View; label: string; icon: typeof Radar }[] = [
  { id: "fleet", label: "Fleet", icon: Boxes },
  { id: "topology", label: "Topology", icon: Network },
  { id: "packages", label: "Packages", icon: Package },
  { id: "conflicts", label: "Conflicts", icon: TriangleAlert },
  { id: "skew", label: "Skew", icon: GitCompareArrows },
];

export default function Sidebar() {
  const view = useApp((state) => state.view);
  const setView = useApp((state) => state.setView);
  const projects = useApp((state) => state.projects);
  const result = useApp((state) => state.result);
  const selectedProject = useApp((state) => state.selectedProject);
  const selectProject = useApp((state) => state.selectProject);

  const conflicts = projects.reduce((sum, project) => sum + project.conflicts.length, 0);
  const packages = projects.reduce((sum, project) => sum + project.stats.packages, 0);

  const counts: Record<View, number | null> = {
    fleet: null,
    topology: null,
    packages,
    conflicts,
    skew: result?.skew.length ?? null,
  };

  return (
    <aside className="flex w-[238px] shrink-0 flex-col border-r border-line bg-[#090c11]">
      <div className="flex items-center gap-2.5 border-b border-line px-4 py-4">
        <div className="relative flex h-8 w-8 items-center justify-center rounded-lg border border-accent/25 bg-accent/5">
          <Radar size={17} className="text-accent" />
          <span className="absolute inset-0 rounded-lg ring-1 ring-accent/10" />
        </div>
        <div className="leading-tight">
          <div className="text-[13px] font-semibold tracking-tight text-fg">pkgradar</div>
          <div className="text-[9px] tracking-[0.16em] text-dim uppercase">uv dependency intel</div>
        </div>
      </div>

      <nav className="flex flex-col gap-0.5 px-2 py-3">
        {NAV.map((item) => {
          const Icon = item.icon;
          const active = view === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setView(item.id)}
              className={`group relative flex items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-[12px] transition ${
                active
                  ? "bg-panel2 text-fg"
                  : "text-muted hover:bg-panel2/60 hover:text-fg"
              }`}
            >
              {active ? (
                <span className="absolute top-1.5 bottom-1.5 left-0 w-0.5 rounded-full bg-accent" />
              ) : null}
              <Icon size={15} className={active ? "text-accent" : "text-dim group-hover:text-muted"} />
              <span className="flex-1">{item.label}</span>
              {counts[item.id] !== null && counts[item.id]! > 0 ? (
                <span className="rounded bg-line px-1.5 py-px font-mono text-[9px] text-muted">
                  {counts[item.id]}
                </span>
              ) : null}
            </button>
          );
        })}
      </nav>

      <div className="mt-1 flex items-center justify-between px-4 pb-1">
        <span className="text-[9px] font-medium tracking-[0.16em] text-dim uppercase">Projects</span>
        <span className="font-mono text-[9px] text-dim">{projects.length}</span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {projects.map((project) => {
          const active = selectedProject === project.id;
          const health = projectHealth(project);
          return (
            <button
              key={project.id}
              onClick={() => {
                selectProject(project.id);
                if (view === "fleet" || view === "skew") setView("topology");
              }}
              className={`mb-0.5 flex w-full flex-col gap-0.5 rounded-md px-2.5 py-2 text-left transition ${
                active ? "bg-panel2" : "hover:bg-panel2/60"
              }`}
            >
              <div className="flex items-center gap-2">
                <HealthDot health={health} />
                <span className="min-w-0 flex-1 truncate text-[11.5px] text-fg">
                  {project.id === "." ? project.name : project.id}
                </span>
                <span className="font-mono text-[9px] text-dim">{project.stats.packages}</span>
              </div>
              <div className="flex items-center gap-1.5 pl-4">
                <span className="truncate font-mono text-[9px] text-dim">{project.path}</span>
              </div>
            </button>
          );
        })}
        {projects.length === 0 ? (
          <div className="px-3 py-4 text-[11px] text-dim">No projects scanned yet.</div>
        ) : null}
      </div>

      <div className="border-t border-line px-4 py-3">
        <div className="flex items-center justify-between text-[10px] text-dim">
          <span>{packages} packages</span>
          <span className="font-mono">{result ? `${result.stats.duration_ms} ms` : "—"}</span>
        </div>
        <div className="mt-1.5 flex items-center gap-2 text-[10px]">
          <span className="text-cve">{result?.stats.advisories ?? 0} advisories</span>
          <span className="text-line2">·</span>
          <span className="text-minor">{conflicts} conflicts</span>
        </div>
      </div>
    </aside>
  );
}

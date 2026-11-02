import {
  ArrowUpRight,
  Boxes,
  Package,
  ShieldAlert,
  TriangleAlert,
  Wrench,
} from "lucide-react";

import { HEALTH_COLOR, pct, projectHealth } from "../lib/health";
import { useApp } from "../store";
import type { Project } from "../types";
import { EmptyState, HealthDot, Meter, StatTile } from "../components/primitives";

export default function Fleet() {
  const projects = useApp((state) => state.projects);
  const result = useApp((state) => state.result);
  const setView = useApp((state) => state.setView);
  const selectProject = useApp((state) => state.selectProject);

  const totals = projects.reduce(
    (acc, project) => ({
      packages: acc.packages + project.stats.packages,
      outdated: acc.outdated + project.stats.outdated,
      advisories: acc.advisories + project.stats.advisories,
      conflicts: acc.conflicts + project.conflicts.length,
      drift: acc.drift + project.stats.drift,
    }),
    { packages: 0, outdated: 0, advisories: 0, conflicts: 0, drift: 0 },
  );

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1180px] px-6 py-6">
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-[18px] font-semibold tracking-tight text-fg">Fleet overview</h1>
            <p className="mt-1 text-[11.5px] text-dim">
              {projects.length} uv projects · {result?.stats.unique_packages ?? 0} unique packages ·{" "}
              {result ? `${(result.stats.duration_ms / 1000).toFixed(1)}s scan` : "scanning"}
            </p>
          </div>
          <div className="flex items-center gap-2 text-[10px] text-dim">
            <span className="h-1.5 w-1.5 rounded-full bg-good" />
            read-only · uv lock + venv + indexes + OSV
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
          <StatTile
            label="Packages"
            value={totals.packages}
            hint={`${result?.stats.unique_packages ?? 0} unique`}
            icon={<Package size={14} />}
          />
          <StatTile
            label="Outdated"
            value={totals.outdated}
            hint="newer release available"
            color="var(--color-minor)"
            icon={<ArrowUpRight size={14} />}
          />
          <StatTile
            label="Advisories"
            value={totals.advisories}
            hint="OSV matches"
            color="var(--color-cve)"
            icon={<ShieldAlert size={14} />}
          />
          <StatTile
            label="Conflicts"
            value={totals.conflicts}
            hint="ranges / env / resolver"
            color="var(--color-major)"
            icon={<TriangleAlert size={14} />}
          />
          <StatTile
            label="Drift"
            value={totals.drift}
            hint="venv vs lock"
            color="var(--color-accent)"
            icon={<Wrench size={14} />}
          />
        </div>

        <div className="mt-6 mb-2 flex items-center justify-between">
          <h2 className="text-[10px] font-medium tracking-[0.16em] text-dim uppercase">Projects</h2>
          <span className="font-mono text-[10px] text-dim">{projects.length}</span>
        </div>

        {projects.length === 0 ? (
          <EmptyState
            title="No uv projects found"
            detail="Point pkgradar at a directory containing pyproject.toml, uv.lock or .venv. Use the root chip in the top bar."
            icon={<Boxes size={28} />}
          />
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {projects.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                onOpen={() => {
                  selectProject(project.id);
                  setView("topology");
                }}
              />
            ))}
          </div>
        )}

        {result?.warnings.length ? (
          <div className="mt-6 rounded-lg border border-line bg-panel px-4 py-3">
            <div className="text-[10px] tracking-[0.14em] text-dim uppercase">Scan warnings</div>
            <ul className="mt-1.5 space-y-1">
              {result.warnings.map((warning) => (
                <li key={warning} className="font-mono text-[10.5px] text-muted">
                  {warning}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ProjectCard({ project, onOpen }: { project: Project; onOpen: () => void }) {
  const health = projectHealth(project);
  const total = project.stats.packages || 1;

  const counts = (() => {
    let cve = 0;
    let major = 0;
    let minor = 0;
    let patch = 0;
    let ok = 0;
    let unknown = 0;
    for (const node of project.nodes) {
      if (node.root) continue;
      if (node.advisories.length) cve += 1;
      else if (node.delta === "major" || node.breaking) major += 1;
      else if (node.delta === "minor") minor += 1;
      else if (node.delta === "patch" || node.delta === "other") patch += 1;
      else if (node.delta === "none") ok += 1;
      else unknown += 1;
    }
    return { cve, major, minor, patch, ok, unknown };
  })();

  const risks = [...project.nodes]
    .filter((node) => !node.root)
    .sort((a, b) => b.risk - a.risk)
    .slice(0, 3);

  return (
    <button
      onClick={onOpen}
      className="group flex flex-col rounded-xl border border-line bg-panel p-4 text-left transition-colors hover:border-line2 hover:bg-panel2/60"
    >
      <div className="flex items-start gap-2">
        <HealthDot health={health} size={9} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium text-fg">{project.name}</div>
          <div className="truncate font-mono text-[9.5px] text-dim">{project.rel_path}</div>
        </div>
        <ArrowUpRight
          size={13}
          className="mt-0.5 text-dim transition-colors group-hover:text-accent"
        />
      </div>

      <div className="mt-3 grid grid-cols-4 gap-1">
        <MiniStat label="pkgs" value={project.stats.packages} />
        <MiniStat label="outdated" value={project.stats.outdated} colour="var(--color-minor)" />
        <MiniStat label="adv" value={project.stats.advisories} colour="var(--color-cve)" />
        <MiniStat label="conf" value={project.conflicts.length} colour="var(--color-major)" />
      </div>

      <div className="mt-3">
        <Meter
          segments={[
            { value: counts.ok, color: HEALTH_COLOR.ok },
            { value: counts.patch, color: HEALTH_COLOR.patch },
            { value: counts.minor, color: HEALTH_COLOR.minor },
            { value: counts.major, color: HEALTH_COLOR.major },
            { value: counts.cve, color: HEALTH_COLOR.cve },
            { value: counts.unknown, color: HEALTH_COLOR.unknown },
          ]}
        />
        <div className="mt-1.5 flex items-center justify-between text-[9px] text-dim">
          <span>
            {pct(counts.ok, total)}% current · {pct(counts.cve + counts.major, total)}% need attention
            {counts.unknown ? ` · ${counts.unknown} unknown` : ""}
          </span>
          <span className="font-mono">{total} total</span>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-1">
        {risks
          .filter((node) => node.risk > 0.1)
          .map((node) => (
            <span
              key={node.id}
              className="max-w-full truncate rounded border border-line bg-ink/50 px-1.5 py-px font-mono text-[9px] text-muted"
              title={`${node.name} ${node.version} → ${node.latest ?? "?"} · risk ${node.risk}`}
            >
              {node.name}
              {node.advisories.length ? (
                <span className="ml-1 text-cve">{node.advisories.length}c</span>
              ) : null}
            </span>
          ))}
        {risks.every((node) => node.risk <= 0.1) ? (
          <span className="text-[9.5px] text-good">no elevated risk</span>
        ) : null}
      </div>

      <div className="mt-3 flex items-center gap-3 border-t border-line/70 pt-2.5 text-[9.5px] text-dim">
        <span className="flex items-center gap-1">
          <span
            className={`h-1 w-1 rounded-full ${project.venv.broken ? "bg-major" : "bg-good"}`}
          />
          {project.venv.broken
            ? "venv broken"
            : project.venv.exists
              ? `py${project.venv.python ?? "?"} · ${project.venv.installed} installed`
              : "no venv"}
        </span>
        <span className="text-line2">·</span>
        <span>
          {project.lock.exists
            ? project.lock.stale === false
              ? "lock stale"
              : `${project.lock.packages} locked`
            : "no lock"}
        </span>
        {project.stats.drift > 0 ? (
          <>
            <span className="text-line2">·</span>
            <span className="text-accent">{project.stats.drift} drift</span>
          </>
        ) : null}
      </div>
    </button>
  );
}

function MiniStat({ label, value, colour }: { label: string; value: number; colour?: string }) {
  return (
    <div className="rounded border border-line/60 bg-ink/40 px-1.5 py-1">
      <div className="font-mono text-[12px] leading-none" style={{ color: colour ?? "var(--color-fg)" }}>
        {value}
      </div>
      <div className="mt-0.5 text-[9px] tracking-wide text-dim uppercase">{label}</div>
    </div>
  );
}

import {
  ArrowRight,
  ChevronDown,
  GitBranch,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState, Pill } from "../components/primitives";
import { alpha } from "../lib/health";
import { useApp } from "../store";

const SEVERITY_COLOR: Record<string, string> = {
  high: "var(--color-major)",
  medium: "var(--color-minor)",
  low: "var(--color-accent)",
};

const KIND_LABEL: Record<string, string> = {
  constraint: "range conflict",
  env: "installed env",
  resolver: "resolver",
  declared: "outside range",
  drift: "drift",
};

const KIND_FOOTER: Record<string, string> = {
  constraint: "no version satisfies all of the above",
  declared: "the installed version falls outside the declared range",
  env: "the installed environment is incompatible",
  resolver: "uv could not resolve the project",
  drift: "the installed environment differs from the lockfile",
};

export default function Conflicts() {
  const result = useApp((state) => state.result);
  const projects = useApp((state) => state.projects);
  const selectProject = useApp((state) => state.selectProject);
  const selectNode = useApp((state) => state.selectNode);
  const setView = useApp((state) => state.setView);
  const [filter, setFilter] = useState<string | null>(null);

  const conflicts = useMemo(() => {
    const all = projects.flatMap((project) => project.conflicts);
    const ordered = [...all].sort((a, b) => {
      const rank = { high: 0, medium: 1, low: 2 };
      return rank[a.severity] - rank[b.severity];
    });
    return filter ? ordered.filter((conflict) => conflict.project_id === filter) : ordered;
  }, [projects, filter]);

  const projectsWithDrift = projects.filter((project) => project.stats.drift > 0);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1080px] px-6 py-6">
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-[18px] font-semibold tracking-tight text-fg">Conflicts &amp; drift</h1>
            <p className="mt-1 text-[11.5px] text-dim">
              Empty constraint intersections, incompatible environments, and lock/venv drift.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <select
              aria-label="Filter conflicts by project"
              value={filter ?? ""}
              onChange={(event) => setFilter(event.target.value || null)}
              className="rounded border border-line bg-panel px-2 py-1.5 font-mono text-[10px] text-muted outline-none"
            >
              <option value="">all projects</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.id}
                </option>
              ))}
            </select>
          </div>
        </div>

        {conflicts.length === 0 ? (
          <div className="mt-6">
            <EmptyState
              icon={<ShieldCheck size={30} className="text-good/70" />}
              title="No hard conflicts"
              detail="Every declared range has a non-empty intersection, the lockfile matches the manifest, and the installed environment matches the lockfile. Outdated packages still show up on the Packages and Skew views."
            />
          </div>
        ) : (
          <div className="mt-5 space-y-3">
            {conflicts.map((conflict) => {
              const project = projects.find((item) => item.id === conflict.project_id);
              const target = project?.nodes.find(
                (node) => node.name === conflict.package && !node.root,
              );
              return (
                <div
                  key={conflict.id}
                  className="overflow-hidden rounded-lg border border-line bg-panel"
                >
                  <div className="flex">
                    <div
                      className="w-[3px] shrink-0"
                      style={{ background: SEVERITY_COLOR[conflict.severity] }}
                    />
                    <div className="min-w-0 flex-1 px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className="rounded px-1.5 py-px font-mono text-[9px] tracking-wide uppercase"
                          style={{
                            color: SEVERITY_COLOR[conflict.severity],
                            border: `1px solid ${alpha(SEVERITY_COLOR[conflict.severity], 27)}`,
                            background: alpha(SEVERITY_COLOR[conflict.severity], 7),
                          }}
                        >
                          {conflict.severity}
                        </span>
                        <Pill>{KIND_LABEL[conflict.kind] ?? conflict.kind}</Pill>
                        <Pill color="var(--color-accent)">{conflict.project_id}</Pill>
                        <span className="text-[12px] font-medium text-fg">{conflict.title}</span>
                        {target ? (
                          <button
                            onClick={() => {
                              selectProject(conflict.project_id);
                              selectNode(target.id);
                              setView("topology");
                            }}
                            className="ml-auto flex items-center gap-1 rounded border border-line px-2 py-1 text-[10px] text-dim transition-colors hover:border-accent/40 hover:text-accent"
                          >
                            <GitBranch size={10} />
                            open in graph
                          </button>
                        ) : null}
                      </div>

                      <p className="mt-2 text-[11px] leading-relaxed text-muted">{conflict.detail}</p>

                      {conflict.blame.length ? (
                        <div className="mt-3 rounded-md border border-line/70 bg-ink/40 p-2.5">
                          <div className="mb-1.5 text-[9px] tracking-[0.14em] text-dim uppercase">
                            Blame chain
                          </div>
                          <div className="space-y-1">
                            {conflict.blame.map((item) => (
                              <div
                                key={`${item.parent_id}:${item.spec}`}
                                className="flex items-center gap-2 font-mono text-[10px]"
                              >
                                <span className="min-w-0 max-w-[260px] truncate text-muted">
                                  {item.parent}
                                </span>
                                <span className="text-dim">requires</span>
                                <span className="text-accent">{item.spec || "any"}</span>
                                {item.resolved ? (
                                  <span className="text-dim">· resolved {item.resolved}</span>
                                ) : null}
                              </div>
                            ))}
                          </div>
                          <div className="mt-2 flex items-center gap-1.5 border-t border-line/60 pt-1.5 font-mono text-[10px]">
                            <ArrowRight size={11} className="text-major" />
                            <span className="text-major">
                              {KIND_FOOTER[conflict.kind] ?? "see the details above"}
                            </span>
                          </div>
                        </div>
                      ) : null}

                      {conflict.suggestion ? (
                        <div className="mt-2 text-[10.5px] text-good/80">
                          → {conflict.suggestion}
                        </div>
                      ) : null}

                      {conflict.raw ? (
                        <details className="group mt-2">
                          <summary className="flex cursor-pointer list-none items-center gap-1 text-[9.5px] text-dim hover:text-muted">
                            <ChevronDown
                              size={10}
                              className="transition group-open:rotate-180"
                            />
                            raw uv output
                          </summary>
                          <pre className="mt-1.5 max-h-52 overflow-auto rounded border border-line bg-ink p-2 font-mono text-[9.5px] leading-relaxed whitespace-pre-wrap text-dim">
                            {conflict.raw}
                          </pre>
                        </details>
                      ) : null}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {projectsWithDrift.length ? (
          <div className="mt-8">
            <div className="mb-2 flex items-center gap-2">
              <TriangleAlert size={13} className="text-accent" />
              <h2 className="text-[10px] font-medium tracking-[0.16em] text-dim uppercase">
                Environment drift
              </h2>
            </div>
            <div className="space-y-2">
              {projectsWithDrift.map((project) => (
                <div
                  key={project.id}
                  className="rounded-lg border border-line bg-panel px-4 py-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[11px] text-fg">{project.id}</span>
                    <Pill color="var(--color-accent)">
                      {project.drift.venv_only.length} installed only
                    </Pill>
                    <Pill color="var(--color-minor)">
                      {project.drift.lock_only.length} locked only
                    </Pill>
                    <Pill color="var(--color-major)">
                      {project.drift.version_mismatch.length} version mismatch
                    </Pill>
                    <span className="ml-auto font-mono text-[9px] text-dim">
                      uv sync would install {project.drift.plan.would_install.length} · uninstall{" "}
                      {project.drift.plan.would_uninstall.length}
                    </span>
                  </div>

                  {project.drift.venv_only.length ? (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {project.drift.venv_only.slice(0, 24).map((name) => (
                        <span
                          key={name}
                          className="rounded border border-line bg-ink/50 px-1.5 py-px font-mono text-[9px] text-dim"
                        >
                          {name}
                        </span>
                      ))}
                      {project.drift.venv_only.length > 24 ? (
                        <span className="px-1 text-[9px] text-dim">
                          +{project.drift.venv_only.length - 24}
                        </span>
                      ) : null}
                    </div>
                  ) : null}

                  {project.drift.version_mismatch.length ? (
                    <div className="mt-2 space-y-0.5">
                      {project.drift.version_mismatch.slice(0, 10).map((row) => (
                        <div
                          key={row.name}
                          className="flex items-center gap-2 font-mono text-[9.5px]"
                        >
                          <span className="w-40 truncate text-muted">{row.name}</span>
                          <span className="text-dim">locked</span>
                          <span className="text-fg">{row.locked}</span>
                          <span className="text-dim">installed</span>
                          <span className="text-minor">{row.installed}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {result?.warnings.length ? (
          <div className="mt-6 rounded-lg border border-line bg-panel px-4 py-3">
            <div className="text-[9px] tracking-[0.14em] text-dim uppercase">Warnings</div>
            <ul className="mt-1 space-y-1 font-mono text-[10px] text-muted">
              {result.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}

import { GitCompareArrows, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState, Pill } from "../components/primitives";
import { useApp } from "../store";

export default function Skew() {
  const result = useApp((state) => state.result);
  const projects = useApp((state) => state.projects);
  const selectProject = useApp((state) => state.selectProject);
  const selectNode = useApp((state) => state.selectNode);
  const setView = useApp((state) => state.setView);
  const [term, setTerm] = useState("");

  const rows = useMemo(() => {
    const skew = result?.skew ?? [];
    const needle = term.trim().toLowerCase();
    return needle
      ? skew.filter((row) => row.name.includes(needle))
      : skew;
  }, [result, term]);

  if (!result) {
    return (
      <div className="p-6">
        <EmptyState title="Waiting for scan" icon={<GitCompareArrows size={28} />} />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
        <div>
          <div className="text-[13px] font-medium text-fg">Version skew</div>
          <div className="font-mono text-[9.5px] text-dim">
            {result.skew.length} packages resolve to more than one version across{" "}
            {projects.length} projects
          </div>
        </div>
        <div className="ml-auto flex items-center gap-1.5 rounded-md border border-line bg-panel px-2 py-1.5">
          <Search size={12} className="text-dim" />
          <input
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            placeholder="filter packages"
            className="w-[180px] bg-transparent text-[11px] text-fg placeholder:text-dim focus:outline-none"
          />
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="p-6">
          <EmptyState
            title={result.skew.length ? "No matches" : "No skew detected"}
            detail={
              result.skew.length
                ? "Clear the filter to see all rows."
                : "Every shared package resolves to the same version in every project."
            }
            icon={<GitCompareArrows size={28} />}
          />
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto">
          <table className="w-full border-collapse text-left">
            <thead className="sticky top-0 z-10 bg-[#0a0d12]/95 backdrop-blur">
              <tr className="border-b border-line">
                <th className="sticky left-0 z-20 bg-[#0a0d12] py-2 pr-4 pl-5 text-[9px] tracking-[0.14em] text-dim uppercase">
                  package
                </th>
                <th className="px-3 py-2 text-[9px] tracking-[0.14em] text-dim uppercase">latest</th>
                <th className="px-3 py-2 text-[9px] tracking-[0.14em] text-dim uppercase">spread</th>
                {projects.map((project) => (
                  <th
                    key={project.id}
                    className="max-w-[150px] truncate px-3 py-2 font-mono text-[9px] text-dim"
                    title={project.path}
                  >
                    {project.id === "." ? project.name : project.id}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.name} className="border-b border-line/50 hover:bg-panel2/40">
                  <td className="sticky left-0 z-10 bg-[#0a0d12] py-1.5 pr-4 pl-5">
                    <span className="font-mono text-[11px] text-fg">{row.name}</span>
                  </td>
                  <td className="px-3 py-1.5 font-mono text-[10px] text-dim">
                    {row.latest ?? "—"}
                  </td>
                  <td className="px-3 py-1.5">
                    <span
                      className={`rounded px-1.5 py-px font-mono text-[9px] ${
                        row.spread >= 4
                          ? "bg-major/10 text-major"
                          : row.spread === 3
                            ? "bg-minor/10 text-minor"
                            : "bg-line text-muted"
                      }`}
                    >
                      {row.spread}
                    </span>
                  </td>
                  {projects.map((project) => {
                    const version = row.versions[project.id];
                    if (!version) {
                      return (
                        <td key={project.id} className="px-3 py-1.5 text-[10px] text-dim/40">
                          —
                        </td>
                      );
                    }
                    const isOldest = version === row.oldest && row.spread > 1;
                    const isNewest = version === row.newest;
                    const behindLatest = row.latest && version !== row.latest;
                    return (
                      <td key={project.id} className="px-3 py-1.5">
                        <button
                          onClick={() => {
                            selectProject(project.id);
                            const node = project.nodes.find(
                              (item) => item.name === row.name && !item.root,
                            );
                            if (node) selectNode(node.id);
                            setView("topology");
                          }}
                          className={`rounded px-1.5 py-0.5 font-mono text-[10px] transition hover:bg-panel2 ${
                            isOldest && behindLatest
                              ? "text-major"
                              : isNewest && behindLatest
                                ? "text-minor"
                                : isNewest
                                  ? "text-good"
                                  : "text-muted"
                          }`}
                          title={`open ${row.name} in ${project.id}`}
                        >
                          {version}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center gap-3 border-t border-line px-5 py-2 text-[9px] text-dim">
        <Pill color="#34d399">newest</Pill>
        <Pill color="#fbbf24">newest but behind PyPI</Pill>
        <Pill color="#f87171">oldest &amp; behind</Pill>
        <span className="ml-auto">click any cell to open that package in the graph</span>
      </div>
    </div>
  );
}

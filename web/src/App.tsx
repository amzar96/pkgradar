import { Radar, RefreshCw } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useRef } from "react";

import { startScan } from "./api";
import Inspector from "./components/Inspector";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";
import { applyTheme } from "./lib/theme";
import { HASH_VIEWS, useApp } from "./store";
import Conflicts from "./views/Conflicts";
import Fleet from "./views/Fleet";
import Packages from "./views/Packages";
import Skew from "./views/Skew";

// React Flow + ELK only load when the topology view is opened. This keeps the
// initial Fleet/Packages bundle small.
const Topology = lazy(() => import("./views/Topology"));

export default function App() {
  const view = useApp((state) => state.view);
  const theme = useApp((state) => state.theme);
  const status = useApp((state) => state.status);
  const error = useApp((state) => state.error);
  const projects = useApp((state) => state.projects);
  const inspectorOpen = useApp((state) => state.inspectorOpen);
  const progress = useApp((state) => state.progress);

  const cancelRef = useRef<(() => void) | null>(null);
  const bootedRef = useRef(false);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const runScan = useCallback((root?: string) => {
    const state = useApp.getState();
    cancelRef.current?.();
    const target = root || state.root;
    state.beginScan(target);
    window.localStorage.setItem("pkgradar:root", target);
    cancelRef.current = startScan(
      {
        root: target,
        offline: state.offline,
        deep: state.deep,
        enrich: true,
        advisories: true,
      },
      {
        onProgress: (data) => useApp.getState().setProgress(data),
        onProject: (project) => useApp.getState().addProject(project),
        onEnrich: (data) => useApp.getState().setProgress(data),
        onDone: (result) => useApp.getState().finish(result),
        onError: (message) => useApp.getState().fail(message),
      },
    );
  }, []);

  useEffect(() => {
    if (bootedRef.current) return;
    bootedRef.current = true;
    fetch("/api/defaults")
      .then((response) => response.json())
      .then((data: { root: string }) => {
        const stored = window.localStorage.getItem("pkgradar:root");
        const root = stored || data.root;
        useApp.setState({ root });
        runScan(root);
      })
      .catch(() => {
        const root = window.localStorage.getItem("pkgradar:root") || ".";
        useApp.setState({ root });
        runScan(root);
      });
    return () => cancelRef.current?.();
  }, [runScan]);

  useEffect(() => {
    if (window.location.hash !== `#${view}`) {
      window.history.pushState(null, "", `#${view}`);
    }
  }, [view]);

  useEffect(() => {
    const sync = () => {
      const hash = window.location.hash.replace("#", "") as (typeof HASH_VIEWS)[number];
      if (HASH_VIEWS.includes(hash)) {
        useApp.setState({ view: hash });
      }
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("hashchange", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("hashchange", sync);
    };
  }, []);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-ink text-fg">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onRescan={runScan} />
        <div className="flex min-h-0 flex-1">
          <main className="relative min-w-0 flex-1">
            <Suspense fallback={<ViewLoading />}>
              {view === "fleet" ? <Fleet /> : null}
              {view === "topology" ? <Topology /> : null}
              {view === "packages" ? <Packages /> : null}
              {view === "conflicts" ? <Conflicts /> : null}
              {view === "skew" ? <Skew /> : null}
            </Suspense>

            {status === "scanning" && projects.length === 0 ? (
              <ScanOverlay
                message={progress.message}
                phase={progress.phase}
                done={progress.done}
                total={progress.total}
              />
            ) : null}

            {status === "error" ? (
              <div className="absolute inset-0 flex items-center justify-center bg-ink/80 backdrop-blur-sm">
                <div className="max-w-md rounded-xl border border-major/30 bg-panel p-6">
                  <div className="text-[13px] font-medium text-major">Scan failed</div>
                  <p className="mt-1.5 font-mono text-[10.5px] leading-relaxed text-muted">
                    {error}
                  </p>
                  <button
                    onClick={() => runScan()}
                    className="mt-4 flex items-center gap-1.5 rounded border border-line px-3 py-1.5 text-[11px] text-muted hover:text-fg"
                  >
                    <RefreshCw size={12} />
                    retry
                  </button>
                </div>
              </div>
            ) : null}
          </main>
          {inspectorOpen ? <Inspector /> : null}
        </div>
      </div>
    </div>
  );
}

function ViewLoading() {
  return (
    <div className="flex h-full items-center justify-center text-[11px] text-dim">
      <span className="pulse-soft">loading view…</span>
    </div>
  );
}

function ScanOverlay({
  message,
  phase,
  done,
  total,
}: {
  message: string;
  phase: string;
  done: number;
  total: number;
}) {
  const phases = [
    { id: "discover", label: "Discovering uv projects" },
    { id: "parse", label: "Parsing uv.lock + .venv" },
    { id: "pypi", label: "Resolving latest releases from the package index" },
    { id: "osv", label: "Checking OSV advisories" },
  ];
  const activeIndex = Math.max(
    0,
    phases.findIndex((item) => item.id === phase),
  );
  const pct = total ? Math.min(100, Math.round((done / total) * 100)) : 0;

  return (
    <div
      className="scanline absolute inset-0 flex items-center justify-center bg-ink/85 backdrop-blur-sm"
      role="status"
      aria-live="polite"
    >
      <div className="w-[360px]">
        <div className="relative mx-auto mb-6 h-[92px] w-[92px]">
          {[0, 1, 2].map((ring) => (
            <span
              key={ring}
              className="absolute rounded-full border border-accent/25"
              style={{
                inset: ring * 14,
                animation: `pulse-soft ${2 + ring * 0.5}s ease-in-out infinite`,
              }}
            />
          ))}
          <span className="absolute inset-0 flex items-center justify-center">
            <Radar size={26} className="text-accent" />
          </span>
          <span className="absolute top-1/2 left-1/2 h-px w-9 origin-left bg-gradient-to-r from-accent/70 to-transparent" />
        </div>

        <div className="text-center">
          <div className="text-[13px] font-medium text-fg">Scanning dependency graph</div>
          <div className="mt-1 truncate font-mono text-[10px] text-dim">{message || "starting…"}</div>
        </div>

        <div className="mt-4 h-1 overflow-hidden rounded-full bg-line">
          <div
            className="h-full rounded-full bg-accent transition-all duration-300"
            style={{ width: `${Math.max(3, pct)}%` }}
          />
        </div>

        <div className="mt-4 space-y-1.5">
          {phases.map((item, index) => {
            const state =
              index < activeIndex ? "done" : index === activeIndex ? "active" : "idle";
            return (
              <div key={item.id} className="flex items-center gap-2 text-[10.5px]">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    state === "done"
                      ? "bg-good"
                      : state === "active"
                        ? "bg-accent pulse-soft"
                        : "bg-line2"
                  }`}
                />
                <span
                  className={
                    state === "idle" ? "text-dim" : state === "active" ? "text-fg" : "text-muted"
                  }
                >
                  {item.label}
                </span>
                {state === "active" && total > 1 ? (
                  <span className="ml-auto font-mono text-[9px] text-dim">
                    {done}/{total}
                  </span>
                ) : null}
              </div>
            );
          })}
        </div>

        <p className="mt-5 text-center text-[9.5px] leading-relaxed text-dim">
          First run queries the configured package index and OSV — cached for 24h afterwards.
        </p>
      </div>
    </div>
  );
}

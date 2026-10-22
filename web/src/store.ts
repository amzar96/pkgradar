import { create } from "zustand";

import type { Project, ScanResult, View } from "./types";

type Status = "idle" | "scanning" | "ready" | "error";
export type LayoutKind = "auto" | "radial" | "compact" | "layered";

interface Progress {
  phase: string;
  message: string;
  done: number;
  total: number;
}

interface AppState {
  view: View;
  status: Status;
  progress: Progress;
  error: string | null;
  projects: Project[];
  result: ScanResult | null;
  root: string;

  selectedProject: string | null;
  selectedNode: string | null;
  search: string;
  layout: LayoutKind;
  depthLimit: number;
  group: string | null;
  onlyOutdated: boolean;
  onlyAdvisories: boolean;
  offline: boolean;
  deep: boolean;
  inspectorOpen: boolean;

  setView: (view: View) => void;
  beginScan: (root: string) => void;
  addProject: (project: Project) => void;
  setProgress: (progress: Progress) => void;
  finish: (result: ScanResult) => void;
  fail: (message: string) => void;
  reset: () => void;

  selectProject: (id: string | null) => void;
  selectNode: (id: string | null) => void;
  setSearch: (value: string) => void;
  setLayout: (layout: LayoutKind) => void;
  setDepthLimit: (value: number) => void;
  setGroup: (group: string | null) => void;
  toggleOutdated: () => void;
  toggleAdvisories: () => void;
  setOffline: (value: boolean) => void;
  setDeep: (value: boolean) => void;
  closeInspector: () => void;
}

export const useApp = create<AppState>((set, get) => ({
  view: "fleet",
  status: "idle",
  progress: { phase: "", message: "", done: 0, total: 0 },
  error: null,
  projects: [],
  result: null,
  root: "",

  selectedProject: null,
  selectedNode: null,
  search: "",
  layout: "auto",
  depthLimit: 1,
  group: null,
  onlyOutdated: false,
  onlyAdvisories: false,
  offline: false,
  deep: true,
  inspectorOpen: false,

  setView: (view) => set({ view }),
  beginScan: (root) =>
    set({
      status: "scanning",
      error: null,
      projects: [],
      result: null,
      root,
      selectedProject: null,
      selectedNode: null,
      inspectorOpen: false,
    }),
  addProject: (project) =>
    set((state) => ({
      projects: [...state.projects.filter((p) => p.id !== project.id), project],
    })),
  setProgress: (progress) => set({ progress }),
  finish: (result) =>
    set((state) => ({
      status: "ready",
      result,
      projects: result.projects,
      selectedProject:
        state.selectedProject && result.projects.some((p) => p.id === state.selectedProject)
          ? state.selectedProject
          : result.projects[0]?.id ?? null,
    })),
  fail: (message) => set({ status: "error", error: message }),
  reset: () =>
    set({
      status: "idle",
      projects: [],
      result: null,
      progress: { phase: "", message: "", done: 0, total: 0 },
      error: null,
    }),

  selectProject: (id) => set({ selectedProject: id, selectedNode: null, inspectorOpen: false }),
  selectNode: (id) =>
    set({
      selectedNode: id,
      inspectorOpen: Boolean(id),
    }),
  setSearch: (value) => set({ search: value }),
  setLayout: (layout) => set({ layout }),
  setDepthLimit: (depthLimit) => set({ depthLimit }),
  setGroup: (group) => set({ group }),
  toggleOutdated: () => set((state) => ({ onlyOutdated: !state.onlyOutdated })),
  toggleAdvisories: () => set((state) => ({ onlyAdvisories: !state.onlyAdvisories })),
  setOffline: (offline) => set({ offline }),
  setDeep: (deep) => set({ deep }),
  closeInspector: () => set({ selectedNode: null, inspectorOpen: false }),
}));

export function activeProject(state: AppState): Project | null {
  const id = state.selectedProject;
  if (!id) return state.projects[0] ?? null;
  return state.projects.find((project) => project.id === id) ?? state.projects[0] ?? null;
}

export function useActiveProject(): Project | null {
  return useApp((state) => activeProject(state));
}

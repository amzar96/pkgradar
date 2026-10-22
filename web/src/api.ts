import type { Project, ScanResult } from "./types";

export interface ScanParams {
  root: string;
  offline?: boolean;
  enrich?: boolean;
  advisories?: boolean;
  deep?: boolean;
}

export interface ScanHandlers {
  onProgress?: (data: { phase: string; message: string; done: number; total: number }) => void;
  onProject?: (project: Project) => void;
  onEnrich?: (data: { message: string; done: number; total: number }) => void;
  onDone?: (result: ScanResult) => void;
  onError?: (message: string) => void;
}

export function startScan(params: ScanParams, handlers: ScanHandlers): () => void {
  const query = new URLSearchParams({
    root: params.root,
    offline: String(params.offline ?? false),
    enrich: String(params.enrich ?? true),
    advisories: String(params.advisories ?? true),
    deep: String(params.deep ?? true),
  });
  const source = new EventSource(`/api/scan?${query.toString()}`);
  let finished = false;

  source.addEventListener("progress", (event) => {
    try {
      handlers.onProgress?.(JSON.parse((event as MessageEvent).data));
    } catch {
      /* ignore malformed frame */
    }
  });
  source.addEventListener("project", (event) => {
    try {
      handlers.onProject?.(JSON.parse((event as MessageEvent).data).project);
    } catch {
      /* ignore */
    }
  });
  source.addEventListener("enrich", (event) => {
    try {
      handlers.onEnrich?.(JSON.parse((event as MessageEvent).data));
    } catch {
      /* ignore */
    }
  });
  source.addEventListener("done", (event) => {
    finished = true;
    try {
      handlers.onDone?.(JSON.parse((event as MessageEvent).data).result);
    } catch (error) {
      handlers.onError?.(String(error));
    }
    source.close();
  });
  source.addEventListener("error", (event) => {
    if ((event as MessageEvent).data) {
      try {
        handlers.onError?.(JSON.parse((event as MessageEvent).data).message);
      } catch {
        handlers.onError?.("scan failed");
      }
      finished = true;
      source.close();
    }
  });
  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED && !finished) {
      handlers.onError?.("lost connection to pkgradar server");
    }
  };

  return () => source.close();
}

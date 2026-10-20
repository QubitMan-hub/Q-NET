import type { Issue, Project, SimState } from "./types";

// Two transports for the same API: HTTP to `qpv serve`, or (static GitHub Pages
// build, VITE_BACKEND=pyodide) the Python engine running in a Web Worker.
export const IN_BROWSER = import.meta.env.VITE_BACKEND === "pyodide";

type Reply = { status: number; kind: "json" | "text"; body: any };
let worker: Worker | null = null;
let nextId = 1;
const pending = new Map<number, { resolve: (r: Reply) => void; reject: (e: Error) => void }>();
const statusListeners = new Set<(text: string) => void>();

export function onEngineStatus(fn: (text: string) => void) {
  statusListeners.add(fn);
  return () => { statusListeners.delete(fn); };
}

function getWorker(): Worker {
  if (worker) return worker;
  worker = new Worker(new URL("./pyworker.ts", import.meta.url), { type: "module" });
  worker.onmessage = (ev) => {
    const m = ev.data;
    if (m.type === "status") statusListeners.forEach((f) => f(m.text));
    else if (m.type === "ready") statusListeners.forEach((f) => f(""));
    else if (m.type === "fatal") {
      statusListeners.forEach((f) => f(`The engine could not start: ${m.text}`));
      pending.forEach((p) => p.reject(new Error(m.text)));
      pending.clear();
    } else if (m.type === "response") {
      const p = pending.get(m.id);
      if (!p) return;
      pending.delete(m.id);
      if (m.error) p.reject(new Error(m.error));
      else p.resolve(JSON.parse(m.payload));
    }
  };
  worker.postMessage({ type: "init", base: new URL(import.meta.env.BASE_URL, document.baseURI).href });
  return worker;
}

async function call(method: string, url: string, body?: unknown): Promise<Reply> {
  if (IN_BROWSER) {
    const w = getWorker();
    return new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
      w.postMessage({ id, method, url, body: body === undefined ? "" : JSON.stringify(body) });
    });
  }
  const res = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let parsed: any = text;
  try { parsed = JSON.parse(text); } catch { /* plain text */ }
  return { status: res.status, kind: typeof parsed === "string" ? "text" : "json", body: parsed };
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const r = await call(method, url, body);
  if (r.status >= 400) {
    const d = r.body?.detail;
    throw new Error(typeof d === "string" ? d : JSON.stringify(d ?? r.body));
  }
  return r.body as T;
}

/** Save API output as a file (works for both transports). */
export async function downloadFrom(url: string, filename: string, mime = "application/json") {
  const r = await call("GET", url);
  if (r.status >= 400) throw new Error(r.body?.detail ?? "download failed");
  const data = typeof r.body === "string" ? r.body : JSON.stringify(r.body, null, 2);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([data], { type: mime }));
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

export interface ProjectResponse { project: Project; issues: Issue[]; revision: number; sim_error: string | null }

export const api = {
  meta: () => req<any>("GET", "/api/meta"),
  project: () => req<ProjectResponse>("GET", "/api/project"),
  putProject: (p: Project) => req<ProjectResponse>("PUT", "/api/project", p),
  loadExample: (name: string) => req<ProjectResponse>("POST", `/api/project/example/${name}`),
  reset: (seed?: number) => req<SimState>("POST", "/api/sim/reset", seed === undefined ? {} : { seed }),
  step: (n: number, since: number) => req<SimState>("POST", "/api/sim/step", { n, since }),
  run: (since: number, until_ns?: number, max_steps?: number) =>
    req<SimState>("POST", "/api/sim/run", { since, until_ns, max_steps }),
  state: (since = 0) => req<SimState>("GET", `/api/sim/state?since=${since}`),
  chain: (msg: number) => req<any[]>("GET", `/api/sim/chain/${msg}`),
  invariants: () => req<any>("GET", "/api/sim/invariants"),
  console: (line: string, since: number) => req<{ result: any; state: SimState }>("POST", "/api/console", { line, since }),
  complete: (prefix: string) => req<string[]>("GET", `/api/console/complete?prefix=${encodeURIComponent(prefix)}`),
  startExperiment: (exp: unknown) => req<{ id: string }>("POST", "/api/experiments", exp),
  experiment: (id: string) => req<any>("GET", `/api/experiments/${id}`),
  cancelExperiment: (id: string) => req<any>("POST", `/api/experiments/${id}/cancel`),
};

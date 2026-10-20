import type { Issue, Project, SimState } from "./types";

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* not JSON */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
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

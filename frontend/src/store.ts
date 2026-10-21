import { create } from "zustand";
import { api, IN_BROWSER, type ProjectResponse } from "./api";

// Per-browser conveniences only (the engine state lives in the engine). Every
// storage access is guarded: private windows and blocked storage must still work.
const SAVED_KEY = "qpv.project.v1";
export function storageGet(key: string): string | null {
  try { return window.localStorage.getItem(key); } catch { return null; }
}
export function storageSet(key: string, value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch { /* storage unavailable: nothing to persist */ }
}
function exampleFromHash(): string | null {
  const m = window.location.hash.match(/example=([\w-]+)/);
  return m ? m[1] : null;
}
import { clone } from "./format";
import type { Analysis, Issue, PortKinds, Project, Ref, ScenarioCatalog, Selection, SimState, VerifierType } from "./types";

export type CanvasView = "network" | "automaton" | "spacetime";
export type DockTab = "events" | "timeline" | "timing" | "console" | "experiments" | "compare" | "validation" | "decision";

export interface ConsoleEntry {
  id: number; cmd: string; status: "running" | "ok" | "error"; text: string; data?: any; view?: string | null; refs?: Ref[];
}

interface Store {
  meta: any | null;
  project: Project | null;
  revision: number;
  issues: Issue[];
  ports: PortKinds;
  verifierTypes: Record<string, VerifierType>;
  analysis: Analysis | null;
  scenarios: ScenarioCatalog | null;
  simError: string | null;
  sim: SimState | null;
  selection: Selection;
  view: CanvasView;
  focus: string | null; // participant whose automaton is shown
  dock: DockTab;
  past: Project[];
  future: Project[];
  playing: boolean;
  playRate: number; // simulated ns per wall-clock second
  busy: boolean;
  dirtyPush: boolean;
  toast: { text: string; error?: boolean } | null;
  linkKind: "quantum" | "classical";
  consoleLog: ConsoleEntry[];
  highlightChain: number[];
  theme: "light" | "dark";

  init(): Promise<void>;
  edit(fn: (p: Project) => void, opts?: { select?: Selection }): void;
  undo(): void;
  redo(): void;
  loadExample(name: string): Promise<void>;
  openDocument(doc: Project): Promise<void>;
  reset(seed?: number): Promise<void>;
  step(n?: number): Promise<void>;
  runToEnd(): Promise<void>;
  runUntil(ns: number): Promise<void>;
  setPlaying(on: boolean): void;
  consoleExec(line: string): Promise<void>;
  clearConsole(): void;
  select(sel: Selection): void;
  setView(v: CanvasView): void;
  setFocus(id: string | null): void;
  setDock(d: DockTab): void;
  setToast(text: string, error?: boolean): void;
  setLinkKind(k: "quantum" | "classical"): void;
  setPlayRate(r: number): void;
  setHighlightChain(ids: number[]): void;
  toggleTheme(): void;
  refreshSim(full?: boolean): Promise<void>;
  loadScenario(body: Record<string, any>): Promise<void>;
  switchAttack(attack: string, policy?: string): Promise<void>;
  autowire(): Promise<void>;
  goTo(ref: Ref): void;
}

let pushTimer: number | undefined;
let playTimer: number | undefined;
let inflight = false;

export const useStore = create<Store>((set, get) => {
  const applyProject = (r: ProjectResponse) => {
    set({ project: r.project, revision: r.revision, issues: r.issues, simError: r.sim_error, ports: r.ports,
      verifierTypes: r.verifier_types, dirtyPush: false });
    refreshAnalysis();
  };

  // Timing and references depend only on the setup: refresh them whenever the engine's project changes.
  const refreshAnalysis = () => {
    const rev = get().revision;
    api.analysis().then((a) => { if (get().revision === rev) set({ analysis: a }); }).catch(() => set({ analysis: null }));
  };

  // Replace the project with one the engine built (scenario, attack switch, auto-wiring).
  const install = async (r: ProjectResponse, toast: string) => {
    const before = get().project;  // undo returns to the project as it was before the engine rebuilt it
    applyProject(r);
    history.replaceState(null, "", window.location.pathname + window.location.search);
    set({ past: before ? [...get().past.slice(-99), before] : get().past, future: [], selection: { kind: "project" }, highlightChain: [],
      focus: r.project.participants.find((p) => p.role === "verifier")?.id ?? null });
    await get().refreshSim(true);
    get().setToast(toast);
  };

  // Merge an incremental engine snapshot into the accumulated one.
  const mergeSim = async (s: SimState, since: number) => {
    const cur = get().sim;
    if ((s as any).error !== undefined && !s.nodes) {
      set({ sim: null, simError: (s as any).error ?? null });
      return;
    }
    if (since === 0 || !cur) {
      set({ sim: s });
      return;
    }
    if (cur.revision === s.revision && s.trace_length === since + s.trace.length && cur.trace.length === since) {
      set({ sim: { ...s, trace: cur.trace.concat(s.trace) } });
    } else {
      set({ sim: await api.state(0) });
    }
  };

  const guard = async (fn: () => Promise<void>) => {
    try {
      await fn();
    } catch (e: any) {
      get().setToast(String(e?.message ?? e), true);
      set({ playing: false });
    }
  };

  const pushNow = async () => {
    const p = get().project;
    if (!p) return;
    const r = await api.putProject(p);
    set({ revision: r.revision, issues: r.issues, simError: r.sim_error, ports: r.ports, verifierTypes: r.verifier_types,
      dirtyPush: false });
    refreshAnalysis();
    await get().refreshSim(true);
  };

  return {
    meta: null, project: null, revision: 0, issues: [], ports: {}, verifierTypes: {}, analysis: null, scenarios: null, simError: null, sim: null,
    selection: { kind: "project" }, view: "network", focus: null, dock: "events",
    past: [], future: [], playing: false, playRate: 4, busy: false, dirtyPush: false, toast: null,
    linkKind: "quantum", consoleLog: [], highlightChain: [], theme: "light",

    async init() {
      await guard(async () => {
        const [meta, proj, scenarios] = await Promise.all([api.meta(), api.project(), api.scenarios()]);
        set({ meta, scenarios });
        applyProject(proj);
        // A shared link (#example=name) wins; otherwise the in-browser build restores
        // the visitor's last project from this browser.
        const shared = exampleFromHash();
        const saved = IN_BROWSER ? storageGet(SAVED_KEY) : null;
        if (shared && meta.examples?.[shared]) {
          applyProject(await api.loadExample(shared));
        } else if (saved) {
          try {
            const r = await api.putProject(JSON.parse(saved));
            applyProject(r);
            get().setToast("Restored your last project from this browser");
          } catch {
            storageSet(SAVED_KEY, null);
          }
        }
        await get().refreshSim(true);
        const p = get().project!;
        const firstVerifier = p.participants.find((x) => x.role === "verifier");
        set({ focus: firstVerifier?.id ?? p.participants[0]?.id ?? null });
      });
    },

    async refreshSim(full = false) {
      const since = full ? 0 : get().sim?.trace.length ?? 0;
      const s = await api.state(since);
      await mergeSim(s, since);
    },

    edit(fn, opts) {
      const cur = get().project;
      if (!cur) return;
      const next = clone(cur);
      try {
        fn(next);
      } catch (e: any) {
        get().setToast(String(e?.message ?? e), true);
        return;
      }
      set({ project: next, past: [...get().past.slice(-99), cur], future: [], dirtyPush: true, playing: false,
        ...(opts?.select ? { selection: opts.select } : {}) });
      window.clearTimeout(pushTimer);
      pushTimer = window.setTimeout(() => guard(pushNow), 280);
    },

    undo() {
      const { past, project, future } = get();
      if (!past.length || !project) return;
      set({ project: past[past.length - 1], past: past.slice(0, -1), future: [project, ...future], dirtyPush: true });
      window.clearTimeout(pushTimer);
      pushTimer = window.setTimeout(() => guard(pushNow), 120);
    },

    redo() {
      const { past, project, future } = get();
      if (!future.length || !project) return;
      set({ project: future[0], future: future.slice(1), past: [...past, project], dirtyPush: true });
      window.clearTimeout(pushTimer);
      pushTimer = window.setTimeout(() => guard(pushNow), 120);
    },

    async loadExample(name) {
      await guard(async () => {
        set({ playing: false });
        const r = await api.loadExample(name);
        applyProject(r);
        history.replaceState(null, "", `#example=${name}`);
        set({ past: [], future: [], selection: { kind: "project" }, highlightChain: [],
          focus: r.project.participants.find((p) => p.role === "verifier")?.id ?? null });
        await get().refreshSim(true);
        get().setToast(`Loaded “${r.project.meta.name}”`);
      });
    },

    async openDocument(doc) {
      await guard(async () => {
        set({ view: "network" });
        if (window.location.hash) history.replaceState(null, "", window.location.pathname + window.location.search);
        const r = await api.putProject(doc);
        applyProject(r);
        set({ past: [], future: [], selection: { kind: "project" }, highlightChain: [] });
        await get().refreshSim(true);
        get().setToast(r.issues.some((i) => i.level === "error") ? "Opened with validation errors" : `Opened “${r.project.meta.name}”`,
          r.issues.some((i) => i.level === "error"));
      });
    },

    async reset(seed) {
      await guard(async () => {
        if (get().dirtyPush) await pushNow();
        set({ playing: false, highlightChain: [] });
        const s = await api.reset(seed);
        await mergeSim(s, 0);
      });
    },

    async step(n = 1) {
      await guard(async () => {
        if (get().dirtyPush) await pushNow();
        const since = get().sim?.trace.length ?? 0;
        await mergeSim(await api.step(n, since), since);
      });
    },

    async runToEnd() {
      await guard(async () => {
        if (get().dirtyPush) await pushNow();
        set({ playing: false });
        const since = get().sim?.trace.length ?? 0;
        await mergeSim(await api.run(since), since);
      });
    },

    async runUntil(nsValue) {
      await guard(async () => {
        const since = get().sim?.trace.length ?? 0;
        await mergeSim(await api.run(since, nsValue), since);
      });
    },

    setPlaying(on) {
      set({ playing: on });
      window.clearInterval(playTimer);
      if (!on) return;
      const tickMs = 50;
      playTimer = window.setInterval(async () => {
        const st = get();
        if (!st.playing) return window.clearInterval(playTimer);
        if (inflight) return;
        if (!st.sim || st.sim.stopped) {
          set({ playing: false });
          return window.clearInterval(playTimer);
        }
        inflight = true;
        try {
          // The engine advances its own clock to `until`; the UI only paces requests.
          const until = st.sim.now_fs / 1e6 + (st.playRate * tickMs) / 1000;
          const since = st.sim.trace.length;
          await mergeSim(await api.run(since, until), since);
        } catch (e: any) {
          get().setToast(String(e?.message ?? e), true);
          set({ playing: false });
        } finally {
          inflight = false;
        }
      }, tickMs);
    },

    async consoleExec(line) {
      const id = Date.now() + Math.random();
      const patch = (e: Partial<ConsoleEntry>) =>
        set({ consoleLog: get().consoleLog.map((x) => (x.id === id ? { ...x, ...e } : x)) });
      set({ consoleLog: [...get().consoleLog.slice(-199), { id, cmd: line, status: "running", text: "" }] });
      try {
        if (get().dirtyPush) await pushNow();
        const since = get().sim?.trace.length ?? 0;
        const rev = get().revision;
        const r = await api.console(line, since);
        patch({ status: r.result.ok ? "ok" : "error", text: r.result.output || (r.result.ok ? "Done." : "That did not work."),
          data: r.result.data, view: r.result.view, refs: r.result.refs });
        if (r.state.revision !== rev) {
          applyProject(await api.project());
          await get().refreshSim(true);
        } else {
          await mergeSim(r.state, since);
        }
      } catch (e: any) {
        patch({ status: "error", text: `The engine could not be reached: ${e?.message ?? e}` });
      }
    },

    clearConsole() { set({ consoleLog: [] }); },

    async loadScenario(body) {
      await guard(async () => {
        set({ playing: false });
        const r = await api.scenario(body);
        await install(r, `Built “${r.project.meta.name}”`);
      });
    },

    async switchAttack(attack, policy) {
      await guard(async () => {
        if (get().dirtyPush) await pushNow();
        const r = await api.attack(attack, policy);
        await install(r, `Now answering: ${get().scenarios?.answerers[attack] ?? attack}`);
        await get().runToEnd();
      });
    },

    async autowire() {
      await guard(async () => {
        if (get().dirtyPush) await pushNow();
        const r = await api.autowire();
        await install(r, `Wired ${r.project.links.length} links`);
      });
    },

    goTo(ref) {
      if (ref.kind === "transition") set({ view: "automaton", focus: get().sim ? Object.values(get().sim!.nodes)
        .find((n) => n.automaton === ref.automaton)?.id ?? get().focus : get().focus });
      get().select(ref.kind === "event" ? { kind: "event", seq: ref.seq } : ref);
    },

    select(sel) {
      set({ selection: sel });
      if (sel.kind === "participant") set({ focus: sel.id });
    },
    setView(v) { set({ view: v }); },
    setFocus(id) { set({ focus: id }); },
    setDock(d) { set({ dock: d }); },
    setToast(text, error) {
      set({ toast: { text, error } });
      window.setTimeout(() => { if (get().toast?.text === text) set({ toast: null }); }, error ? 6000 : 2600);
    },
    setLinkKind(k) { set({ linkKind: k }); },
    setPlayRate(r) { set({ playRate: r }); },
    setHighlightChain(ids) { set({ highlightChain: ids }); },
    toggleTheme() {
      const t = get().theme === "light" ? "dark" : "light";
      document.documentElement.dataset.theme = t;
      set({ theme: t });
    },
  };
});

export const selectedParticipant = (s: { project: Project | null; focus: string | null }) =>
  s.project?.participants.find((p) => p.id === s.focus) ?? null;

// Autosave the project in the in-browser build so a reload does not lose work.
if (IN_BROWSER) {
  let saveTimer: number | undefined;
  useStore.subscribe((st, prev) => {
    if (!st.project || st.project === prev.project) return;
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => storageSet(SAVED_KEY, JSON.stringify(st.project)), 400);
  });
}

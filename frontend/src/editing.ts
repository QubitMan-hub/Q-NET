// Document-editing operations shared by canvases, palette, inspector and shortcuts.
// Each call is one undoable edit of the project document; the engine is reset
// with the new document by the store.

import { useStore } from "./store";
import { clone, uniqueId } from "./format";
import type { AutomatonSpec, Project, Role } from "./types";

export function blankAutomaton(name: string, role: Role): AutomatonSpec {
  return {
    name, role, description: "", ports: ["port"], params: {}, variables: {}, initial: "start",
    states: [
      { id: "start", kind: "initial", label: "Start", ui: { x: 0, y: 0 } },
      { id: "done", kind: "terminal", outcome: "done", label: "Done", ui: { x: 0, y: 180 } },
    ],
    transitions: [{ id: "t0", from: "start", to: "done", trigger: { type: "start" }, guard: true, actions: [] }],
  };
}

/** Ensure the automaton exists in the project, copying it from the library if needed. */
export function ensureAutomaton(p: Project, name: string): boolean {
  if (p.automata[name]) return true;
  const lib = useStore.getState().meta?.automata ?? {};
  if (!lib[name]) return false;
  p.automata[name] = clone(lib[name]);
  return true;
}

export function addParticipant(role: Role, ui: { x: number; y: number }) {
  const s = useStore.getState();
  const prefix = { verifier: "V", prover: "P", adversary: "E", other: "N" }[role];
  const id = uniqueId(prefix, s.project!.participants.map((p) => p.id));
  s.edit((p) => {
    let automaton = Object.values(p.automata).find((a) => a.role === role)?.name;
    if (!automaton) {
      const lib: Record<string, AutomatonSpec> = s.meta?.automata ?? {};
      automaton = Object.values(lib).find((a) => a.role === role && ensureAutomaton(p, a.name))?.name;
    }
    if (!automaton) {
      automaton = uniqueId(`${role}_automaton`, Object.keys(p.automata));
      p.automata[automaton] = blankAutomaton(automaton, role);
    }
    p.participants.push({
      id, role, label: id, position: [0, 0], automaton, params: {}, processing_ns: 0, start_ns: 0,
      clock: { offset_ns: 0, drift_ppm: 0 }, capabilities: s.meta?.role_profiles?.[role] ?? "unrestricted", noise: {}, group: null,
      ui: { x: Math.round(ui.x), y: Math.round(ui.y) },
    });
  }, { select: { kind: "participant", id } });
}

export function duplicateParticipant(pid: string) {
  const s = useStore.getState();
  const src = s.project?.participants.find((p) => p.id === pid);
  if (!src) return;
  const id = uniqueId(src.id, s.project!.participants.map((p) => p.id));
  s.edit((p) => {
    const c = clone(src);
    c.id = id;
    c.label = c.label === src.id ? id : `${c.label} (copy)`;
    c.ui = { x: (src.ui?.x ?? 0) + 40, y: (src.ui?.y ?? 0) + 60 };
    p.participants.push(c);
  }, { select: { kind: "participant", id } });
}

export function deleteSelection() {
  const s = useStore.getState();
  const sel = s.selection;
  if (sel.kind === "participant") {
    s.edit((p) => {
      p.participants = p.participants.filter((x) => x.id !== sel.id);
      p.links = p.links.filter((l) => l.a.node !== sel.id && l.b.node !== sel.id);
      p.resources = p.resources.filter((r) =>
        !(r.holders ?? []).some((h: any) => (typeof h === "string" ? h : h.node) === sel.id));
      if (p.verification.verifiers) p.verification.verifiers = p.verification.verifiers.filter((v) => v !== sel.id);
    }, { select: { kind: "project" } });
  } else if (sel.kind === "link") {
    s.edit((p) => { p.links = p.links.filter((l) => l.id !== sel.id); }, { select: { kind: "project" } });
  } else if (sel.kind === "state") {
    s.edit((p) => {
      const a = p.automata[sel.automaton];
      if (a.initial === sel.id) throw new Error("The initial state cannot be deleted; make another state initial first.");
      a.states = a.states.filter((x) => x.id !== sel.id);
      a.transitions = a.transitions.filter((t) => t.from !== sel.id && t.to !== sel.id);
    }, { select: { kind: "project" } });
  } else if (sel.kind === "transition") {
    s.edit((p) => {
      const a = p.automata[sel.automaton];
      a.transitions = a.transitions.filter((t) => t.id !== sel.id);
    }, { select: { kind: "project" } });
  }
}

export function addState(automaton: string, kind: "normal" | "terminal", outcome: string | null, at?: { x: number; y: number }) {
  const s = useStore.getState();
  const a = s.project!.automata[automaton];
  const base = kind === "terminal" ? (outcome ?? "end") : "state";
  const id = uniqueId(base, a.states.map((x) => x.id));
  s.edit((p) => {
    const ys = p.automata[automaton].states.map((x) => x.ui?.y ?? 0);
    p.automata[automaton].states.push({
      id, kind, outcome, label: id, ui: at ?? { x: 240, y: (ys.length ? Math.max(...ys) : 0) + 140 },
    });
  }, { select: { kind: "state", automaton, id } });
}

export function addTransition(automaton: string, from: string, to: string) {
  const s = useStore.getState();
  const a = s.project!.automata[automaton];
  const id = uniqueId("t", a.transitions.map((t) => t.id));
  s.edit((p) => {
    p.automata[automaton].transitions.push({ id, from, to, trigger: { type: "auto" }, guard: true, actions: [], label: "" });
  }, { select: { kind: "transition", automaton, id } });
}

/** Layered layout of an automaton: BFS depth from the initial state gives the row. */
export function layoutAutomaton(automaton: string) {
  useStore.getState().edit((p) => {
    const a = p.automata[automaton];
    const depth = new Map<string, number>([[a.initial, 0]]);
    const queue = [a.initial];
    while (queue.length) {
      const cur = queue.shift()!;
      for (const t of a.transitions.filter((t) => t.from === cur)) {
        if (!depth.has(t.to)) { depth.set(t.to, depth.get(cur)! + 1); queue.push(t.to); }
      }
    }
    const rows = new Map<number, string[]>();
    for (const st of a.states) {
      const d = depth.get(st.id) ?? Math.max(0, ...depth.values()) + 1;
      rows.set(d, [...(rows.get(d) ?? []), st.id]);
    }
    for (const [d, ids] of rows) {
      ids.forEach((id, i) => {
        const st = a.states.find((x) => x.id === id)!;
        st.ui = { x: (i - (ids.length - 1) / 2) * 280, y: d * 170 };
      });
    }
  });
}

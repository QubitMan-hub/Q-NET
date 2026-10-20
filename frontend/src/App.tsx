import { useCallback, useEffect, useRef, useState } from "react";
import { useStore, type DockTab } from "./store";
import { nsLabel } from "./format";
import type { Project, Role } from "./types";
import { NetworkCanvas } from "./components/NetworkCanvas";
import { AutomatonCanvas } from "./components/AutomatonCanvas";
import { Spacetime } from "./components/Spacetime";
import { Inspector } from "./components/Inspector";
import { ConsolePanel, DecisionPanel, EventLog, Experiments, Timeline, ValidationPanel } from "./components/Dock";
import { Brand, Icon } from "./components/ui";
import { deleteSelection, duplicateParticipant, addState } from "./editing";
import { IN_BROWSER, onEngineStatus } from "./api";

function useDrag(initial: number, axis: "x" | "y", invert = false, min = 120, max = 2000) {
  const [size, setSize] = useState(initial);
  const start = useRef<{ p: number; s: number } | null>(null);
  const onDown = useCallback((e: React.PointerEvent) => {
    start.current = { p: axis === "x" ? e.clientX : e.clientY, s: size };
    const move = (ev: PointerEvent) => {
      if (!start.current) return;
      const d = (axis === "x" ? ev.clientX : ev.clientY) - start.current.p;
      setSize(Math.min(max, Math.max(min, start.current.s + (invert ? -d : d))));
    };
    const up = () => { start.current = null; window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }, [size, axis, invert, min, max]);
  return [size, onDown] as const;
}

function blankProject(): Project {
  return {
    format: "qpvsim-project", version: 1,
    meta: { name: "Untitled protocol", description: "", protocol: { name: "custom", version: "0.1", references: [] },
      assumptions: [], limitations: ["Simulation results are evidence about the modelled behaviour only; they are not security proofs."] },
    physics: { signal_speed_mps: 299792458, allow_superluminal: false },
    simulation: { seed: 1, backend: "density_matrix", max_time_ns: 1000, max_events: 100000, stop_when: "verifiers_decided", priorities: {} },
    claim: { prover: null, position: [0, 0] },
    participants: [], links: [], resources: [], automata: {},
    verification: { rule: "all", verifiers: null }, experiments: [],
  };
}

function Toolbar() {
  const s = useStore();
  const fileRef = useRef<HTMLInputElement>(null);
  const sim = s.sim;
  const outcome = sim?.decision.outcome;
  const download = () => {
    if (!s.project) return;
    const blob = new Blob([JSON.stringify(s.project, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${s.project.meta.name.replace(/[^\w.-]+/g, "_")}.qpv.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return (
    <div className="toolbar">
      <div className="brand"><Brand /><span>QPV Workbench</span></div>
      <input className="project-name" value={s.project?.meta.name ?? ""} aria-label="Project name"
        onChange={(e) => s.edit((p) => { p.meta.name = e.target.value; })} />
      <div className="tool-group">
        <select className="btn" style={{ width: 150 }} value="" aria-label="Open example" onChange={(e) => e.target.value && s.loadExample(e.target.value)}>
          <option value="">Examples…</option>
          {Object.entries(s.meta?.examples ?? {}).map(([k, v]) => <option key={k} value={k}>{v as string}</option>)}
        </select>
        <button className="btn ghost" title="Start an empty project" onClick={() => s.openDocument(blankProject())} data-testid="btn-new"><Icon.plus />New</button>
        <button className="btn ghost" title="Open project file" onClick={() => fileRef.current?.click()}><Icon.open />Open</button>
        <button className="btn ghost" title="Save project file (Ctrl+S)" onClick={download} data-testid="btn-save"><Icon.save />Save</button>
        <input ref={fileRef} type="file" accept=".json,application/json" hidden onChange={async (e) => {
          const f = e.target.files?.[0];
          if (!f) return;
          try { await s.openDocument(JSON.parse(await f.text()) as Project); } catch (err: any) { s.setToast(`Could not open ${f.name}: ${err.message}`, true); }
          e.target.value = "";
        }} />
        <span className="tool-sep" />
        <button className="btn ghost" title="Undo (Ctrl+Z)" disabled={!s.past.length} onClick={s.undo}><Icon.undo /></button>
        <button className="btn ghost" title="Redo (Ctrl+Shift+Z)" disabled={!s.future.length} onClick={s.redo}><Icon.redo /></button>
      </div>
      <span className="grow" />
      <div className="tool-group" aria-label="Simulation controls">
        <button className="btn ghost" title="Reset (R)" onClick={() => s.reset()} data-testid="btn-reset"><Icon.reset />Reset</button>
        <button className="btn ghost" title="Execute one event (N)" disabled={!sim || sim.stopped} onClick={() => s.step(1)} data-testid="btn-step"><Icon.step />Step</button>
        <button className={`btn ${s.playing ? "active" : "ghost"}`} title="Play: advance engine time continuously (Space)" disabled={!sim || sim.stopped}
          onClick={() => s.setPlaying(!s.playing)} data-testid="btn-play">{s.playing ? <Icon.pause /> : <Icon.play />}{s.playing ? "Pause" : "Play"}</button>
        <select className="btn" value={s.playRate} title="Playback rate (simulated ns per second)" aria-label="Playback rate"
          onChange={(e) => s.setPlayRate(Number(e.target.value))}>
          {[0.5, 1, 2, 4, 10, 25].map((r) => <option key={r} value={r}>{r} ns/s</option>)}
        </select>
        <button className="btn primary" title="Run to completion (E)" disabled={!sim || sim.stopped} onClick={() => s.runToEnd()} data-testid="btn-run"><Icon.end />Run</button>
      </div>
      <div className="clock" title="Global simulation time (engine clock)">
        <span className="t" data-testid="clock">{sim ? nsLabel(sim.now_fs, 6) : "—"}</span>
        <span className="xs mono muted">{sim ? `${sim.events_executed} events · ${sim.pending.length} pending` : s.simError ? "invalid project" : "—"}</span>
      </div>
      <span className={`status-pill ${s.simError ? "error" : outcome ?? "pending"}`} data-testid="outcome">
        {s.simError ? "cannot run" : outcome === "accept" ? "accepted" : outcome === "reject" ? "rejected" : sim?.stopped ? "stopped" : "running"}
      </span>
      <button className="btn ghost" title="Toggle dark theme" onClick={s.toggleTheme}><Icon.theme /></button>
    </div>
  );
}

function Palette() {
  const linkKind = useStore((s) => s.linkKind);
  const setLinkKind = useStore((s) => s.setLinkKind);
  const view = useStore((s) => s.view);
  const project = useStore((s) => s.project);
  const focus = useStore((s) => s.focus);
  const roles: [Role, string, string][] = [
    ["verifier", "Verifier", "Trusted; sends challenges, enforces deadlines"],
    ["prover", "Prover", "Claims to be at the claimed position"],
    ["adversary", "Adversary", "Attacker; capabilities enforced"],
    ["other", "Other", "Generic participant"],
  ];
  const aname = project?.participants.find((p) => p.id === focus)?.automaton;
  return (
    <div className="palette">
      <div>
        <h4>Participants</h4>
        {roles.map(([r, label, hint]) => (
          <div key={r} className="palette-item" draggable title={hint}
            onDragStart={(e) => { e.dataTransfer.setData("application/qpv-role", r); e.dataTransfer.effectAllowed = "copy"; }}>
            <span className={`swatch ${r}`} />{label}
          </div>
        ))}
        <div className="hint">Drag onto the network canvas.</div>
      </div>
      <div>
        <h4>Channels</h4>
        <button className={`palette-item${linkKind === "quantum" ? " on" : ""}`} onClick={() => setLinkKind("quantum")} aria-pressed={linkKind === "quantum"}>
          <span className="chan quantum" />Quantum channel</button>
        <button className={`palette-item${linkKind === "classical" ? " on" : ""}`} onClick={() => setLinkKind("classical")} aria-pressed={linkKind === "classical"}>
          <span className="chan classical" />Classical channel</button>
        <div className="hint">Connect two ports to create the selected channel kind. Delay = length / speed + latency.</div>
      </div>
      {view === "automaton" && aname && (
        <div>
          <h4>States ({aname})</h4>
          <button className="palette-item" onClick={() => addState(aname, "normal", null)}>Normal state</button>
          <button className="palette-item" onClick={() => addState(aname, "terminal", "accept")}><span className="swatch prover" />Accept (terminal)</button>
          <button className="palette-item" onClick={() => addState(aname, "terminal", "reject")}><span className="swatch adversary" />Reject (terminal)</button>
          <button className="palette-item" onClick={() => addState(aname, "terminal", "abort")}><span className="swatch other" />Abort (terminal)</button>
          <div className="hint">Transitions carry the trigger (start, receive, timer, auto), guard, and actions — quantum operations, measurements, sends, timers, verdicts. Edit them in the inspector.</div>
        </div>
      )}
      <div>
        <h4>Shortcuts</h4>
        <table className="shortcuts"><tbody>
          {[["Space", "play / pause"], ["N", "step one event"], ["E", "run to the end"], ["R", "reset"], ["Del", "delete selection"],
            ["Ctrl D", "duplicate participant"], ["Ctrl Z", "undo (Shift: redo)"], ["Ctrl S", "save project file"],
            ["1 2 3", "network, automaton, spacetime"], ["`", "focus the console"], ["Esc", "select the project"]].map(([k, v]) => (
            <tr key={k}><td><span className="kbd">{k}</span></td><td>{v}</td></tr>
          ))}
        </tbody></table>
      </div>
    </div>
  );
}

const DOCK_TABS: [DockTab, string][] = [
  ["events", "Events"], ["timeline", "Timeline"], ["console", "Console"],
  ["experiments", "Experiments"], ["validation", "Validation"], ["decision", "Decision"],
];

function Boot({ error }: { error: string | null }) {
  const [status, setStatus] = useState(IN_BROWSER ? "Starting…" : "Connecting to the simulation engine…");
  useEffect(() => onEngineStatus((t) => t && setStatus(t)), []);
  return (
    <div className="boot">
      <Brand />
      <h1>QPV Workbench</h1>
      <p className="boot-status" role="status">{status}</p>
      {IN_BROWSER && !error && (
        <p className="boot-note">The simulation engine runs entirely in your browser. The first visit downloads
          the Python runtime and NumPy (about 15 MB); later visits load from cache.</p>
      )}
      {error && <p className="boot-error">{error}</p>}
    </div>
  );
}

export default function App() {
  const s = useStore();
  const [leftW, dragLeft] = useDrag(196, "x", false, 150, 400);
  const [rightW, dragRight] = useDrag(360, "x", true, 260, 720);
  const [dockH, dragDock] = useDrag(300, "y", true, 120, 900);

  useEffect(() => { s.init(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
      const st = useStore.getState();
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "z") { if (typing) return; e.preventDefault(); e.shiftKey ? st.redo() : st.undo(); return; }
      if (mod && e.key.toLowerCase() === "y") { if (typing) return; e.preventDefault(); st.redo(); return; }
      if (mod && e.key.toLowerCase() === "s") {
        e.preventDefault();
        (document.querySelector('button[title^="Save project"]') as HTMLButtonElement | null)?.click();
        return;
      }
      if (typing) return;
      if (mod && e.key.toLowerCase() === "d") { e.preventDefault(); if (st.selection.kind === "participant") duplicateParticipant(st.selection.id); return; }
      if (mod || e.altKey) return;
      if (e.key === " ") { e.preventDefault(); st.setPlaying(!st.playing); }
      else if (e.key === "n" || e.key === "N") st.step(1);
      else if (e.key === "e" || e.key === "E") st.runToEnd();
      else if (e.key === "r" || e.key === "R") st.reset();
      else if (e.key === "Delete" || e.key === "Backspace") deleteSelection();
      else if (e.key === "1") st.setView("network");
      else if (e.key === "2") st.setView("automaton");
      else if (e.key === "3") st.setView("spacetime");
      else if (e.key === "`") { e.preventDefault(); st.setDock("console"); setTimeout(() => (document.querySelector('[data-testid="console-input"]') as HTMLInputElement | null)?.focus(), 30); }
      else if (e.key === "Escape") st.select({ kind: "project" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!s.project) return <Boot error={s.toast?.error ? s.toast.text : null} />;
  const errors = s.issues.filter((i) => i.level === "error").length;
  const warnings = s.issues.filter((i) => i.level === "warning").length;
  const focusAut = s.project.participants.find((p) => p.id === s.focus)?.automaton;
  return (
    <div className="app">
      <Toolbar />
      <div className="workspace" style={{ gridTemplateColumns: `${leftW}px 1px minmax(0, 1fr) 1px ${rightW}px` }}>
        <div className="panel"><div className="panel-head">Palette</div><div className="panel-body"><Palette /></div></div>
        <div className="splitter-v" onPointerDown={dragLeft} role="separator" aria-orientation="vertical" />
        <div className="workspace" style={{ gridTemplateRows: `minmax(0, 1fr) 1px ${dockH}px`, minWidth: 0 }}>
          <div className="panel" style={{ background: "var(--paper)" }}>
            <div className="tabs" role="tablist">
              <button className={`tab${s.view === "network" ? " on" : ""}`} onClick={() => s.setView("network")} role="tab">Network</button>
              <button className={`tab${s.view === "automaton" ? " on" : ""}`} onClick={() => s.setView("automaton")} role="tab">
                Automaton{s.focus ? <span className="count">{s.focus} · {focusAut}</span> : null}</button>
              <button className={`tab${s.view === "spacetime" ? " on" : ""}`} onClick={() => s.setView("spacetime")} role="tab">Spacetime</button>
              <span className="spacer" />
              <span className="xs muted" style={{ alignSelf: "center", paddingRight: 10 }}>
                {s.project.meta.protocol.name} · backend {s.project.simulation.backend} · seed {s.sim?.seed ?? s.project.simulation.seed}
              </span>
            </div>
            <div style={{ position: "relative", flex: 1, minHeight: 0, display: "flex" }}>
              {s.view === "network" && <NetworkCanvas />}
              {s.view === "automaton" && <AutomatonCanvas />}
              {s.view === "spacetime" && <Spacetime />}
            </div>
          </div>
          <div className="splitter-h" onPointerDown={dragDock} role="separator" aria-orientation="horizontal" />
          <div className="panel">
            <div className="tabs" role="tablist">
              {DOCK_TABS.map(([k, label]) => (
                <button key={k} role="tab" className={`tab${s.dock === k ? " on" : ""}`} onClick={() => s.setDock(k)} data-testid={`dock-${k}`}>
                  {label}
                  {k === "events" && s.sim && <span className="count">{s.sim.trace_length}</span>}
                  {k === "validation" && (errors + warnings > 0) && <span className="count" style={{ color: errors ? "var(--reject)" : "var(--warn)" }}>{errors ? `${errors} errors` : `${warnings} warnings`}</span>}
                  {k === "decision" && s.sim && <span className="count">{s.sim.decision.outcome}</span>}
                </button>
              ))}
            </div>
            <div style={{ flex: 1, minHeight: 0 }}>
              {s.dock === "events" && <EventLog />}
              {s.dock === "timeline" && <Timeline />}
              {s.dock === "console" && <ConsolePanel />}
              {s.dock === "experiments" && <Experiments />}
              {s.dock === "validation" && <ValidationPanel />}
              {s.dock === "decision" && <DecisionPanel />}
            </div>
          </div>
        </div>
        <div className="splitter-v" onPointerDown={dragRight} role="separator" aria-orientation="vertical" />
        <div className="panel">
          <div className="panel-head">Inspector<span className="grow" />
            {s.selection.kind !== "project" && <button className="btn ghost" onClick={() => s.select({ kind: "project" })}>Project</button>}
          </div>
          <div className="panel-body"><Inspector /></div>
        </div>
      </div>
      {s.toast && <div className={`toast${s.toast.error ? " error" : ""}`} role="status">{s.toast.text}</div>}
    </div>
  );
}

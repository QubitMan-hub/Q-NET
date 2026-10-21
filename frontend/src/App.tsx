import { useCallback, useEffect, useRef, useState } from "react";
import { useStore, type DockTab } from "./store";
import { nsLabel } from "./format";
import type { Project } from "./types";
import { GLOSSARY } from "./glossary";
import { NetworkCanvas } from "./components/NetworkCanvas";
import { AutomatonCanvas } from "./components/AutomatonCanvas";
import { Geometry } from "./components/SpaceView";
import { Inspector } from "./components/Inspector";
import { ConsolePanel, DecisionPanel, EventLog, Experiments, Timeline, ValidationPanel } from "./components/Dock";
import { ComparePanel, TimingPanel } from "./components/QpvPanels";
import { ScenarioDialog, StartScreen } from "./components/ScenarioDialog";
import { PlayPanel, answering } from "./components/PlayPanel";
import { Brand, Icon } from "./components/ui";
import { deleteSelection, duplicateParticipant, addState } from "./editing";
import { IN_BROWSER, onEngineStatus } from "./api";
import { storageGet, storageSet } from "./store";

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

type Panels = { left: boolean; right: boolean; expert: boolean; toggle: (side: "left" | "right") => void; toggleExpert: () => void;
  showWelcome: () => void; buildScenario: () => void };

function Toolbar({ panels }: { panels: Panels }) {
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
      <div className="tool-group">
        {panels.expert && <button className={`btn ghost${panels.left ? " active" : ""}`} title="Show or hide the palette" aria-pressed={panels.left}
          onClick={() => panels.toggle("left")}><Icon.panelLeft /></button>}
        <button className={`btn ghost${panels.right ? " active" : ""}`} title="Show or hide the side panel" aria-pressed={panels.right}
          onClick={() => panels.toggle("right")}><Icon.panelRight /></button>
      </div>
      <input className="project-name" value={s.project?.meta.name ?? ""} aria-label="Project name" data-rev={s.revision}
        onChange={(e) => s.edit((p) => { p.meta.name = e.target.value; })} />
      <div className="tool-group">
        {panels.expert && <select className="btn" style={{ width: 150 }} value="" aria-label="Open example" onChange={(e) => e.target.value && s.loadExample(e.target.value)}>
          <option value="">Examples…</option>
          {Object.entries(s.meta?.examples ?? {}).map(([k, v]) => <option key={k} value={k}>{v as string}</option>)}
        </select>}
        <button className="btn ghost" title="New scenario: dimension, verifiers, claim, prover or attack (or a blank project)" onClick={panels.buildScenario}
          data-testid="btn-new"><Icon.plus /><span className="lbl">New</span></button>
        <button className="btn ghost" title="Open project file" onClick={() => fileRef.current?.click()}><Icon.open /><span className="lbl">Open</span></button>
        <button className="btn ghost" title="Save project file (Ctrl+S)" onClick={download} data-testid="btn-save"><Icon.save /><span className="lbl">Save</span></button>
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
        <button className="btn ghost" title="Reset (R)" onClick={() => s.reset()} data-testid="btn-reset"><Icon.reset /><span className="lbl">Reset</span></button>
        {panels.expert && <>
        <button className="btn ghost" title="Execute one event (N)" disabled={!sim || sim.stopped} onClick={() => s.step(1)} data-testid="btn-step"><Icon.step /><span className="lbl">Step</span></button>
        <button className={`btn ${s.playing ? "active" : "ghost"}`} title="Play: advance engine time continuously (Space)" disabled={!sim || sim.stopped}
          onClick={() => s.setPlaying(!s.playing)} data-testid="btn-play">{s.playing ? <Icon.pause /> : <Icon.play />}<span className="lbl">{s.playing ? "Pause" : "Play"}</span></button>
        <select className="btn rate" value={s.playRate} title="Playback rate (simulated ns per second)" aria-label="Playback rate"
          onChange={(e) => s.setPlayRate(Number(e.target.value))}>
          {[0.5, 1, 2, 4, 10, 25].map((r) => <option key={r} value={r}>{r} ns/s</option>)}
        </select>
        </>}
        <button className="btn primary" title="Run to completion (E)" disabled={!sim || sim.stopped} onClick={() => s.runToEnd()} data-testid="btn-run"><Icon.end /><span className="lbl lbl-keep">Run</span></button>
      </div>
      <div className="clock" title="Global simulation time (engine clock)">
        <span className="t" data-testid="clock">{sim ? nsLabel(sim.now_fs, 6) : "—"}</span>
        <span className="xs mono muted">{sim ? `${sim.events_executed} events · ${sim.pending.length} pending` : s.simError ? "invalid project" : "—"}</span>
      </div>
      <span className={`status-pill ${s.simError ? "error" : outcome ?? "pending"}`} data-testid="outcome" data-rev={sim?.revision ?? ""}>
        {s.simError ? "cannot run" : outcome === "accept" ? "accepted" : outcome === "reject" ? "rejected" : sim?.stopped ? "stopped" : "running"}
      </span>
      <button className={`btn ghost${panels.expert ? " active" : ""}`} aria-pressed={panels.expert} onClick={panels.toggleExpert} data-testid="btn-expert"
        title="Expert tools: palette, protocol editor, step-by-step playback, event log, experiments">Expert</button>
      <button className="btn ghost" title="Getting started" aria-label="Getting started" onClick={panels.showWelcome}><Icon.help /></button>
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
  const kinds: [string, string, string, string][] = [
    ["verifier:quantum", "Quantum verifier", "verifier vq", GLOSSARY.quantum_verifier],
    ["verifier:classical", "Classical verifier", "verifier vc", GLOSSARY.classical_verifier],
    ["prover", "Prover", "prover", GLOSSARY.prover],
    ["adversary", "Adversary", "adversary", GLOSSARY.adversary],
    ["other", "Other", "other", GLOSSARY.other],
  ];
  const aname = project?.participants.find((p) => p.id === focus)?.automaton;
  return (
    <div className="palette">
      <div>
        <h4>Participants</h4>
        {kinds.map(([k, label, swatch, hint]) => (
          <div key={k} className="palette-item" draggable title={hint}
            onDragStart={(e) => { e.dataTransfer.setData("application/qpv-role", k); e.dataTransfer.effectAllowed = "copy"; }}>
            <span className={`swatch ${swatch}`} />{label}
          </div>
        ))}
        <div className="hint">Drag onto the network canvas.</div>
      </div>
      <div>
        <h4>Channels</h4>
        <button className={`palette-item${linkKind === "quantum" ? " on" : ""}`} onClick={() => setLinkKind("quantum")} aria-pressed={linkKind === "quantum"}
          title={GLOSSARY.quantum_link}><span className="chan quantum" />Quantum channel</button>
        <button className={`palette-item${linkKind === "classical" ? " on" : ""}`} onClick={() => setLinkKind("classical")} aria-pressed={linkKind === "classical"}
          title={GLOSSARY.classical_link}><span className="chan classical" />Classical channel</button>
        <div className="hint">Drag between two ports to connect them; a port that carries only one kind decides the channel. Delay = length / speed + latency.</div>
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
  ["decision", "Result"], ["compare", "Compare"], ["timing", "Timing"], ["events", "Events"], ["timeline", "Timeline"],
  ["console", "Console"], ["experiments", "Experiments"], ["validation", "Validation"],
];
const SIMPLE_TABS: DockTab[] = ["decision", "compare", "timing"];

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

const WELCOME_KEY = "qpv.welcome.dismissed";
const EXPERT_KEY = "qpv.expert";

export default function App() {
  const s = useStore();
  const [leftW, dragLeft] = useDrag(196, "x", false, 150, 400);
  const [rightW, dragRight] = useDrag(360, "x", true, 260, 720);
  const [dockH, dragDock] = useDrag(300, "y", true, 120, 900);
  const narrow = typeof window !== "undefined" && window.innerWidth < 1100;
  const [left, setLeft] = useState(!narrow);
  const [right, setRight] = useState(window.innerWidth >= 900);
  const [welcome, setWelcome] = useState(() => storageGet(WELCOME_KEY) !== "1");
  const [builder, setBuilder] = useState(false);
  const [expert, setExpert] = useState(() => storageGet(EXPERT_KEY) === "1");
  const [details, setDetails] = useState(false);
  const panels: Panels = {
    left: left && expert, right, expert,
    toggle: (side) => (side === "left" ? setLeft((v) => !v) : setRight((v) => !v)),
    toggleExpert: () => setExpert((v) => {
      storageSet(EXPERT_KEY, v ? null : "1");
      const st = useStore.getState();
      if (v && !SIMPLE_TABS.includes(st.dock)) st.setDock("decision");
      if (v && st.view === "automaton") st.setView("network");
      return !v;
    }),
    showWelcome: () => setWelcome(true),
    buildScenario: () => setBuilder(true),
  };
  const closeWelcome = () => { setWelcome(false); storageSet(WELCOME_KEY, "1"); };
  // Give the canvas room when the window becomes narrow (panels can be reopened).
  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth < 1100) setLeft(false);
      if (window.innerWidth < 900) setRight(false);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => { if (s.selection.kind !== "project") setDetails(true); }, [s.selection]);

  useEffect(() => { s.init(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // A shared link (#example=name) opened in a tab that is already running.
  useEffect(() => {
    const onHash = () => {
      const m = window.location.hash.match(/example=([\w-]+)/);
      const st = useStore.getState();
      if (m && st.meta?.examples?.[m[1]]) st.loadExample(m[1]);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

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
      else if (e.key === "2" && storageGet(EXPERT_KEY) === "1") st.setView("automaton");
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
  const dock = expert || SIMPLE_TABS.includes(s.dock) ? s.dock : "decision";
  const focusAut = s.project.participants.find((p) => p.id === s.focus)?.automaton;
  return (
    <div className="app">
      <Toolbar panels={panels} />
      <div className="workspace" style={{ gridTemplateColumns: `${panels.left ? leftW : 0}px ${panels.left ? 1 : 0}px minmax(0, 1fr) ${right ? 1 : 0}px ${right ? `min(${rightW}px, 70vw)` : "0px"}` }}>
        <div className="panel" style={panels.left ? undefined : { visibility: "hidden", overflow: "hidden" }}><div className="panel-head">Palette</div><div className="panel-body"><Palette /></div></div>
        <div className="splitter-v" onPointerDown={dragLeft} role="separator" aria-orientation="vertical" style={panels.left ? undefined : { visibility: "hidden", overflow: "hidden" }} />
        <div className="workspace" style={{ gridTemplateRows: `minmax(0, 1fr) 1px ${dockH}px`, minWidth: 0 }}>
          <div className="panel" style={{ background: "var(--paper)" }}>
            <div className="tabs" role="tablist">
              <button className={`tab${s.view === "network" ? " on" : ""}`} onClick={() => s.setView("network")} role="tab">Network</button>
              {expert && <button className={`tab${s.view === "automaton" ? " on" : ""}`} onClick={() => s.setView("automaton")} role="tab">
                Automaton{s.focus ? <span className="count">{s.focus} · {focusAut}</span> : null}</button>}
              <button className={`tab${s.view === "spacetime" ? " on" : ""}`} onClick={() => s.setView("spacetime")} role="tab">Geometry</button>
              <span className="spacer" />
              {expert && <label className="who-answers" title={s.analysis?.qpv ? `${GLOSSARY.attack} Switching reruns at once.` : "Switching who answers needs a QPV setup (build one with New)."}>
                Who answers
                <select className="select attack-switch" value={answering(s.project)} aria-label="Who answers at the claim" data-testid="attack-switch"
                  disabled={!s.analysis?.qpv} onChange={(e) => s.switchAttack(e.target.value)}>
                  {!answering(s.project) && <option value="">—</option>}
                  {Object.entries(s.scenarios?.answerers ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>}
              {expert && <span className="xs muted tab-info" style={{ alignSelf: "center", paddingRight: 10 }}>
                {s.project.meta.protocol.name} · backend {s.project.simulation.backend} · seed {s.sim?.seed ?? s.project.simulation.seed}
              </span>}
            </div>
            <div style={{ position: "relative", flex: 1, minHeight: 0, display: "flex" }}>
              {s.view === "network" && <NetworkCanvas />}
              {s.view === "automaton" && <AutomatonCanvas />}
              {s.view === "spacetime" && <Geometry />}
            </div>
          </div>
          <div className="splitter-h" onPointerDown={dragDock} role="separator" aria-orientation="horizontal" />
          <div className="panel">
            <div className="tabs" role="tablist">
              {DOCK_TABS.filter(([k]) => expert || SIMPLE_TABS.includes(k)).map(([k, label]) => (
                <button key={k} role="tab" className={`tab${dock === k ? " on" : ""}`} onClick={() => s.setDock(k)} data-testid={`dock-${k}`}>
                  {label}
                  {k === "events" && s.sim && <span className="count">{s.sim.trace_length}</span>}
                  {k === "validation" && (errors + warnings > 0) && <span className="count" style={{ color: errors ? "var(--reject)" : "var(--warn)" }}>{errors ? `${errors} errors` : `${warnings} warnings`}</span>}
                  {k === "decision" && s.sim && <span className="count">{s.sim.decision.outcome}</span>}
                  {k === "timing" && !!s.analysis?.timing.issues.length && <span className="count" style={{ color: "var(--warn)" }}>{s.analysis.timing.issues.length}</span>}
                </button>
              ))}
            </div>
            <div style={{ flex: 1, minHeight: 0 }}>
              {dock === "events" && <EventLog />}
              {dock === "timeline" && <Timeline />}
              {dock === "timing" && <TimingPanel />}
              {dock === "compare" && <ComparePanel />}
              {dock === "console" && <ConsolePanel />}
              {dock === "experiments" && <Experiments />}
              {dock === "validation" && <ValidationPanel />}
              {dock === "decision" && <DecisionPanel />}
            </div>
          </div>
        </div>
        <div className="splitter-v" onPointerDown={dragRight} role="separator" aria-orientation="vertical" style={right ? undefined : { visibility: "hidden" }} />
        <div className="panel" style={right ? undefined : { visibility: "hidden", overflow: "hidden" }}>
          <div className="tabs" role="tablist">
            <button role="tab" className={`tab${details ? "" : " on"}`} onClick={() => { setDetails(false); s.select({ kind: "project" }); }} data-testid="tab-play">Play</button>
            <button role="tab" className={`tab${details ? " on" : ""}`} onClick={() => setDetails(true)} data-testid="tab-details">Details</button>
            <span className="spacer" />
            {details && s.selection.kind !== "project" && <button className="btn ghost" onClick={() => s.select({ kind: "project" })}>Project</button>}
          </div>
          <div className="panel-body">{details ? <Inspector /> : <PlayPanel onDetails={() => setDetails(true)} />}</div>
        </div>
      </div>
      {welcome && <StartScreen onClose={closeWelcome} onBuild={() => setBuilder(true)} />}
      {builder && <ScenarioDialog onClose={() => setBuilder(false)} />}
      {s.toast && <div className={`toast${s.toast.error ? " error" : ""}`} role="status">{s.toast.text}</div>}
    </div>
  );
}

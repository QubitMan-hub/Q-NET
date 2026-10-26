import { useState } from "react";
import type { Project } from "../types";
import { useStore } from "../store";
import { IN_BROWSER } from "../api";
import { GLOSSARY } from "../glossary";
import { Field, NumberInput, Select } from "./ui";

/** An empty project for building a protocol from scratch in the editor. */
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

const DIMS = [1, 2, 3] as const;
const COLUMNS: [string, string][] = [["honest", "Honest prover"], ["unentangled", "Unentangled attack"], ["teleport", "Teleportation attack"]];

async function buildAndRun(body: Record<string, any>) {
  const s = useStore.getState();
  await s.loadScenario(body);
  await useStore.getState().runToEnd();
  s.setView("spacetime");
  s.setDock("decision");
}

/** Build a complete QPV scenario in one step: dimension, verifiers, claim, prover or attack. */
export function ScenarioDialog({ onClose }: { onClose: () => void }) {
  const answerers = useStore((s) => s.scenarios?.answerers ?? {});
  const policies = useStore((s) => s.scenarios?.policies ?? ["breidbart"]);
  const [f, setF] = useState({ dim: 2, verifiers: 3, radius: 3, claim: [0, 0, 0], tolerance: 0.5, combine: "xor", who: "honest", policy: "breidbart" });
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch });
  const minV = f.dim === 1 ? 2 : f.dim + 1;
  const teleportBlocked = f.who === "teleport" && f.combine !== "xor";
  const body = () => ({
    dim: f.dim, verifiers: f.verifiers, radius_m: f.radius, claim: f.claim.slice(0, Math.max(2, f.dim)), tolerance_ns: f.tolerance,
    combine: f.combine, policy: f.policy,
    ...(["honest", "displaced"].includes(f.who) ? { prover: f.who } : { attack: f.who }),
  });
  const go = async (run: boolean) => {
    onClose();
    if (run) await buildAndRun(body()); else await useStore.getState().loadScenario(body());
  };
  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog" role="dialog" aria-labelledby="scenario-title" onClick={(e) => e.stopPropagation()} data-testid="scenario-dialog">
        <h2 id="scenario-title">New QPV scenario</h2>
        <p>Verifiers are placed evenly around the claimed position, wired, timed and ready to run.</p>
        <Field label="Dimension" title={GLOSSARY.hull}>
          <div className="seg" role="radiogroup" aria-label="Dimension">
            {DIMS.map((d) => <button key={d} role="radio" aria-checked={f.dim === d} className={`btn ghost${f.dim === d ? " active" : ""}`}
              onClick={() => set({ dim: d, verifiers: d === 1 ? 2 : Math.max(d + 1, f.verifiers === 2 ? d + 1 : f.verifiers) })}>{d}D</button>)}
          </div>
        </Field>
        <Field label="Verifiers" title="One quantum verifier plus classical verifiers sending basis shares; at least d+1 for secure positioning.">
          {f.dim === 1 ? <span className="small">2 (one on each side)</span>
            : <NumberInput value={f.verifiers} min={minV} max={12} step={1} ariaLabel="Number of verifiers" onCommit={(v) => set({ verifiers: Math.max(minV, Math.round(v ?? minV)) })} />}
        </Field>
        <Field label="Distance (m)" title="How far each verifier stands from the claimed position.">
          <NumberInput value={f.radius} min={0.01} step={0.5} ariaLabel="Verifier distance" onCommit={(v) => set({ radius: v ?? 3 })} />
        </Field>
        <Field label="Claimed position (m)" title={GLOSSARY.claim}>
          <div className="row">
            {f.claim.slice(0, Math.max(1, f.dim)).map((c, i) => <NumberInput key={i} value={c} step={0.5} ariaLabel={`Claim ${"xyz"[i]}`}
              onCommit={(v) => set({ claim: f.claim.map((x, j) => (j === i ? v ?? 0 : x)) })} />)}
          </div>
        </Field>
        <Field label="Who answers" title={GLOSSARY.attack}>
          <Select value={f.who} options={Object.entries(answerers).map(([value, label]) => ({ value, label }))} onChange={(v) => set({ who: v })} ariaLabel="Who answers" />
        </Field>
        {f.who === "unentangled" && (
          <Field label="Measurement" title={GLOSSARY.policy}><Select value={f.policy} options={policies} onChange={(v) => set({ policy: v })} /></Field>
        )}
        <details className="advanced">
          <summary>Advanced</summary>
          <div>
            <Field label="Tolerance (ns)" title={GLOSSARY.tolerance}>
              <NumberInput value={f.tolerance} min={0} step={0.1} ariaLabel="Tolerance" onCommit={(v) => set({ tolerance: v ?? 0.5 })} />
            </Field>
            <Field label="Basis from shares" title={GLOSSARY.combine}>
              <Select value={f.combine} options={[{ value: "xor", label: "XOR of bits" }, { value: "inner_product", label: "inner product of bit strings" }]}
                onChange={(v) => set({ combine: v })} />
            </Field>
          </div>
        </details>
        {teleportBlocked && <div className="note" style={{ color: "var(--reject)" }}>The teleportation chain attack applies to XOR shares only.</div>}
        {f.combine === "inner_product" && f.verifiers < 3 && <div className="note" style={{ color: "var(--reject)" }}>The inner product needs at least 3 verifiers.</div>}
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn ghost" onClick={() => { onClose(); useStore.getState().openDocument(blankProject()); }}
            title="An empty project to build in the editor" data-testid="btn-blank">Blank project</button>
          <span className="grow" />
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn" disabled={teleportBlocked} onClick={() => go(false)}>Build</button>
          <button className="btn primary" disabled={teleportBlocked} onClick={() => go(true)} data-testid="scenario-run">Build and run</button>
        </div>
      </div>
    </div>
  );
}

/** First-visit guide: ready-made 1D, 2D and 3D scenarios, or build your own. */
export function StartScreen({ onClose, onBuild }: { onClose: () => void; onBuild: () => void }) {
  const ready = useStore((s) => s.scenarios?.ready ?? []);
  const showAttacks = useStore((s) => s.showAttacks);
  const toggleAttacks = useStore((s) => s.toggleAttacks);
  const columns = showAttacks ? COLUMNS : COLUMNS.slice(0, 1);
  const open = async (id: string) => { onClose(); await buildAndRun({ id }); };
  return (
    <div className="welcome start" role="dialog" aria-labelledby="welcome-title" data-testid="start-screen">
      <h2 id="welcome-title">Simulate quantum position verification</h2>
      <p>Verifiers send a qubit and the pieces of its basis so they meet only at the claimed position; whoever answers there in time,
        and correctly, is accepted. Pick a setup to run it now{IN_BROWSER ? " in your browser" : ""}.</p>
      <table className="start-grid">
        <thead><tr><th />{columns.map(([, label]) => <th key={label}>{label}</th>)}</tr></thead>
        <tbody>
          {DIMS.map((d) => (
            <tr key={d}>
              <th>{d}D <span className="muted">{d === 1 ? "2 verifiers" : `${d + 1} verifiers`}</span></th>
              {columns.map(([who]) => {
                const r = ready.find((x) => x.id === `${d}d_${who}`);
                return <td key={who}>{r && <button className="btn" onClick={() => open(r.id)} data-testid={`start-${r.id}`}>Run</button>}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <label className="row small" style={{ marginBottom: 8 }}>
        <input type="checkbox" checked={showAttacks} onChange={toggleAttacks} data-testid="show-attacks" />
        Show attack examples (unentangled and entangled attackers)
      </label>
      <p className="welcome-note">The honest prover is always accepted.{showAttacks && <> The unentangled attack wins about 85% of rounds (cos²(π/8));
        the teleportation attack, with entanglement, always wins.</>} Results describe the model, not a security proof.</p>
      <div className="row">
        <button className="btn" onClick={() => { onClose(); onBuild(); }}>Build your own…</button>
        <span className="grow" />
        <button className="btn primary" onClick={onClose}>Start exploring</button>
      </div>
    </div>
  );
}

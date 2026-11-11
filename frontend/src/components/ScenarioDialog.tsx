import { useState } from "react";
import type { Project, Recipe, RecipeField } from "../types";
import { storageGet, storageSet, useStore } from "../store";
import { IN_BROWSER } from "../api";
import { GLOSSARY } from "../glossary";
import { Advanced, Check, Field, Icon, NumberInput, Select, TextInput } from "./ui";
import { copyText, recipeLink } from "../links";

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

/** Saved recipes ("My scenarios"), kept in this browser. */
const MY_KEY = "qpv.myRecipes";
export function myRecipes(): Recipe[] {
  try { return JSON.parse(storageGet(MY_KEY) ?? "[]"); } catch { return []; }
}
export function saveMyRecipes(list: Recipe[]) { storageSet(MY_KEY, JSON.stringify(list)); }

const DEFAULT_RECIPE: Recipe = { base: { dim: 2, who: "honest" }, twists: [] };

/** Participant ids a recipe will have, for the party pickers (verifiers, prover or attackers, added parties). */
function parties(r: Recipe): string[] {
  const dim = Number(r.base.dim ?? 2);
  const n = r.base.verifiers ?? (dim === 1 ? 2 : dim + 1);
  const ids = Array.from({ length: n }, (_, j) => `V${j}`);
  ids.push(...(["honest", "displaced"].includes(r.base.who ?? "honest") ? ["P"] : Array.from({ length: n }, (_, j) => `E${j}`)));
  let a = 0, m = 0;
  for (const t of r.twists) {
    if (t.type === "join") ids.push(t.id || `A${++a}`);
    if (t.type === "intercept") ids.push(`M${++m}`);
  }
  return ids;
}

function FieldInput({ f, value, onChange, recipe, label }: {
  f: RecipeField; value: any; onChange: (v: any) => void; recipe: Recipe; label: string;
}) {
  if (f.type === "bool") return <Check checked={!!value} onChange={onChange} label={label} />;
  const v = value ?? f.default;
  let input;
  if (f.type === "choice") {
    input = <Select value={String(v)} ariaLabel={label} options={(f.choices ?? []).map((c) => ({ value: String(c), label: String(c) }))}
      onChange={(x) => onChange(typeof f.default === "number" ? Number(x) : x)} />;
  } else if (f.type === "party" || f.type === "verifier") {
    const ids = parties(recipe).filter((id) => f.type === "party" || id.startsWith("V"));
    const opts = [...(f.allow_all ? ["all"] : []), ...ids, ...(ids.includes(v) || v === "all" ? [] : [v])];
    input = <Select value={String(v)} ariaLabel={label} options={opts} onChange={onChange} />;
  } else {
    input = <NumberInput value={v === null || v === undefined ? null : Number(v)} allowNull={f.default === null}
      step={0.1} ariaLabel={label} onCommit={onChange} />;
  }
  return <Field label={label}>{input}</Field>;
}

/** Compose any scenario: a base QPV setup plus twists, all described by the engine's recipe schema. */
export function ScenarioDialog({ onClose, initial }: { onClose: () => void; initial?: Recipe | null }) {
  const schema = useStore((s) => s.scenarios?.recipe);
  const [r, setR] = useState<Recipe>(() => JSON.parse(JSON.stringify(initial ?? DEFAULT_RECIPE)));
  const [json, setJson] = useState<string | null>(null);
  const [adding, setAdding] = useState("");
  if (!schema) return null;
  const base = (k: string, v: any) => setR({ ...r, base: { ...r.base, [k]: v } });
  const twist = (i: number, k: string, v: any) => setR({ ...r, twists: r.twists.map((t, j) => (j === i ? { ...t, [k]: v } : t)) });
  const move = (i: number, d: number) => {
    const t = [...r.twists]; const j = i + d;
    if (j < 0 || j >= t.length) return;
    [t[i], t[j]] = [t[j], t[i]];
    setR({ ...r, twists: t });
  };
  const add = (type: string) => {
    if (!type) return;
    const fields = schema.twists[type].fields;
    setR({ ...r, twists: [...r.twists, { type, ...Object.fromEntries(Object.entries(fields).map(([k, f]) => [k, f.default])) }] });
    setAdding("");
  };
  const dim = Number(r.base.dim ?? 2);
  const protocol: string = r.base.protocol ?? "bb84";
  const claim: number[] = r.base.claim ?? [0, 0, 0];
  const go = async (run: boolean) => { onClose(); await useStore.getState().loadRecipe(r, run); };
  const save = () => {
    const title = (r.title ?? "").trim() || `My scenario ${myRecipes().length + 1}`;
    saveMyRecipes([...myRecipes().filter((x) => x.title !== title), { ...r, title }]);
    useStore.getState().setToast(`Saved “${title}” to My scenarios`);
  };
  const shown = (f: RecipeField) => !(f.dims && dim < f.dims);
  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog builder" role="dialog" aria-labelledby="scenario-title" onClick={(e) => e.stopPropagation()} data-testid="scenario-dialog">
        <h2 id="scenario-title">Scenario builder</h2>
        <p>Start from a standard setup, then add twists: move people, slow or break links, put someone in the middle,
          leak secrets. Every scenario in the demo list is built this way.</p>
        <Field label="Name"><TextInput value={r.title ?? ""} placeholder="My scenario" onCommit={(v) => setR({ ...r, title: v })} /></Field>
        <h3 className="builder-h">Setup</h3>
        <Field label="Dimension" title={GLOSSARY.hull}>
          <div className="seg" role="radiogroup" aria-label="Dimension">
            {[1, 2, 3].map((d) => <button key={d} role="radio" aria-checked={dim === d} className={`btn ghost${dim === d ? " active" : ""}`}
              onClick={() => setR({ ...r, base: { ...r.base, dim: d, verifiers: d === 1 ? undefined : r.base.verifiers } })}>{d}D</button>)}
          </div>
        </Field>
        {dim > 1 && <Field label="Verifiers" title="At least d + 1 for secure positioning; empty = d + 1.">
          <NumberInput value={r.base.verifiers ?? null} allowNull nullLabel={String(dim + 1)} min={dim + 1} max={12} step={1}
            ariaLabel="Number of verifiers" onCommit={(v) => base("verifiers", v === null ? undefined : Math.round(v))} /></Field>}
        <Field label="Distance (m)" title="How far each verifier stands from the claimed position.">
          <NumberInput value={r.base.radius_m ?? 3} min={0.01} step={0.5} ariaLabel="Verifier distance" onCommit={(v) => base("radius_m", v ?? 3)} />
        </Field>
        <Field label="Claimed position (m)" title={GLOSSARY.claim}>
          <div className="row">
            {[0, 1, 2].slice(0, Math.max(1, dim)).map((i) => <NumberInput key={i} value={claim[i] ?? 0} step={0.5} ariaLabel={`Claim ${"xyz"[i]}`}
              onCommit={(v) => base("claim", [0, 1, 2].map((j) => (j === i ? v ?? 0 : claim[j] ?? 0)).slice(0, Math.max(2, dim)))} />)}
          </div>
        </Field>
        <Field label="Protocol" title="Which position-verification protocol the verifiers run.">
          <Select value={protocol} ariaLabel="Protocol"
            onChange={(v) => setR({ ...r, base: { ...r.base, protocol: v, who: "honest", ...(v === "bb84f" ? { dim: 1 } : {}) } })}
            options={Object.entries(schema.protocols).map(([value, p]) => ({ value, label: p.label }))} />
        </Field>
        {protocol === "qudit" && <FieldInput f={schema.base.qudit_d} label={schema.base.qudit_d.label} value={r.base.qudit_d} recipe={r}
          onChange={(v) => base("qudit_d", v)} />}
        {protocol === "bb84f" && (["f", "f_bits", "pairs"] as const).map((k) => (
          <FieldInput key={k} f={schema.base[k]} label={schema.base[k].label} value={r.base[k]} recipe={r} onChange={(v) => base(k, v)} />
        ))}
        <Field label="Who answers" title={GLOSSARY.attack}>
          <Select value={r.base.who ?? "honest"} ariaLabel="Who answers" onChange={(v) => base("who", v)}
            options={(schema.protocols[protocol]?.answerers ?? Object.keys(schema.answerers)).map((value) => ({ value, label: schema.answerers[value] ?? value }))} />
        </Field>
        <Field label="Real site" title="Place the verifiers at real coordinates with real links and detectors (2D, 3 verifiers).">
          <Select value={r.base.site ?? "none"} ariaLabel="Real site" onChange={(v) => base("site", v === "none" ? undefined : v)}
            options={[{ value: "none", label: "None (regular layout)" }, ...Object.entries(schema.sites).map(([value, label]) => ({ value, label }))]} />
        </Field>
        <Advanced>
          {(protocol === "bb84" ? ["tolerance_ns", "policy", "combine", "bases"] as const : ["tolerance_ns"] as const).filter((k) => schema.base[k]).map((k) => (
            <FieldInput key={k} f={schema.base[k]} label={schema.base[k].label} value={r.base[k]} recipe={r} onChange={(v) => base(k, v)} />
          ))}
        </Advanced>
        <h3 className="builder-h">Twists <span className="muted small">applied in order</span></h3>
        {r.twists.length === 0 && <div className="note">No twists: the standard setup. Add one below.</div>}
        {r.twists.map((t, i) => {
          const spec = schema.twists[t.type];
          return (
            <div key={i} className="twist" data-testid={`twist-${i}`}>
              <div className="row twist-head">
                <b className="grow">{i + 1}. {spec?.label ?? t.type}</b>
                <button className="btn ghost" aria-label="Move up" onClick={() => move(i, -1)}><Icon.up /></button>
                <button className="btn ghost" aria-label="Move down" onClick={() => move(i, 1)}><Icon.down /></button>
                <button className="btn ghost danger" aria-label="Remove twist" onClick={() => setR({ ...r, twists: r.twists.filter((_, j) => j !== i) })}><Icon.trash /></button>
              </div>
              {Object.entries(spec?.fields ?? {}).filter(([, f]) => shown(f)).map(([k, f]) => (
                <FieldInput key={k} f={f} label={f.label} value={t[k]} recipe={r} onChange={(v) => twist(i, k, v)} />
              ))}
            </div>
          );
        })}
        <div className="row" style={{ marginTop: 6 }}>
          <Select value={adding} ariaLabel="Add a twist" onChange={add}
            options={[{ value: "", label: "+ Add a twist…" }, ...Object.entries(schema.twists).map(([value, t]) => ({ value, label: t.label }))]} />
        </div>
        <details className="advanced" onToggle={(e) => setJson((e.target as HTMLDetailsElement).open ? JSON.stringify(r, null, 1) : null)}>
          <summary>Recipe as JSON</summary>
          {json !== null && <textarea className="textarea code" rows={10} spellCheck={false} value={json} onChange={(e) => setJson(e.target.value)}
            onBlur={() => { try { setR(JSON.parse(json)); } catch (e: any) { useStore.getState().setToast(`Not valid JSON: ${e.message}`, true); } }} />}
        </details>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn ghost" onClick={() => { onClose(); useStore.getState().openDocument(blankProject()); }}
            title="An empty project to build in the editor" data-testid="btn-blank">Blank project</button>
          <span className="grow" />
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn" onClick={save} data-testid="scenario-save">Save</button>
          <button className="btn" title="Copy a link that opens exactly this scenario" data-testid="scenario-link"
            onClick={async () => { const l = recipeLink(r); useStore.getState().setToast(await copyText(l) ? "Link copied" : l); }}>Copy link</button>
          <button className="btn" onClick={() => go(false)}>Build</button>
          <button className="btn primary" onClick={() => go(true)} data-testid="scenario-run">Build and run</button>
        </div>
      </div>
    </div>
  );
}

/** First visit: three clear ways in, and the standard setups for anyone who wants to start from scratch. */
export function StartScreen({ onClose, onBuild, onDemos }: {
  onClose: () => void; onBuild: () => void; onDemos: () => void; onEdit: (r: Recipe) => void;
}) {
  const ready = useStore((s) => s.scenarios?.ready ?? []);
  const count = useStore((s) => s.scenarios?.demos.demos.length ?? 0);
  const showAttacks = useStore((s) => s.showAttacks);
  const toggleAttacks = useStore((s) => s.toggleAttacks);
  const columns = showAttacks ? COLUMNS : COLUMNS.slice(0, 1);
  const open = async (id: string) => { onClose(); await buildAndRun({ id }); };
  const watch = async (id: string) => {
    onClose();
    await useStore.getState().loadDemo(id);
    await useStore.getState().reset();
    await useStore.getState().animateRound();
  };
  const ways: [string, string, () => void, string][] = [
    ["Watch an honest prover pass", "Two verifiers time a photon and its key to meet at one spot. See the answer come back in time.",
      () => watch("a1_midway"), "start-watch-honest"],
    ["Watch cheaters break it", "Two cheaters share one entangled pair and pass every round. The protocol's biggest weakness.",
      () => watch("d1_teleport"), "start-watch-cheat"],
    [`Browse all ${count} scenarios`, "Noise, lost photons, moving provers, real cities, other protocols. Each runs with one click.",
      () => { onClose(); onDemos(); }, "start-demos"],
  ];
  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="welcome start" role="dialog" aria-labelledby="welcome-title" data-testid="start-screen" onClick={(e) => e.stopPropagation()}>
        <div className="start-hero">
          <h2 id="welcome-title">Can a prover prove where it is?</h2>
          <p>Quantum position verification checks a location with the speed of light and a photon that cannot be copied.
            This workbench simulates it{IN_BROWSER ? ", right here in your browser" : ""}: honest provers, cheaters, real-world hardware.</p>
        </div>
        <div className="start-ways">
          {ways.map(([title, text, fn, testid]) => (
            <button key={testid} className="start-way" onClick={fn} data-testid={testid}>
              <b>{title}</b><span>{text}</span><Icon.chevron />
            </button>
          ))}
        </div>
        <details className="start-more">
          <summary>Start from a standard setup</summary>
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
          <label className="row small">
            <input type="checkbox" checked={showAttacks} onChange={toggleAttacks} data-testid="show-attacks" />
            Include the cheaters (without and with entanglement)
          </label>
        </details>
        <div className="row start-foot">
          <button className="btn ghost" onClick={() => { onClose(); onBuild(); }}>Build your own</button>
          <span className="grow" />
          <span className="muted small">Results describe the model, not a security proof.</span>
          <button className="btn primary" onClick={onClose}>Start exploring</button>
        </div>
      </div>
    </div>
  );
}

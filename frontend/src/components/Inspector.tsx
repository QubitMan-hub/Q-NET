import { useEffect, useMemo, useState } from "react";
import { useStore } from "../store";
import { api } from "../api";
import { nsLabel, short } from "../format";
import type { Action, AutomatonSpec, Issue, LinkSpec, ParticipantSpec, Project, Role, StateSpec, TransitionSpec, VerifierType } from "../types";
import { Advanced, Check, Field, NumberInput, Section, Select, TextArea, TextInput, Icon } from "./ui";
import { GLOSSARY } from "../glossary";
import { deleteSelection, duplicateParticipant, ensureAutomaton } from "../editing";

function JsonField({ value, onCommit, rows = 3 }: { value: any; onCommit: (v: any) => void; rows?: number }) {
  const text = JSON.stringify(value, null, 1);
  const [v, setV] = useState(text);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setV(text); setErr(null); }, [text]);
  return (
    <div>
      <textarea className="textarea code" rows={rows} value={v} spellCheck={false}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => {
          if (v === text) return;
          try { onCommit(JSON.parse(v)); setErr(null); } catch (e: any) { setErr(`Not valid JSON: ${e.message}`); }
        }} />
      {err && <div className="note" style={{ color: "var(--reject)" }}>{err}</div>}
    </div>
  );
}

/** A literal-or-expression value: numbers/booleans/JSON stay literal, anything else is an expression string. */
function parseLiteral(s: string): any {
  const t = s.trim();
  if (t === "") return "";
  try { return JSON.parse(t); } catch { return s; }
}

function Issues({ prefix }: { prefix: string | string[] }) {
  const issues = useStore((s) => s.issues);
  const pre = Array.isArray(prefix) ? prefix : [prefix];
  const mine = issues.filter((i) => pre.some((p) => i.path.startsWith(p)));
  if (!mine.length) return null;
  return (
    <div className="section" style={{ padding: 0 }}>
      {mine.map((i: Issue, k) => (
        <div className="issue" key={k}><span className={`lvl ${i.level}`}>{i.level}</span>
          <span className="grow">{i.message}<div className="path">{i.path}</div></span></div>
      ))}
    </div>
  );
}

function KV({ rows }: { rows: [string, any, boolean?][] }) {
  return (
    <table className="kv-table"><tbody>
      {rows.map(([k, v, mono], i) => <tr key={i}><td>{k}</td><td className={mono === false ? "" : "mono"}>{v}</td></tr>)}
    </tbody></table>
  );
}

// ======================================================================= project
function ProjectInspector({ p }: { p: Project }) {
  const edit = useStore((s) => s.edit);
  const meta = useStore((s) => s.meta);
  const select = useStore((s) => s.select);
  const ids = p.participants.map((x) => x.id);
  return (
    <>
      <Section title="Project">
        <Field label="Name"><TextInput value={p.meta.name} onCommit={(v) => edit((d) => { d.meta.name = v; })} /></Field>
        <Field label="Description" stack><TextArea value={p.meta.description} onCommit={(v) => edit((d) => { d.meta.description = v; })} /></Field>
        <Field label="Protocol"><TextInput value={p.meta.protocol.name} onCommit={(v) => edit((d) => { d.meta.protocol.name = v; })} /></Field>
        <Field label="Version"><TextInput value={p.meta.protocol.version} onCommit={(v) => edit((d) => { d.meta.protocol.version = v; })} /></Field>
        <Field label="References" stack><TextArea rows={3} value={p.meta.protocol.references.join("\n")}
          onCommit={(v) => edit((d) => { d.meta.protocol.references = v.split("\n").filter(Boolean); })} /></Field>
      </Section>
      <Section title="Claim and verification">
        <Field label="Claimed x (m)" title={GLOSSARY.claim}><NumberInput value={p.claim.position[0] ?? 0} step={0.1} onCommit={(v) => edit((d) => { d.claim.position[0] = v ?? 0; })} /></Field>
        <Field label="Claimed prover" title={GLOSSARY.claimed_prover}>
          <Select value={p.claim.prover ?? ""} options={[{ value: "", label: "(none: attack scenario)" }, ...ids.map((i) => ({ value: i, label: i }))]}
            onChange={(v) => edit((d) => { d.claim.prover = v || null; })} />
        </Field>
        <Field label="Decision rule" title={GLOSSARY.rule}>
          <Select value={p.verification.rule} options={[{ value: "all", label: "all verifiers accept" }, { value: "any", label: "any verifier accepts" }, { value: "k_of_n", label: "k of n accept" }]}
            onChange={(v) => edit((d) => { d.verification.rule = v; if (v === "k_of_n" && !d.verification.k) d.verification.k = 1; })} />
        </Field>
        {p.verification.rule === "k_of_n" && <Field label="k"><NumberInput value={p.verification.k ?? 1} step={1} min={1} onCommit={(v) => edit((d) => { d.verification.k = v ?? 1; })} /></Field>}
        <Field label="Verifiers" title="Empty = every participant with role verifier">
          <TextInput value={(p.verification.verifiers ?? []).join(", ")} placeholder="all role=verifier"
            onCommit={(v) => edit((d) => { const l = v.split(",").map((x) => x.trim()).filter(Boolean); d.verification.verifiers = l.length ? l : null; })} />
        </Field>
      </Section>
      <Section title="Physics and simulation">
        <Field label="Signal speed" title="metres per second; the default is the exact SI speed of light">
          <NumberInput value={p.physics.signal_speed_mps} onCommit={(v) => edit((d) => { d.physics.signal_speed_mps = v ?? 299792458; })} />
        </Field>
        <Field label="Backend" title={GLOSSARY.backend}>
          <Select value={p.simulation.backend} options={Object.keys(meta?.backends ?? { density_matrix: 1 })}
            onChange={(v) => edit((d) => { d.simulation.backend = v; })} />
        </Field>
        <div className="note" style={{ marginBottom: 6 }}>{meta?.backends?.[p.simulation.backend]?.formalism}</div>
        <Field label="Seed" title={GLOSSARY.seed}><NumberInput value={p.simulation.seed} step={1} min={0} onCommit={(v) => edit((d) => { d.simulation.seed = Math.round(v ?? 0); })} /></Field>
        <Field label="Max time (ns)" title={GLOSSARY.max_time}><NumberInput value={p.simulation.max_time_ns} min={0} onCommit={(v) => edit((d) => { d.simulation.max_time_ns = v ?? 1000; })} /></Field>
        <Field label="Stop when" title={GLOSSARY.stop_when}>
          <Select value={p.simulation.stop_when} options={[{ value: "verifiers_decided", label: "all verifiers decided" }, { value: "quiescent", label: "no events remain" }]}
            onChange={(v) => edit((d) => { d.simulation.stop_when = v; })} />
        </Field>
        <Field label="Priorities" stack title="Event kind -> priority overrides (lower runs first at equal time)">
          <JsonField value={p.simulation.priorities} onCommit={(v) => edit((d) => { d.simulation.priorities = v; })} rows={2} />
        </Field>
      </Section>
      <Section title="Pre-shared resources" aside={
        <span className="row">
          <button className="btn ghost" onClick={() => edit((d) => { d.resources.push({ id: `epr${d.resources.length}`, type: "epr", state: "phi+", werner_p: 0, holders: [{ node: ids[0] ?? "", slot: "e" }, { node: ids[1] ?? "", slot: "e" }] }); })}>+ EPR pair</button>
          <button className="btn ghost" onClick={() => edit((d) => { d.resources.push({ id: `rand${d.resources.length}`, type: "shared_random", holders: [], vars: { r: "rand_bit()" } }); })}>+ shared random</button>
        </span>}>
        {p.resources.length === 0 && <div className="note">None. Resources model out-of-band setup before t = 0 (shared verifier randomness, pre-shared entanglement).</div>}
        {p.resources.map((r, i) => (
          <div key={i} className="row" style={{ marginBottom: 4 }}>
            <button className="btn ghost grow" style={{ justifyContent: "flex-start" }} onClick={() => select({ kind: "resource", index: i })}>
              <span className="mono">{r.id}</span><span className="muted">{r.type} · {(r.holders ?? []).map((h: any) => typeof h === "string" ? h : `${h.node}.${h.slot}`).join(", ")}</span>
            </button>
          </div>
        ))}
      </Section>
      <Section title="Assumptions">
        <TextArea rows={5} value={p.meta.assumptions.join("\n")} onCommit={(v) => edit((d) => { d.meta.assumptions = v.split("\n").filter(Boolean); })} />
      </Section>
      <Section title="Limitations">
        <TextArea rows={5} value={p.meta.limitations.join("\n")} onCommit={(v) => edit((d) => { d.meta.limitations = v.split("\n").filter(Boolean); })} />
      </Section>
      <Issues prefix={["format", "simulation", "physics", "claim", "verification", "resources"]} />
    </>
  );
}

// ======================================================================= participant
function ParticipantInspector({ p, project }: { p: ParticipantSpec; project: Project }) {
  const edit = useStore((s) => s.edit);
  const meta = useStore((s) => s.meta);
  const live = useStore((s) => s.sim?.nodes[p.id]);
  const select = useStore((s) => s.select);
  const setView = useStore((s) => s.setView);
  const upd = (fn: (q: ParticipantSpec, d: Project) => void) => edit((d) => { fn(d.participants.find((x) => x.id === p.id)!, d); });
  const automata = Array.from(new Set([...Object.keys(project.automata), ...Object.keys(meta?.automata ?? {})])).sort();
  const spec: AutomatonSpec | undefined = project.automata[p.automaton];
  const capsProfile = typeof p.capabilities === "string" ? p.capabilities : p.capabilities?.profile ?? "unrestricted";
  const capsOverrides = typeof p.capabilities === "string" ? {} : Object.fromEntries(Object.entries(p.capabilities).filter(([k]) => k !== "profile"));
  const vtype: VerifierType = p.verifier_type ?? useStore.getState().verifierTypes[p.id] ?? "classical";
  return (
    <>
      <Section title={<><span className={`swatch ${p.role}`} style={{ display: "inline-block", marginRight: 6 }} />Participant {p.id}</>} aside={
        <span className="row">
          <button className="btn ghost" title="Duplicate (Ctrl+D)" onClick={() => duplicateParticipant(p.id)}><Icon.copy /></button>
          <button className="btn ghost danger" title="Delete (Del)" onClick={() => deleteSelection()}><Icon.trash /></button>
        </span>}>
        <Field label="Id"><TextInput value={p.id} code onCommit={(v) => edit((d) => {
          const id = v.trim();
          if (!id || d.participants.some((x) => x.id === id)) throw new Error(`Id “${id}” is empty or already used.`);
          const q = d.participants.find((x) => x.id === p.id)!;
          q.id = id;
          for (const l of d.links) { if (l.a.node === p.id) l.a.node = id; if (l.b.node === p.id) l.b.node = id; }
          for (const r of d.resources) r.holders = (r.holders ?? []).map((h: any) => typeof h === "string" ? (h === p.id ? id : h) : (h.node === p.id ? { ...h, node: id } : h));
          if (d.verification.verifiers) d.verification.verifiers = d.verification.verifiers.map((x) => x === p.id ? id : x);
          if (d.claim.prover === p.id) d.claim.prover = id;
        }, { select: { kind: "participant", id: v.trim() } })} /></Field>
        <Field label="Label"><TextInput value={p.label} onCommit={(v) => upd((q) => { q.label = v; })} /></Field>
        <Field label="Role" title={GLOSSARY[p.role]}>
          <Select<Role> value={p.role} options={["verifier", "prover", "adversary", "other"]} onChange={(v) => upd((q) => { q.role = v; })} />
        </Field>
        {p.role === "verifier" && (
          <Field label="Verifier type" title={GLOSSARY[`${vtype}_verifier`]}>
            <Select<VerifierType> value={vtype} options={[{ value: "quantum", label: "quantum (sends the qubit)" }, { value: "classical", label: "classical (sends a basis share)" }]}
              onChange={(v) => edit((d) => {
                const q = d.participants.find((x) => x.id === p.id)!;
                q.verifier_type = v;
                if (q.automaton.startsWith("qpv_verifier_") && ensureAutomaton(d, `qpv_verifier_${v}`)) q.automaton = `qpv_verifier_${v}`;
              })} />
          </Field>
        )}
        <Field label="Position x, y (m)" title={GLOSSARY.position}>
          <div className="row">
            <NumberInput value={p.position[0] ?? 0} step={0.1} ariaLabel="x position" onCommit={(v) => upd((q) => { q.position[0] = v ?? 0; })} />
            <NumberInput value={p.position[1] ?? 0} step={0.1} ariaLabel="y position" onCommit={(v) => upd((q) => { q.position[1] = v ?? 0; })} />
          </div>
        </Field>
        <Field label="Processing (ns)" title={GLOSSARY.processing}>
          <NumberInput value={p.processing_ns} step={0.05} min={0} onCommit={(v) => upd((q) => { q.processing_ns = v ?? 0; })} />
        </Field>
        <Advanced>
          <Field label="Start at (ns)" title={GLOSSARY.start}><NumberInput value={p.start_ns} step={1} min={0} onCommit={(v) => upd((q) => { q.start_ns = v ?? 0; })} /></Field>
          <Field label="Clock offset (ns)" title={GLOSSARY.clock}><NumberInput value={p.clock.offset_ns} step={0.1} onCommit={(v) => upd((q) => { q.clock.offset_ns = v ?? 0; })} /></Field>
          <Field label="Clock drift (ppm)" title={GLOSSARY.clock}><NumberInput value={p.clock.drift_ppm} step={1} onCommit={(v) => upd((q) => { q.clock.drift_ppm = v ?? 0; })} /></Field>
          <Field label="Coalition" title={GLOSSARY.coalition}><TextInput value={p.group ?? ""} placeholder="none" onCommit={(v) => upd((q) => { q.group = v || null; })} /></Field>
        </Advanced>
      </Section>
      <Section title="Strategy (automaton)" aside={<button className="btn ghost" onClick={() => setView("automaton")}>Open</button>}>
        <Field label="Automaton" title={GLOSSARY.automaton}>
          <Select value={p.automaton} options={automata} onChange={(v) => edit((d) => {
            if (!ensureAutomaton(d, v)) throw new Error(`Unknown automaton ${v}`);
            d.participants.find((x) => x.id === p.id)!.automaton = v;
          })} />
        </Field>
        {spec?.description && <div className="note" style={{ marginBottom: 6 }}>{spec.description}</div>}
        {Object.entries(spec?.params ?? {}).map(([k, d]) => (
          <Field key={k} label={k} title={(GLOSSARY as Record<string, string>)[k.replace(/_ns$/, "")] ?? d.description}>
            <TextInput code value={JSON.stringify(p.params[k] ?? d.default)}
              onCommit={(v) => upd((q) => { q.params[k] = parseLiteral(v); })} />
          </Field>
        ))}
      </Section>
      <Section title="Capabilities" aside={<span className="xs muted">enforced at run time</span>}>
        <Field label="Profile" title={GLOSSARY.capabilities}>
          <Select value={capsProfile} options={Object.keys(meta?.profiles ?? { unrestricted: 1 })}
            onChange={(v) => upd((q) => { q.capabilities = Object.keys(capsOverrides).length ? { profile: v, ...capsOverrides } : v; })} />
        </Field>
        <div className="note" style={{ marginBottom: 6 }}>{meta?.profiles?.[capsProfile]?.description}</div>
        <Advanced>
          <Field label="Overrides" stack title='e.g. {"max_qubits": 1, "min_processing_ns": 0.3}'>
            <JsonField value={capsOverrides} rows={2} onCommit={(v) => upd((q) => { q.capabilities = Object.keys(v).length ? { profile: capsProfile, ...v } : capsProfile; })} />
          </Field>
          <div className="small muted" style={{ margin: "6px 0 2px" }}>Local noise</div>
          {(["measurement_flip", "gate_depolarizing", "memory_t1_ns", "memory_t2_ns"] as const).map((k) => (
            <Field key={k} label={k.replace(/_/g, " ")}>
              <NumberInput value={p.noise[k] ?? null} allowNull nullLabel="off" min={0} onCommit={(v) => upd((q) => { if (v === null) delete q.noise[k]; else q.noise[k] = v; })} />
            </Field>
          ))}
        </Advanced>
      </Section>
      {live && (
        <Section title="Runtime" aside={<span className="xs muted">engine state</span>}>
          <KV rows={[
            ["state", live.busy ? `${live.state} → executing ${live.busy.transition} until ${nsLabel(live.busy.complete_fs)}` : live.state],
            ["entered", nsLabel(live.state_entered_fs)],
            ["local clock", `${nsLabel(live.local_time_fs)} (${live.clock})`],
            ["outcome", live.outcome ?? "—"],
            ["variables", short(live.vars, 200)],
            ["mailbox", live.mailbox.length ? live.mailbox.map((m) => `m${m}`).join(", ") : "empty"],
            ["timers", Object.keys(live.timers).length ? Object.entries(live.timers).map(([k, v]: any) => `${k} @ ${nsLabel(v.target_local_fs)} local`).join("; ") : "none"],
            ["observations", short(live.observations, 200)],
          ]} />
          {live.error && <div className="explain" style={{ color: "var(--reject)", marginTop: 6 }}>{live.error}</div>}
          {live.verdict && <div className="explain" style={{ marginTop: 6 }}>
            <b style={{ color: live.verdict.outcome === "accept" ? "var(--accept)" : "var(--reject)" }}>{live.verdict.outcome}</b> at {nsLabel(live.verdict.time_fs)}: {live.verdict.reason}
          </div>}
          {Object.entries(live.qubits).map(([slot, q]: any) => (
            <div key={slot} className="explain" style={{ marginTop: 6 }}>
              <b className="mono">{slot}</b> Bloch ({q.bloch?.map((x: number) => x.toFixed(3)).join(", ")}), purity {q.purity?.toFixed(4)}
              {q.entangled_with?.length > 0 && <> · entangled with {q.entangled_with.join(", ")}</>}
              <div className="note">Simulation-only view of the backend state; the participant itself cannot read it.</div>
            </div>
          ))}
          {live.history.length > 0 && <div style={{ marginTop: 8 }}>
            <div className="xs muted" style={{ marginBottom: 3 }}>Transition history</div>
            {live.history.map((h, i) => (
              <div key={i} className="row small" style={{ cursor: "pointer" }} onClick={() => select({ kind: "event", seq: h.begin_record })}>
                <span className="mono muted" style={{ width: 92, textAlign: "right" }}>{nsLabel(h.begin_fs, 4)}</span>
                <span className="mono">{h.transition}</span><span className="muted">{h.from} → {h.to}</span>
              </div>
            ))}
          </div>}
        </Section>
      )}
      <Issues prefix={[`participants[${p.id}]`, `automata.${p.automaton}`]} />
    </>
  );
}

// ======================================================================= link
function LinkInspector({ id, project }: { id: string; project: Project }) {
  const edit = useStore((s) => s.edit);
  const summary = useStore((s) => s.sim?.links?.find((l) => l.id === id));
  const l = project.links.find((x) => x.id === id);
  if (!l) return <div className="empty">Link no longer exists.</div>;
  const upd = (fn: (x: LinkSpec) => void) => edit((d) => fn(d.links.find((x) => x.id === id)!));
  const endpoints = project.participants.map((p) => p.id);
  return (
    <>
      <Section title={<><span className={`chan ${l.kind}`} style={{ display: "inline-block", marginRight: 8, verticalAlign: 3 }} />Link {l.id}</>}
        aside={<button className="btn ghost danger" onClick={() => deleteSelection()}><Icon.trash /></button>}>
        <Field label="Kind" title={GLOSSARY[`${l.kind}_link`]}><Select value={l.kind} options={["quantum", "classical"]} onChange={(v) => upd((x) => { x.kind = v; })} /></Field>
        {(["a", "b"] as const).map((end) => (
          <Field key={end} label={`Endpoint ${end.toUpperCase()}`}>
            <div className="row">
              <Select value={l[end].node} options={endpoints} onChange={(v) => upd((x) => { x[end].node = v; })} />
              <TextInput code value={l[end].port} ariaLabel="port" onCommit={(v) => upd((x) => { x[end].port = v; })} />
            </div>
          </Field>
        ))}
        <Check checked={l.directed} onChange={(v) => upd((x) => { x.directed = v; })} label="Directed (A → B only)" />
      </Section>
      <Section title="Propagation" aside={<span className="xs muted">delay from the engine</span>}>
        {summary && <div className="explain" style={{ marginBottom: 8 }}>
          {summary.distance_m.toPrecision(7)} m at {summary.speed_mps} m/s → {nsLabel(summary.propagation_fs)}
          {summary.latency_fs > 0 && <> + latency {nsLabel(summary.latency_fs)}</>} = <b>{nsLabel(summary.delay_fs)}</b>
        </div>}
        <Field label="Length (m)" title="Empty = straight-line distance between the endpoints"><NumberInput value={l.length_m} allowNull nullLabel="straight line" min={0} onCommit={(v) => upd((x) => { x.length_m = v; })} /></Field>
        <Field label="Speed (m/s)" title="Empty = project signal speed"><NumberInput value={l.speed_mps} allowNull nullLabel="project speed" min={0} onCommit={(v) => upd((x) => { x.speed_mps = v; })} /></Field>
        <Advanced>
          <Field label="Latency (ns)" title={GLOSSARY.latency}><NumberInput value={l.latency_ns} min={0} step={0.1} onCommit={(v) => upd((x) => { x.latency_ns = v ?? 0; })} /></Field>
          <Field label="Jitter (ns)" title={GLOSSARY.jitter}><NumberInput value={l.jitter_ns} min={0} step={0.1} onCommit={(v) => upd((x) => { x.jitter_ns = v ?? 0; })} /></Field>
          <Field label="Loss probability" title={GLOSSARY.loss}><NumberInput value={l.loss_prob} min={0} max={1} step={0.05} onCommit={(v) => upd((x) => { x.loss_prob = v ?? 0; })} /></Field>
          <Field label="Attenuation (dB/km)" title={GLOSSARY.attenuation}><NumberInput value={l.attenuation_db_per_km} min={0} step={0.1} onCommit={(v) => upd((x) => { x.attenuation_db_per_km = v ?? 0; })} /></Field>
        </Advanced>
      </Section>
      <Section title="Noise">
        {l.kind === "classical" && <div className="note">Classical channels carry bits exactly; noise applies to quantum channels.</div>}
        {l.kind === "quantum" && (["depolarizing", "dephasing", "bitflip", "amplitude_damping"] as const).map((k) => (
          <Field key={k} label={k.replace("_", " ")} title={k === "depolarizing" ? GLOSSARY.depolarizing : undefined}>
            <NumberInput value={l.noise[k] ?? null} allowNull nullLabel="off" min={0} max={1} step={0.05} onCommit={(v) => upd((x) => { if (v === null) delete x.noise[k]; else x.noise[k] = v; })} />
          </Field>
        ))}
      </Section>
      <Issues prefix={`links[${l.id}]`} />
    </>
  );
}

// ======================================================================= state
function StateInspector({ automaton, id, project }: { automaton: string; id: string; project: Project }) {
  const edit = useStore((s) => s.edit);
  const focus = useStore((s) => s.focus);
  const live = useStore((s) => (focus ? s.sim?.nodes[focus] : undefined));
  const a = project.automata[automaton];
  const st = a?.states.find((x) => x.id === id);
  if (!a || !st) return <div className="empty">State no longer exists.</div>;
  const upd = (fn: (x: StateSpec, aa: AutomatonSpec) => void) => edit((d) => {
    const aa = d.automata[automaton];
    fn(aa.states.find((x) => x.id === id)!, aa);
  });
  const visits = live?.automaton === automaton ? live.state_log.filter((s) => s.state === id) : [];
  return (
    <>
      <Section title={<>State <span className="mono">{st.id}</span> <span className="muted">in {automaton}</span></>}
        aside={<button className="btn ghost danger" onClick={() => deleteSelection()}><Icon.trash /></button>}>
        <Field label="Id"><TextInput code value={st.id} onCommit={(v) => edit((d) => {
          const aa = d.automata[automaton];
          const nid = v.trim();
          if (!nid || aa.states.some((x) => x.id === nid)) throw new Error(`State id “${nid}” is empty or taken.`);
          aa.states.find((x) => x.id === id)!.id = nid;
          aa.transitions.forEach((t) => { if (t.from === id) t.from = nid; if (t.to === id) t.to = nid; });
          if (aa.initial === id) aa.initial = nid;
        }, { select: { kind: "state", automaton, id: v.trim() } })} /></Field>
        <Field label="Label"><TextInput value={st.label ?? ""} onCommit={(v) => upd((x) => { x.label = v; })} /></Field>
        <Field label="Kind"><Select value={st.kind ?? "normal"} options={["initial", "normal", "terminal"]} onChange={(v) => upd((x, aa) => {
          x.kind = v as any;
          if (v === "initial") { aa.states.forEach((o) => { if (o.id !== id && o.kind === "initial") o.kind = "normal"; }); aa.initial = id; }
        })} /></Field>
        {st.kind === "terminal" && <Field label="Outcome" title={GLOSSARY.outcome}><Select value={st.outcome ?? "done"} options={["accept", "reject", "abort", "done"]} onChange={(v) => upd((x) => { x.outcome = v; })} /></Field>}
        <Field label="Description" stack><TextArea value={st.description ?? ""} onCommit={(v) => upd((x) => { x.description = v; })} /></Field>
        <div className="note">Outgoing transitions are tried in list order; the first whose trigger is satisfied and guard is true fires.</div>
      </Section>
      {visits.length > 0 && <Section title={`Occupancy (${focus})`}>
        {visits.map((v, i) => <div key={i} className="small mono">{nsLabel(v.entered_fs)} → {v.exited_fs === null ? "now" : nsLabel(v.exited_fs)}</div>)}
      </Section>}
      <Issues prefix={`automata.${automaton}.states[${id}]`} />
    </>
  );
}

// ======================================================================= transition
const OPS_FIELDS: Record<string, string[]> = {
  set: ["var", "expr"], send: ["port", "tag", "value"], send_qubit: ["port", "tag", "qubit"],
  prepare: ["qubit", "state"], prepare_bb84: ["qubit", "bit", "basis"], gate: ["gate", "qubits", "angle"],
  measure: ["qubit", "basis", "angle", "result", "discard"], bell_measure: ["qubits", "results"], discard: ["qubit"],
  timer: ["name", "after_ns", "at_ns"], cancel_timer: ["name"], verdict: ["outcome", "reason"], record: ["key", "value"], log: ["text"],
};
const EXPR_FIELDS = new Set(["expr", "value", "bit", "basis", "angle", "after_ns", "at_ns", "reason", "text"]);

function ActionEditor({ a, onChange, onRemove, onMove }: { a: Action; onChange: (a: Action) => void; onRemove: () => void; onMove: (d: number) => void }) {
  const fields = OPS_FIELDS[a.op] ?? Object.keys(a).filter((k) => k !== "op");
  return (
    <div className="action-row">
      <div className="row">
        <div style={{ width: 130 }}>
          <Select value={a.op} options={Object.keys(OPS_FIELDS)} onChange={(op) => onChange({ op })} />
        </div>
        <span className="grow" />
        <button className="btn ghost" title="Move up" aria-label="Move action up" onClick={() => onMove(-1)}><Icon.up /></button>
        <button className="btn ghost" title="Move down" aria-label="Move action down" onClick={() => onMove(1)}><Icon.down /></button>
        <button className="btn ghost danger" title="Remove" aria-label="Remove action" onClick={onRemove}><Icon.trash /></button>
      </div>
      {fields.map((f) => {
        const v = a[f];
        const isList = f === "qubits" || f === "results";
        return (
          <Field key={f} label={f} title={EXPR_FIELDS.has(f) ? "expression" : "literal"}>
            <TextInput code value={v === undefined ? "" : isList ? (v as string[]).join(", ") : typeof v === "string" ? v : JSON.stringify(v)}
              placeholder={EXPR_FIELDS.has(f) ? "expression" : ""}
              onCommit={(s) => {
                const next = { ...a };
                if (s.trim() === "") delete next[f];
                else if (isList) next[f] = s.split(",").map((x) => x.trim()).filter(Boolean);
                else if (f === "discard") next[f] = s.trim() !== "false";
                else if (EXPR_FIELDS.has(f)) next[f] = /^-?\d+(\.\d+)?$/.test(s.trim()) ? Number(s) : s;
                else next[f] = s;
                onChange(next);
              }} />
          </Field>
        );
      })}
    </div>
  );
}

function TransitionInspector({ automaton, id, project }: { automaton: string; id: string; project: Project }) {
  const edit = useStore((s) => s.edit);
  const focus = useStore((s) => s.focus);
  const sim = useStore((s) => s.sim);
  const select = useStore((s) => s.select);
  const meta = useStore((s) => s.meta);
  const a = project.automata[automaton];
  const t = a?.transitions.find((x) => x.id === id);
  const runs = useMemo(() => (sim?.trace ?? []).filter((r) => r.kind === "transition.begin" && r.data.transition === id &&
    sim?.nodes[r.node!]?.automaton === automaton), [sim, id, automaton]);
  if (!a || !t) return <div className="empty">Transition no longer exists.</div>;
  const upd = (fn: (x: TransitionSpec) => void) => edit((d) => fn(d.automata[automaton].transitions.find((x) => x.id === id)!));
  const states = a.states.map((s) => s.id);
  const idx = a.transitions.indexOf(t);
  return (
    <>
      <Section title={<>Transition <span className="mono">{t.id}</span> <span className="muted">in {automaton}</span></>}
        aside={<button className="btn ghost danger" onClick={() => deleteSelection()}><Icon.trash /></button>}>
        <Field label="Id"><TextInput code value={t.id} onCommit={(v) => edit((d) => {
          const nid = v.trim();
          const aa = d.automata[automaton];
          if (!nid || aa.transitions.some((x) => x.id === nid)) throw new Error(`Transition id “${nid}” is empty or taken.`);
          aa.transitions.find((x) => x.id === id)!.id = nid;
        }, { select: { kind: "transition", automaton, id: v.trim() } })} /></Field>
        <Field label="Label"><TextInput value={t.label ?? ""} onCommit={(v) => upd((x) => { x.label = v; })} /></Field>
        <Field label="From → to">
          <div className="row">
            <Select value={t.from} options={states} onChange={(v) => upd((x) => { x.from = v; })} />
            <Select value={t.to} options={states} onChange={(v) => upd((x) => { x.to = v; })} />
          </div>
        </Field>
        <Field label="Priority" title="Order among transitions leaving the same state">
          <div className="row"><span className="mono small">#{a.transitions.filter((x) => x.from === t.from).indexOf(t) + 1}</span>
            <button className="btn ghost" disabled={idx === 0} onClick={() => edit((d) => { const l = d.automata[automaton].transitions; [l[idx - 1], l[idx]] = [l[idx], l[idx - 1]]; })}>Earlier</button>
            <button className="btn ghost" disabled={idx === a.transitions.length - 1} onClick={() => edit((d) => { const l = d.automata[automaton].transitions; [l[idx + 1], l[idx]] = [l[idx], l[idx + 1]]; })}>Later</button>
          </div>
        </Field>
      </Section>
      <Section title="Trigger and guard">
        <Field label="Trigger">
          <Select value={t.trigger.type} options={meta?.triggers ?? ["auto", "receive", "start", "timer"]}
            onChange={(v) => upd((x) => { x.trigger = v === "receive" ? { type: v, tags: ["msg"] } : v === "timer" ? { type: v, name: "timeout" } : { type: v as any }; })} />
        </Field>
        {t.trigger.type === "receive" && <>
          <Field label="Message tags" title="All listed tags must be present in the mailbox"><TextInput code value={(t.trigger.tags ?? []).join(", ")}
            onCommit={(v) => upd((x) => { x.trigger.tags = v.split(",").map((s) => s.trim()).filter(Boolean); })} /></Field>
          <Field label="Port"><TextInput code value={t.trigger.port ?? ""} placeholder="any" onCommit={(v) => upd((x) => { x.trigger.port = v || null; })} /></Field>
        </>}
        {t.trigger.type === "timer" && <Field label="Timer name"><TextInput code value={t.trigger.name ?? ""} onCommit={(v) => upd((x) => { x.trigger.name = v; })} /></Field>}
        <Field label="Guard" title="Expression; available: parameters, variables, msg, msgs, now, pos, claim_pos, claim_travel_ns, …">
          <TextInput code value={typeof t.guard === "string" ? t.guard : String(t.guard ?? true)} onCommit={(v) => upd((x) => { x.guard = v.trim() === "" || v.trim() === "true" ? true : v; })} />
        </Field>
        <Field label="Duration (ns)" title="Expression; empty = participant processing time">
          <TextInput code value={t.duration_ns === null || t.duration_ns === undefined ? "" : String(t.duration_ns)} placeholder="participant default"
            onCommit={(v) => upd((x) => { x.duration_ns = v.trim() === "" ? null : (/^\d+(\.\d+)?$/.test(v.trim()) ? Number(v) : v); })} />
        </Field>
      </Section>
      <Section title={`Actions (${t.actions.length})`} aside={<button className="btn ghost" onClick={() => upd((x) => { x.actions.push({ op: "set", var: "v", expr: "0" }); })}><Icon.plus />Add</button>}>
        {t.actions.length === 0 && <div className="note">No actions: the transition only changes state.</div>}
        {t.actions.map((act, i) => (
          <ActionEditor key={i} a={act}
            onChange={(na) => upd((x) => { x.actions[i] = na; })}
            onRemove={() => upd((x) => { x.actions.splice(i, 1); })}
            onMove={(dlt) => upd((x) => { const j = i + dlt; if (j < 0 || j >= x.actions.length) return; [x.actions[i], x.actions[j]] = [x.actions[j], x.actions[i]]; })} />
        ))}
      </Section>
      <Section title={`Executions (${runs.length})`} aside={<span className="xs muted">from the trace</span>}>
        {runs.length === 0 && <div className="note">Not fired in the current run.</div>}
        {runs.map((r) => (
          <div key={r.seq} className="explain" style={{ marginBottom: 6, cursor: "pointer" }} onClick={() => select({ kind: "event", seq: r.seq })}>
            <div><b>{r.node}</b> at <span className="mono">{nsLabel(r.time_fs)}</span> (local {nsLabel(r.data.local_time_fs)})</div>
            <div>{r.explain}</div>
            {(r.data.evaluations ?? []).map((e: any, i: number) => (
              <div key={i} className="mono xs row" style={{ gap: 4 }}>
                <span className={e.result ? "cx-ok" : "cx-err"} style={{ width: 12, display: "inline-flex" }}>{e.result ? <Icon.check /> : <Icon.cross />}</span>
                {e.transition}: {typeof e.guard === "string" ? e.guard : "true"} <span className="muted">({e.result ? "true" : "false"})</span></div>
            ))}
            {(r.data.actions ?? []).map((ac: any, i: number) => <div key={`a${i}`} className="mono xs muted">{short(ac, 110)}</div>)}
          </div>
        ))}
        {focus && sim?.nodes[focus]?.automaton !== automaton && <div className="note">The focused participant uses a different automaton.</div>}
      </Section>
      <Issues prefix={`automata.${automaton}.transitions[${id}]`} />
    </>
  );
}

// ======================================================================= message / event / resource
function MessageInspector({ id }: { id: number }) {
  const sim = useStore((s) => s.sim);
  const select = useStore((s) => s.select);
  const setHighlight = useStore((s) => s.setHighlightChain);
  const [chain, setChain] = useState<any[]>([]);
  useEffect(() => {
    let alive = true;
    api.chain(id).then((c) => { if (alive) { setChain(c); setHighlight(c.map((m: any) => m.id)); } }).catch(() => setChain([]));
    return () => { alive = false; };
  }, [id, sim?.trace_length, setHighlight]);
  useEffect(() => () => setHighlight([]), [setHighlight]);
  const m = sim?.messages.find((x) => x.id === id);
  if (!m) return <div className="empty">Message m{id} is not part of the current run.</div>;
  const delivery = sim!.trace.find((r) => (r.kind === "msg.deliver" || r.kind === "msg.loss" || r.kind === "msg.refused") && r.data.msg === id);
  return (
    <>
      <Section title={<><span className={`chan ${m.kind}`} style={{ display: "inline-block", marginRight: 8, verticalAlign: 3 }} />Message m{m.id} <span className="mono">'{m.tag}'</span></>}>
        <KV rows={[
          ["value", m.kind === "quantum" ? "(qubit)" : JSON.stringify(m.value)],
          ["from", `${m.src}.${m.src_port} (transition ${m.sent_by_transition})`],
          ["to", `${m.dst}.${m.dst_port}`],
          ["link", m.link],
          ["action executed", nsLabel(m.send_time_fs)],
          ["departed", nsLabel(m.depart_time_fs)],
          ["arrived", nsLabel(m.arrival_time_fs)],
          ["delay", `${nsLabel(m.delay_fs)} (${m.distance_m.toPrecision(7)} m)`],
          ["status", m.status],
          ["consumed", m.consumed_time_fs !== null ? `${nsLabel(m.consumed_time_fs)} by ${m.consumed_by}` : "—"],
        ]} />
        {delivery && <div className="explain" style={{ marginTop: 6 }}>{delivery.explain}</div>}
      </Section>
      <Section title="Causal path" aside={<span className="xs muted">highlighted in the spacetime view</span>}>
        <div className="note" style={{ marginBottom: 6 }}>Every message this one causally depends on: messages its sender had consumed before sending it, recursively.</div>
        {chain.map((c) => (
          <div key={c.id} className="row small" style={{ cursor: "pointer", padding: "2px 0" }} onClick={() => select({ kind: "message", id: c.id })}>
            <span className={`chan ${c.kind}`} />
            <span className="mono">m{c.id}</span>
            <span className="grow">{c.src} → {c.dst} <span className="mono">'{c.tag}'</span></span>
            <span className="mono muted">{nsLabel(c.depart_time_fs, 3)} → {nsLabel(c.arrival_time_fs, 3)}</span>
          </div>
        ))}
      </Section>
    </>
  );
}

function EventInspector({ seq }: { seq: number }) {
  const sim = useStore((s) => s.sim);
  const select = useStore((s) => s.select);
  const r = sim?.trace[seq];
  if (!r) return <div className="empty">Trace record {seq} is not in the current run.</div>;
  const msgId = r.data.msg;
  return (
    <>
      <Section title={<>Record #{r.seq} <span className="mono">{r.kind}</span></>}>
        <KV rows={[
          ["global time", `${nsLabel(r.time_fs)} (${r.time_fs} fs)`],
          ["participant", r.node ?? "—"],
          ["scheduler event", r.event ?? "—"],
          ...(r.data.local_time_fs !== undefined ? [["local time", nsLabel(r.data.local_time_fs)] as [string, any]] : []),
        ]} />
        <div className="explain" style={{ marginTop: 8 }}>{r.explain || "No explanation recorded."}</div>
        <div className="row" style={{ marginTop: 8, gap: 4 }}>
          {r.node && <button className="btn" onClick={() => select({ kind: "participant", id: r.node! })}>Participant {r.node}</button>}
          {typeof msgId === "number" && <button className="btn" onClick={() => select({ kind: "message", id: msgId })}>Message m{msgId}</button>}
          {r.kind === "transition.begin" && sim!.nodes[r.node!] && <button className="btn" onClick={() => select({ kind: "transition", automaton: sim!.nodes[r.node!].automaton, id: r.data.transition })}>Transition {r.data.transition}</button>}
        </div>
      </Section>
      <Section title="Data"><pre className="mono xs" style={{ whiteSpace: "pre-wrap", margin: 0 }}>{JSON.stringify(r.data, null, 1)}</pre></Section>
    </>
  );
}

function ResourceInspector({ index, project }: { index: number; project: Project }) {
  const edit = useStore((s) => s.edit);
  const r = project.resources[index];
  if (!r) return <div className="empty">Resource no longer exists.</div>;
  return (
    <>
      <Section title={<>Resource <span className="mono">{r.id}</span> <span className="muted">{r.type}</span></>}
        aside={<button className="btn ghost danger" onClick={() => edit((d) => { d.resources.splice(index, 1); }, { select: { kind: "project" } })}><Icon.trash /></button>}>
        <div className="note" style={{ marginBottom: 6 }}>
          {r.type === "epr" ? "A Bell pair distributed before t = 0; each holder finds its half in the named qubit slot. Holders need a capability profile that allows entanglement; werner_p depolarises one half."
            : "Classical values evaluated once before t = 0 and copied into each holder's variables (e.g. verifiers' private shared randomness)."}
        </div>
        <JsonField value={r} rows={10} onCommit={(v) => edit((d) => { d.resources[index] = v; })} />
      </Section>
      <Issues prefix={`resources[${r.id}]`} />
    </>
  );
}

export function Inspector() {
  const project = useStore((s) => s.project);
  const sel = useStore((s) => s.selection);
  if (!project) return null;
  let body;
  switch (sel.kind) {
    case "participant": {
      const p = project.participants.find((x) => x.id === sel.id);
      body = p ? <ParticipantInspector p={p} project={project} /> : <div className="empty">Participant no longer exists.</div>;
      break;
    }
    case "link": body = <LinkInspector id={sel.id} project={project} />; break;
    case "state": body = <StateInspector automaton={sel.automaton} id={sel.id} project={project} />; break;
    case "transition": body = <TransitionInspector automaton={sel.automaton} id={sel.id} project={project} />; break;
    case "message": body = <MessageInspector id={sel.id} />; break;
    case "event": body = <EventInspector seq={sel.seq} />; break;
    case "resource": body = <ResourceInspector index={sel.index} project={project} />; break;
    default: body = <ProjectInspector p={project} />;
  }
  return <div className="inspector" data-testid="inspector">{body}</div>;
}

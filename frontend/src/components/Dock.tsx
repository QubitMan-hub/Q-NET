import { useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../store";
import { api } from "../api";
import { KIND_COLOR, nsLabel, ns } from "../format";
import { Experiments } from "./Experiments";
import { Icon } from "./ui";

// ======================================================================= events
export function EventLog() {
  const sim = useStore((s) => s.sim);
  const select = useStore((s) => s.select);
  const selection = useStore((s) => s.selection);
  const [q, setQ] = useState("");
  const [node, setNode] = useState("");
  const [kind, setKind] = useState("");
  const [follow, setFollow] = useState(true);
  const body = useRef<HTMLDivElement>(null);
  const trace = sim?.trace ?? [];
  const kinds = useMemo(() => Array.from(new Set(trace.map((r) => r.kind))).sort(), [trace]);
  const rows = useMemo(() => {
    const ql = q.toLowerCase();
    return trace.filter((r) => (!node || r.node === node) && (!kind || r.kind === kind) &&
      (!ql || r.explain.toLowerCase().includes(ql) || JSON.stringify(r.data).toLowerCase().includes(ql)));
  }, [trace, q, node, kind]);
  useEffect(() => { if (follow && body.current) body.current.scrollTop = body.current.scrollHeight; }, [rows.length, follow]);
  if (!sim) return <div className="empty">No simulation. Fix the project’s validation errors to run it.</div>;
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div className="log-tools">
        <input className="input" placeholder="Search explanations and data…" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 260 }} aria-label="Search events" />
        <select className="select" value={node} onChange={(e) => setNode(e.target.value)} aria-label="Filter by participant">
          <option value="">all participants</option>
          {Object.keys(sim.nodes).map((n) => <option key={n}>{n}</option>)}
        </select>
        <select className="select" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Filter by kind">
          <option value="">all kinds</option>
          {kinds.map((k) => <option key={k}>{k}</option>)}
        </select>
        <label className="check"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />Follow</label>
        <span className="grow" />
        <span className="xs muted">{rows.length} of {trace.length} records · {sim.events_executed} events executed · {sim.pending.length} pending</span>
      </div>
      <div className="panel-body" ref={body}>
        <table className="grid">
          <thead><tr><th style={{ width: 46 }}>#</th><th style={{ width: 120, textAlign: "right" }}>time (ns)</th><th style={{ width: 150 }}>kind</th><th style={{ width: 60 }}>who</th><th>what happened and why</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.seq} className={selection.kind === "event" && selection.seq === r.seq ? "sel" : ""} onClick={() => select({ kind: "event", seq: r.seq })}>
                <td className="k muted">{r.seq}</td>
                <td className="t">{ns(r.time_fs)}</td>
                <td className="k"><span className="kind-dot" style={{ background: KIND_COLOR[r.kind] ?? "var(--ink-3)" }} />{r.kind}</td>
                <td className="k">{r.node ?? ""}</td>
                <td>{r.explain}</td>
              </tr>
            ))}
            {sim.pending.slice(0, 50).map((e) => (
              <tr key={`p${e.id}`} style={{ opacity: 0.55 }}>
                <td className="k muted">…</td><td className="t">{ns(e.time_fs)}</td>
                <td className="k">{e.kind}</td><td className="k">{e.node ?? ""}</td>
                <td className="muted">pending: {e.label} (priority {e.priority}, scheduled at {nsLabel(e.scheduled_at_fs, 3)})</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ======================================================================= timeline
export function Timeline() {
  const sim = useStore((s) => s.sim);
  const project = useStore((s) => s.project);
  const select = useStore((s) => s.select);
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const [zoom, setZoom] = useState(1);
  useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);
  if (!sim || !project) return <div className="empty">No simulation to show.</div>;
  const nodes = project.participants.map((p) => p.id).filter((id) => sim.nodes[id]);
  const tmax = Math.max(sim.now_fs, ...sim.messages.map((m) => m.arrival_time_fs ?? 0), 1) * 1.04;
  const left = 90, laneH = 46;
  const W = Math.max(400, (width - left - 20) * zoom);
  const X = (fs: number) => left + (fs / tmax) * W;
  const H = nodes.length * laneH + 30;
  const step = (() => { const raw = tmax / 1e6 / 10; const p = 10 ** Math.floor(Math.log10(raw)); const m = raw / p; return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p; })();
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div className="log-tools">
        <span className="small muted">Per-participant timelines: state occupancy (bars), transitions in progress (dark), messages sent ▲ and received ▼, timers ◇, verdicts ●.</span>
        <span className="grow" />
        <button className="btn ghost" onClick={() => setZoom((z) => Math.max(1, z / 1.5))}>−</button>
        <span className="xs mono">{zoom.toFixed(1)}×</span>
        <button className="btn ghost" onClick={() => setZoom((z) => Math.min(40, z * 1.5))}>+</button>
      </div>
      <div className="panel-body" ref={wrap}>
        <svg width={W + left + 20} height={H}>
          {Array.from({ length: Math.floor(tmax / 1e6 / step) + 1 }, (_, i) => i * step).map((t) => (
            <g key={t}>
              <line x1={X(t * 1e6)} x2={X(t * 1e6)} y1={18} y2={H} stroke="var(--grid)" />
              <text className="tick" x={X(t * 1e6)} y={12} textAnchor="middle">{+t.toFixed(6)}</text>
            </g>
          ))}
          {nodes.map((id, i) => {
            const n = sim.nodes[id];
            const y = 22 + i * laneH;
            const role = project.participants.find((p) => p.id === id)!.role;
            const sends = sim.messages.filter((m) => m.src === id && m.depart_time_fs !== null);
            const recvs = sim.messages.filter((m) => m.dst === id && m.arrival_time_fs !== null);
            const timers = sim.trace.filter((r) => r.node === id && (r.kind === "timer.fire" || r.kind === "timer.set"));
            return (
              <g key={id}>
                <text x={8} y={y + 18} fontSize={12} fontWeight={700} fill={`var(--${role})`} style={{ cursor: "pointer" }} onClick={() => select({ kind: "participant", id })}>{id}</text>
                <line x1={left} x2={X(tmax)} y1={y + laneH - 6} y2={y + laneH - 6} stroke="var(--rule)" />
                {n.state_log.map((s, k) => {
                  const x0 = X(s.entered_fs), x1 = X(s.exited_fs ?? sim.now_fs);
                  return (
                    <g key={k}>
                      <rect x={x0} y={y + 6} width={Math.max(1, x1 - x0)} height={18} fill={`var(--${role}-soft, var(--sunken))`} stroke={`var(--${role})`} strokeWidth={0.6} />
                      {x1 - x0 > 40 && <text x={x0 + 4} y={y + 19} fontSize={10} fontFamily="var(--font-code)" fill="var(--ink)">{s.state}</text>}
                      <title>{`${id} in '${s.state}' from ${nsLabel(s.entered_fs)} to ${s.exited_fs === null ? "now" : nsLabel(s.exited_fs)}`}</title>
                    </g>
                  );
                })}
                {n.history.filter((h) => h.complete_fs > h.begin_fs).map((h, k) => (
                  <rect key={`b${k}`} x={X(h.begin_fs)} y={y + 6} width={Math.max(2, X(h.complete_fs) - X(h.begin_fs))} height={18} fill="var(--ink)" opacity={0.8}>
                    <title>{`${h.transition}: ${nsLabel(h.begin_fs)} → ${nsLabel(h.complete_fs)}`}</title>
                  </rect>
                ))}
                {n.busy && <rect x={X(n.busy.begin_fs)} y={y + 6} width={Math.max(2, X(Math.min(n.busy.complete_fs, sim.now_fs)) - X(n.busy.begin_fs))} height={18} fill="var(--ink)" opacity={0.5} />}
                {sends.map((m) => (
                  <path key={`s${m.id}`} d={`M ${X(m.depart_time_fs!)} ${y + 28} l -4 7 h 8 z`} fill={m.kind === "quantum" ? "var(--quantum)" : "var(--classical)"}
                    style={{ cursor: "pointer" }} onClick={() => select({ kind: "message", id: m.id })}><title>{`sent m${m.id} '${m.tag}' at ${nsLabel(m.depart_time_fs)}`}</title></path>
                ))}
                {recvs.map((m) => (
                  <path key={`r${m.id}`} d={`M ${X(m.arrival_time_fs!)} ${y + 37} l -4 -7 h 8 z`} fill="none" stroke={m.kind === "quantum" ? "var(--quantum)" : "var(--classical)"} strokeWidth={1.5}
                    style={{ cursor: "pointer" }} onClick={() => select({ kind: "message", id: m.id })}><title>{`received m${m.id} '${m.tag}' at ${nsLabel(m.arrival_time_fs)}`}</title></path>
                ))}
                {timers.map((r) => {
                  const t = r.kind === "timer.set" ? r.data.fire_fs : r.time_fs;
                  return (
                    <path key={`t${r.seq}`} d={`M ${X(t)} ${y + 1} l 4 4 l -4 4 l -4 -4 z`} fill={r.kind === "timer.fire" ? "var(--warn)" : "none"} stroke="var(--warn)"
                      style={{ cursor: "pointer" }} onClick={() => select({ kind: "event", seq: r.seq })}>
                      <title>{`timer '${r.data.name}' ${r.kind === "timer.set" ? "due" : "fired"} at ${nsLabel(t)}`}</title>
                    </path>
                  );
                })}
                {n.verdict && <circle cx={X(n.verdict.time_fs)} cy={y + 15} r={5} fill={n.verdict.outcome === "accept" ? "var(--accept)" : "var(--reject)"}><title>{`verdict ${n.verdict.outcome}: ${n.verdict.reason}`}</title></circle>}
              </g>
            );
          })}
          <line x1={X(sim.now_fs)} x2={X(sim.now_fs)} y1={16} y2={H} stroke="var(--now)" />
        </svg>
      </div>
    </div>
  );
}

// ======================================================================= console
export { ConsolePanel } from "./Console";

// ======================================================================= validation
export function ValidationPanel() {
  const issues = useStore((s) => s.issues);
  const simError = useStore((s) => s.simError);
  const sim = useStore((s) => s.sim);
  const select = useStore((s) => s.select);
  const project = useStore((s) => s.project);
  const [inv, setInv] = useState<any>(null);
  useEffect(() => { setInv(null); }, [sim?.trace_length, sim?.revision]);
  const go = (path: string) => {
    const m = path.match(/^participants\[([^\]]+)\]/);
    if (m && project?.participants.some((p) => p.id === m[1])) return select({ kind: "participant", id: m[1] });
    const l = path.match(/^links\[([^\]]+)\]/);
    if (l) return select({ kind: "link", id: l[1] });
    const t = path.match(/^automata\.([^.]+)\.transitions\[([^\]]+)\]/);
    if (t) return select({ kind: "transition", automaton: t[1], id: t[2] });
    const s = path.match(/^automata\.([^.]+)\.states\[([^\]]+)\]/);
    if (s) return select({ kind: "state", automaton: s[1], id: s[2] });
    select({ kind: "project" });
  };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", height: "100%", minHeight: 0 }}>
      <div style={{ overflow: "auto", borderRight: "1px solid var(--rule)" }}>
        <div className="panel-head">Project validation <span className="muted" style={{ fontWeight: 400 }}>{issues.filter((i) => i.level === "error").length} errors, {issues.filter((i) => i.level === "warning").length} warnings</span></div>
        {simError && <div className="issue"><span className="lvl error">blocked</span><span>{simError}</span></div>}
        {issues.length === 0 && !simError && <div className="empty">No errors or warnings. Static checks cover references, reachability, expressions, ports, capabilities vs. strategies, relativistic link speeds and resources.</div>}
        {issues.map((i, k) => (
          <div key={k} className="issue" style={{ cursor: "pointer" }} onClick={() => go(i.path)}>
            <span className={`lvl ${i.level}`}>{i.level}</span>
            <span className="grow">{i.message}<div className="path">{i.path}</div></span>
          </div>
        ))}
      </div>
      <div style={{ overflow: "auto" }}>
        <div className="panel-head">Trace invariants <span className="grow" />
          <button className="btn" disabled={!sim} onClick={async () => setInv(await api.invariants())}>Check current trace</button>
        </div>
        {!inv && <div className="empty">Checks the engine’s own trace for consistency: event ordering, monotonic time, delivery timing, the light-speed bound, causal consumption, FSM consistency and single verdicts. Passing them says nothing about protocol security.</div>}
        {inv && (
          <>
            <div className="issue"><span className={`lvl ${inv.ok ? "" : "error"}`} style={{ color: inv.ok ? "var(--accept)" : undefined }}>{inv.ok ? "pass" : "fail"}</span>
              <span>{inv.ok ? `All ${inv.checked.length} invariants hold for ${sim?.trace_length} records.` : `${inv.violations.length} violation(s).`}</span></div>
            {inv.checked.map((k: string) => {
              const v = inv.violations.filter((x: any) => x.invariant === k);
              return (
                <div key={k} className="issue"><span className="lvl" style={{ color: v.length ? "var(--reject)" : "var(--accept)", width: 16 }} aria-label={v.length ? "violated" : "holds"}>{v.length ? <Icon.cross /> : <Icon.check />}</span>
                  <span className="grow"><span className="mono">{k}</span> — {inv.descriptions[k]}
                    {v.map((x: any, i: number) => <div key={i} className="path" style={{ color: "var(--reject)" }}>{x.message}</div>)}</span></div>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}

// ======================================================================= decision
export function DecisionPanel() {
  const sim = useStore((s) => s.sim);
  const project = useStore((s) => s.project);
  const select = useStore((s) => s.select);
  if (!sim || !project) return <div className="empty">No simulation.</div>;
  const d = sim.decision;
  return (
    <div style={{ overflow: "auto", height: "100%" }}>
      <div className="decision-banner">
        <span className={`verdict ${d.outcome}`}>{d.outcome === "pending" ? "Undecided" : d.outcome === "accept" ? "Position accepted" : "Position rejected"}</span>
        <span className="muted">{d.accepts}/{d.verifiers.length} verifiers accepted · rule: {d.rule_text} · claim x = {project.claim.position[0]} m{project.claim.prover ? ` by ${project.claim.prover}` : " (no honest prover present)"}</span>
      </div>
      {d.verifiers.map((v: any) => (
        <div key={v.id} className="vcard">
          <h4>
            <span style={{ cursor: "pointer", color: "var(--verifier)" }} onClick={() => select({ kind: "participant", id: v.id })}>{v.id}</span>
            <span className={`status-pill ${v.verdict ?? (v.status === "error" ? "error" : "pending")}`}>{v.verdict ?? v.status}</span>
            <span className="muted small" style={{ fontWeight: 400 }}>{v.category}{v.decided_at_fs !== null ? ` at ${nsLabel(v.decided_at_fs)}` : ""}</span>
          </h4>
          <div className="small">{v.reason ?? "No verdict yet."}</div>
          {v.trigger && <div className="small muted">Fired by <span className="mono">{v.transition}</span> on {v.trigger}.</div>}
          {v.facts?.length > 0 && <ul>{v.facts.map((f: string, i: number) => <li key={i}>{f}</li>)}</ul>}
          {Object.keys(v.observations ?? {}).length > 0 && <div className="xs mono muted" style={{ marginTop: 4 }}>{Object.entries(v.observations).map(([k, x]) => `${k}=${typeof x === "number" ? (x as number).toFixed(6) : x}`).join("   ")}</div>}
        </div>
      ))}
      <div className="vcard note">
        This is a deterministic observation of one simulated round (seed {sim.seed}). Acceptance probabilities need repeated runs (Experiments tab); security claims need independent analysis.
        {sim.stop_reason && <> Run stopped: {sim.stop_reason}.</>}
      </div>
    </div>
  );
}

export { Experiments };

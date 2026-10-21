import { useEffect, useMemo, useState } from "react";
import { useStore } from "../store";
import { api, downloadFrom } from "../api";
import { clone, uniqueId } from "../format";
import type { ExperimentSpec } from "../types";
import { Field, NumberInput, TextInput } from "./ui";

function parseValues(s: string): any[] {
  return s.split(",").map((x) => x.trim()).filter(Boolean).map((x) => { try { return JSON.parse(x); } catch { return x; } });
}

/** Acceptance rate per sweep point with 95% Wilson intervals, plotted from the engine's run records. */
function AcceptanceChart({ points, axis }: { points: any[]; axis: string }) {
  const W = 560, H = 246, l = 52, r = 16, t = 30, b = 46;
  const n = points.length;
  const x = (i: number) => l + (n === 1 ? (W - l - r) / 2 : (i / (n - 1)) * (W - l - r));
  const y = (p: number) => t + (1 - p) * (H - t - b);
  const verifierIds: string[] = Object.keys(points[0]?.summary.verifiers ?? {});
  const vcolors = ["var(--verifier)", "var(--quantum)", "var(--classical)", "var(--adversary)"];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Acceptance probability by sweep value">
      {[0, 0.25, 0.5, 0.75, 1].map((p) => (
        <g key={p}><line x1={l} x2={W - r} y1={y(p)} y2={y(p)} stroke="var(--grid)" />
          <text className="tick" x={l - 6} y={y(p) + 3} textAnchor="end">{p.toFixed(2)}</text></g>
      ))}
      {points.map((pt, i) => {
        const a = pt.summary.acceptance;
        return (
          <g key={i}>
            <line x1={x(i)} x2={x(i)} y1={y(a.lo)} y2={y(a.hi)} stroke="var(--ink)" strokeWidth={1.5} />
            <line x1={x(i) - 5} x2={x(i) + 5} y1={y(a.lo)} y2={y(a.lo)} stroke="var(--ink)" />
            <line x1={x(i) - 5} x2={x(i) + 5} y1={y(a.hi)} y2={y(a.hi)} stroke="var(--ink)" />
            <circle cx={x(i)} cy={y(a.p)} r={4.5} fill="var(--ink)"><title>{`accept ${a.p.toFixed(4)} [${a.lo.toFixed(4)}, ${a.hi.toFixed(4)}] n=${pt.summary.n}`}</title></circle>
            {verifierIds.map((v, k) => (
              <circle key={v} cx={x(i) + 9 + k * 6} cy={y(pt.summary.verifiers[v].accept.p)} r={2.5} fill={vcolors[k % 4]}>
                <title>{`${v} accepts ${pt.summary.verifiers[v].accept.p.toFixed(4)}`}</title></circle>
            ))}
            <text className="tick" x={x(i)} y={H - b + 16} textAnchor="middle">{Object.values(pt.assignment).map((v) => JSON.stringify(v)).join(", ") || "base"}</text>
          </g>
        );
      })}
      {n > 1 && <polyline points={points.map((pt, i) => `${x(i)},${y(pt.summary.acceptance.p)}`).join(" ")} fill="none" stroke="var(--ink)" strokeWidth={1} opacity={0.5} />}
      <text x={(l + W - r) / 2} y={H - 8} textAnchor="middle" fontSize={11} fill="var(--ink-3)">{axis || "configuration"}</text>
      <text transform={`translate(13 ${(t + H - b) / 2}) rotate(-90)`} textAnchor="middle" fontSize={11} fill="var(--ink-3)">P(accept), 95% CI</text>
      {verifierIds.map((v, k) => (
        <g key={v} transform={`translate(${l + 8 + k * 70} 12)`}>
          <circle r={3} fill={vcolors[k % 4]} /><text x={7} y={3.5} fontSize={10} fill="var(--ink-2)">{v} alone</text>
        </g>
      ))}
    </svg>
  );
}

function Histogram({ values, label }: { values: number[]; label: string }) {
  const W = 360, H = 170, l = 40, r = 10, t = 10, b = 36;
  if (!values.length) return <div className="note">No response times recorded (no answers arrived).</div>;
  const min = Math.min(...values), max = Math.max(...values);
  const bins = 24;
  const width = (max - min) / bins || 1e-6;
  const counts = new Array(bins).fill(0);
  for (const v of values) counts[Math.min(bins - 1, Math.floor((v - min) / width))]++;
  const cmax = Math.max(...counts);
  const bw = (W - l - r) / bins;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={label}>
      {counts.map((c, i) => (
        <rect key={i} x={l + i * bw + 0.5} width={bw - 1} y={t + (1 - c / cmax) * (H - t - b)} height={(c / cmax) * (H - t - b)} fill="var(--verifier)">
          <title>{`${(min + i * width).toFixed(6)}–${(min + (i + 1) * width).toFixed(6)} ns: ${c}`}</title></rect>
      ))}
      <line x1={l} x2={W - r} y1={H - b} y2={H - b} stroke="var(--rule-strong)" />
      <text className="tick" x={l} y={H - b + 13} textAnchor="start">{min.toFixed(6)}</text>
      <text className="tick" x={W - r} y={H - b + 13} textAnchor="end">{max.toFixed(6)}</text>
      <text x={(l + W - r) / 2} y={H - 6} textAnchor="middle" fontSize={11} fill="var(--ink-3)">{label}</text>
      <text className="tick" x={l - 5} y={t + 8} textAnchor="end">{cmax}</text>
    </svg>
  );
}

/** An experiment job in the engine, polled until it finishes. */
export function useExperimentJob() {
  const setToast = useStore((s) => s.setToast);
  const [job, setJob] = useState<any>(null);
  useEffect(() => {
    if (!job || job.status !== "running") return;
    const h = window.setInterval(async () => {
      try {
        const j = await api.experiment(job.id);
        setJob(j);
        if (j.status !== "running") window.clearInterval(h);
        if (j.status === "error") setToast(j.error, true);
      } catch (e: any) { setToast(String(e.message), true); window.clearInterval(h); }
    }, 300);
    return () => window.clearInterval(h);
  }, [job?.id, job?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const start = async (exp: unknown) => {
    const { id } = await api.startExperiment(exp);
    setJob({ id, status: "running", done: 0, total: null });
  };
  return { job, start, cancel: () => job && api.cancelExperiment(job.id) };
}

export function JobProgress({ job }: { job: any }) {
  const res = job.result;
  return (
    <div style={{ marginTop: 10 }}>
      <div className="progress"><div style={{ width: `${job.total ? (100 * job.done) / job.total : job.status === "done" ? 100 : 3}%` }} /></div>
      <div className="xs muted" style={{ marginTop: 3 }}>{job.status === "running" ? `${job.done}${job.total ? ` / ${job.total}` : ""} runs` : job.status === "done" ? `done in ${res?.wall_time_s.toFixed(2)} s (${Math.round(res?.runs_per_second ?? 0)} runs/s)` : job.error}</div>
    </div>
  );
}

export function Experiments() {
  const project = useStore((s) => s.project)!;
  const edit = useStore((s) => s.edit);
  const setToast = useStore((s) => s.setToast);
  const presets = useStore((s) => s.scenarios?.presets ?? {});
  const exps = project.experiments;
  const [selId, setSelId] = useState<string | null>(exps[0]?.id ?? null);
  const [draft, setDraft] = useState<ExperimentSpec>(() => clone(exps[0] ?? { id: "exp1", name: "New experiment", runs: 200, seed: 1, sweep: [] }));
  const { job, start, cancel } = useExperimentJob();
  const [pointIdx, setPointIdx] = useState(0);
  const [preset, setPreset] = useState({ name: "noise", from: 0, to: 0.5, steps: 6 });

  useEffect(() => {
    const e = exps.find((x) => x.id === selId);
    if (e) setDraft(clone(e));
  }, [selId, project.meta.name]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async () => {
    setPointIdx(0);
    await start(draft);
  };
  // A QPV preset sweep: one quantity varied across the whole setup (engine axis "preset:<name>").
  const applyPreset = (name: string, from: number, to: number, steps: number) => {
    setPreset({ name, from, to, steps });
    const values = presets[name]?.values ?? Array.from({ length: steps }, (_, i) => +(from + ((to - from) * i) / Math.max(1, steps - 1)).toFixed(9));
    setDraft({ ...draft, id: `sweep_${name}`, name: presets[name]?.label ?? name, sweep: [{ path: `preset:${name}`, values }] });
  };
  const saveToProject = () => edit((p) => {
    const i = p.experiments.findIndex((e) => e.id === draft.id);
    if (i >= 0) p.experiments[i] = clone(draft); else p.experiments.push(clone(draft));
  });
  const res = job?.result;
  const axis = (draft.sweep ?? []).map((s) => presets[s.path.replace(/^preset:/, "")]?.label ?? s.path).join(" × ");
  const pt = res?.points[pointIdx];
  const rttVerifier = pt ? Object.keys(pt.summary.verifiers)[0] : null;

  const sweepText = useMemo(() => (draft.sweep ?? []).map((s) => `${s.path}: ${s.values.map((v) => JSON.stringify(v)).join(", ")}`).join("\n"), [draft.sweep]);

  return (
    <div className="exp-layout">
      <div className="exp-side">
        <div className="row" style={{ marginBottom: 8 }}>
          <select className="select" value={selId ?? ""} onChange={(e) => setSelId(e.target.value || null)} aria-label="Saved experiments">
            <option value="">(unsaved draft)</option>
            {exps.map((e) => <option key={e.id} value={e.id}>{e.name ?? e.id}</option>)}
          </select>
          <button className="btn" onClick={() => { const id = uniqueId("exp", exps.map((e) => e.id)); setSelId(null); setDraft({ id, name: "New experiment", runs: 200, seed: 1, sweep: [] }); }}>New</button>
        </div>
        <Field label="Id"><TextInput code value={draft.id} onCommit={(v) => setDraft({ ...draft, id: v })} /></Field>
        <Field label="Name"><TextInput value={draft.name ?? ""} onCommit={(v) => setDraft({ ...draft, name: v })} /></Field>
        <Field label="Runs per point"><NumberInput value={draft.runs} min={1} step={100} onCommit={(v) => setDraft({ ...draft, runs: Math.round(v ?? 100) })} /></Field>
        <Field label="Master seed"><NumberInput value={draft.seed} min={0} step={1} onCommit={(v) => setDraft({ ...draft, seed: Math.round(v ?? 0) })} /></Field>
        {useStore.getState().meta?.parallel_experiments !== false && <Field label="Workers" title="Parallel processes (results identical to 1 worker)"><NumberInput value={draft.workers ?? 1} min={1} max={32} step={1} onCommit={(v) => setDraft({ ...draft, workers: Math.round(v ?? 1) })} /></Field>}
        <Field label="QPV sweep" title="Vary one QPV quantity across the whole setup">
          <select className="select" value={preset.name} aria-label="Sweep preset" onChange={(e) => {
            const r = presets[e.target.value]?.range ?? [0, 1, 6];
            applyPreset(e.target.value, r[0], r[1], r[2]);
          }}>
            {Object.entries(presets).map(([k, p]) => <option key={k} value={k}>{p.label}</option>)}
          </select>
        </Field>
        {!presets[preset.name]?.values && (
          <div className="row" style={{ marginBottom: 6 }}>
            {(["from", "to", "steps"] as const).map((f) => (
              <NumberInput key={f} value={preset[f]} ariaLabel={`Sweep ${f}`} step={f === "steps" ? 1 : 0.1} min={f === "steps" ? 2 : undefined}
                onCommit={(v) => { const n = { ...preset, [f]: v ?? preset[f] }; applyPreset(n.name, n.from, n.to, Math.round(n.steps)); }} />
            ))}
          </div>
        )}
        <Field label="Sweep" stack title="One axis per line: path: v1, v2, … (axes form a grid)">
          <textarea className="textarea code" rows={3} defaultValue={sweepText} key={sweepText} spellCheck={false}
            placeholder="participants.E0.processing_ns: 0, 0.2, 0.4"
            onBlur={(e) => {
              const sweep = e.target.value.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
                const k = l.indexOf(":");
                return { path: l.slice(0, k).trim(), values: parseValues(l.slice(k + 1)) };
              }).filter((s) => s.path && s.values.length);
              setDraft({ ...draft, sweep });
            }} />
        </Field>
        <div className="note" style={{ marginBottom: 8 }}>Paths address the project document; list items by id, e.g. <span className="mono">links.q0.noise.depolarizing</span>, <span className="mono">participants.E0.params.policy</span>.</div>
        <div className="row">
          <button className="btn primary" onClick={() => run().catch((e) => setToast(String(e.message), true))} disabled={job?.status === "running"}>Run experiment</button>
          {job?.status === "running" && <button className="btn" onClick={cancel}>Cancel</button>}
          <button className="btn" onClick={saveToProject}>Save to project</button>
        </div>
        {job && <JobProgress job={job} />}
      </div>
      <div className="exp-main">
        {!res && <div className="empty">Experiments repeat the current project many times with independent seeds and optional parameter sweeps. Each run’s seed is recorded, so any run can be reproduced exactly. Results are raw per-run records plus statistics derived from them.</div>}
        {res && (
          <>
            <div className="row" style={{ marginBottom: 6 }}>
              <b>{res.experiment.name ?? res.experiment.id}</b>
              <span className="muted small">{res.provenance.project_name} · backend {res.provenance.backend} · engine {res.provenance.engine_version} · seed {res.experiment.seed}</span>
              <span className="grow" />
              <button className="btn" onClick={() => downloadFrom(`/api/experiments/${job.id}/csv`, "results.csv", "text/csv").catch((e) => setToast(String(e.message), true))}>Download CSV</button>
              <button className="btn" onClick={() => downloadFrom(`/api/experiments/${job.id}/raw`, "results.json").catch((e) => setToast(String(e.message), true))}>Download raw runs</button>
            </div>
            <AcceptanceChart points={res.points} axis={axis} />
            <table className="grid" style={{ marginTop: 6 }}>
              <thead><tr><th>point</th><th>n</th><th>P(accept)</th><th>95% CI</th>{Object.keys(res.points[0].summary.verifiers).map((v) => <th key={v}>{v}: outcomes</th>)}<th>errors</th></tr></thead>
              <tbody>
                {res.points.map((p: any, i: number) => (
                  <tr key={i} className={i === pointIdx ? "sel" : ""} onClick={() => setPointIdx(i)}>
                    <td className="k">{Object.entries(p.assignment).map(([k, v]) => `${k.split(".").slice(-1)[0]}=${JSON.stringify(v)}`).join(", ") || "base"}</td>
                    <td className="num">{p.summary.n}</td>
                    <td className="num">{p.summary.acceptance.p.toFixed(4)}</td>
                    <td className="num">[{p.summary.acceptance.lo.toFixed(4)}, {p.summary.acceptance.hi.toFixed(4)}]</td>
                    {Object.values(p.summary.verifiers).map((v: any, k) => <td key={k} className="small">{Object.entries(v.categories).map(([c, n]) => `${c} ${n}`).join(", ")}</td>)}
                    <td className="num">{p.summary.errors}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {pt && rttVerifier && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 10 }}>
                <div>
                  <div className="small" style={{ fontWeight: 600, marginBottom: 4 }}>Round-trip time at {rttVerifier} (selected point)</div>
                  <Histogram values={pt.summary.verifiers[rttVerifier].rtt_values ?? []} label="challenge → answer (ns, verifier clock)" />
                </div>
                <div className="small">
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>Mean operation counts per run</div>
                  <table className="kv-table"><tbody>
                    {Object.entries(pt.summary.mean_counters).map(([k, v]: any) => <tr key={k}><td>{k.replace(/_/g, " ")}</td><td className="mono">{v.toFixed(3)}</td></tr>)}
                  </tbody></table>
                </div>
              </div>
            )}
            <div className="note" style={{ marginTop: 10 }}>{res.interpretation}</div>
          </>
        )}
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { api, IN_BROWSER } from "../api";
import { useStore } from "../store";
import { download } from "../links";
import type { TheoryResult } from "../types";
import { useExperimentJob, JobProgress } from "./Experiments";
import { NumberInput } from "./ui";

/** Measured pass rate (with 95% intervals) along one setting, with the theory curve where a formula exists. */
function Curve({ points, theory, unit, label }: { points: any[]; theory: TheoryResult | null; unit: string; label: string }) {
  const W = 620, H = 316, l = 52, r = 18, t = 36, b = 50;
  const xs = points.map((p) => Number(Object.values(p.assignment)[0]));
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const X = (v: number) => l + (x1 === x0 ? (W - l - r) / 2 : ((v - x0) / (x1 - x0)) * (W - l - r));
  const Y = (p: number) => t + (1 - p) * (H - t - b);
  const th = theory?.theory ?? [];
  // theory as a dashed line, broken where no formula applies
  const segs: string[][] = [];
  th.forEach((v, i) => {
    if (v === null || v === undefined) { segs.push([]); return; }
    if (!segs.length) segs.push([]);
    segs[segs.length - 1].push(`${X(xs[i])},${Y(v)}`);
  });
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart wide" role="img" aria-label={`Pass rate against ${label}`} data-testid="chart-svg">
      {[0, 0.25, 0.5, 0.75, 1].map((p) => (
        <g key={p}><line x1={l} x2={W - r} y1={Y(p)} y2={Y(p)} stroke="var(--grid)" />
          <text className="tick" x={l - 6} y={Y(p) + 3} textAnchor="end">{Math.round(100 * p)}%</text></g>
      ))}
      {segs.filter((s) => s.length > 1).map((s, i) => (
        <polyline key={i} points={s.join(" ")} fill="none" stroke="var(--warn)" strokeWidth={2} strokeDasharray="6 4" />
      ))}
      {th.map((v, i) => v !== null && v !== undefined && (
        <circle key={`t${i}`} cx={X(xs[i])} cy={Y(v)} r={3} fill="var(--panel)" stroke="var(--warn)" strokeWidth={1.5}>
          <title>{`theory ${(100 * v).toFixed(1)}%`}</title></circle>
      ))}
      <polyline points={points.map((p, i) => `${X(xs[i])},${Y(p.summary.acceptance.p)}`).join(" ")} fill="none" stroke="var(--ink)" strokeWidth={1.5} />
      {points.map((p, i) => {
        const a = p.summary.acceptance;
        return (
          <g key={i}>
            <line x1={X(xs[i])} x2={X(xs[i])} y1={Y(a.lo)} y2={Y(a.hi)} stroke="var(--ink)" strokeWidth={1.5} />
            <circle cx={X(xs[i])} cy={Y(a.p)} r={4.5} fill="var(--ink)">
              <title>{`${xs[i]} ${unit}: ${(100 * a.p).toFixed(1)}% [${(100 * a.lo).toFixed(1)}, ${(100 * a.hi).toFixed(1)}] of ${p.summary.n}`}</title></circle>
            <text className="tick" x={X(xs[i])} y={H - b + 16} textAnchor="middle">{+xs[i].toPrecision(4)}</text>
          </g>
        );
      })}
      <text x={(l + W - r) / 2} y={H - 12} textAnchor="middle" fontSize={11} fill="var(--ink-3)">{label}{unit ? ` (${unit})` : ""}</text>
      <text transform={`translate(13 ${(t + H - b) / 2}) rotate(-90)`} textAnchor="middle" fontSize={11} fill="var(--ink-3)">rounds passed</text>
      <g transform={`translate(${l + 4} 14)`} fontSize={10.5} fill="var(--ink-2)">
        <circle r={4} fill="var(--ink)" /><text x={9} y={3.5}>measured, 95% interval</text>
        {th.some((v) => v !== null) && <><line x1={150} x2={172} stroke="var(--warn)" strokeWidth={2} strokeDasharray="6 4" /><text x={178} y={3.5}>theory</text></>}
      </g>
    </svg>
  );
}

const NUMERIC = (p: { values?: unknown[] }) => !p.values;

export function ChartDialog({ onClose }: { onClose: () => void }) {
  const presets = useStore((s) => s.scenarios?.presets ?? {});
  const title = useStore((s) => s.project?.meta.name ?? "");
  const setToast = useStore((s) => s.setToast);
  const names = Object.keys(presets).filter((k) => NUMERIC(presets[k]));
  const [name, setName] = useState(names.includes("noise") ? "noise" : names[0]);
  const range = presets[name]?.range ?? [0, 1, 6];
  const [from, setFrom] = useState(range[0]);
  const [to, setTo] = useState(range[1]);
  const [steps, setSteps] = useState(range[2] ?? 6);
  const [runs, setRuns] = useState(IN_BROWSER ? 100 : 300);
  const [theory, setTheory] = useState<TheoryResult | null>(null);
  const { job, start } = useExperimentJob();

  const pick = (n: string) => {
    const r = presets[n]?.range ?? [0, 1, 6];
    setName(n); setFrom(r[0]); setTo(r[1]); setSteps(r[2] ?? 6); setTheory(null);
  };
  const values = Array.from({ length: Math.max(2, steps) }, (_, i) => +(from + ((to - from) * i) / Math.max(1, steps - 1)).toFixed(9));
  const run = async () => {
    setTheory(null);
    try {
      await start({ id: "chart", name: `chart ${name}`, runs, seed: 7, sweep: [{ path: `preset:${name}`, values }] });
    } catch (e: any) { setToast(String(e?.message ?? e), true); }
  };
  const points = job?.status === "done" ? job.result?.points ?? [] : [];
  useEffect(() => {
    if (!points.length) return;
    const vs = points.map((p: any) => Number(Object.values(p.assignment)[0]));
    api.theory(name, vs).then(setTheory).catch(() => setTheory(null));
  }, [job?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const csv = () => download(["value,passed,n,rate,ci_lo,ci_hi,theory"].concat(points.map((p: any, i: number) => {
    const a = p.summary.acceptance;
    return [Object.values(p.assignment)[0], p.summary.accepted, p.summary.n, a.p, a.lo, a.hi, theory?.theory[i] ?? ""].join(",");
  })).join("\n") + "\n", `qpv-chart-${name}.csv`, "text/csv");

  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog chart-dialog" role="dialog" aria-labelledby="chart-title" onClick={(e) => e.stopPropagation()} data-testid="chart-dialog">
        <h2 id="chart-title">Pass-rate chart</h2>
        <p>How the pass rate of <b>{title}</b> changes as one setting changes, with the theory line where a simple formula exists.</p>
        <div className="chart-controls">
          <label className="small">Setting
            <select className="select" value={name} onChange={(e) => pick(e.target.value)} data-testid="chart-preset">
              {names.map((k) => <option key={k} value={k}>{presets[k].label}</option>)}
            </select></label>
          <label className="small">From<NumberInput value={from} step={0.1} ariaLabel="From" onCommit={(v) => setFrom(v ?? 0)} /></label>
          <label className="small">To<NumberInput value={to} step={0.1} ariaLabel="To" onCommit={(v) => setTo(v ?? 1)} /></label>
          <label className="small">Points<NumberInput value={steps} min={2} max={20} step={1} ariaLabel="Points" onCommit={(v) => setSteps(Math.round(v ?? 6))} /></label>
          <label className="small">Rounds each<NumberInput value={runs} min={10} max={5000} step={50} ariaLabel="Rounds per point" onCommit={(v) => setRuns(Math.round(v ?? 100))} /></label>
          <button className="btn primary" onClick={run} disabled={job?.status === "running"} data-testid="chart-run">Draw</button>
        </div>
        {job && job.status !== "done" && <JobProgress job={job} />}
        {points.length > 0 && <Curve points={points} theory={theory} unit={presets[name]?.unit ?? ""} label={presets[name]?.label ?? name} />}
        {theory && <div className="note">{theory.label ? `Who answers: ${theory.label}. ` : ""}{theory.note}</div>}
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" disabled={!points.length} onClick={csv}>Save CSV</button>
          <span className="grow" />
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

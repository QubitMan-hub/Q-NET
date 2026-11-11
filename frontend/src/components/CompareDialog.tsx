import { useRef, useState } from "react";
import { api, IN_BROWSER } from "../api";
import { useStore } from "../store";
import { download } from "../links";
import { NumberInput } from "./ui";

type Cell = { p: number; lo: number; hi: number; n: number; theory: number | null; source: string };
const pct = (p: number) => `${Math.round(100 * p)}%`;

/** Every protocol against every kind of answerer, side by side, measured and against theory. */
export function CompareDialog({ onClose }: { onClose: () => void }) {
  const cmp = useStore((s) => s.scenarios?.comparison);
  const setToast = useStore((s) => s.setToast);
  const [rounds, setRounds] = useState(IN_BROWSER ? 100 : 300);
  const [cells, setCells] = useState<Record<string, Cell>>({});
  const [running, setRunning] = useState<string | null>(null);
  const stop = useRef(false);
  if (!cmp) return null;
  const jobs = cmp.rows.flatMap((row, i) => cmp.columns.map((c) => ({ key: `${i}:${c.id}`, cell: row.cells[c.id] })))
    .filter((j) => j.cell);
  const done = Object.keys(cells).length;

  const run = async () => {
    stop.current = false;
    setCells({});
    const out: Record<string, Cell> = {};
    try {
      for (const j of jobs) {
        if (stop.current) break;
        setRunning(j.key);
        out[j.key] = await api.compare(j.cell!.recipe, rounds);
        setCells({ ...out });
      }
    } catch (e: any) { setToast(String(e?.message ?? e), true); }
    finally { setRunning(null); }
  };
  const csv = () => download(["protocol," + cmp.columns.map((c) => `"${c.label}"`).join(",")].concat(cmp.rows.map((row, i) =>
    `"${row.label}",` + cmp.columns.map((c) => cells[`${i}:${c.id}`]?.p.toFixed(4) ?? "").join(","))).join("\n") + "\n",
    "qpv-protocol-comparison.csv", "text/csv");
  const open = async (i: number, col: string) => {
    const cell = cmp.rows[i].cells[col];
    if (!cell) return;
    onClose();
    await useStore.getState().loadRecipe({ ...cell.recipe, title: `${cmp.rows[i].label}: ${cmp.columns.find((c) => c.id === col)?.label}` });
  };

  return (
    <div className="dialog-backdrop" onClick={running ? undefined : onClose}>
      <div className="dialog compare" role="dialog" aria-labelledby="compare-title" onClick={(e) => e.stopPropagation()} data-testid="compare-dialog">
        <h2 id="compare-title">Compare protocols</h2>
        <p>The share of rounds each kind of answerer passes, for every protocol in the workbench. Small numbers next to a
          result are theory. Click a result to open that setup.</p>
        <div className="row report-controls">
          <label className="small">Rounds each</label>
          <NumberInput value={rounds} min={20} max={5000} step={50} ariaLabel="Rounds per cell" onCommit={(v) => setRounds(Math.round(v ?? 100))} />
          <span className="grow" />
          {running ? <button className="btn" onClick={() => { stop.current = true; }}>Stop</button>
            : <button className="btn primary" onClick={run} data-testid="compare-run">Run {jobs.length} setups</button>}
        </div>
        {(running || done > 0) && <div className="progress" style={{ margin: "8px 0" }}><div style={{ width: `${(100 * done) / jobs.length}%` }} /></div>}
        <div className="report-table">
          <table className="grid compare-grid">
            <thead><tr><th>Protocol</th>{cmp.columns.map((c) => <th key={c.id} className="num">{c.label}</th>)}</tr></thead>
            <tbody>
              {cmp.rows.map((row, i) => (
                <tr key={row.label}>
                  <td><b>{row.label}</b></td>
                  {cmp.columns.map((c) => {
                    const key = `${i}:${c.id}`, r = cells[key], has = !!row.cells[c.id];
                    const level = r ? (r.p > 0.95 ? "high" : r.p > 0.6 ? "mid" : "low") : "";
                    return (
                      <td key={c.id} className={`num cmp ${c.id !== "honest" ? level : ""}`} data-testid={`cmp-${key}`}>
                        {!has ? <span className="muted">—</span>
                          : r ? <button className="cmp-cell" onClick={() => open(i, c.id)} title={r.source}>
                              <b>{pct(r.p)}</b>{r.theory !== null && <span className="muted xs"> {pct(r.theory)}</span>}</button>
                          : running === key ? <span className="muted">running…</span> : <span className="muted">·</span>}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="note" style={{ marginTop: 8 }}>{cmp.note}</div>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" disabled={!done || !!running} onClick={csv}>Save CSV</button>
          <span className="grow" />
          <button className="btn" disabled={!!running} onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

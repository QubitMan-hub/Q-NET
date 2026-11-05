import { useRef, useState } from "react";
import { api, IN_BROWSER } from "../api";
import { useStore } from "../store";
import { describeChance, download, testRule } from "../links";
import type { ReportRow } from "../types";
import { NumberInput } from "./ui";

const pct = (p: number) => `${(100 * p).toFixed(1)}%`;

/** Runs every gallery scenario (or one section) many times and tabulates measured against expected pass rates. */
export function ReportDialog({ onClose }: { onClose: () => void }) {
  const catalog = useStore((s) => s.scenarios?.demos);
  const setToast = useStore((s) => s.setToast);
  const [rounds, setRounds] = useState(IN_BROWSER ? 100 : 300);
  const [only, setOnly] = useState("");
  const [rows, setRows] = useState<ReportRow[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const stop = useRef(false);
  const demos = (catalog?.demos ?? []).filter((d) => !only || d.section === only);

  const run = async () => {
    stop.current = false;
    setRows([]);
    const out: ReportRow[] = [];
    try {
      for (const d of demos) {
        if (stop.current) break;
        setRunning(d.id);
        out.push(await api.reportRow(d.id, rounds));
        setRows([...out]);
      }
    } catch (e: any) {
      setToast(String(e?.message ?? e), true);
    } finally {
      setRunning(null);
    }
  };
  const save = async (format: "md" | "csv" | "html") => {
    const text = await api.reportRender(rows, format);
    download(text, `qpv-scenario-report.${format}`, { md: "text/markdown", csv: "text/csv", html: "text/html" }[format]);
  };
  const print = async () => {
    const url = URL.createObjectURL(new Blob([await api.reportRender(rows, "html")], { type: "text/html" }));
    const w = window.open(url, "_blank");
    if (!w) { setToast("Allow pop-ups to print the report", true); return; }
    w.addEventListener("load", () => { w.focus(); w.print(); });
  };
  const good = rows.filter((r) => r.ok).length;
  return (
    <div className="dialog-backdrop" onClick={running ? undefined : onClose}>
      <div className="dialog report" role="dialog" aria-labelledby="report-title" onClick={(e) => e.stopPropagation()} data-testid="report-dialog">
        <h2 id="report-title">Scenario report</h2>
        <p>Runs every scenario in the gallery and checks the measured pass rate against what is expected. Save the
          table as Markdown, CSV or a printable page (print it to PDF).</p>
        <div className="row report-controls">
          <label className="small">Rounds each</label>
          <NumberInput value={rounds} min={10} max={5000} step={50} ariaLabel="Rounds per scenario" onCommit={(v) => setRounds(Math.round(v ?? 100))} />
          <select className="select" value={only} onChange={(e) => setOnly(e.target.value)} aria-label="Which scenarios" style={{ width: "auto" }}>
            <option value="">All {catalog?.demos.length ?? 0} scenarios</option>
            {Object.entries(catalog?.sections ?? {}).map(([k, v]) => <option key={k} value={k}>Section {k}: {v}</option>)}
          </select>
          <span className="grow" />
          {running ? <button className="btn" onClick={() => { stop.current = true; }}>Stop</button>
            : <button className="btn primary" onClick={run} data-testid="report-run">Run {demos.length} scenarios</button>}
        </div>
        {(running || rows.length > 0) && (
          <div className="progress" style={{ margin: "8px 0" }}><div style={{ width: `${(100 * rows.length) / Math.max(1, demos.length)}%` }} /></div>
        )}
        {running && <div className="xs muted">Running {running}… ({rows.length} of {demos.length} done)</div>}
        {rows.length > 0 && (
          <>
            <div className="report-summary" data-testid="report-summary"><b>{good} of {rows.length}</b> match their expected pass rate.</div>
            <div className="report-table">
              <table className="grid">
                <thead><tr><th>Scenario</th><th className="num">Passed</th><th className="num">95% interval</th><th className="num">Expected</th><th>Match</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className={r.ok ? "" : "warn"}>
                      <td><b>{r.title}</b>{r.test && <div className="xs muted">{testRule(r.test)}: passes {describeChance(r.test.pass_probability)}</div>}</td>
                      <td className="num">{pct(r.p)}</td>
                      <td className="num">{pct(r.lo)}–{pct(r.hi)}</td>
                      <td className="num">{r.expect_rate[0] === r.expect_rate[1] ? pct(r.expect_rate[0]) : `${pct(r.expect_rate[0])}–${pct(r.expect_rate[1])}`}</td>
                      <td className={r.ok ? "good" : "bad"}>{r.ok ? "yes" : "no"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" disabled={!rows.length || !!running} onClick={() => save("md")}>Markdown</button>
          <button className="btn" disabled={!rows.length || !!running} onClick={() => save("csv")}>CSV</button>
          <button className="btn" disabled={!rows.length || !!running} onClick={() => save("html")}>Web page</button>
          <button className="btn" disabled={!rows.length || !!running} onClick={print}>Print / PDF</button>
          <span className="grow" />
          <button className="btn" disabled={!!running} onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

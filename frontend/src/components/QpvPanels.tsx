import { useStore } from "../store";
import { nsLabel } from "../format";
import { GLOSSARY } from "../glossary";
import type { Ref } from "../types";
import { Icon } from "./ui";
import { JobProgress, useExperimentJob } from "./Experiments";

const ns3 = (fs: number | null | undefined) => (fs === null || fs === undefined ? "—" : (fs / 1e6).toFixed(3));
const signed = (fs: number) => `${fs >= 0 ? "+" : "−"}${Math.abs(fs / 1e6).toFixed(3)} ns`;

/** Clickable references into the run (message, trace record, transition, participant). */
export function RefChips({ refs }: { refs?: Ref[] }) {
  const goTo = useStore((s) => s.goTo);
  if (!refs?.length) return null;
  const label = (r: Ref) => (r.kind === "message" ? `message m${r.id}` : r.kind === "event" ? `trace #${r.seq}`
    : r.kind === "transition" ? `transition ${r.id}` : r.id);
  return (
    <span className="ref-chips">
      {refs.map((r, i) => <button key={i} className="ref-chip" onClick={() => goTo(r)} title="Show it in the workbench">{label(r)}</button>)}
    </span>
  );
}

/** Every verifier's schedule from the engine, with slack for an honest prover at the claim. */
export function TimingPanel() {
  const analysis = useStore((s) => s.analysis);
  const select = useStore((s) => s.select);
  const t = analysis?.timing;
  if (!t?.rows.length) {
    return <div className="empty">{t?.issues[0] ?? "No timing yet."} Timing needs verifiers that send a challenge and arm a timer named “deadline”.</div>;
  }
  const meet = Math.max(...t.rows.map((r) => r.at_claim_fs));
  return (
    <div style={{ overflow: "auto", height: "100%" }} data-testid="timing-panel">
      <table className="grid timing">
        <thead><tr>
          <th>verifier</th><th className="num">distance (m)</th><th className="num">sends (ns)</th>
          <th className="num">reaches claim (ns)</th><th className="num" title={GLOSSARY.deadline}>deadline (ns)</th>
          <th className="num">honest answer (ns)</th><th className="num">answer this run (ns)</th><th className="num" title={GLOSSARY.slack}>slack</th>
        </tr></thead>
        <tbody>
          {t.rows.map((r) => (
            <tr key={r.id} className={r.inconsistent.length ? "warn" : ""} onClick={() => select({ kind: "participant", id: r.id })}
              title={r.inconsistent.join("\n") || undefined}>
              <td className="k"><span className={`vtype ${r.type}`}>{r.type === "quantum" ? <Icon.qubit /> : <Icon.bit />}</span>{r.id} <span className="muted">{r.type}</span></td>
              <td className="num">{r.distance_m.toFixed(3)}</td>
              <td className="num">{ns3(r.send_fs)}</td>
              <td className={`num${r.at_claim_fs < meet ? " bad" : ""}`}>{ns3(r.at_claim_fs)}</td>
              <td className="num">{ns3(r.deadline_fs)}</td>
              <td className="num">{ns3(r.honest_answer_fs)}</td>
              <td className="num">{ns3(r.answer_fs)}</td>
              <td className={`num ${r.slack_fs < 0 ? "bad" : "good"}`}>{signed(r.slack_fs)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="timing-notes">
        {t.issues.length ? t.issues.map((i, k) => <div key={k} className="issue"><span className="lvl warning">timing</span><span>{i}</span></div>)
          : <div className="note">All challenges reach the claimed position together at {nsLabel(meet, 3)}; an honest prover there answers every verifier with time to spare.
            Times are global and come from the engine's schedule, clocks included; distances use the project signal speed and the engine's round-up delays.</div>}
      </div>
    </div>
  );
}

/** The honest prover against every attack on this setup, with theory alongside. */
export function ComparePanel() {
  const analysis = useStore((s) => s.analysis);
  const scenarios = useStore((s) => s.scenarios);
  const setToast = useStore((s) => s.setToast);
  const xor = useStore((s) => {
    const v0 = s.project?.participants.find((p) => p.automaton === "qpv_verifier_quantum");
    return (v0?.params?.combine ?? "xor") === "xor";
  });
  const { job, start } = useExperimentJob();
  if (!analysis?.qpv) {
    return <div className="empty">Compare runs the honest prover and each attack on a QPV setup (one quantum and some classical verifiers). Build one with <b>Scenario</b> in the toolbar.</div>;
  }
  const attacks = ["honest", "unentangled", ...(xor ? ["teleport"] : []), "guess"];
  const run = (runs: number) => start({ id: "compare", name: "Honest vs attacks", runs, seed: 1, sweep: [{ path: "preset:attack", values: attacks }] })
    .catch((e) => setToast(String(e.message), true));
  const points: any[] = job?.result?.points ?? [];
  const W = 640, H = 230, l = 160, r = 70, top = 18, rowH = (H - top - 26) / attacks.length;
  const X = (p: number) => l + p * (W - l - r);
  return (
    <div className="exp-layout" data-testid="compare-panel">
      <div className="exp-side">
        <p className="small" style={{ marginTop: 0 }}>Runs this setup with the honest prover and each attack, then sets the measured acceptance rate against what theory predicts.</p>
        <div className="row">
          <button className="btn primary" disabled={job?.status === "running"} onClick={() => run(200)}>Compare (200 runs each)</button>
          <button className="btn" disabled={job?.status === "running"} onClick={() => run(2000)}>2,000 runs</button>
        </div>
        {job && <JobProgress job={job} />}
        {!xor && <div className="note" style={{ marginTop: 8 }}>The teleportation chain only applies to XOR shares, so it is left out for the inner-product basis.</div>}
      </div>
      <div className="exp-main">
        {!points.length ? <div className="empty">Results appear here: acceptance with 95% confidence intervals, and the theoretical value for each attacker as a mark.</div> : (
          <>
            <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Acceptance by attacker, against theory">
              {[0, 0.25, 0.5, 0.75, 1].map((p) => (
                <g key={p}><line x1={X(p)} x2={X(p)} y1={top - 6} y2={H - 26} stroke="var(--grid)" />
                  <text className="tick" x={X(p)} y={H - 12} textAnchor="middle">{p.toFixed(2)}</text></g>
              ))}
              {points.map((pt, i) => {
                const a = pt.assignment["preset:attack"], acc = pt.summary.acceptance, ref = analysis.references[a];
                const y = top + i * rowH + rowH / 2;
                return (
                  <g key={a}>
                    <text x={l - 10} y={y + 4} textAnchor="end" fontSize={12} fill="var(--ink)">{scenarios?.answerers[a] ?? a}</text>
                    <rect x={X(0)} y={y - 7} width={X(acc.p) - X(0)} height={14} fill={a === "honest" ? "var(--prover)" : "var(--adversary)"} opacity={0.75} />
                    <line x1={X(acc.lo)} x2={X(acc.hi)} y1={y} y2={y} stroke="var(--ink)" strokeWidth={1.5} />
                    <path d={`M ${X(ref.value)} ${y - 11} v 22`} stroke="var(--ink)" strokeWidth={2} strokeDasharray="3 2"><title>{`theory ${ref.value.toFixed(4)}: ${ref.source}`}</title></path>
                    <text x={W - r + 6} y={y + 4} fontSize={11} fill="var(--ink-2)" fontFamily="var(--font-code)">{acc.p.toFixed(3)}</text>
                  </g>
                );
              })}
            </svg>
            <table className="grid" style={{ marginTop: 6 }}>
              <thead><tr><th>who answers</th><th className="num">measured</th><th className="num">95% CI</th><th className="num">theory</th><th className="num">gap</th><th>source of the theoretical value</th></tr></thead>
              <tbody>{points.map((pt) => {
                const a = pt.assignment["preset:attack"], acc = pt.summary.acceptance, ref = analysis.references[a];
                return (
                  <tr key={a}><td className="k">{scenarios?.answerers[a] ?? a}</td><td className="num">{acc.p.toFixed(4)}</td>
                    <td className="num">[{acc.lo.toFixed(4)}, {acc.hi.toFixed(4)}]</td><td className="num">{ref.value.toFixed(4)}</td>
                    <td className={`num ${ref.value >= acc.lo && ref.value <= acc.hi ? "good" : "bad"}`}>{(acc.p - ref.value >= 0 ? "+" : "") + (acc.p - ref.value).toFixed(4)}</td>
                    <td className="small">{ref.source}</td></tr>
                );
              })}</tbody>
            </table>
            <div className="note" style={{ marginTop: 8 }}>A gap inside the confidence interval (green) means the run agrees with theory. Theory assumes noise-free channels; the unentangled bound is for the two-verifier game. None of this is a security proof.</div>
          </>
        )}
      </div>
    </div>
  );
}

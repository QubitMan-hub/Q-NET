import { useState } from "react";
import { useStore } from "../store";
import type { Project } from "../types";
import { useExperimentJob } from "./Experiments";

/** Who currently answers at the claim, in the engine's scenario vocabulary. */
export function answering(p: Project): string {
  const autos = p.participants.filter((q) => q.role !== "verifier").map((q) => q.automaton).join(" ");
  if (autos.includes("qpv_adv_chain")) return "teleport";
  if (autos.includes("qpv_adv_unentangled")) return "unentangled";
  if (autos.includes("qpv_adv_guess")) return "guess";
  const prover = p.participants.find((q) => q.id === p.claim.prover);
  return prover ? (prover.role === "prover" ? "honest" : "displaced") : "";
}

const WORLDS: [number, string, string][] = [[1, "Line", "2 verifiers"], [2, "Plane", "3 verifiers"], [3, "Space", "4 verifiers"]];

const WHO: Record<string, [string, string]> = {
  honest: ["Honest prover", "Really stands at the spot. Should always pass."],
  displaced: ["Prover in the wrong place", "Claims the spot from 1 m away. Its answers arrive too late."],
  unentangled: ["Cheaters, no entanglement", "Surround the spot and share what they measure. Win about 85% of rounds."],
  teleport: ["Cheaters with entanglement", "Share EPR pairs and teleport the qubit. Beat XOR-based verifiers every time."],
  guess: ["Wild guessers", "Guess the basis and the answer. Rarely win."],
};

const cheating = (who: string) => !["honest", "displaced"].includes(who);
const whoArgs = (who: string) => (cheating(who) ? { attack: who } : { prover: who });
const pct = (p: number) => `${Math.round(100 * p)}%`;

function headline(outcome: string, who: string) {
  if (outcome === "accept") return cheating(who) ? "Fooled! The cheaters passed as the prover." : "Accepted. The prover is where it claims.";
  if (outcome === "reject") return cheating(who) ? "Caught! The verifiers spotted the cheaters." : who === "displaced" ? "Caught! The prover is not where it claims." : "Rejected.";
  return "Ready. Play a round to see what happens.";
}

/** The friendly right panel: pick a world and who answers, play a round, then play a hundred. */
export function PlayPanel({ onDetails }: { onDetails: () => void }) {
  const project = useStore((s) => s.project)!;
  const analysis = useStore((s) => s.analysis);
  const sim = useStore((s) => s.sim);
  const revision = useStore((s) => s.revision);
  const setToast = useStore((s) => s.setToast);
  const showAttacks = useStore((s) => s.showAttacks);
  const toggleAttacks = useStore((s) => s.toggleAttacks);
  const [busy, setBusy] = useState(false);
  const [scoreRev, setScoreRev] = useState(-1);
  const { job, start } = useExperimentJob();
  const who = answering(project);
  const dim = analysis?.qpv ? analysis.dimension : 0;

  const act = async (fn: () => Promise<void>) => { setBusy(true); try { await fn(); } finally { setBusy(false); } };
  const build = (d: number, w: string) => act(async () => {
    await useStore.getState().loadScenario({ dim: d, ...whoArgs(w) });
    await useStore.getState().runToEnd();
    useStore.getState().setView("spacetime");
  });
  const pickWho = (w: string) => (analysis?.qpv ? act(() => useStore.getState().switchAttack(w)) : build(2, w));
  const again = () => act(async () => {
    const s = useStore.getState();
    await s.reset(Math.floor(Math.random() * 1e9));
    await useStore.getState().runToEnd();
  });
  const hundred = () => {
    setScoreRev(revision);
    start({ id: "play", name: "100 rounds", runs: 100, seed: Math.floor(Math.random() * 1e9), sweep: [] })
      .catch((e) => setToast(String(e.message), true));
  };

  const outcome = sim?.decision.outcome ?? "pending";
  const verdicts = sim?.decision.verifiers ?? [];
  const why = (verdicts.find((v: any) => v.verdict === "reject") ?? verdicts[0])?.sentence;
  const score = scoreRev === revision ? job?.result?.points?.[0]?.summary : null;
  const theory = analysis?.references[who]?.value;

  return (
    <div className="play" data-testid="play-panel">
      <p className="play-intro">The verifiers time their signals to meet at one spot. Only someone really there can answer every verifier in time, unless cheaters team up.</p>

      <h3><span className="play-step">1</span>Pick a world</h3>
      <div className="play-worlds" role="radiogroup" aria-label="World">
        {WORLDS.map(([d, name, sub]) => (
          <button key={d} role="radio" aria-checked={dim === d} className={`play-world${dim === d ? " on" : ""}`} disabled={busy}
            onClick={() => build(d, who || "honest")} data-testid={`play-dim-${d}`}>
            <b>{d}D {name}</b><span>{sub}</span>
          </button>
        ))}
      </div>

      <h3><span className="play-step">2</span>Who stands at the spot?</h3>
      <div className="play-who" role="radiogroup" aria-label="Who answers">
        {Object.entries(WHO).filter(([k]) => showAttacks || !cheating(k) || k === who).map(([k, [name, desc]]) => (
          <button key={k} role="radio" aria-checked={who === k} className={`play-card ${cheating(k) ? "cheat" : "true"}${who === k ? " on" : ""}`}
            disabled={busy} onClick={() => pickWho(k)} data-testid={`play-who-${k}`}>
            <b>{name}</b><span>{desc}</span>
          </button>
        ))}
        <button className="btn ghost" onClick={toggleAttacks} aria-pressed={showAttacks} data-testid="toggle-attacks">
          {showAttacks ? "Hide attack examples" : "Show attack examples"}</button>
      </div>

      <h3><span className="play-step">3</span>Play</h3>
      <div className={`play-result ${outcome}`} data-testid="play-result">
        <div className="play-headline">{headline(outcome, who)}</div>
        {why && outcome !== "pending" && <div className="play-why">{why}</div>}
      </div>
      <div className="row">
        <button className="btn primary grow" disabled={busy} onClick={outcome === "pending" ? () => act(() => useStore.getState().runToEnd()) : again}
          data-testid="play-round">{outcome === "pending" ? "Play a round" : "Play another round"}</button>
        <button className="btn grow" disabled={busy || job?.status === "running"} onClick={hundred} data-testid="play-hundred">Play 100 rounds</button>
      </div>
      {scoreRev === revision && job && (
        <div className="play-score" data-testid="play-score">
          {score ? <>
            <div><b>Passed {score.accepted} of {score.n}</b>{theory !== undefined && <span className="muted"> · theory says {pct(theory)}</span>}</div>
            <div className="play-bar"><div style={{ width: pct(score.acceptance.p) }} />
              {theory !== undefined && <i style={{ left: pct(theory) }} title={`Theory: ${pct(theory)}`} />}</div>
          </> : <div className="muted">Playing… {job.done ?? 0} rounds</div>}
        </div>
      )}

      <div className="play-foot">
        <span className="muted small">Explore the 3D view in the Geometry tab. Click a node to change its settings.</span>
        <button className="btn ghost" onClick={onDetails} data-testid="play-details">Edit details</button>
      </div>
    </div>
  );
}

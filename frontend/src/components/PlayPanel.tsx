import { useState } from "react";
import { useStore } from "../store";
import type { Project, Recipe } from "../types";
import { useExperimentJob } from "./Experiments";
import { DemoCard } from "./Demos";
import { Icon } from "./ui";
import { describeChance, testRule } from "../links";

/** Who currently answers at the claim, in the engine's scenario vocabulary. */
export function answering(p: Project): string {
  const autos = p.participants.filter((q) => q.role !== "verifier").map((q) => q.automaton).join(" ");
  if (autos.includes("qpv_adv_chain") || autos.includes("qpv_adv_teleport_qudit")) return "teleport";
  if (autos.includes("qpv_adv_budget")) return "budget";
  if (autos.includes("qpv_adv_linear")) return "linear";
  if (autos.includes("qpv_adv_relay")) return "relay";
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
  budget: ["Cheaters with an entanglement budget", "Teleport into the pair named by x. Need a pair for every possible x to always win."],
  linear: ["Cheaters with one EPR pair", "Beat f = xor of parities with a single shared pair."],
  relay: ["Colluders relaying bits", "Forward each verifier's bit at light speed. Beat classical checks every time."],
};

const cheating = (who: string) => !["honest", "displaced"].includes(who);
const whoArgs = (who: string) => (cheating(who) ? { attack: who } : { prover: who });
const pct = (p: number) => `${Math.round(100 * p)}%`;
const OUTCOME: Record<string, string> = { wrong_answer: "wrong answers", timeout: "too late or no answer", lost: "'no photon' reports",
  error: "errors", undecided: "undecided", rejected: "rejected" };

function headline(outcome: string, who: string) {
  if (outcome === "accept") return cheating(who) ? "Fooled! The cheaters passed as the prover." : "Accepted. The prover is where it claims.";
  if (outcome === "reject") return cheating(who) ? "Caught! The verifiers spotted the cheaters." : who === "displaced" ? "Caught! The prover is not where it claims." : "Rejected.";
  if (outcome === "running") return "Watch the qubit and the basis travel…";
  return "Ready. Play a round to see what happens.";
}

/** The friendly right panel: pick a world and who answers, play a round, then play a hundred. */
export function PlayPanel({ onDetails, onDemos, onEdit, onChart }: {
  onDetails: () => void; onDemos: () => void; onEdit: (r: Recipe) => void; onChart: () => void;
}) {
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
  const demo = project.meta.demo;
  const who = demo ? (demo.who === "honest" ? "honest" : "cheat") : answering(project);
  const dim = analysis?.qpv ? analysis.dimension : 0;
  const protocol = analysis?.protocol ?? "bb84";
  const protoWho = protocol !== "bb84" ? useStore.getState().scenarios?.protocols[protocol]?.answerers : undefined;

  const act = async (fn: () => Promise<void>) => { setBusy(true); try { await fn(); } finally { setBusy(false); } };
  const build = (d: number, w: string) => act(async () => {
    await useStore.getState().loadScenario({ dim: d, ...whoArgs(w) });
    await useStore.getState().runToEnd();
    useStore.getState().setView("spacetime");
  });
  const pickWho = (w: string) => (analysis?.qpv ? act(() => useStore.getState().switchAttack(w)) : build(2, w));
  const playing = useStore((s) => s.playing);
  const again = () => act(async () => {
    const s = useStore.getState();
    await s.reset(Math.floor(Math.random() * 1e9));
    await useStore.getState().animateRound();
  });
  const hundred = () => {
    setScoreRev(revision);
    start({ id: "play", name: "100 rounds", runs: 100, seed: Math.floor(Math.random() * 1e9), sweep: [] })
      .catch((e) => setToast(String(e.message), true));
  };

  const outcome = playing ? "running" : sim?.decision.outcome ?? "pending";
  const verdicts = sim?.decision.verifiers ?? [];
  const score = scoreRev === revision ? job?.result?.points?.[0]?.summary : null;
  const theory = demo ? undefined : analysis?.references[who]?.value ?? undefined;  // demos change the setup the theory assumes
  const test = score?.test;
  const outcomes = score ? Object.values(score.verifiers ?? {}).reduce((acc: Record<string, number>, v: any) => {
    for (const [k, n] of Object.entries(v.categories as Record<string, number>)) acc[k] = Math.max(acc[k] ?? 0, n);
    return acc;
  }, {}) : {};
  const how = Object.entries(outcomes).filter(([k]) => k !== "accepted").map(([k, n]) => `${n} ${OUTCOME[k] ?? k}`);

  const variation = (
    <>
      <h3>World</h3>
      <div className="play-worlds" role="radiogroup" aria-label="World">
        {WORLDS.map(([d, name, sub]) => (
          <button key={d} role="radio" aria-checked={dim === d} className={`play-world${dim === d ? " on" : ""}`} disabled={busy}
            onClick={() => build(d, !who || ["budget", "linear", "relay", "cheat"].includes(who) ? "honest" : who)} data-testid={`play-dim-${d}`}>
            <b>{d}D {name}</b><span>{sub}</span>
          </button>
        ))}
      </div>
      <h3>Who stands at the spot?</h3>
      <div className="play-who" role="radiogroup" aria-label="Who answers">
        {Object.entries(WHO).filter(([k]) => (protoWho ? protoWho.includes(k) : !["budget", "linear", "relay"].includes(k))
          && (showAttacks || !cheating(k) || k === who)).map(([k, [name, desc]]) => (
          <button key={k} role="radio" aria-checked={who === k} className={`play-card ${cheating(k) ? "cheat" : "true"}${who === k ? " on" : ""}`}
            disabled={busy} onClick={() => pickWho(k)} data-testid={`play-who-${k}`}>
            <span className={`who-dot ${cheating(k) ? "cheat" : "true"}`} aria-hidden />
            <span className="who-text"><b>{name}</b><span>{desc}</span></span>
          </button>
        ))}
        <button className="btn ghost toggle-attacks" onClick={toggleAttacks} aria-pressed={showAttacks} data-testid="toggle-attacks">
          {showAttacks ? "Hide the cheaters" : "Show the cheaters too"}</button>
      </div>
    </>
  );
  const decided = outcome === "accept" || outcome === "reject";
  // colour tells whether the verifiers got it right: an accepted cheater is bad news, a rejected one good news
  const tone = !decided ? outcome : (outcome === "accept") !== cheating(who) ? "good" : "bad";

  return (
    <div className="play" data-testid="play-panel">
      {demo ? <DemoCard demo={demo} recipe={project.meta.recipe} site={project.meta.site} onBrowse={onDemos} onChart={analysis?.qpv ? onChart : undefined}
          onEdit={project.meta.recipe ? () => onEdit(project.meta.recipe!) : undefined} />
        : <div className="play-intro">
            <h2>{project.meta.name}</h2>
            <p>The verifiers time a photon and its key to meet at one spot. Only someone really there can answer every verifier in time, unless cheaters team up.</p>
            <div className="row play-links">
              <button className="btn ghost" onClick={onDemos} data-testid="play-demos">Browse scenarios</button>
              {analysis?.qpv && <button className="btn ghost" onClick={onChart} data-testid="play-chart">Pass-rate chart</button>}
            </div>
          </div>}

      <section className="play-stage" aria-label="Play">
        <div className={`play-result ${tone}`} data-testid="play-result" aria-live="polite">
          <div className="play-headline">{headline(outcome, who)}</div>
          {decided && verdicts.length > 0 && (
            <ul className="play-verdicts">
              {verdicts.map((v: any) => (
                <li key={v.id} className={v.verdict === "accept" ? "ok" : "bad"}>
                  {v.verdict === "accept" ? <Icon.check /> : <Icon.cross />}<span>{v.plain ?? v.sentence}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="row play-actions">
          {playing
            ? <button className="btn primary grow" onClick={() => useStore.getState().runToEnd()} data-testid="play-round">Skip to end</button>
            : <button className="btn primary grow" disabled={busy} onClick={outcome === "pending" ? () => act(() => useStore.getState().animateRound()) : again}
              data-testid="play-round">{outcome === "pending" ? "Play a round" : "Play another round"}</button>}
          <button className="btn grow" disabled={busy || job?.status === "running"} onClick={hundred} data-testid="play-hundred">Play 100 rounds</button>
        </div>
        {scoreRev === revision && job && (
          <div className="play-score" data-testid="play-score">
            {score ? <>
              <div className="play-score-line"><b>Passed {score.accepted} of {score.n}</b>
                {theory !== undefined && <span className="muted">theory says {pct(theory)}</span>}</div>
              <div className="play-bar" role="img" aria-label={`${pct(score.acceptance.p)} of rounds passed`}>
                <div style={{ width: pct(score.acceptance.p) }} />
                {theory !== undefined && <i style={{ left: pct(theory) }} title={`Theory: ${pct(theory)}`} />}</div>
              {how.length > 0 && <div className="muted small" data-testid="play-outcomes">Failed rounds: {how.join(", ")}</div>}
              {test && <div className="play-test" data-testid="play-test">
                <b>Judged over {testRule(test)}:</b> passes {describeChance(test.pass_probability)}
                {test.blocks ? <span className="muted"> ({test.blocks_passed} of {test.blocks} played blocks passed)</span> : null}
              </div>}
            </> : <div className="muted">Playing… {job.done ?? 0} rounds</div>}
          </div>
        )}
      </section>

      {demo
        ? <details className="variation"><summary>Try a variation</summary>{variation}</details>
        : <section className="variation open">{variation}</section>}

      <div className="play-foot">
        <span className="muted small">Click anything in the view to see its details.</span>
        <button className="btn ghost" onClick={onDetails} data-testid="play-details">Details</button>
      </div>
    </div>
  );
}

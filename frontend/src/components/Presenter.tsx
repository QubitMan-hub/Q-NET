import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { copyText, describeChance, presentLink, testRule } from "../links";
import { useExperimentJob } from "./Experiments";
import { Geometry } from "./SpaceView";

const pct = (p: number) => `${Math.round(100 * p)}%`;

function headline(outcome: string | undefined, who: string) {
  if (outcome === "accept") return who === "honest" ? "Accepted" : "Fooled: the cheaters passed";
  if (outcome === "reject") return who === "honest" ? "Rejected" : "Caught";
  return "Running…";
}

/** Presentation mode: the chosen gallery scenarios one at a time, full screen. Each step runs one round, then
 *  plays the scenario's rounds (100 unless it fixes its own) and sets the measured pass rate against the expected one. */
export function Presenter() {
  const present = useStore((s) => s.present)!;
  const demos = useStore((s) => s.scenarios?.demos);
  const sim = useStore((s) => s.sim);
  const revision = useStore((s) => s.revision);
  const setIndex = useStore((s) => s.setPresentIndex);
  const stop = useStore((s) => s.stopPresentation);
  const { job, start } = useExperimentJob();
  const [ready, setReady] = useState(-1);  // revision of the project the current step built
  const step = useRef(0);
  const id = present.ids[present.index];
  const demo = demos?.demos.find((d) => d.id === id);
  const sectionName = demo ? demos?.sections[demo.section] : "";

  useEffect(() => {
    const mine = ++step.current;
    setReady(-1);
    (async () => {
      await useStore.getState().loadDemo(id);
      if (mine !== step.current) return;
      history.replaceState(null, "", presentLink(present.ids).slice(window.location.origin.length) + `&at=${present.index}`);
      setReady(useStore.getState().revision);
      await start({ id: "present", name: "rounds", runs: demo?.runs ?? 100, seed: 1000 + present.index, sweep: [] });
    })().catch((e) => useStore.getState().setToast(String(e?.message ?? e), true));
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      if (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ") { e.preventDefault(); setIndex(present.index + 1); }
      else if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); setIndex(present.index - 1); }
      else if (e.key === "Escape") stop();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [present.index]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!demo) return null;
  const who = demo.who === "honest" ? "honest" : "cheat";
  const score = ready === revision && job?.status === "done" ? job.result?.points?.[0]?.summary : null;
  const [lo, hi] = demo.expect_rate;
  const ok = score ? score.acceptance.hi >= lo - 1e-9 && score.acceptance.lo <= hi + 1e-9 : null;
  const outcome = ready === revision ? sim?.decision.outcome : undefined;
  const link = presentLink(present.ids);

  return (
    <div className="presenter" role="dialog" aria-label="Presentation" data-testid="presenter">
      <div className="presenter-bar">
        <span className="presenter-count">{present.index + 1} / {present.ids.length}</span>
        <span className="muted">{demo.section}. {sectionName}</span>
        <span className="grow" />
        <button className="btn ghost" onClick={async () => useStore.getState().setToast(await copyText(link) ? "Presentation link copied" : link)}
          title="A link that opens this presentation">Copy link</button>
        <button className="btn" disabled={present.index === 0} onClick={() => setIndex(present.index - 1)} data-testid="present-prev">← Back</button>
        <button className="btn primary" disabled={present.index === present.ids.length - 1} onClick={() => setIndex(present.index + 1)}
          data-testid="present-next">Next →</button>
        <button className="btn ghost" onClick={stop} data-testid="present-exit" title="Leave the presentation (Esc)">Exit</button>
      </div>
      <div className="presenter-body">
        <div className="presenter-card">
          <span className={`demo-who ${who}`}>{who === "honest" ? "honest prover" : "cheaters"}</span>
          <h1>{demo.title}</h1>
          <p className="presenter-watch">{demo.watch}</p>
          <div className={`presenter-round ${outcome ?? "pending"}`} data-testid="present-round">
            <span className="muted small">One round</span>
            <b>{headline(outcome, who)}</b>
          </div>
          <div className="presenter-score" data-testid="present-score">
            <div className="row"><span className="muted small grow">{demo.runs ?? 100} rounds</span>
              {score && <b className={ok ? "ok" : "bad"}>{ok ? "as expected" : "outside the expected range"}</b>}</div>
            <div className="presenter-bar-chart" aria-hidden>
              <div className="expected" style={{ left: pct(lo), width: `max(3px, ${pct(hi - lo)})` }} title="expected range" />
              {score && <div className="measured" style={{ width: pct(score.acceptance.p) }} />}
            </div>
            <div className="presenter-numbers">
              <div><span className="muted small">Measured</span><b>{score ? pct(score.acceptance.p) : job?.status === "running" ? `${job.done ?? 0}…` : "…"}</b></div>
              <div><span className="muted small">Expected</span><b>{lo === hi ? pct(lo) : `${pct(lo)}–${pct(hi)}`}</b></div>
            </div>
            <p className="small">{demo.expect}</p>
            {score?.test && <p className="small presenter-test"><b>Over {testRule(score.test)}:</b> passes {describeChance(score.test.pass_probability)}.</p>}
          </div>
        </div>
        <div className="presenter-view"><Geometry /></div>
      </div>
    </div>
  );
}

import { useState } from "react";
import { useStore } from "../store";
import type { DemoInfo, Recipe, SiteInfo } from "../types";
import { copyText, recipeLink, scenarioLink } from "../links";
import { myRecipes, saveMyRecipes } from "./ScenarioDialog";

/** Short chip names for the gallery's sections (the full names head each section). */
const SHORT: Record<string, string> = { A: "Basics", B: "Real world", C: "No entanglement", D: "Entanglement", E: "Identity",
  F: "Loss & leaks", G: "Beyond BB84", "★": "Mine" };

type Entry = { key: string; title: string; who?: string; expect?: string; recipe: Recipe; demo?: string; section: string };

function Row({ e, current, onRun, onEdit, onDelete }: {
  e: Entry; current: boolean; onRun: () => void; onEdit: () => void; onDelete?: () => void;
}) {
  return (
    <div className={`demo-row${current ? " on" : ""}`}>
      <button className="demo-run" onClick={onRun} data-testid={`demo-${e.key}`} title="Run this scenario">
        {e.who && <span className={`demo-who ${e.who}`}>{e.who === "honest" ? "honest" : "cheat"}</span>}
        <span className="grow"><b>{e.title}</b>{e.expect && <span className="demo-expect">{e.expect}</span>}</span>
      </button>
      <button className="btn ghost" title="Open in the scenario builder to change it" onClick={onEdit}>Edit</button>
      {onDelete && <button className="btn ghost danger" title="Remove from My scenarios" onClick={onDelete}>Remove</button>}
    </div>
  );
}

/** All scenarios (the gallery from demos.json plus "My scenarios"), with search and section filters. */
export function ScenarioList({ onPicked, onEdit, compact }: { onPicked: () => void; onEdit: (r: Recipe) => void; compact?: boolean }) {
  const catalog = useStore((s) => s.scenarios?.demos);
  const current = useStore((s) => s.project?.meta.demo);
  const [mine, setMine] = useState(myRecipes);
  const [q, setQ] = useState("");
  const [only, setOnly] = useState<string>("");
  const sections: Record<string, string> = { ...(mine.length ? { "★": "My scenarios" } : {}), ...(catalog?.sections ?? {}) };
  const entries: Entry[] = [
    ...mine.map((r, i): Entry => ({ key: `mine-${i}`, title: r.title ?? `Scenario ${i + 1}`, recipe: r, expect: r.expect, section: "★" })),
    ...(catalog?.demos ?? []).map((d): Entry => ({
      key: d.id, title: d.title, who: d.who ?? undefined, expect: d.expect, demo: d.id, section: d.section,
      recipe: { ...d.recipe, title: d.title, watch: d.watch, expect: d.expect, ...(d.who ? { who: d.who } : {}) },
    })),
  ];
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = entries.filter((e) => (!only || e.section === only)
    && words.every((w) => `${e.title} ${e.expect ?? ""} ${sections[e.section] ?? ""}`.toLowerCase().includes(w)));
  const run = async (e: Entry) => {
    onPicked();
    if (e.demo) await useStore.getState().loadDemo(e.demo);
    else await useStore.getState().loadRecipe(e.recipe);
  };
  const edit = (e: Entry) => { onPicked(); onEdit({ ...e.recipe, title: e.title }); };
  return (
    <div className={`scenario-list${compact ? " compact" : ""}`}>
      <div className="scenario-filters">
        <input className="input" placeholder="Search scenarios: loss, teleport, clock, 3D…" value={q} onChange={(e) => setQ(e.target.value)}
          aria-label="Search scenarios" data-testid="scenario-search" />
        <div className="chips" role="radiogroup" aria-label="Section">
          {[["", "All"], ...Object.keys(sections).map((k) => [k, k])].map(([k, label]) => (
            <button key={k || "all"} role="radio" aria-checked={only === k} className={`chip${only === k ? " on" : ""}`}
              title={k ? sections[k] : "All sections"} onClick={() => setOnly(k)}>{k ? SHORT[k] ?? label : label}</button>
          ))}
        </div>
      </div>
      {Object.entries(sections).map(([letter, title]) => {
        const list = shown.filter((e) => e.section === letter);
        if (!list.length) return null;
        return (
          <section key={letter} className="demo-section">
            <h3><span className="demo-letter">{letter}</span>{title}</h3>
            {list.map((e) => (
              <Row key={e.key} e={e} current={e.demo ? current?.id === e.demo : current?.title === e.title} onRun={() => run(e)}
                onEdit={() => edit(e)}
                onDelete={e.demo ? undefined : () => {
                  const next = mine.filter((r) => r.title !== e.title); saveMyRecipes(next); setMine(next);
                }} />
            ))}
          </section>
        );
      })}
      {!shown.length && <div className="empty">No scenario matches “{q}”.</div>}
    </div>
  );
}

/** The scenario gallery as a dialog. */
export function DemoDialog({ onClose, onEdit, onReport, onCompare }: {
  onClose: () => void; onEdit: (r: Recipe) => void; onReport: () => void; onCompare: () => void;
}) {
  const n = useStore((s) => s.scenarios?.demos.demos.length ?? 0);
  const sections = useStore((s) => s.scenarios?.demos.sections ?? {});
  const [show, setShow] = useState("all");
  const present = () => {
    onClose();
    const ids = show === "all" ? "all" : (useStore.getState().scenarios?.demos.demos ?? []).filter((d) => d.section === show).map((d) => d.id);
    useStore.getState().startPresentation(ids);
  };
  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog demos" role="dialog" aria-labelledby="demos-title" onClick={(e) => e.stopPropagation()} data-testid="demo-dialog">
        <h2 id="demos-title">Scenarios</h2>
        <p>{n} ready-made cases, each a standard setup plus a few twists. Click one to run it, then press
          <b> Play 100 rounds</b> for the pass rate. <b>Edit</b> opens it in the builder.</p>
        <ScenarioList onPicked={onClose} onEdit={onEdit} />
        <div className="row demo-dialog-actions" style={{ marginTop: 12 }}>
          <button className="btn" onClick={() => { onClose(); onEdit({ base: { dim: 1, who: "honest" }, twists: [] }); }}>
            New scenario…</button>
          <span className="present-pick">
            <select className="select" value={show} onChange={(e) => setShow(e.target.value)} aria-label="Scenarios to present">
              <option value="all">All {n}</option>
              {Object.entries(sections).map(([k, v]) => <option key={k} value={k}>{k}: {v}</option>)}
            </select>
            <button className="btn" onClick={present} data-testid="btn-present" title="Show the scenarios one by one, full screen">Present</button>
          </span>
          <button className="btn" onClick={() => { onClose(); onCompare(); }} data-testid="btn-compare"
            title="Every protocol against every kind of cheater, side by side">Compare protocols…</button>
          <button className="btn" onClick={() => { onClose(); onReport(); }} data-testid="btn-report"
            title="Run every scenario and save a table of measured against expected pass rates">Report…</button>
          <span className="grow" />
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

/** Shown in the Play panel while a recipe-built scenario is loaded: what it is, what to watch, what to expect. */
export function DemoCard({ demo, recipe, site, onBrowse, onEdit, onChart }: {
  demo: DemoInfo; recipe?: Recipe; site?: SiteInfo; onBrowse: () => void; onEdit?: () => void; onChart?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  // a gallery scenario gets a short link; anything else carries its whole recipe in the link
  const link = demo.id ? scenarioLink(demo.id) : recipe ? recipeLink(recipe) : null;
  const copy = async () => {
    if (!link) return;
    if (await copyText(link)) { setCopied(true); setTimeout(() => setCopied(false), 1500); }
    else useStore.getState().setToast(link);
  };
  return (
    <div className="demo-card" data-testid="demo-card">
      <div className="row">
        <span className={`demo-who ${demo.who}`}>{demo.who === "honest" ? "honest" : "cheat"}</span>
        <b className="grow">{demo.title}</b>
      </div>
      {demo.watch && <p>{demo.watch}</p>}
      {demo.expect && <p className="demo-expect-line"><b>Expected:</b> {demo.expect}</p>}
      {site && <SiteFacts site={site} />}
      <div className="row demo-actions">
        {onEdit && <button className="btn ghost" onClick={onEdit} data-testid="demo-edit">Change it…</button>}
        {link && <button className="btn ghost" onClick={copy} title={link} data-testid="demo-copy-link">{copied ? "Link copied" : "Copy link"}</button>}
        {onChart && <button className="btn ghost" onClick={onChart} data-testid="demo-chart">Chart…</button>}
        <button className="btn ghost" onClick={onBrowse}>All scenarios…</button>
      </div>
    </div>
  );
}

const fmtM = (m: number) => (m >= 1000 ? `${(m / 1000).toFixed(1)} km` : m >= 1 ? `${m.toFixed(1)} m` : `${(100 * m).toFixed(1)} cm`);

/** The real-world numbers of a site: where, how far, how precise, how lossy. */
export function SiteFacts({ site }: { site: SiteInfo }) {
  const [lat, lon] = site.claim_latlon;
  const hw = site.hardware ?? {};
  return (
    <div className="site-facts" data-testid="site-facts">
      <div><span className="muted">Claim at</span> {lat.toFixed(5)}°N, {lon.toFixed(5)}°E ·{" "}
        <a href={`https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=15/${lat}/${lon}`} target="_blank" rel="noreferrer">map</a></div>
      <div className="site-grid">
        <span><b>{fmtM(site.distance_m)}</b><i>verifier distance</i></span>
        <span><b>±{fmtM(site.precision_m)}</b><i>location precision</i></span>
        <span><b>{site.photon_loss === null ? "—" : `${Math.round(100 * site.photon_loss)}%`}</b><i>photons lost</i></span>
        <span><b>{hw.links === "fibre" ? `fibre ×${hw.route_factor}` : "free space"}</b><i>honest links</i></span>
      </div>
    </div>
  );
}

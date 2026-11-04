import { useState } from "react";
import { useStore } from "../store";
import type { DemoInfo, Recipe } from "../types";
import { myRecipes, saveMyRecipes } from "./ScenarioDialog";

type Entry = { key: string; title: string; who?: string; expect?: string; recipe: Recipe; demo?: string };

function Row({ e, current, onRun, onEdit, onDelete }: {
  e: Entry; current: boolean; onRun: () => void; onEdit: () => void; onDelete?: () => void;
}) {
  return (
    <div className={`demo-row${current ? " on" : ""}`}>
      <button className="demo-run" onClick={onRun} data-testid={`demo-${e.key}`}>
        {e.who && <span className={`demo-who ${e.who}`}>{e.who === "honest" ? "honest" : "cheat"}</span>}
        <span className="grow"><b>{e.title}</b>{e.expect && <span className="demo-expect">{e.expect}</span>}</span>
      </button>
      <button className="btn ghost" title="Open in the scenario builder to change it" onClick={onEdit}>Edit</button>
      {onDelete && <button className="btn ghost danger" title="Remove from My scenarios" onClick={onDelete}>Remove</button>}
    </div>
  );
}

/** Every demo is a recipe kept as data; this lists them with your own saved recipes. */
export function DemoDialog({ onClose, onEdit }: { onClose: () => void; onEdit: (r: Recipe) => void }) {
  const catalog = useStore((s) => s.scenarios?.demos);
  const current = useStore((s) => s.project?.meta.demo);
  const [mine, setMine] = useState(myRecipes);
  const demos = catalog?.demos ?? [];
  const run = async (e: Entry) => {
    onClose();
    if (e.demo) await useStore.getState().loadDemo(e.demo);
    else await useStore.getState().loadRecipe(e.recipe);
  };
  const edit = (e: Entry) => { onClose(); onEdit({ ...e.recipe, title: e.title }); };
  const groups = Object.entries(catalog?.sections ?? {}).map(([letter, title]) => [letter, title,
    demos.filter((d) => d.section === letter).map((d): Entry => ({
      key: d.id, title: d.title, who: d.who ?? undefined, expect: d.expect, demo: d.id,
      recipe: { ...d.recipe, title: d.title, watch: d.watch, expect: d.expect, ...(d.who ? { who: d.who } : {}) },
    }))] as const);
  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog demos" role="dialog" aria-labelledby="demos-title" onClick={(e) => e.stopPropagation()} data-testid="demo-dialog">
        <h2 id="demos-title">Scenarios</h2>
        <p>{demos.length} ready-made cases, one per scenario in the write-up. Each is a recipe: a standard setup plus a few
          twists. Run one, or open it in the builder to change it. Press <b>Play 100 rounds</b> afterwards for the pass rate.</p>
        {mine.length > 0 && (
          <section className="demo-section">
            <h3><span className="demo-letter">★</span>My scenarios</h3>
            {mine.map((r, i) => {
              const e: Entry = { key: `mine-${i}`, title: r.title ?? `Scenario ${i + 1}`, recipe: r, expect: r.expect };
              return <Row key={e.key} e={e} current={current?.title === e.title} onRun={() => run(e)} onEdit={() => edit(e)}
                onDelete={() => { const next = mine.filter((_, j) => j !== i); saveMyRecipes(next); setMine(next); }} />;
            })}
          </section>
        )}
        {groups.map(([letter, title, list]) => (
          <section key={letter} className="demo-section">
            <h3><span className="demo-letter">{letter}</span>{title}</h3>
            {list.map((e) => <Row key={e.key} e={e} current={current?.id === e.demo} onRun={() => run(e)} onEdit={() => edit(e)} />)}
          </section>
        ))}
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" onClick={() => { onClose(); onEdit({ base: { dim: 1, who: "honest" }, twists: [] }); }}>
            New scenario…</button>
          <span className="grow" />
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

/** Shown in the Play panel while a recipe-built scenario is loaded: what it is, what to watch, what to expect. */
export function DemoCard({ demo, onBrowse, onEdit }: { demo: DemoInfo; onBrowse: () => void; onEdit?: () => void }) {
  return (
    <div className="demo-card" data-testid="demo-card">
      <div className="row">
        <span className={`demo-who ${demo.who}`}>{demo.who === "honest" ? "honest" : "cheat"}</span>
        <b className="grow">{demo.title}</b>
      </div>
      {demo.watch && <p>{demo.watch}</p>}
      {demo.expect && <p className="demo-expect-line"><b>Expected:</b> {demo.expect}</p>}
      <div className="row">
        {onEdit && <button className="btn ghost" onClick={onEdit} data-testid="demo-edit">Change this scenario…</button>}
        <button className="btn ghost" onClick={onBrowse}>All scenarios…</button>
      </div>
    </div>
  );
}

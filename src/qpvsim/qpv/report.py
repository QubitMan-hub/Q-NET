"""A report over the scenario gallery: every demo run many times, measured pass rate against expected.

``row(demo_id, rounds)`` runs one demo and returns its line of the report; ``render(rows, fmt)`` turns the
lines into Markdown, CSV or a printable HTML page.  A demo that fixes its own number of rounds (``runs`` in
``demos.json``, for setups that change from round to round) is always run exactly that many times.
"""

from __future__ import annotations

import datetime as _dt
import html
from typing import Any, Callable, Dict, List, Optional

from .. import __version__
from ..experiments import run_experiment
from . import recipe
from .rounds import describe

TEXT_KEYS = ("id", "section", "title", "watch", "expect", "who")


def compose_demo(d: Dict[str, Any]) -> Dict[str, Any]:
    return recipe.compose({**d["recipe"], **{k: d[k] for k in TEXT_KEYS if k in d}})


def row(demo_id: str, rounds: int = 300, seed: int = 11) -> Dict[str, Any]:
    d = recipe.demo(demo_id)
    runs = int(d.get("runs") or rounds)
    s = run_experiment(compose_demo(d), {"runs": runs, "seed": seed})["points"][0]["summary"]
    acc = s["acceptance"]
    lo, hi = d.get("expect_rate", [0.0, 1.0])
    cats: Dict[str, int] = {}
    for v in s["verifiers"].values():  # how rounds ended, counted at the verifier that saw most of each kind
        for k, n in v["categories"].items():
            cats[k] = max(cats.get(k, 0), n)
    out = {"id": d["id"], "section": d["section"], "title": d["title"], "who": d.get("who", ""),
           "expect": d["expect"], "expect_rate": [lo, hi], "n": s["n"], "accepted": s["accepted"],
           "p": acc["p"], "lo": acc["lo"], "hi": acc["hi"], "outcomes": cats,
           "ok": bool(acc["hi"] >= lo - 1e-9 and acc["lo"] <= hi + 1e-9)}
    if s.get("test"):
        t = s["test"]
        out["test"] = {k: t[k] for k in ("rounds", "min_correct", "min_answered", "pass_probability")}
    return out


def report(rounds: int = 300, ids: Optional[List[str]] = None, seed: int = 11,
           progress: Optional[Callable[[int, int, str], None]] = None) -> List[Dict[str, Any]]:
    ids = ids or [d["id"] for d in recipe.demos()["demos"]]
    rows = []
    for i, demo_id in enumerate(ids):
        if progress:
            progress(i, len(ids), demo_id)
        rows.append(row(demo_id, rounds, seed))
    return rows


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _expected(r: Dict[str, Any]) -> str:
    lo, hi = r["expect_rate"]
    return _pct(lo) if lo == hi else f"{_pct(lo)}–{_pct(hi)}"


def _test(r: Dict[str, Any]) -> str:
    t = r.get("test")
    if not t:
        return ""
    rule = f"{t['rounds']} rounds"
    if t["min_answered"]:
        rule += f", ≥{_pct(t['min_answered'])} answered"
    rule += f", ≥{_pct(t['min_correct'])} right"
    return f"{rule}: passes {describe(t['pass_probability'])}"


def render(rows: List[Dict[str, Any]], fmt: str = "md", sections: Optional[Dict[str, str]] = None) -> str:
    sections = sections or recipe.demos().get("sections", {})
    when = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    good = sum(r["ok"] for r in rows)
    head = (f"QPV Workbench {__version__} scenario report, {when}. {good} of {len(rows)} scenarios match their "
            "expected pass rate (the 95% interval of the measured rate overlaps the expected range).")
    if fmt == "csv":
        lines = ["id,section,title,who,rounds,passed,pass_rate,ci_lo,ci_hi,expected_lo,expected_hi,matches,test"]
        for r in rows:
            cells = [r["id"], r["section"], r["title"], r["who"], r["n"], r["accepted"], f"{r['p']:.4f}",
                     f"{r['lo']:.4f}", f"{r['hi']:.4f}", r["expect_rate"][0], r["expect_rate"][1],
                     "yes" if r["ok"] else "NO", _test(r)]
            lines.append(",".join('"' + str(c).replace('"', '""') + '"' if any(ch in str(c) for ch in ',"\n') else str(c)
                                  for c in cells))
        return "\n".join(lines) + "\n"
    if fmt == "md":
        out = ["# QPV Workbench: scenario report", "", head, "",
               "| Case | Scenario | Rounds | Passed | 95% interval | Expected | Matches | Many-round test |",
               "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in rows:
            out.append(f"| {r['section']} | {r['title']} | {r['n']} | {_pct(r['p'])} | {_pct(r['lo'])}–{_pct(r['hi'])} "
                       f"| {_expected(r)} | {'yes' if r['ok'] else '**no**'} | {_test(r)} |")
        out += ["", "Each round is one simulated protocol run. Results describe the model, not a security proof."]
        return "\n".join(out) + "\n"
    if fmt == "html":
        esc = html.escape
        body = []
        for letter, name in sections.items():
            part = [r for r in rows if r["section"] == letter]
            if not part:
                continue
            body.append(f"<h2>{esc(letter)}. {esc(name)}</h2><table><thead><tr><th>Scenario</th><th>Rounds</th>"
                        "<th>Passed</th><th>95% interval</th><th>Expected</th><th>Matches</th><th>Many-round test</th>"
                        "</tr></thead><tbody>")
            for r in part:
                body.append(f"<tr class='{'ok' if r['ok'] else 'bad'}'><td><b>{esc(r['title'])}</b><br>"
                            f"<small>{esc(r['expect'])}</small></td><td>{r['n']}</td><td>{_pct(r['p'])}</td>"
                            f"<td>{_pct(r['lo'])}–{_pct(r['hi'])}</td><td>{_expected(r)}</td>"
                            f"<td>{'yes' if r['ok'] else 'NO'}</td><td>{esc(_test(r))}</td></tr>")
            body.append("</tbody></table>")
        style = ("body{font:14px/1.45 system-ui,sans-serif;color:#18222f;max-width:1000px;margin:24px auto;padding:0 16px}"
                 "table{border-collapse:collapse;width:100%;margin-bottom:18px}th,td{text-align:left;padding:5px 8px;"
                 "border-bottom:1px solid #d3dae2;vertical-align:top}th{font-size:12px;color:#6f7c8a}"
                 "tr.bad td{background:#f7e0e4}small{color:#6f7c8a}h2{font-size:16px;margin:22px 0 6px}"
                 "@media print{body{margin:0}tr{break-inside:avoid}}")
        return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>QPV scenario report</title>"
                f"<style>{style}</style></head><body><h1>QPV Workbench: scenario report</h1><p>{esc(head)}</p>"
                + "".join(body) + "<p><small>Each round is one simulated protocol run. Results describe the model, "
                "not a security proof.</small></p></body></html>\n")
    raise ValueError("format must be md, csv or html")

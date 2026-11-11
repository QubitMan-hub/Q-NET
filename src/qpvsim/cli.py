"""Command-line entry point: ``qpv serve | run | console | experiment | validate | examples``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import timeunits as tu
from .console import Console, _format_results
from .experiments import results_to_csv
from .invariants import check_trace
from .session import Session, dump_json


def _session(project: str | None) -> Session:
    s = Session()
    if project:
        s.load(project if Path(project).exists() else f"example:{project}")
    return s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qpv", description="QPV Workbench")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("serve", help="start the graphical workbench (HTTP server)")
    p.add_argument("project", nargs="?")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open", action="store_true", help="open the workbench in your web browser")
    p.add_argument("--scenario", help="start on this gallery scenario (see 'qpv scenarios')")

    p = sub.add_parser("run", help="run one simulation headlessly")
    p.add_argument("project", help="project file or example name")
    p.add_argument("--seed", type=int)
    p.add_argument("--trace", help="write the full trace JSON here")
    p.add_argument("--quiet", action="store_true")

    p = sub.add_parser("console", help="interactive console (or run a script with --script)")
    p.add_argument("project", nargs="?")
    p.add_argument("--script", help="file with one console command per line; exits non-zero on failure")

    p = sub.add_parser("experiment", help="run an experiment saved in a project, or an ad-hoc batch")
    p.add_argument("project")
    p.add_argument("--id", help="saved experiment id")
    p.add_argument("--runs", type=int, default=100)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--json", help="write raw + derived results JSON")
    p.add_argument("--csv", help="write derived statistics CSV")

    p = sub.add_parser("validate", help="validate a project file")
    p.add_argument("project")

    sub.add_parser("scenarios", help="list the scenario gallery (every case in the write-up)")
    p = sub.add_parser("scenario", help="run a gallery scenario or a recipe file for many rounds and report the pass rate")
    p.add_argument("scenario", help="scenario id from 'qpv scenarios', or a recipe .json file")
    p.add_argument("--rounds", type=int, default=100)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--save", help="also write the built project here (open it with 'qpv serve <file>')")

    p = sub.add_parser("report", help="run every gallery scenario and write a report of measured vs expected pass rates")
    p.add_argument("--rounds", type=int, default=300, help="rounds per scenario (default 300)")
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--only", nargs="*", help="only these scenario ids")
    p.add_argument("--format", choices=["md", "csv", "html"], help="default: from the --out extension, else md")
    p.add_argument("--out", help="write the report here (default: print it)")

    p = sub.add_parser("protocols", help="compare the protocols side by side (honest, guessing, unentangled and "
                                         "entangled cheaters)")
    p.add_argument("--rounds", type=int, default=300)
    p.add_argument("--seed", type=int, default=21)

    p = sub.add_parser("rounds", help="how many rounds separate an honest prover from a cheater")
    p.add_argument("--honest", type=float, required=True, help="honest prover's per-round pass rate, e.g. 0.98")
    p.add_argument("--cheat", type=float, required=True, help="best cheater's per-round pass rate, e.g. 0.854")
    p.add_argument("--risk", type=float, default=1e-6, help="allowed chance of either mistake (default 1e-6)")

    sub.add_parser("examples", help="list bundled examples")
    p = sub.add_parser("export-examples", help="write the bundled example projects to a directory")
    p.add_argument("directory")

    a = ap.parse_args(argv)
    if a.cmd == "serve":
        import uvicorn
        from .server.app import create_app
        url = f"http://{a.host}:{a.port}/" + (f"#scenario={a.scenario}" if a.scenario else "")
        if not (Path(__file__).parent / "server" / "static" / "index.html").exists():
            print("The web interface is not built yet. Run:  cd frontend && npm install && npm run build", file=sys.stderr)
            return 1
        print(f"QPV Workbench on {url}  (Ctrl-C to stop)")
        if a.open:
            import threading
            import webbrowser
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        uvicorn.run(create_app(_session(a.project)), host=a.host, port=a.port, log_level="warning")
        return 0
    if a.cmd == "report":
        from .qpv import report as qreport
        fmt = a.format or (Path(a.out).suffix.lstrip(".").replace("markdown", "md") if a.out else "md")
        fmt = {"htm": "html", "txt": "md"}.get(fmt, fmt)
        rows = qreport.report(a.rounds, a.only, a.seed,
                              progress=lambda i, n, d: print(f"\r[{i + 1}/{n}] {d:<26}", end="", file=sys.stderr))
        print(file=sys.stderr)
        text = qreport.render(rows, fmt)
        if a.out:
            Path(a.out).write_text(text)
            print(f"{sum(r['ok'] for r in rows)} of {len(rows)} scenarios match; report written to {a.out}")
        else:
            print(text, end="")
        return 0 if all(r["ok"] for r in rows) else 3
    if a.cmd == "protocols":
        from .qpv import protocols as qprot
        cols = qprot.COMPARISON["columns"]
        print(f"{'':44}" + "".join(f"{c['label'][:24]:>26}" for c in cols))
        for row in qprot.COMPARISON["rows"]:
            cells = []
            for c in cols:
                cell = row["cells"].get(c["id"])
                if not cell:
                    cells.append(f"{'-':>26}")
                    continue
                r = qprot.compare_cell(cell["recipe"], a.rounds, a.seed)
                th = "" if r["theory"] is None else f" (theory {100 * r['theory']:.0f}%)"
                cells.append(f"{f'{100 * r[chr(112)]:.0f}%{th}':>26}")
            print(f"{row['label'][:44]:44}" + "".join(cells))
        print("\n" + qprot.COMPARISON["note"])
        return 0
    if a.cmd == "rounds":
        from .qpv import rounds as qrounds
        r = qrounds.rounds_needed(a.honest, a.cheat, a.risk)
        if r is None:
            print("No number of rounds separates them: the honest pass rate must be above the cheater's.")
            return 1
        print(f"{r['rounds']} rounds, accepting with at least {r['pass_mark']} right ({100 * r['min_correct']:.1f}%):\n"
              f"  honest prover fails with probability {r['honest_fails']:.2e}\n"
              f"  cheater passes with probability {r['cheater_passes']:.2e}")
        return 0
    if a.cmd == "scenarios":
        from .qpv import recipe
        g = recipe.demos()
        for letter, title in g["sections"].items():
            print(f"\n{letter}. {title}")
            for d in g["demos"]:
                if d["section"] == letter:
                    print(f"  {d['id']:<22} {d['title']}")
        print("\nRun one:  qpv scenario <id>      Open one:  qpv serve --open --scenario <id>")
        return 0
    if a.cmd == "scenario":
        return _run_scenario(a)
    if a.cmd == "examples":
        from .library import EXAMPLES, example
        for n in EXAMPLES:
            print(f"{n:<34} {example(n)['meta']['name']}")
        return 0
    if a.cmd == "export-examples":
        from .library import write_examples
        for path in write_examples(Path(a.directory)):
            print(path)
        return 0
    s = _session(a.project)
    if a.cmd == "validate":
        issues = s.validate()
        for i in issues:
            print(f"[{i['level']}] {i['path']}: {i['message']}")
        print("valid" if not any(i["level"] == "error" for i in issues) else "INVALID")
        return 1 if any(i["level"] == "error" for i in issues) else 0
    if a.cmd == "run":
        if s.sim is None:
            print(s.sim_error, file=sys.stderr)
            return 1
        if a.seed is not None:
            s.reset(a.seed)
        sim = s.run()
        if not a.quiet:
            for r in sim.trace:
                print(f"{tu.fmt(r.time):>16}  {r.kind:<20} {r.node or '':<6} {r.explain}")
        dec = sim.snapshot(since=len(sim.trace))["decision"]
        print(dec["summary"])
        for line in dec["explanation"]:
            print("  -", line)
        inv = check_trace(sim)
        print("invariants:", "all hold" if inv["ok"] else inv["violations"])
        if a.trace:
            dump_json(s.export_trace(), a.trace)
        return 0 if inv["ok"] else 2
    if a.cmd == "experiment":
        exp = s.saved_experiment(a.id) if a.id else {"id": "cli", "runs": a.runs, "seed": a.seed}
        exp = {**exp, "workers": a.workers}
        res = s.experiment(exp, progress=lambda d, t: print(f"\r{d}/{t}", end="", file=sys.stderr))
        print(file=sys.stderr)
        print(_format_results(res))
        if a.json:
            dump_json(res, a.json)
        if a.csv:
            Path(a.csv).write_text(results_to_csv(res))
        return 0
    if a.cmd == "console":
        con = Console(s)
        if a.script:
            ok = True
            for line in Path(a.script).read_text().splitlines():
                if not line.strip() or line.strip().startswith("#"):
                    continue
                res = con.execute(line)
                print(f"> {line}\n{res.output}")
                if not res.ok:
                    ok = False
                    break
            return 0 if ok else 1
        try:
            import readline  # noqa: F401

            def completer(text, state):
                opts = con.complete(readline.get_line_buffer())
                return opts[state] if state < len(opts) else None
            readline.set_completer(completer)
            readline.parse_and_bind("tab: complete")
        except ImportError:
            pass
        print("QPV Workbench console — 'help' for commands, Ctrl-D to exit")
        while True:
            try:
                line = input("qpv> ")
            except EOFError:
                print()
                return 0
            res = con.execute(line)
            if res.output:
                print(res.output)
    return 0


def _run_scenario(a) -> int:
    """Build a gallery scenario (or a recipe file), run it for many rounds and print what happened."""
    import json
    from .experiments import run_experiment
    from .qpv import recipe
    if a.scenario.endswith(".json"):
        r = json.loads(Path(a.scenario).read_text())
        title, expect = r.get("title", a.scenario), r.get("expect", "")
    else:
        try:
            d = recipe.demo(a.scenario)
        except KeyError:
            print(f"unknown scenario {a.scenario!r}; 'qpv scenarios' lists them", file=sys.stderr)
            return 1
        r = {**d["recipe"], **{k: d[k] for k in ("id", "section", "title", "watch", "expect", "who") if k in d}}
        title, expect = d["title"], d["expect"]
    doc = recipe.compose(r)
    print(title)
    if doc["meta"].get("description"):
        print("  " + doc["meta"]["description"])
    runs = (d.get("runs") if not a.scenario.endswith(".json") else None) or a.rounds
    res = run_experiment(doc, {"runs": runs, "seed": a.seed})["points"][0]["summary"]
    acc = res["acceptance"]
    print(f"\nPassed {res['accepted']} of {res['n']} rounds ({100 * acc['p']:.1f}%, 95% CI {100 * acc['lo']:.1f}-{100 * acc['hi']:.1f}%)")
    for vid, v in res["verifiers"].items():
        print(f"  {vid}: " + ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in v["categories"].items()))
    if res.get("test"):
        from .qpv.rounds import describe
        t = res["test"]
        print(f"Judged over {t['rounds']} rounds (at least {100 * t['min_answered']:.0f}% answered, "
              f"{100 * t['min_correct']:.0f}% of those right): passes {describe(t['pass_probability'])}"
              + (f"; {t['blocks_passed']} of {t['blocks']} recorded blocks of {t['rounds']} passed" if t["blocks"] else ""))
    if expect:
        print(f"Expected: {expect}")
    if a.save:
        dump_json(doc, a.save)
        print(f"Project written to {a.save}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

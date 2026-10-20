"""Command-line entry point: ``qpv serve | run | console | experiment | validate | examples``."""

from __future__ import annotations

import argparse
import json
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

    sub.add_parser("examples", help="list bundled examples")
    p = sub.add_parser("export-examples", help="write the bundled example projects to a directory")
    p.add_argument("directory")

    a = ap.parse_args(argv)
    if a.cmd == "serve":
        import uvicorn
        from .server.app import create_app
        print(f"QPV Workbench on http://{a.host}:{a.port}")
        uvicorn.run(create_app(_session(a.project)), host=a.host, port=a.port, log_level="warning")
        return 0
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


if __name__ == "__main__":
    sys.exit(main())

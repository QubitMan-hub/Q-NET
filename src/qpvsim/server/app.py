"""FastAPI bridge between the browser UI and a :class:`~qpvsim.session.Session`.

The server is a thin, single-user adapter: every endpoint calls the session
and returns what the engine produced.  A lock serialises access.  Experiments
run in a background thread and report progress for polling.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..console import Console, _strip_runs
from ..experiments import results_to_csv
from ..library import EXAMPLES, automaton_library, example
from ..protocol.automaton import ACTIONS, TRIGGER_TYPES
from ..protocol.capabilities import profile_catalog
from ..protocol.expr import ENGINE_FUNCTIONS, PURE_FUNCTIONS
from ..quantum import backend_catalog
from ..session import Session, SessionError

STATIC = Path(__file__).parent / "static"


def create_app(session: Optional[Session] = None) -> FastAPI:
    app = FastAPI(title="QPV Workbench", version=__version__)
    S = session or Session()
    console = Console(S)
    lock = threading.RLock()
    jobs: Dict[str, Dict[str, Any]] = {}

    def guarded(fn):
        with lock:
            try:
                return fn()
            except (SessionError, KeyError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc.args[0] if exc.args else exc)) from None

    @app.get("/api/meta")
    def meta():
        return {
            "version": __version__, "backends": backend_catalog(), "profiles": profile_catalog(),
            "actions": {k: {"required": v["required"], "exprs": v["exprs"], "doc": v["doc"]} for k, v in ACTIONS.items()},
            "triggers": sorted(TRIGGER_TYPES),
            "functions": {**{k: "builtin" for k in PURE_FUNCTIONS}, **ENGINE_FUNCTIONS},
            "examples": {n: example(n)["meta"]["name"] for n in EXAMPLES},
            "automata": automaton_library(),
            "console_commands": console.catalog(),
        }

    @app.get("/api/project")
    def get_project():
        with lock:
            return {"project": S.project, "issues": S.validate(), "revision": S.revision,
                    "sim_error": S.sim_error}

    @app.put("/api/project")
    def put_project(doc: Dict[str, Any] = Body(...)):
        def f():
            issues = S.set_project(doc, keep_run_if_layout_only=True)
            return {"project": S.project, "issues": issues, "revision": S.revision, "sim_error": S.sim_error}
        return guarded(f)

    @app.post("/api/project/validate")
    def validate(doc: Dict[str, Any] = Body(...)):
        from ..protocol.project import normalize, validate_project
        try:
            return {"issues": [i.as_dict() for i in validate_project(normalize(doc))]}
        except Exception as exc:  # malformed documents
            return {"issues": [{"level": "error", "path": "", "message": f"{type(exc).__name__}: {exc}"}]}

    @app.post("/api/project/example/{name}")
    def load_example(name: str):
        def f():
            S.load(f"example:{name}")
            return {"project": S.project, "issues": S.validate(), "revision": S.revision, "sim_error": S.sim_error}
        return guarded(f)

    @app.get("/api/project/export")
    def export_project():
        with lock:
            name = S.project["meta"]["name"].replace(" ", "_").replace("—", "-")
            return JSONResponse(S.project, headers={"Content-Disposition": f'attachment; filename="{name}.qpv.json"'})

    @app.post("/api/sim/reset")
    def reset(body: Dict[str, Any] = Body(default={})):
        def f():
            S.reset(body.get("seed"))
            return S.state()
        return guarded(f)

    @app.post("/api/sim/step")
    def step(body: Dict[str, Any] = Body(default={})):
        def f():
            S.step(int(body.get("n", 1)))
            return S.state(int(body.get("since", 0)))
        return guarded(f)

    @app.post("/api/sim/run")
    def run(body: Dict[str, Any] = Body(default={})):
        def f():
            S.run(body.get("until_ns"), body.get("max_steps"))
            return S.state(int(body.get("since", 0)))
        return guarded(f)

    @app.get("/api/sim/state")
    def state(since: int = 0):
        with lock:
            return S.state(since)

    @app.get("/api/sim/chain/{msg_id}")
    def chain(msg_id: int):
        return guarded(lambda: S.require_sim().causal_chain(msg_id))

    @app.get("/api/sim/invariants")
    def invariants():
        return guarded(S.invariants)

    @app.get("/api/sim/export")
    def export_trace():
        def f():
            return JSONResponse(S.export_trace(),
                                headers={"Content-Disposition": 'attachment; filename="trace.qpvtrace.json"'})
        return guarded(f)

    @app.post("/api/console")
    def run_console(body: Dict[str, Any] = Body(...)):
        with lock:
            since = int(body.get("since", 0))
            res = console.execute(str(body.get("line", "")))
            return {"result": res.as_dict(), "state": S.state(since) if S.sim else S.state()}

    @app.get("/api/console/complete")
    def complete(prefix: str = ""):
        with lock:
            return console.complete(prefix)

    @app.post("/api/experiments")
    def start_experiment(exp: Dict[str, Any] = Body(...)):
        job_id = uuid.uuid4().hex[:10]
        with lock:
            project = S.project
        job = {"id": job_id, "status": "running", "done": 0, "total": None, "result": None, "error": None,
               "cancel": False}
        jobs[job_id] = job

        def progress(done, total):
            job["done"], job["total"] = done, total

        def work():
            try:
                from ..experiments import run_experiment
                res = run_experiment(project, exp, progress=progress, cancel=lambda: job["cancel"])
                with lock:
                    S.results.append(res)
                job["result"] = res
                job["status"] = "done"
            except Exception as exc:  # reported to the client verbatim
                job["error"] = f"{type(exc).__name__}: {exc}"
                job["status"] = "error"

        threading.Thread(target=work, daemon=True).start()
        return {"id": job_id}

    @app.get("/api/experiments/{job_id}")
    def get_experiment(job_id: str, raw: bool = False):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "no such job")
        out = {k: v for k, v in job.items() if k not in ("result", "cancel")}
        if job["result"] is not None:
            out["result"] = job["result"] if raw else _strip_runs(job["result"])
        return out

    @app.post("/api/experiments/{job_id}/cancel")
    def cancel_experiment(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "no such job")
        job["cancel"] = True
        return {"ok": True}

    @app.get("/api/experiments/{job_id}/csv", response_class=PlainTextResponse)
    def experiment_csv(job_id: str):
        job = jobs.get(job_id)
        if job is None or job["result"] is None:
            raise HTTPException(404, "no results")
        return results_to_csv(job["result"])

    @app.get("/api/experiments/{job_id}/raw")
    def experiment_raw(job_id: str):
        job = jobs.get(job_id)
        if job is None or job["result"] is None:
            raise HTTPException(404, "no results")
        return JSONResponse(job["result"], headers={"Content-Disposition": 'attachment; filename="results.json"'})

    if (STATIC / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(STATIC / "index.html")
    else:
        @app.get("/")
        def no_ui():
            return PlainTextResponse("QPV Workbench API is running, but the UI bundle is not built. "
                                     "Run `npm install && npm run build` in frontend/.")

    app.state.session = S
    return app

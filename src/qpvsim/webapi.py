"""Framework-free request dispatcher for the workbench API.

One implementation of every ``/api/...`` route, used by two transports:

* the FastAPI server (``qpvsim.server.app``), and
* the in-browser build, where Pyodide runs this module in a Web Worker and the
  UI calls :func:`handle_json` instead of making HTTP requests (GitHub Pages).

Each call returns ``(status, payload, kind)`` where ``kind`` is ``"json"`` or
``"text"``.  Errors from the session become status 400 with a message.
"""

from __future__ import annotations

import copy
import json
import re
import threading
import uuid
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .console import Console, _strip_runs
from .experiments import results_to_csv, run_experiment
from .library import EXAMPLES, automaton_library, example
from .protocol.automaton import ACTIONS, TRIGGER_TYPES
from .protocol.capabilities import profile_catalog
from .protocol.expr import ENGINE_FUNCTIONS, PURE_FUNCTIONS
from .protocol.project import normalize, validate_project
from .quantum import backend_catalog
from .session import Session, SessionError

Result = Tuple[int, Any, str]


class NotFound(Exception):
    pass


class WebAPI:
    """Routes API requests to a :class:`Session`.

    ``background_experiments`` runs experiments in a thread (server); without
    threads (browser) they run to completion inside the request.
    ``allow_parallel`` permits multi-process experiment workers.
    """

    def __init__(self, session: Optional[Session] = None, background_experiments: bool = True,
                 allow_parallel: bool = True):
        self.session = session or Session()
        self.console = Console(self.session)
        self.lock = threading.RLock()
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.background = background_experiments
        self.allow_parallel = allow_parallel
        self.routes: list[tuple[str, re.Pattern, Callable[..., Result]]] = []
        R = self._route
        R("GET", r"/api/meta", self.meta)
        R("GET", r"/api/project", self.get_project)
        R("PUT", r"/api/project", self.put_project)
        R("POST", r"/api/project/validate", self.validate)
        R("POST", r"/api/project/example/(?P<name>[\w\-]+)", self.load_example)
        R("GET", r"/api/project/export", self.export_project)
        R("POST", r"/api/sim/reset", self.reset)
        R("POST", r"/api/sim/step", self.step)
        R("POST", r"/api/sim/run", self.run)
        R("GET", r"/api/sim/state", self.state)
        R("GET", r"/api/sim/chain/(?P<msg>\d+)", self.chain)
        R("GET", r"/api/sim/invariants", self.invariants)
        R("GET", r"/api/sim/export", self.export_trace)
        R("POST", r"/api/console", self.run_console)
        R("GET", r"/api/console/complete", self.complete)
        R("POST", r"/api/experiments", self.start_experiment)
        R("GET", r"/api/experiments/(?P<job>\w+)", self.get_experiment)
        R("POST", r"/api/experiments/(?P<job>\w+)/cancel", self.cancel_experiment)
        R("GET", r"/api/experiments/(?P<job>\w+)/csv", self.experiment_csv)
        R("GET", r"/api/experiments/(?P<job>\w+)/raw", self.experiment_raw)

    def _route(self, method: str, pattern: str, fn: Callable[..., Result]) -> None:
        self.routes.append((method, re.compile(pattern + r"$"), fn))

    # ------------------------------------------------------------ dispatch
    def handle(self, method: str, url: str, body: Any = None) -> Result:
        parts = urlsplit(url)
        query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
        for m, pat, fn in self.routes:
            match = pat.match(parts.path)
            if match and m == method.upper():
                try:
                    with self.lock:
                        return fn(body=body, query=query, **match.groupdict())
                except NotFound as exc:
                    return 404, {"detail": str(exc)}, "json"
                except (SessionError, KeyError, ValueError) as exc:
                    msg = exc.args[0] if exc.args else str(exc)
                    return 400, {"detail": str(msg)}, "json"
        return 404, {"detail": f"no route for {method} {parts.path}"}, "json"

    @staticmethod
    def ok(payload: Any) -> Result:
        return 200, payload, "json"

    # ------------------------------------------------------------ project
    def meta(self, **_) -> Result:
        return self.ok({
            "version": __version__, "backends": backend_catalog(), "profiles": profile_catalog(),
            "actions": {k: {"required": v["required"], "exprs": v["exprs"], "doc": v["doc"]} for k, v in ACTIONS.items()},
            "triggers": sorted(TRIGGER_TYPES),
            "functions": {**{k: "builtin" for k in PURE_FUNCTIONS}, **ENGINE_FUNCTIONS},
            "examples": {n: example(n)["meta"]["name"] for n in EXAMPLES},
            "automata": automaton_library(),
            "console_commands": self.console.catalog(),
            "parallel_experiments": self.allow_parallel,
        })

    def _project_payload(self, issues=None) -> Dict[str, Any]:
        S = self.session
        return {"project": S.project, "issues": S.validate() if issues is None else issues,
                "revision": S.revision, "sim_error": S.sim_error}

    def get_project(self, **_) -> Result:
        return self.ok(self._project_payload())

    def put_project(self, body=None, **_) -> Result:
        issues = self.session.set_project(body, keep_run_if_layout_only=True)
        return self.ok(self._project_payload(issues))

    def validate(self, body=None, **_) -> Result:
        try:
            return self.ok({"issues": [i.as_dict() for i in validate_project(normalize(body))]})
        except Exception as exc:  # malformed documents
            return self.ok({"issues": [{"level": "error", "path": "", "message": f"{type(exc).__name__}: {exc}"}]})

    def load_example(self, name, **_) -> Result:
        self.session.load(f"example:{name}")
        return self.ok(self._project_payload())

    def export_project(self, **_) -> Result:
        return self.ok(self.session.project)

    # ------------------------------------------------------------ simulation
    def reset(self, body=None, **_) -> Result:
        self.session.reset((body or {}).get("seed"))
        return self.ok(self.session.state())

    def step(self, body=None, **_) -> Result:
        body = body or {}
        self.session.step(int(body.get("n", 1)))
        return self.ok(self.session.state(int(body.get("since", 0))))

    def run(self, body=None, **_) -> Result:
        body = body or {}
        self.session.run(body.get("until_ns"), body.get("max_steps"))
        return self.ok(self.session.state(int(body.get("since", 0))))

    def state(self, query=None, **_) -> Result:
        return self.ok(self.session.state(int((query or {}).get("since", 0))))

    def chain(self, msg, **_) -> Result:
        return self.ok(self.session.require_sim().causal_chain(int(msg)))

    def invariants(self, **_) -> Result:
        return self.ok(self.session.invariants())

    def export_trace(self, **_) -> Result:
        return self.ok(self.session.export_trace())

    # ------------------------------------------------------------ console
    def run_console(self, body=None, **_) -> Result:
        body = body or {}
        since = int(body.get("since", 0))
        res = self.console.execute(str(body.get("line", "")))
        S = self.session
        return self.ok({"result": res.as_dict(), "state": S.state(since) if S.sim else S.state()})

    def complete(self, query=None, **_) -> Result:
        return self.ok(self.console.complete((query or {}).get("prefix", "")))

    # ------------------------------------------------------------ experiments
    def _job(self, job: str) -> Dict[str, Any]:
        if job not in self.jobs:
            raise NotFound("no such experiment job")
        return self.jobs[job]

    def start_experiment(self, body=None, **_) -> Result:
        exp = dict(body or {})
        if not self.allow_parallel:
            exp["workers"] = 1
        job_id = uuid.uuid4().hex[:10]
        project = copy.deepcopy(self.session.project)
        job = {"id": job_id, "status": "running", "done": 0, "total": None, "result": None,
               "error": None, "cancel": False}
        self.jobs[job_id] = job

        def progress(done, total):
            job["done"], job["total"] = done, total

        def work():
            try:
                res = run_experiment(project, exp, progress=progress, cancel=lambda: job["cancel"])
                with self.lock:
                    self.session.results.append(res)
                job["result"] = res
                job["status"] = "done"
            except Exception as exc:  # reported to the client verbatim
                job["error"] = f"{type(exc).__name__}: {exc}"
                job["status"] = "error"

        if self.background:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()
        return self.ok({"id": job_id})

    def get_experiment(self, job, query=None, **_) -> Result:
        j = self._job(job)
        out = {k: v for k, v in j.items() if k not in ("result", "cancel")}
        if j["result"] is not None:
            raw = str((query or {}).get("raw", "")).lower() in ("1", "true")
            out["result"] = j["result"] if raw else _strip_runs(j["result"])
        return self.ok(out)

    def cancel_experiment(self, job, **_) -> Result:
        self._job(job)["cancel"] = True
        return self.ok({"ok": True})

    def experiment_csv(self, job, **_) -> Result:
        j = self._job(job)
        if j["result"] is None:
            raise NotFound("no results")
        return 200, results_to_csv(j["result"]), "text"

    def experiment_raw(self, job, **_) -> Result:
        j = self._job(job)
        if j["result"] is None:
            raise NotFound("no results")
        return self.ok(j["result"])


_BROWSER_API: Optional[WebAPI] = None


def handle_json(method: str, url: str, body_json: str = "") -> str:
    """Entry point for the in-browser build: JSON in, JSON out (``{status, kind, body}``)."""
    global _BROWSER_API
    if _BROWSER_API is None:
        _BROWSER_API = WebAPI(background_experiments=False, allow_parallel=False)
    body = json.loads(body_json) if body_json else None
    status, payload, kind = _BROWSER_API.handle(method, url, body)
    return json.dumps({"status": status, "kind": kind, "body": payload}, default=str)

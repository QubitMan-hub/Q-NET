"""A workbench session: the editable project plus its current simulation.

The session is the programmatic API shared by the console, the HTTP server
and scripts.  All execution goes through :class:`~qpvsim.engine.Simulation`;
the session never fabricates state.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import timeunits as tu
from .engine import ENGINE_VERSION, Simulation
from .experiments import provenance, run_experiment
from .invariants import check_trace
from .library import automaton_library, example
from .protocol.project import (ProjectError, get_path, load_project, normalize,
                               save_project, set_path, strip_ui, validate_project)


class SessionError(RuntimeError):
    pass


class Session:
    def __init__(self, project: Optional[Dict[str, Any]] = None):
        self.sim: Optional[Simulation] = None
        self.project: Dict[str, Any] = normalize(project or example("qpv_bb84_honest"))
        self.sim_error: Optional[str] = None
        self.checkpoints: Dict[str, Simulation] = {}
        self.results: List[Dict[str, Any]] = []
        self.project_path: Optional[str] = None
        self.revision = 0
        self.reset()

    # ------------------------------------------------------------ project
    def set_project(self, doc: Dict[str, Any], reset: bool = True,
                    keep_run_if_layout_only: bool = False) -> List[Dict[str, Any]]:
        """Replace the project.  Editor callers pass ``keep_run_if_layout_only`` so that
        moving nodes on a canvas does not restart the run; loading always restarts it."""
        new = normalize(copy.deepcopy(doc))
        layout_only = (keep_run_if_layout_only and hasattr(self, "project")
                       and strip_ui(new) == strip_ui(self.project))
        self.project = new
        if layout_only and self.sim is not None:
            # canvas layout does not influence execution: keep the running simulation
            self.sim.project["participants"] = new["participants"]
            self.sim.project["automata"] = new["automata"]
            return [i.as_dict() for i in validate_project(self.project)]
        self.revision += 1
        if reset:
            self.reset()
        return [i.as_dict() for i in validate_project(self.project)]

    def load(self, source: str) -> Dict[str, Any]:
        if source.startswith("example:"):
            doc = example(source.split(":", 1)[1])
            self.project_path = None
        else:
            doc = load_project(source)
            self.project_path = source
        self.set_project(doc)
        return self.project

    def save(self, path: Optional[str] = None) -> str:
        path = path or self.project_path
        if not path:
            raise SessionError("no path given and project was not loaded from a file")
        save_project(self.project, path)
        self.project_path = path
        return path

    def validate(self) -> List[Dict[str, Any]]:
        return [i.as_dict() for i in validate_project(self.project)]

    def modify(self, fn: Callable[[Dict[str, Any]], None], reset: bool = True) -> None:
        """Apply ``fn`` to a copy of the project, then install the copy (restarting the run)."""
        doc = copy.deepcopy(self.project)
        fn(doc)
        self.set_project(doc, reset=reset)

    def edit(self, path: str, value: Any, reset: bool = True) -> None:
        self.modify(lambda doc: set_path(doc, path, value), reset=reset)

    def get(self, path: str) -> Any:
        return get_path(self.project, path)

    def use_strategy(self, participant: str, automaton: str) -> None:
        lib = automaton_library()
        if automaton not in self.project["automata"] and automaton not in lib:
            raise SessionError(f"unknown automaton {automaton!r}")

        def apply(doc):
            doc["automata"].setdefault(automaton, copy.deepcopy(lib.get(automaton)))
            set_path(doc, f"participants.{participant}.automaton", automaton)
        self.modify(apply)

    # ------------------------------------------------------------ simulation
    def reset(self, seed: Optional[int] = None) -> Optional[Simulation]:
        try:
            self.sim = Simulation(self.project, seed=seed)
            self.sim_error = None
        except ProjectError as exc:
            self.sim = None
            self.sim_error = str(exc)
        except Exception as exc:  # resource setup failures etc.
            self.sim = None
            self.sim_error = f"{type(exc).__name__}: {exc}"
        return self.sim

    def require_sim(self) -> Simulation:
        if self.sim is None:
            raise SessionError(self.sim_error or "no simulation (project invalid?)")
        return self.sim

    def step(self, n: int = 1) -> int:
        sim = self.require_sim()
        done = 0
        for _ in range(max(0, n)):
            if sim.step() is None:
                break
            done += 1
        return done

    def run(self, until_ns: Optional[float] = None, max_steps: Optional[int] = None) -> Simulation:
        sim = self.require_sim()
        sim.run(until_fs=None if until_ns is None else tu.ns(until_ns), max_steps=max_steps)
        return sim

    def advance(self, dt_ns: float) -> Simulation:
        sim = self.require_sim()
        return sim.advance(tu.ns(dt_ns))

    def checkpoint(self, name: str) -> None:
        self.checkpoints[name] = copy.deepcopy(self.require_sim())

    def restore(self, name: str) -> None:
        if name not in self.checkpoints:
            raise SessionError(f"no checkpoint {name!r}")
        self.sim = copy.deepcopy(self.checkpoints[name])

    def state(self, since: int = 0) -> Dict[str, Any]:
        if self.sim is None:
            return {"error": self.sim_error, "revision": self.revision}
        s = self.sim.snapshot(since=since)
        s["revision"] = self.revision
        return s

    def invariants(self) -> Dict[str, Any]:
        return check_trace(self.require_sim())

    def export_trace(self) -> Dict[str, Any]:
        sim = self.require_sim()
        return {
            "format": "qpvsim-trace", "version": 1, "engine_version": ENGINE_VERSION,
            "provenance": provenance(self.project), "project": self.project,
            "seed": sim.seed, "stopped": sim.stopped, "stop_reason": sim.stop_reason,
            "trace": [r.as_dict() for r in sim.trace],
            "messages": [m.as_dict() for m in sim.messages.values()],
            "events": [e.summary() | {"exec_index": e.exec_index} for e in sim.scheduler.all_events()],
            "final_states": {nid: sim.node_snapshot(n) for nid, n in sim.nodes.items()},
            "decision": sim.snapshot(since=len(sim.trace))["decision"],
            "invariants": check_trace(sim),
        }

    # ------------------------------------------------------------ experiments
    def experiment(self, exp: Dict[str, Any], **kw) -> Dict[str, Any]:
        res = run_experiment(self.project, exp, **kw)
        self.results.append(res)
        return res

    def saved_experiment(self, exp_id: str) -> Dict[str, Any]:
        for e in self.project.get("experiments", []):
            if e.get("id") == exp_id:
                return e
        raise SessionError(f"no saved experiment {exp_id!r}")


def dump_json(obj: Any, path: str) -> None:
    Path(path).write_text(json.dumps(obj, indent=2, default=str) + "\n")

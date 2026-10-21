"""qpvsim — an event-driven, quantum-capable, adversary-aware QPV simulation workbench.

Public API::

    from qpvsim import Simulation, load_project, example, run_experiment
    sim = Simulation(example("qpv_bb84_honest")).run()
    print(sim.snapshot()["decision"]["summary"])
"""

from .engine import ENGINE_VERSION, Simulation, TraceRecord, Message
from .decision import decide
from .invariants import check_trace
from .library import example, EXAMPLES, automaton_library
from .protocol.project import (ProjectError, load_project, save_project, validate_project,
                               set_path, get_path, normalize)

__version__ = ENGINE_VERSION

__all__ = [
    "Simulation", "TraceRecord", "Message", "decide", "check_trace", "example", "EXAMPLES",
    "automaton_library", "ProjectError", "load_project", "save_project", "validate_project",
    "set_path", "get_path", "normalize", "__version__",
]

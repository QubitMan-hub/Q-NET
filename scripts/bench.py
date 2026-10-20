"""Performance benchmark: per-run cost, scaling with participants, and quantum group size.

    python scripts/bench.py            # prints a table; numbers are machine-dependent
"""

import copy
import time

import numpy as np

from qpvsim import Simulation, example, normalize
from qpvsim.experiments import run_experiment
from qpvsim.quantum import DensityMatrixBackend, StateVectorBackend
from qpvsim.quantum import base as qb


def timed(fn, repeat=1):
    t0 = time.perf_counter()
    for _ in range(repeat):
        out = fn()
    return (time.perf_counter() - t0) / repeat, out


def chain_project(n_relays: int):
    """V0 -> E1 -> ... -> En -> P <- V1: relays forward the qubit and theta (stress test)."""
    doc = normalize(example("qpv_bb84_honest"))
    relay = {
        "name": "relay", "role": "other", "ports": ["in", "out"], "params": {}, "variables": {},
        "initial": "s", "states": [{"id": "s", "kind": "initial"}, {"id": "d", "kind": "terminal", "outcome": "done"}],
        "transitions": [
            {"id": "fwd_q", "from": "s", "to": "s", "trigger": {"type": "receive", "tags": ["q"], "port": "in"},
             "duration_ns": 0, "actions": [{"op": "send_qubit", "port": "out", "tag": "q", "qubit": "q"}]},
            {"id": "back", "from": "s", "to": "d", "trigger": {"type": "receive", "tags": ["answer"], "port": "out"},
             "duration_ns": 0, "actions": [{"op": "send", "port": "in", "tag": "answer", "value": "msg.value"}]},
        ],
    }
    doc["automata"]["relay"] = relay
    xs = np.linspace(-3, 0, n_relays + 2)[1:-1]
    doc["links"] = [l for l in doc["links"] if l["id"] not in ("q0", "c0")]
    prev = ("V0", "prover")
    for i, x in enumerate(xs):
        rid = f"R{i}"
        doc["participants"].append({"id": rid, "role": "other", "label": rid, "position": [float(x), 0.0],
                                    "automaton": "relay", "params": {}, "processing_ns": 0, "start_ns": 0,
                                    "clock": {"offset_ns": 0, "drift_ppm": 0}, "capabilities": "unrestricted",
                                    "noise": {}, "group": None, "ui": {}})
        for kind in ("quantum", "classical"):
            doc["links"].append({"id": f"r{kind[0]}{i}", "kind": kind, "a": {"node": prev[0], "port": prev[1]},
                                 "b": {"node": rid, "port": "in"}})
        prev = (rid, "out")
    for kind in ("quantum", "classical"):
        doc["links"].append({"id": f"r{kind[0]}last", "kind": kind, "a": {"node": prev[0], "port": prev[1]},
                             "b": {"node": "P", "port": "left"}})
    for v in ("V0", "V1"):
        p = next(q for q in doc["participants"] if q["id"] == v)
        p["params"]["tolerance_ns"] = 10.0
    return normalize(doc)


def main():
    print("== single runs (mean wall time per run) ==")
    for name in ("qpv_bb84_honest", "qpv_bb84_collusion_unentangled", "qpv_bb84_teleportation_attack"):
        doc = normalize(example(name))
        t, sim = timed(lambda: Simulation(doc).run(), 50)
        print(f"  {name:<34} {t * 1e3:7.2f} ms   {sim.scheduler.executed_count:4d} events   "
              f"{sim.scheduler.executed_count / t:9.0f} events/s")
    print("== experiment throughput (1000 runs) ==")
    for w in (1, 4):
        res = run_experiment(example("qpv_bb84_collusion_unentangled"), {"runs": 1000, "seed": 1, "workers": w})
        print(f"  workers={w}: {res['runs_per_second']:8.0f} runs/s")
    print("== scaling with participants (relay chain) ==")
    for n in (1, 10, 50, 100, 200):
        doc = chain_project(n)
        t, sim = timed(lambda: Simulation(doc).run(), 3)
        dec = sim.snapshot(since=len(sim.trace))["decision"]["outcome"]
        print(f"  {n + 3:4d} participants: {t * 1e3:8.2f} ms  {sim.scheduler.executed_count:6d} events  "
              f"{len(sim.trace):6d} records  outcome={dec}")
    print("== quantum backend: n-qubit GHZ preparation + measurement ==")
    for n in (4, 8, 10, 12):
        for cls in (DensityMatrixBackend, StateVectorBackend):
            b = cls(np.random.default_rng(0), max_group=24)

            def ghz():
                qs = [b.create(qb.KET["0"]) for _ in range(n)]
                b.apply_unitary([qs[0]], qb.H)
                for i in range(n - 1):
                    b.apply_unitary([qs[i], qs[i + 1]], qb.CNOT)
                return [b.measure(q, qb.I2) for q in qs]
            t, out = timed(ghz, 2)
            assert len(set(out)) == 1
            print(f"  n={n:2d} {cls.info.name:<15} {t * 1e3:9.2f} ms")


if __name__ == "__main__":
    main()

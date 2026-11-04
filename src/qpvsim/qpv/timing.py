"""When each verifier really sends and judges, and whether the timing of a setup is consistent.

The schedule comes from running the project once in the engine: a verifier's send time is the global
departure of its first message and its deadline is the global fire time of its timer named
``deadline`` (clock offset and drift included).  Arrivals at the claim use the project signal speed
and the engine's round-up propagation delays.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from .. import timeunits as tu
from ..engine import Simulation
from ..protocol.project import setup_key, verifier_ids, verifier_type
from .cache import memo
from .geometry import vec


def schedule(project: Dict[str, Any]) -> Dict[str, Any]:
    return _schedule(setup_key(project), project)


@memo()
def _schedule(project: Dict[str, Any]) -> Dict[str, Any]:
    sim = Simulation(project).run()
    rows, missing = [], []
    for vid in verifier_ids(sim.project):
        sent = sorted((m for m in sim.messages.values() if m.src == vid and m.depart_time is not None),
                      key=lambda m: (m.depart_time, m.id))
        armed = [r.data["fire_fs"] for r in sim.trace if r.node == vid and r.kind == "timer.set"
                 and r.data["name"] == "deadline"]
        answers = [m.arrival_time for m in sim.messages.values() if m.dst == vid and m.arrival_time is not None]
        if not sent or not armed:
            missing.append(f"{vid} never {'sent a challenge' if not sent else 'armed a timer named ' + repr('deadline')}")
        node = sim.nodes[vid]
        p = node.cfg
        # timers whose target had already passed when they were armed fire at once, so they fire late
        overdue = [{"name": r.data["name"], "target_fs": node.clock.to_global(r.data["target_local_fs"]),
                    "fired_fs": r.data["fire_fs"]}
                   for r in sim.trace if r.node == vid and r.kind == "timer.set"
                   and node.clock.to_global(r.data["target_local_fs"]) < r.data["fire_fs"]]
        meeting = node.observations.get("meeting_ns")
        rows.append({"id": vid, "type": verifier_type(sim.project, p), "position": p["position"],
                     "send_fs": sent[0].depart_time if sent else None, "deadline_fs": armed[-1] if armed else None,
                     "answer_fs": min(answers) if answers else None, "overdue_timers": overdue,
                     "meeting_ns": meeting, "t_ref_ns": node.params.get("t_ref_ns")})
    reason = "; ".join(missing) or (None if rows else "the project has no verifiers")
    return {"verifiers": rows, "reason": reason}


def table(project: Dict[str, Any]) -> Dict[str, Any]:
    """Per-verifier timing with slack for an honest prover at the claim, and inconsistencies."""
    s = schedule(project)
    if s["reason"]:
        return {"rows": [], "issues": [s["reason"]]}
    claim, speed = project["claim"]["position"], project["physics"]["signal_speed_mps"]
    prover = next((p for p in project["participants"] if p["id"] == project["claim"].get("prover")), None)
    proc = tu.ns(prover["processing_ns"]) if prover else 0
    rows: List[Dict[str, Any]] = []
    for v in s["verifiers"]:
        dist = float(math.dist(vec(v["position"]), vec(claim)))
        rows.append({**v, "distance_m": dist, "travel_fs": tu.propagation_fs(dist, speed),
                     "at_claim_fs": v["send_fs"] + tu.propagation_fs(dist, speed)})
    meet = max(r["at_claim_fs"] for r in rows)
    issues = []
    moved = next((r for r in rows if isinstance(r["meeting_ns"], (int, float)) and isinstance(r["t_ref_ns"], (int, float))
                  and r["meeting_ns"] > r["t_ref_ns"] + 1e-6), None)
    if moved:
        far = max(rows, key=lambda r: r["distance_m"])
        issues.append(f"The meeting time moved from {moved['t_ref_ns']:g} ns to {moved['meeting_ns']:.6f} ns: "
                      f"{far['id']} is {far['distance_m']:.6g} m from the claim and could not reach it by "
                      f"{moved['t_ref_ns']:g} ns without sending before t = 0.")
    for r in rows:
        r["honest_answer_fs"] = meet + proc + r["travel_fs"]
        r["slack_fs"] = r["deadline_fs"] - r["honest_answer_fs"]
        r["inconsistent"] = [f"{r['id']}'s timer '{o['name']}' was due at {o['target_fs'] / tu.NS:.6f} ns, before "
                             f"it could be set, so it fired late at {o['fired_fs'] / tu.NS:.6f} ns"
                             for o in r["overdue_timers"]]
        if r["at_claim_fs"] < meet:
            r["inconsistent"].append(f"{r['id']}'s challenge reaches the claim {(meet - r['at_claim_fs']) / tu.NS:.6f} ns "
                                     "before the others")
        if r["slack_fs"] < 0:
            r["inconsistent"].append(f"an honest prover at the claim misses {r['id']}'s deadline by "
                                     f"{-r['slack_fs'] / tu.NS:.6f} ns")
        issues += r["inconsistent"]
    return {"rows": rows, "issues": issues}

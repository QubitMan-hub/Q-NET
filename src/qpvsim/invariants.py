"""Trace invariants checked after (or during) a run.

These are *consistency* checks of the engine's own output, used by the test
suite and exposed to users (``validate`` console command, Validation panel).
Passing them shows the trace obeys the documented semantics; it says nothing
about the security of the modelled protocol.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Dict, List

from . import timeunits as tu

if TYPE_CHECKING:  # pragma: no cover
    from .engine import Simulation

INVARIANTS = {
    "monotonic_time": "Trace timestamps never decrease.",
    "event_order": "Every executed event had the smallest (time, priority, seq) key among the events pending at that moment; the clock never runs backwards.",
    "delivery_timing": "Every arrival equals departure + link delay, and departure is the "
                       "sending transition's completion time.",
    "relativistic_bound": "No message travels faster than the vacuum speed of light over the "
                          "straight-line distance between its endpoints.",
    "causal_consumption": "Messages are consumed only after they arrive, by their destination.",
    "causal_past": "A message's causal past only contains messages its sender had consumed before it departed.",
    "fsm_consistency": "Each participant's transitions chain: every transition starts in the state "
                       "the previous one entered, and only defined transitions occur.",
    "single_verdict": "Each participant records at most one verdict, and only on a completed transition.",
    "terminal_quiet": "No transition begins after a participant has reached a terminal state.",
}


def check_trace(sim: "Simulation") -> Dict[str, Any]:
    violations: List[Dict[str, Any]] = []

    def bad(inv: str, msg: str, **ctx):
        violations.append({"invariant": inv, "message": msg, **ctx})

    # monotonic time
    last = -1
    for r in sim.trace:
        if r.time < last:
            bad("monotonic_time", f"record {r.seq} at {r.time} fs precedes {last} fs", record=r.seq)
        last = r.time

    # event order: whenever an event executed, no event that was already pending had a smaller key
    executed = sorted((e for e in sim.scheduler.all_events() if e.exec_index is not None),
                      key=lambda e: e.exec_index)
    for a, b in zip(executed, executed[1:]):
        if b.key < a.key and b.scheduled_exec_count <= a.exec_index:
            bad("event_order", f"event {b.id} {b.key} was pending but executed after {a.id} {a.key}")
    if any(b.time < a.time for a, b in zip(executed, executed[1:])):
        bad("event_order", "global clock moved backwards between executed events")

    c = 299_792_458
    allow_ftl = bool(sim.project["physics"].get("allow_superluminal"))
    completes = {}
    for r in sim.trace:
        if r.kind == "transition.complete":
            for mid in r.data.get("sent", []):
                completes[mid] = r.time
    for m in sim.messages.values():
        if m.depart_time is None:
            continue
        if completes.get(m.id) != m.depart_time:
            bad("delivery_timing", f"message {m.id} departed at {m.depart_time} fs but its transition "
                                   f"completed at {completes.get(m.id)}", msg=m.id)
        if m.arrival_time is not None and m.arrival_time != m.depart_time + m.delay_fs:
            bad("delivery_timing", f"message {m.id} arrival {m.arrival_time} != depart + delay", msg=m.id)
        if not allow_ftl and m.arrival_time is not None:
            a = sim.nodes[m.src].position
            b = sim.nodes[m.dst].position
            dist = math.dist(a, b) if len(a) == len(b) else 0.0
            min_delay = tu.propagation_fs(dist, c)
            if m.arrival_time - m.depart_time < min_delay:  # exact: delays are rounded up
                bad("relativistic_bound", f"message {m.id} took {m.arrival_time - m.depart_time} fs over "
                                          f"{dist:.6g} m (< {min_delay} fs at c)", msg=m.id)
        if m.consumed_time is not None:
            if m.arrival_time is None or m.consumed_time < m.arrival_time:
                bad("causal_consumption", f"message {m.id} consumed at {m.consumed_time} before arrival", msg=m.id)
            if not (m.consumed_by or "").startswith(m.dst + ":"):
                bad("causal_consumption", f"message {m.id} consumed by {m.consumed_by}, not {m.dst}", msg=m.id)
        for p in m.causal_past:
            pm = sim.messages.get(p)
            if pm is None or pm.consumed_time is None or pm.dst != m.src or pm.consumed_time > m.send_time:
                bad("causal_past", f"message {m.id} lists {p} in its causal past inconsistently", msg=m.id)

    # FSM consistency and verdicts
    for nid, node in sim.nodes.items():
        aut = node.automaton
        tids = {t.id: t for t in aut.transitions}
        state = aut.initial
        finished_at = None
        verdicts = 0
        for r in sim.trace:
            if r.node != nid:
                continue
            if r.kind == "transition.begin":
                if finished_at is not None:
                    bad("terminal_quiet", f"{nid} began '{r.data['transition']}' after reaching a terminal state",
                        node=nid, record=r.seq)
                t = tids.get(r.data["transition"])
                if t is None:
                    bad("fsm_consistency", f"{nid} executed unknown transition {r.data['transition']}",
                        node=nid, record=r.seq)
                elif t.src != state or r.data["from"] != state:
                    bad("fsm_consistency", f"{nid} began '{t.id}' from '{r.data['from']}' while in '{state}'",
                        node=nid, record=r.seq)
            elif r.kind == "transition.complete":
                state = r.data["to"]
                if aut.is_terminal(state):
                    finished_at = r.time
            elif r.kind == "verdict":
                verdicts += 1
        if verdicts > 1:
            bad("single_verdict", f"{nid} recorded {verdicts} verdicts", node=nid)
        if state != node.state and node.error is None:
            bad("fsm_consistency", f"{nid} replayed state '{state}' differs from engine state '{node.state}'",
                node=nid)
    return {"ok": not violations, "checked": sorted(INVARIANTS), "descriptions": INVARIANTS,
            "violations": violations}

"""Verification decision and its explanation, derived from the engine state.

The overall decision combines the verifiers' individual verdicts with the
project's rule (``all`` | ``any`` | ``k_of_n``).  A verifier that halted, or
that has not (yet) recorded a verdict, counts as *not accepting*.  For each
verifier we reconstruct, from the trace, the transition that produced its
verdict, the trigger that fired it (a message or a timer), the guard results,
and the timing of the consumed messages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Tuple

from . import timeunits as tu

if TYPE_CHECKING:  # pragma: no cover
    from .engine import Simulation


def classify_reason(v: Dict[str, Any]) -> str:
    """Coarse category used for statistics: accepted | timeout | wrong_answer | error | undecided | rejected."""
    if v["status"] == "error":
        return "error"
    if v["verdict"] is None:
        return "undecided"
    if v["verdict"] == "accept":
        return "accepted"
    if v.get("trigger_type") == "timer":
        return "timeout"
    if v.get("trigger_type") == "receive":
        return "wrong_answer"
    return "rejected"


def _ns(fs: int) -> str:
    return f"{fs / tu.NS:.3f} ns"


def explain(sim: "Simulation", vid: str, entry: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """One plain sentence about a verifier's verdict, with references into the run."""
    node = sim.nodes[vid]
    if entry["status"] == "error":
        return f"Rejected: {vid} halted: {node.error}", [{"kind": "participant", "id": vid}]
    if entry["verdict"] is None:
        return f"{vid} has not decided yet (state '{node.state}').", [{"kind": "participant", "id": vid}]
    vd = node.verdict
    refs = [{"kind": "event", "seq": vd["begin_record"]},
            {"kind": "transition", "automaton": node.automaton.name, "id": vd["transition"]}]
    deadline = next((r.data["fire_fs"] for r in reversed(sim.trace)
                     if r.node == vid and r.kind == "timer.set" and r.data["name"] == "deadline"), None)
    consumed = [sim.messages[m] for m in entry.get("consumed", [])]
    if consumed:
        m = consumed[0]
        refs.insert(0, {"kind": "message", "id": m.id})
    if vd["outcome"] == "accept":
        early = f", {_ns(deadline - m.arrival_time)} before the deadline" if deadline is not None and consumed else ""
        value = f" {m.value!r}" if consumed else ""
        return f"Accepted: the correct answer{value} reached {vid} at {tu.fmt(vd['time_fs'], digits=3)}{early}.", refs
    if consumed:  # judged on a message: a guard rejected it
        failed = next((e for e in entry.get("evaluations") or [] if not e["result"]), None)
        if failed:
            refs.append({"kind": "transition", "automaton": node.automaton.name, "id": failed["transition"]})
            return f"Rejected: {vid} received the answer {m.value!r}, which failed the check `{failed['guard']}`.", refs
        return f"Rejected: {vid} received the answer {m.value!r}: {vd.get('reason') or 'no reason given'}.", refs
    late = sorted((m for m in sim.messages.values() if m.dst == vid and m.depart_time is not None
                   and m.status != "lost"), key=lambda m: m.depart_time + m.delay_fs)
    when = f" ({tu.fmt(deadline)})" if deadline is not None else ""
    if late and deadline is not None:
        m = late[0]
        refs.insert(0, {"kind": "message", "id": m.id})
        return f"Rejected: the answer reaches {vid} {_ns(m.depart_time + m.delay_fs - deadline)} after its deadline{when}.", refs
    return f"Rejected: no answer was sent to {vid} before its deadline{when}.", refs


def decide(sim: "Simulation") -> Dict[str, Any]:
    ver = sim.project["verification"]
    rule = ver.get("rule", "all")
    per: List[Dict[str, Any]] = []
    lines: List[str] = []
    for vid in sim.verifiers:
        node = sim.nodes.get(vid)
        if node is None:
            continue
        entry: Dict[str, Any] = {"id": vid, "state": node.state, "verdict": None, "reason": None,
                                 "decided_at_fs": None, "status": "pending", "observations": dict(node.observations)}
        if node.error:
            entry.update(status="error", reason=node.error)
            lines.append(f"{vid} halted with an error and does not accept: {node.error}")
        elif node.verdict:
            vd = node.verdict
            entry.update(status="decided", verdict=vd["outcome"], reason=vd.get("reason"),
                         decided_at_fs=vd["time_fs"], transition=vd.get("transition"))
            begin = sim.trace[vd["begin_record"]] if vd.get("begin_record") is not None else None
            facts = []
            if begin is not None:
                d = begin.data
                entry["trigger"] = d.get("trigger")
                entry["trigger_type"] = d.get("trigger_type")
                entry["guard"] = d.get("guard")
                entry["evaluations"] = d.get("evaluations")
                if d.get("trigger_type") == "timer":
                    facts.append(f"triggered by timer '{d.get('timer')}' expiring at {tu.fmt(begin.time)} "
                                 f"(local {tu.fmt(d.get('local_time_fs'))})")
                consumed = [sim.messages[m] for m in d.get("consumed", []) if m in sim.messages]
                entry["consumed"] = [m.id for m in consumed]
                for m in consumed:
                    facts.append(f"message {m.id} '{m.tag}'={m.value!r} from port {m.dst_port} arrived at "
                                 f"{tu.fmt(m.arrival_time)} (local {tu.fmt(node.local(m.arrival_time))}), "
                                 f"departed {m.src} at {tu.fmt(m.depart_time)}")
                failed = [e for e in (d.get("evaluations") or []) if not e["result"]]
                for e in failed:
                    facts.append(f"guard `{e['guard']}` of '{e['transition']}' was false")
                if isinstance(d.get("guard"), str):
                    facts.append(f"guard `{d.get('guard')}` was true")
            entry["facts"] = facts
            lines.append(f"{vid} {'accepted' if vd['outcome'] == 'accept' else 'rejected'} at "
                         f"{tu.fmt(vd['time_fs'])}: {vd.get('reason') or '(no reason)'}"
                         + (f" [{'; '.join(facts)}]" if facts else ""))
        else:
            entry["status"] = "undecided"
            lines.append(f"{vid} has not reached a verdict (state '{node.state}')")
        entry["category"] = classify_reason(entry)
        entry["sentence"], entry["refs"] = explain(sim, vid, entry)
        per.append(entry)
    accepts = sum(1 for e in per if e["verdict"] == "accept")
    n = len(per)
    if rule == "all":
        ok = n > 0 and accepts == n
        rule_text = f"all {n} verifiers must accept"
    elif rule == "any":
        ok = accepts >= 1
        rule_text = "at least one verifier must accept"
    else:
        k = int(ver.get("k", n))
        ok = accepts >= k
        rule_text = f"at least {k} of {n} verifiers must accept"
    complete = all(e["status"] in ("decided", "error") for e in per)
    outcome = "accept" if ok else ("reject" if complete or sim.stopped else "pending")
    summary = (f"Position claim {outcome.upper()}ED: {accepts}/{n} verifiers accepted; rule: {rule_text}."
               if outcome != "pending" else f"Undecided so far: {accepts}/{n} verifiers accepted; rule: {rule_text}.")
    return {"outcome": outcome, "rule": rule, "rule_text": rule_text, "accepts": accepts,
            "verifiers": per, "sentences": [e["sentence"] for e in per], "complete": complete, "summary": summary, "explanation": lines,
            "claim": sim.project.get("claim")}

"""Declarative finite-state automata for protocol participants.

An automaton specification (JSON) has::

    {
      "name": "...", "role": "verifier", "description": "...",
      "ports": ["prover"],
      "params": {"tolerance_ns": {"default": 0.5, "description": "..."}},
      "variables": {"x": 0},
      "initial": "idle",
      "states": [{"id": "idle", "kind": "initial|normal|terminal",
                  "outcome": "accept|reject|abort|done|null", "label": "...",
                  "description": "..."}],
      "transitions": [{
          "id": "t1", "from": "idle", "to": "wait", "label": "...",
          "trigger": {"type": "start"}
                   | {"type": "timer", "name": "deadline"}
                   | {"type": "receive", "tags": ["q", "theta"], "port": null}
                   | {"type": "auto"},
          "guard": "msg.value == x",          # expression, default true
          "duration_ns": null,                # expression; null -> participant processing time
          "actions": [{"op": "...", ...}]
      }]
    }

Transitions leaving a state are tried in list order; the first whose trigger
is satisfied and whose guard is true fires (deterministic priority).  See
docs/PROTOCOL_DSL.md for the action reference.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .expr import ENGINE_FUNCTIONS, PURE_FUNCTIONS, ExprError, functions_used, names_used, validate_syntax

TRIGGER_TYPES = {"start", "timer", "receive", "auto"}
STATE_KINDS = {"initial", "normal", "terminal"}
OUTCOMES = {None, "accept", "reject", "abort", "done", "error"}

# op -> (required fields, expression fields)
ACTIONS: Dict[str, Dict[str, Any]] = {
    "set": {"required": ["var", "expr"], "exprs": ["expr"],
            "doc": "Assign the value of an expression to a local variable."},
    "send": {"required": ["port", "tag", "value"], "exprs": ["value"],
             "doc": "Send a classical message on a port."},
    "send_qubit": {"required": ["port", "tag", "qubit"], "exprs": [],
                   "doc": "Send the qubit held in a memory slot through a quantum link."},
    "prepare": {"required": ["qubit", "state"], "exprs": [],
                "doc": "Prepare a fresh qubit in |0>,|1>,|+>,|->,|+i>,|-i> in a slot."},
    "prepare_bb84": {"required": ["qubit", "bit", "basis"], "exprs": ["bit", "basis"],
                     "doc": "Prepare H^basis|bit> (basis 0 = Z, 1 = X)."},
    "gate": {"required": ["gate", "qubits"], "exprs": ["angle"],
             "doc": "Apply a named gate to one or two slots (RX/RY/RZ take an angle)."},
    "measure": {"required": ["qubit", "result"], "exprs": ["basis", "angle"],
                "doc": "Projective measurement; basis Z/X/Y/angle or 0(Z)/1(X)."},
    "bell_measure": {"required": ["qubits", "results"], "exprs": [],
                     "doc": "Bell-state measurement (CNOT, H, Z-measure both)."},
    "discard": {"required": ["qubit"], "exprs": [], "doc": "Discard a qubit (partial trace)."},
    "timer": {"required": ["name"], "exprs": ["after_ns", "at_ns"],
              "doc": "Arm a named timer after a delay or at an absolute local time."},
    "cancel_timer": {"required": ["name"], "exprs": [], "doc": "Cancel a named timer."},
    "verdict": {"required": ["outcome"], "exprs": ["reason"],
                "doc": "Record this participant's accept/reject decision and reason."},
    "record": {"required": ["key", "value"], "exprs": ["value"],
               "doc": "Record a named observation (metric) for analysis."},
    "log": {"required": ["text"], "exprs": ["text"], "doc": "Append a message to the trace."},
}

BUILTIN_NAMES = {"msg", "msgs", "now", "pos", "claim_pos", "claim_travel_ns", "node_id",
                 "role", "speed_m_per_ns"}


@dataclass
class Issue:
    level: str  # "error" | "warning"
    path: str
    message: str

    def as_dict(self):
        return {"level": self.level, "path": self.path, "message": self.message}


@dataclass
class Transition:
    id: str
    src: str
    dst: str
    trigger: Dict[str, Any]
    guard: Any
    duration_ns: Any
    actions: List[Dict[str, Any]]
    label: str = ""
    index: int = 0

    @property
    def trigger_type(self) -> str:
        return self.trigger.get("type", "auto")

    def describe_trigger(self) -> str:
        t = self.trigger
        tt = t.get("type")
        if tt == "receive":
            tags = ", ".join(t.get("tags", []))
            port = f" on port {t['port']}" if t.get("port") else ""
            return f"receive [{tags}]{port}"
        if tt == "timer":
            return f"timer '{t.get('name')}' expires"
        return tt or "auto"


@dataclass
class Automaton:
    name: str
    spec: Dict[str, Any]
    initial: str
    states: Dict[str, Dict[str, Any]]
    transitions: List[Transition]
    outgoing: Dict[str, List[Transition]] = field(default_factory=dict)

    def is_terminal(self, state: str) -> bool:
        return self.states[state].get("kind") == "terminal"

    def outcome(self, state: str) -> Optional[str]:
        return self.states[state].get("outcome")


def compile_automaton(name: str, spec: Dict[str, Any]) -> Automaton:
    states = {s["id"]: s for s in spec.get("states", [])}
    trans = []
    for i, t in enumerate(spec.get("transitions", [])):
        trans.append(Transition(
            id=t.get("id") or f"t{i}", src=t["from"], dst=t["to"],
            trigger=dict(t.get("trigger") or {"type": "auto"}),
            guard=t.get("guard", True), duration_ns=t.get("duration_ns"),
            actions=list(t.get("actions", [])), label=t.get("label", ""), index=i))
    outgoing: Dict[str, List[Transition]] = {s: [] for s in states}
    for t in trans:
        outgoing.setdefault(t.src, []).append(t)
    return Automaton(name=name, spec=spec, initial=spec.get("initial"), states=states,
                     transitions=trans, outgoing=outgoing)


def _expr_fields(action: Dict[str, Any]) -> List[str]:
    meta = ACTIONS.get(action.get("op"), {})
    return [f for f in meta.get("exprs", []) if f in action]


def automaton_operations(spec: Dict[str, Any]) -> Dict[str, Set[str]]:
    """Static summary of operations used (for capability pre-checks)."""
    ops: Dict[str, Set[str]] = {"ops": set(), "gates": set(), "bases": set()}
    for t in spec.get("transitions", []):
        for a in t.get("actions", []):
            op = a.get("op")
            ops["ops"].add(op)
            if op == "gate":
                ops["gates"].add(str(a.get("gate", "")).upper())
            if op == "measure":
                b = a.get("basis", "Z")
                if isinstance(b, str) and b.strip("'\"") in ("Z", "X", "Y", "angle"):
                    ops["bases"].add(b.strip("'\""))
                elif b in (0, 1):
                    ops["bases"].add("Z" if b == 0 else "X")
                else:
                    ops["bases"].add("?dynamic")
    return ops


def validate_automaton(name: str, spec: Dict[str, Any], base: str = "") -> List[Issue]:
    p = base or f"automata.{name}"
    issues: List[Issue] = []
    err = lambda path, msg: issues.append(Issue("error", path, msg))  # noqa: E731
    warn = lambda path, msg: issues.append(Issue("warning", path, msg))  # noqa: E731

    if not isinstance(spec, dict):
        return [Issue("error", p, "automaton must be an object")]
    states = spec.get("states")
    if not isinstance(states, list) or not states:
        err(f"{p}.states", "automaton needs at least one state")
        return issues
    ids: Set[str] = set()
    for i, s in enumerate(states):
        sid = s.get("id") if isinstance(s, dict) else None
        if not sid or not isinstance(sid, str):
            err(f"{p}.states[{i}]", "state needs a string id")
            continue
        if sid in ids:
            err(f"{p}.states[{sid}]", "duplicate state id")
        ids.add(sid)
        kind = s.get("kind", "normal")
        if kind not in STATE_KINDS:
            err(f"{p}.states[{sid}].kind", f"unknown state kind {kind!r}")
        if s.get("outcome") not in OUTCOMES:
            err(f"{p}.states[{sid}].outcome", f"unknown outcome {s.get('outcome')!r}")
    init = spec.get("initial")
    if init not in ids:
        err(f"{p}.initial", f"initial state {init!r} is not defined")

    params = spec.get("params", {}) or {}
    variables = spec.get("variables", {}) or {}
    clash = set(params) & set(variables)
    for c in sorted(clash):
        err(f"{p}.variables.{c}", "variable name collides with a parameter")
    for nm in list(params) + list(variables):
        if nm in BUILTIN_NAMES:
            err(f"{p}", f"name {nm!r} is reserved")
    known_names = set(params) | set(variables) | BUILTIN_NAMES
    ports = set(spec.get("ports", []) or [])

    timers_set: Set[str] = set()
    timers_used: Set[str] = set()
    trans_ids: Set[str] = set()
    adj: Dict[str, Set[str]] = {s: set() for s in ids}
    assigned: Set[str] = set()
    for i, t in enumerate(spec.get("transitions", []) or []):
        tid = t.get("id") or f"t{i}"
        tp = f"{p}.transitions[{tid}]"
        if tid in trans_ids:
            err(tp, "duplicate transition id")
        trans_ids.add(tid)
        src, dst = t.get("from"), t.get("to")
        if src not in ids:
            err(f"{tp}.from", f"unknown state {src!r}")
        if dst not in ids:
            err(f"{tp}.to", f"unknown state {dst!r}")
        if src in ids and dst in ids:
            adj[src].add(dst)
            sdef = next(s for s in states if s.get("id") == src)
            if sdef.get("kind") == "terminal":
                warn(tp, f"transition leaves terminal state {src!r} and can never fire")
        trig = t.get("trigger") or {"type": "auto"}
        ttype = trig.get("type")
        if ttype not in TRIGGER_TYPES:
            err(f"{tp}.trigger", f"unknown trigger type {ttype!r}")
        if ttype == "timer":
            if not trig.get("name"):
                err(f"{tp}.trigger", "timer trigger needs a name")
            timers_used.add(trig.get("name"))
        if ttype == "receive":
            tags = trig.get("tags")
            if not tags or not isinstance(tags, list):
                err(f"{tp}.trigger", "receive trigger needs a non-empty list of tags")
            if trig.get("port") and ports and trig["port"] not in ports:
                warn(f"{tp}.trigger.port", f"port {trig['port']!r} not declared in ports")
        if ttype == "start" and src != init:
            warn(f"{tp}.trigger", "start trigger on a non-initial state can never fire")
        for fld in ("guard", "duration_ns"):
            e = t.get(fld)
            msg = validate_syntax(e)
            if msg:
                err(f"{tp}.{fld}", msg)
        for j, a in enumerate(t.get("actions", []) or []):
            ap = f"{tp}.actions[{j}]"
            op = a.get("op") if isinstance(a, dict) else None
            if op not in ACTIONS:
                err(ap, f"unknown action op {op!r}")
                continue
            for req in ACTIONS[op]["required"]:
                if req not in a:
                    err(ap, f"action '{op}' requires field '{req}'")
            for fld in _expr_fields(a):
                msg = validate_syntax(a[fld])
                if msg:
                    err(f"{ap}.{fld}", msg)
            if op == "timer":
                if ("after_ns" in a) == ("at_ns" in a):
                    err(ap, "timer needs exactly one of after_ns / at_ns")
                timers_set.add(a.get("name"))
            if op in ("send", "send_qubit") and ports and a.get("port") not in ports:
                warn(f"{ap}.port", f"port {a.get('port')!r} not declared in ports")
            if op == "set":
                assigned.add(a.get("var"))
            if op == "measure":
                assigned.add(a.get("result"))
            if op == "bell_measure":
                assigned.update(a.get("results") or [])
                if len(a.get("qubits") or []) != 2 or len(a.get("results") or []) != 2:
                    err(ap, "bell_measure needs exactly two qubits and two results")
            if op == "verdict" and a.get("outcome") not in ("accept", "reject"):
                err(f"{ap}.outcome", "verdict outcome must be 'accept' or 'reject'")
    # name resolution (best effort: msg fields checked at run time)
    names_ok = known_names | assigned
    for i, t in enumerate(spec.get("transitions", []) or []):
        tid = t.get("id") or f"t{i}"
        exprs = [("guard", t.get("guard"))] + [("duration_ns", t.get("duration_ns"))]
        for j, a in enumerate(t.get("actions", []) or []):
            if isinstance(a, dict):
                exprs += [(f"actions[{j}].{f}", a[f]) for f in _expr_fields(a)]
        for fld, e in exprs:
            if isinstance(e, str) and validate_syntax(e) is None:
                unknown = names_used(e) - names_ok - {"pi", "true", "false", "null",
                                                       "True", "False", "None"}
                for u in sorted(unknown):
                    err(f"{p}.transitions[{tid}].{fld}",
                        f"unknown name {u!r} (not a parameter, variable or builtin)")
                for fn in sorted(functions_used(e) - set(PURE_FUNCTIONS) - set(ENGINE_FUNCTIONS)):
                    err(f"{p}.transitions[{tid}].{fld}", f"unknown function {fn!r}")
    for tn in sorted(timers_used - timers_set):
        warn(f"{p}", f"timer {tn!r} is used as a trigger but never armed")
    # reachability
    if init in ids:
        seen = {init}
        dq = deque([init])
        while dq:
            s = dq.popleft()
            for d in adj.get(s, ()):
                if d not in seen:
                    seen.add(d)
                    dq.append(d)
        for s in sorted(ids - seen):
            warn(f"{p}.states[{s}]", "state is unreachable from the initial state")
        for s in states:
            sid = s.get("id")
            if sid in ids and s.get("kind") != "terminal" and not adj.get(sid):
                warn(f"{p}.states[{sid}]", "non-terminal state has no outgoing transitions (deadlock)")
    if not any(s.get("kind") == "terminal" for s in states):
        warn(p, "automaton has no terminal state")
    return issues

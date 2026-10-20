"""The simulation engine: the single source of truth.

:class:`Simulation` compiles a project document into runtime participants,
links and resources, then executes it through the discrete-event
:class:`~qpvsim.kernel.Scheduler`.  Everything a user can see (states,
messages, timestamps, decisions) is produced here and recorded in an
append-only trace; the UI, console and experiment runner only read it.

Execution model (docs/SEMANTICS.md):

1. A participant reacts to *stimuli*: its start event, message deliveries and
   timer expiries.  Delivered messages wait in its mailbox; expired timers wait
   in a set, until a transition consumes them.
2. On each stimulus, if the participant is idle, the transitions leaving its
   current state are tried in declaration order.  The first one whose trigger
   is satisfied and whose guard is true **begins** at the current time ``t``:
   the source state is exited, actions execute in order (variables, quantum
   operations and measurements, timers take effect at ``t``), and outgoing
   messages and the verdict are buffered.
3. The transition **completes** at ``t + d`` where ``d`` is its duration
   (participant processing time unless overridden; never below the capability
   minimum).  At completion the target state is entered, buffered messages
   depart and the verdict is recorded.  Stimuli arriving while busy are queued.
4. A message departing at ``t_d`` over a link of length ``L`` and speed ``v``
   arrives at ``t_d + round(L / v) + latency (+ jitter)``.
"""

from __future__ import annotations

import copy
import math
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from . import timeunits as tu
from .kernel import Event, LocalClock, Scheduler
from .protocol.automaton import Automaton, Transition, compile_automaton
from .protocol.capabilities import Capabilities, CapabilityViolation, make_capabilities
from .protocol.expr import ExprError, Record, evaluate
from .protocol.project import (ProjectError, errors, link_length_m, normalize,
                               validate_project, verifier_ids)
from .quantum import QuantumBackend, QuantumError, make_backend
from .quantum import base as qb

ENGINE_VERSION = "0.1.0"
MAX_ZERO_TIME_FIRINGS = 10_000


class ProtocolError(RuntimeError):
    pass


# ---------------------------------------------------------------- records
@dataclass
class TraceRecord:
    seq: int
    time: int
    kind: str
    node: Optional[str]
    event: Optional[int]
    data: Dict[str, Any]
    explain: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"seq": self.seq, "time_fs": self.time, "time_ns": self.time / tu.NS,
                "kind": self.kind, "node": self.node, "event": self.event,
                "data": _jsonable(self.data), "explain": self.explain}


@dataclass
class Message:
    id: int
    kind: str  # classical | quantum
    tag: str
    value: Any  # classical payload, or None for quantum
    qubit: Optional[int]
    src: str
    src_port: str
    dst: str
    dst_port: str
    link: str
    sent_by_transition: str
    send_time: int  # transition begin (when the action executed)
    depart_time: Optional[int] = None
    arrival_time: Optional[int] = None
    delay_fs: Optional[int] = None
    distance_m: float = 0.0
    speed_mps: float = 0.0
    latency_fs: int = 0
    jitter_fs: int = 0
    status: str = "pending"  # pending|in_flight|delivered|consumed|lost|refused|unconsumed
    consumed_time: Optional[int] = None
    consumed_by: Optional[str] = None
    causal_past: List[int] = field(default_factory=list)
    send_event: Optional[int] = None
    deliver_event: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "tag": self.tag,
            "value": _jsonable(self.value), "src": self.src, "src_port": self.src_port,
            "dst": self.dst, "dst_port": self.dst_port, "link": self.link,
            "sent_by_transition": self.sent_by_transition,
            "send_time_fs": self.send_time, "depart_time_fs": self.depart_time,
            "arrival_time_fs": self.arrival_time, "delay_fs": self.delay_fs,
            "distance_m": self.distance_m, "speed_mps": self.speed_mps,
            "latency_fs": self.latency_fs, "jitter_fs": self.jitter_fs,
            "status": self.status, "consumed_time_fs": self.consumed_time,
            "consumed_by": self.consumed_by, "causal_past": list(self.causal_past),
            "send_event": self.send_event, "deliver_event": self.deliver_event,
        }


@dataclass
class QubitSlot:
    qid: int
    stored_at: int
    last_update: int
    origin: str


@dataclass
class OutLink:
    link: Dict[str, Any]
    dst: str
    dst_port: str
    distance_m: float
    speed_mps: float
    base_delay_fs: int
    latency_fs: int


@dataclass
class Busy:
    transition: Transition
    begin: int
    complete: int
    event_id: int
    sends: List[Message]
    verdict: Optional[Dict[str, Any]]
    record_seq: int


class Node:
    """Runtime state of one participant."""

    def __init__(self, cfg: Dict[str, Any], automaton: Automaton, caps: Capabilities,
                 rng: np.random.Generator):
        self.cfg = cfg
        self.id: str = cfg["id"]
        self.role: str = cfg["role"]
        self.automaton = automaton
        self.caps = caps
        self.rng = rng
        self.position = [float(x) for x in cfg["position"]]
        self.clock = LocalClock.from_config(cfg.get("clock"))
        self.processing_fs = tu.ns(cfg.get("processing_ns", 0))
        self.noise = dict(cfg.get("noise") or {})
        spec = automaton.spec
        self.params: Dict[str, Any] = {}
        for k, d in (spec.get("params") or {}).items():
            self.params[k] = d.get("default") if isinstance(d, dict) else d
        self.params.update(copy.deepcopy(cfg.get("params") or {}))
        self.vars: Dict[str, Any] = copy.deepcopy(spec.get("variables") or {})
        self.state: str = automaton.initial
        self.state_entered: int = 0
        self.started = False
        self.pending_start = False
        self.mailbox: List[Message] = []
        self.expired_timers: List[str] = []
        self.timers: Dict[str, int] = {}  # name -> event id
        self.timer_info: Dict[str, Dict[str, Any]] = {}
        self.busy: Optional[Busy] = None
        self.qubits: Dict[str, QubitSlot] = {}
        self.consumed: List[int] = []
        self.verdict: Optional[Dict[str, Any]] = None
        self.observations: Dict[str, Any] = {}
        self.finished = False
        self.outcome: Optional[str] = None
        self.error: Optional[str] = None
        self.history: List[Dict[str, Any]] = []
        self.state_log: List[Dict[str, Any]] = [{"state": self.state, "entered_fs": 0, "exited_fs": None}]
        self.zero_time_firings = 0
        self.last_fire_time = -1

    def local(self, t: int) -> int:
        return self.clock.local(t)


def stream_seed(seed: int, name: str) -> np.random.SeedSequence:
    """Independent, name-addressed random stream (stable across project edits)."""
    return np.random.SeedSequence([int(seed), zlib.crc32(name.encode("utf-8"))])


def make_rng(seed: int, name: str) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(stream_seed(seed, name)))


def _jsonable(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return repr(v)


# ================================================================ Simulation
class Simulation:
    """A single, deterministic execution of a project."""

    def __init__(self, project: Dict[str, Any], seed: Optional[int] = None, validate: bool = True,
                 copy_project: bool = True):
        """``copy_project=False`` is for batch runners that pass an already-normalised
        document they promise not to mutate; the engine itself never mutates it."""
        if copy_project:
            project = normalize(copy.deepcopy(project))
        self.issues = validate_project(project) if validate else []
        if errors(self.issues):
            raise ProjectError(errors(self.issues))
        self.project = project
        self.seed: int = int(project["simulation"]["seed"] if seed is None else seed)
        simcfg = project["simulation"]
        self.max_time = tu.ns(simcfg["max_time_ns"])
        self.max_events = int(simcfg["max_events"])
        self.stop_when = simcfg["stop_when"]
        self.speed_mps = project["physics"]["signal_speed_mps"]
        self.claim_pos = [float(x) for x in project["claim"]["position"]]
        self.scheduler = Scheduler(simcfg.get("priorities"))
        self.backend: QuantumBackend = make_backend(simcfg["backend"], make_rng(self.seed, "quantum"))
        self.trace: List[TraceRecord] = []
        self.messages: Dict[int, Message] = {}
        self._next_msg = 1
        self.nodes: Dict[str, Node] = {}
        self.out_links: Dict[Tuple[str, str, str], OutLink] = {}
        self.link_rngs: Dict[str, np.random.Generator] = {}
        self.stopped = False
        self.stop_reason: Optional[str] = None
        self.verifiers = verifier_ids(project)
        self.counters = {"classical_sent": 0, "quantum_sent": 0, "lost": 0, "transitions": 0,
                         "quantum_ops": 0, "measurements": 0, "capability_violations": 0,
                         "protocol_errors": 0}
        self._listeners: List[Callable[[TraceRecord], None]] = []
        self._build()

    # ------------------------------------------------------------ build
    def _build(self) -> None:
        p = self.project
        for cfg in p["participants"]:
            spec = p["automata"][cfg["automaton"]]
            aut = compile_automaton(cfg["automaton"], spec)
            caps = make_capabilities(cfg.get("capabilities"))
            node = Node(cfg, aut, caps, make_rng(self.seed, f"node:{cfg['id']}"))
            self.nodes[node.id] = node
        for link in p["links"]:
            length = link_length_m(p, link)
            speed = link.get("speed_mps") or self.speed_mps
            base = tu.propagation_fs(length, speed)
            lat = tu.ns(link.get("latency_ns", 0))
            a, b = link["a"], link["b"]
            self.out_links[(a["node"], a["port"], link["kind"])] = OutLink(
                link, b["node"], b["port"], length, speed, base, lat)
            if not link.get("directed"):
                self.out_links[(b["node"], b["port"], link["kind"])] = OutLink(
                    link, a["node"], a["port"], length, speed, base, lat)
            self.link_rngs[link["id"]] = make_rng(self.seed, f"link:{link['id']}")
        self._record(0, "sim.init", None, {
            "seed": self.seed, "backend": self.backend.info.name,
            "engine_version": ENGINE_VERSION,
            "participants": list(self.nodes), "links": [l["id"] for l in p["links"]],
        }, f"Simulation initialised with seed {self.seed} and backend '{self.backend.info.name}'.")
        self._setup_resources()
        for node in self.nodes.values():
            t0 = tu.ns(node.cfg.get("start_ns", 0))
            self.scheduler.schedule(t0, "node.start", node=node.id, label=f"start {node.id}")

    def _setup_resources(self) -> None:
        rrng = make_rng(self.seed, "resources")
        for r in self.project["resources"]:
            if r["type"] == "shared_random":
                values = {}
                for k, e in (r.get("vars") or {}).items():
                    values[k] = evaluate(e, {}, self._random_functions(rrng))
                for holder in r.get("holders") or []:
                    self.nodes[holder].vars.update(copy.deepcopy(values))
                self._record(0, "resource.shared_random", None,
                             {"resource": r.get("id"), "holders": r.get("holders"), "values": values},
                             "Pre-shared classical randomness distributed out-of-band before t=0 "
                             "(trust assumption: verifiers share private randomness).")
            elif r["type"] == "epr":
                h0, h1 = r["holders"]
                for h in (h0, h1):
                    n = self.nodes[h["node"]]
                    if not n.caps.entanglement:
                        raise CapabilityViolation(n.id, "entanglement",
                                                  "pre-shared entanglement forbidden by profile")
                q0, q1 = self.backend.create_entangled(qb.BELL[r.get("state", "phi+")], 2)
                wp = float(r.get("werner_p", 0) or 0)
                if wp > 0:
                    self.backend.apply_channel([q1], qb.depolarizing_kraus(wp))
                for h, q in ((h0, q0), (h1, q1)):
                    n = self.nodes[h["node"]]
                    self._store_qubit(n, h["slot"], q, 0, origin=f"resource {r.get('id')}")
                self._record(0, "resource.epr", None,
                             {"resource": r.get("id"), "holders": r["holders"], "state": r.get("state", "phi+"),
                              "werner_p": wp},
                             f"Pre-shared EPR pair ({r.get('state', 'phi+')}) distributed before t=0 to "
                             f"{h0['node']}.{h0['slot']} and {h1['node']}.{h1['slot']}.")

    # ------------------------------------------------------------ tracing
    def _record(self, time: int, kind: str, node: Optional[str], data: Dict[str, Any],
                explain: str = "") -> TraceRecord:
        ev = self.scheduler.current
        rec = TraceRecord(len(self.trace), time, kind, node, ev.id if ev else None, data, explain)
        self.trace.append(rec)
        for fn in self._listeners:
            fn(rec)
        return rec

    def add_listener(self, fn: Callable[[TraceRecord], None]) -> None:
        self._listeners.append(fn)

    # ------------------------------------------------------------ control
    @property
    def now(self) -> int:
        return self.scheduler.now

    @property
    def done(self) -> bool:
        return self.stopped

    def step(self) -> Optional[Event]:
        """Execute exactly one scheduled event.  Returns it, or None if finished."""
        if self.stopped:
            return None
        nxt = self.scheduler.peek()
        if nxt is None:
            self._stop("quiescent: no pending events")
            return None
        if nxt.time > self.max_time:
            self._stop(f"time limit {tu.fmt(self.max_time)} reached")
            return None
        if self.scheduler.executed_count >= self.max_events:
            self._stop(f"event limit {self.max_events} reached")
            return None
        ev = self.scheduler.pop()
        try:
            self._dispatch(ev)
        finally:
            self.scheduler.finish_current()
        self._check_stop()
        return ev

    def run(self, until_fs: Optional[int] = None, max_steps: Optional[int] = None) -> "Simulation":
        """Run until stopped, or until the next event lies beyond ``until_fs``."""
        steps = 0
        while not self.stopped:
            if max_steps is not None and steps >= max_steps:
                break
            nxt = self.scheduler.peek()
            if until_fs is not None and (nxt is None or nxt.time > until_fs):
                if nxt is None:
                    self.step()
                else:
                    self.scheduler.now = max(self.scheduler.now, until_fs)
                break
            self.step()
            steps += 1
        return self

    def advance(self, dt_fs: int) -> "Simulation":
        return self.run(until_fs=self.now + dt_fs)

    def _check_stop(self) -> None:
        if self.stopped:
            return
        if self.stop_when == "verifiers_decided" and self.verifiers and all(
                self.nodes[v].finished for v in self.verifiers if v in self.nodes):
            self._stop("all verifiers reached a terminal state")
        elif self.scheduler.peek() is None:
            self._stop("quiescent: no pending events")

    def _stop(self, reason: str) -> None:
        if self.stopped:
            return
        self.stopped = True
        self.stop_reason = reason
        for m in self.messages.values():
            if m.status == "delivered":
                m.status = "unconsumed"
        self._record(self.now, "sim.stop", None, {"reason": reason,
                                                  "pending_events": len(self.scheduler)},
                     f"Simulation stopped: {reason}.")

    # ------------------------------------------------------------ dispatch
    def _dispatch(self, ev: Event) -> None:
        handler = {
            "node.start": self._on_start,
            "msg.deliver": self._on_deliver,
            "msg.loss": self._on_loss,
            "transition.complete": self._on_complete,
            "timer.fire": self._on_timer,
        }.get(ev.kind)
        if handler is None:
            raise RuntimeError(f"no handler for event kind {ev.kind}")
        handler(ev)

    def _on_start(self, ev: Event) -> None:
        node = self.nodes[ev.node]
        node.started = True
        node.pending_start = True
        self._record(ev.time, "node.start", node.id,
                     {"state": node.state, "local_time_fs": node.local(ev.time)},
                     f"{node.id} starts in state '{node.state}' (local clock "
                     f"{tu.fmt(node.local(ev.time))}; {node.clock.describe()}).")
        self._evaluate(node)

    def _on_deliver(self, ev: Event) -> None:
        msg = self.messages[ev.payload["msg"]]
        node = self.nodes[msg.dst]
        msg.arrival_time = ev.time
        explain = (f"Arrival {tu.fmt(ev.time)} = departure {tu.fmt(msg.depart_time)} + propagation "
                   f"{tu.fmt(msg.delay_fs - msg.latency_fs - msg.jitter_fs)} "
                   f"({msg.distance_m:.6g} m at {msg.speed_mps:.9g} m/s)")
        if msg.latency_fs:
            explain += f" + fixed latency {tu.fmt(msg.latency_fs)}"
        if msg.jitter_fs:
            explain += f" + jitter {tu.fmt(msg.jitter_fs)}"
        explain += f" over link {msg.link}."
        if msg.kind == "quantum":
            if not node.caps.quantum_receive or (node.caps.max_qubits is not None
                                                  and len(node.qubits) >= node.caps.max_qubits):
                why = ("cannot receive qubits" if not node.caps.quantum_receive
                       else f"quantum memory full ({node.caps.max_qubits} qubits)")
                self.backend.discard(msg.qubit)
                msg.status = "refused"
                self._record(ev.time, "msg.refused", node.id, {"msg": msg.id, "reason": why},
                             explain + f" Qubit lost at {node.id}: {why}.")
                return
            self._apply_link_noise(msg)
            slot = msg.tag
            if slot in node.qubits:
                self.backend.discard(node.qubits[slot].qid)
            self._store_qubit(node, slot, msg.qubit, ev.time, origin=f"msg {msg.id}")
        msg.status = "delivered"
        node.mailbox.append(msg)
        self._record(ev.time, "msg.deliver", node.id, {
            "msg": msg.id, "kind": msg.kind, "tag": msg.tag, "value": msg.value,
            "from": msg.src, "port": msg.dst_port, "link": msg.link,
            "depart_fs": msg.depart_time, "delay_fs": msg.delay_fs,
            "local_time_fs": node.local(ev.time)}, explain)
        self._evaluate(node)

    def _on_loss(self, ev: Event) -> None:
        msg = self.messages[ev.payload["msg"]]
        msg.status = "lost"
        msg.arrival_time = None
        self.counters["lost"] += 1
        self._record(ev.time, "msg.loss", msg.dst, {"msg": msg.id, "kind": msg.kind, "tag": msg.tag,
                                                   "link": msg.link, "p_survive": ev.payload.get("p_survive")},
                     f"{msg.kind.capitalize()} message {msg.id} ('{msg.tag}') was lost on link {msg.link} "
                     f"(survival probability {ev.payload.get('p_survive'):.6g}); it would have arrived now.")

    def _on_timer(self, ev: Event) -> None:
        node = self.nodes[ev.node]
        name = ev.payload["name"]
        if node.timers.get(name) != ev.id:
            return  # superseded (should have been cancelled)
        del node.timers[name]
        info = node.timer_info.pop(name, {})
        node.expired_timers.append(name)
        self._record(ev.time, "timer.fire", node.id,
                     {"name": name, "local_time_fs": node.local(ev.time), **info},
                     f"Timer '{name}' of {node.id} expired at global {tu.fmt(ev.time)} "
                     f"(local {tu.fmt(node.local(ev.time))}); {info.get('how', '')}")
        self._evaluate(node)

    # ------------------------------------------------------------ FSM core
    def _random_functions(self, rng: np.random.Generator) -> Dict[str, Callable]:
        return {
            "rand_bit": lambda: int(rng.integers(0, 2)),
            "rand_int": lambda lo, hi: int(rng.integers(int(lo), int(hi) + 1)),
            "rand_uniform": lambda: float(rng.random()),
            "rand_choice": lambda seq: seq[int(rng.integers(0, len(seq)))],
        }

    def _functions(self, node: Node) -> Dict[str, Callable]:
        f = self._random_functions(node.rng)
        speed_m_per_ns = self.speed_mps / 1e9
        f["travel_ns"] = lambda d: float(d) / speed_m_per_ns
        # snap a float-ns value onto the engine's femtosecond grid, so comparisons
        # with ``now``/``msg.time`` agree exactly with integer-fs timers
        f["fs_round"] = lambda x: tu.ns(x) / tu.NS
        return f

    def _msg_record(self, node: Node, m: Message) -> Record:
        return Record(id=m.id, tag=m.tag, kind=m.kind, port=m.dst_port,
                      value=(m.tag if m.kind == "quantum" else m.value),
                      time=node.local(m.arrival_time) / tu.NS)

    def _context(self, node: Node, msgs: List[Message], t: int) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {}
        ctx.update(node.params)
        ctx.update(node.vars)
        ctx["now"] = node.local(t) / tu.NS
        ctx["pos"] = list(node.position)
        ctx["claim_pos"] = list(self.claim_pos)
        ctx["claim_travel_ns"] = math.dist(node.position, self.claim_pos) / (self.speed_mps / 1e9) \
            if len(node.position) == len(self.claim_pos) else float("nan")
        ctx["node_id"] = node.id
        ctx["role"] = node.role
        ctx["speed_m_per_ns"] = self.speed_mps / 1e9
        recs = {m.tag: self._msg_record(node, m) for m in msgs}
        ctx["msgs"] = Record(recs)
        ctx["msg"] = self._msg_record(node, msgs[0]) if msgs else None
        return ctx

    def _match_trigger(self, node: Node, tr: Transition) -> Tuple[bool, List[Message], Optional[str]]:
        trig = tr.trigger
        tt = trig.get("type", "auto")
        if tt == "start":
            return node.pending_start, [], None
        if tt == "timer":
            return trig.get("name") in node.expired_timers, [], trig.get("name")
        if tt == "auto":
            return True, [], None
        if tt == "receive":
            chosen: List[Message] = []
            port = trig.get("port")
            for tag in trig.get("tags", []):
                m = next((m for m in node.mailbox if m.tag == tag and m not in chosen
                          and (port is None or m.dst_port == port)), None)
                if m is None:
                    return False, [], None
                chosen.append(m)
            return True, chosen, None
        return False, [], None

    def _evaluate(self, node: Node) -> None:
        if node.busy or node.finished or not node.started:
            return
        t = self.now
        evaluations = []
        for tr in node.automaton.outgoing.get(node.state, []):
            ok, msgs, timer = self._match_trigger(node, tr)
            if not ok:
                continue
            ctx = self._context(node, msgs, t)
            try:
                g = evaluate(tr.guard if tr.guard is not None else True, ctx, self._functions(node))
            except ExprError as exc:
                self._halt(node, "protocol.error", f"guard of transition '{tr.id}': {exc}")
                return
            evaluations.append({"transition": tr.id, "trigger": tr.describe_trigger(),
                                "guard": tr.guard, "result": bool(g)})
            if g:
                self._begin(node, tr, msgs, timer, evaluations, ctx)
                return
        if evaluations:
            self._record(t, "guards.rejected", node.id, {"state": node.state, "evaluations": evaluations},
                         f"{node.id}: triggers matched in state '{node.state}' but every guard was false; "
                         f"inputs stay queued.")
        node.pending_start = False

    def _begin(self, node: Node, tr: Transition, msgs: List[Message], timer: Optional[str],
               evaluations: List[Dict[str, Any]], ctx: Dict[str, Any]) -> None:
        t = self.now
        if t == node.last_fire_time:
            node.zero_time_firings += 1
            if node.zero_time_firings > MAX_ZERO_TIME_FIRINGS:
                self._halt(node, "protocol.error", "too many transitions at one instant (livelock)")
                return
        else:
            node.zero_time_firings = 0
            node.last_fire_time = t
        # consume trigger
        if tr.trigger_type == "start":
            node.pending_start = False
        if timer is not None:
            node.expired_timers.remove(timer)
        for m in msgs:
            node.mailbox.remove(m)
            m.status = "consumed"
            m.consumed_time = t
            m.consumed_by = f"{node.id}:{tr.id}"
            node.consumed.append(m.id)
        if tr.trigger_type != "start":
            node.pending_start = False
        self.counters["transitions"] += 1
        node.state_log[-1]["exited_fs"] = t
        begin_rec = self._record(t, "transition.begin", node.id, {
            "transition": tr.id, "label": tr.label, "from": tr.src, "to": tr.dst,
            "trigger": tr.describe_trigger(), "trigger_type": tr.trigger_type,
            "consumed": [m.id for m in msgs], "timer": timer,
            "guard": tr.guard, "evaluations": evaluations,
            "local_time_fs": node.local(t)}, "")
        sends: List[Message] = []
        verdict = None
        actions_log: List[Dict[str, Any]] = []
        try:
            for a in tr.actions:
                out = self._exec_action(node, tr, a, ctx, t, sends)
                actions_log.append(out)
                if a["op"] == "verdict":
                    verdict = out["verdict"]
            dur_expr = tr.duration_ns
            if dur_expr is None:
                dur = node.processing_fs
                dur_src = f"participant processing time {tu.fmt(node.processing_fs)}"
            else:
                val = evaluate(dur_expr, ctx, self._functions(node))
                if not isinstance(val, (int, float)) or val < 0:
                    raise ProtocolError(f"duration_ns evaluated to {val!r}")
                dur = tu.ns(val)
                dur_src = f"transition duration expression `{dur_expr}` = {tu.fmt(dur)}"
            min_fs = tu.ns(node.caps.min_processing_ns)
            if dur < min_fs:
                dur_src += f", raised to capability minimum {tu.fmt(min_fs)}"
                dur = min_fs
        except CapabilityViolation as exc:
            begin_rec.data["actions"] = actions_log
            self._halt(node, "capability.violation", str(exc), capability=exc.capability)
            for m in sends:
                if m.qubit is not None and self.backend.exists(m.qubit):
                    self.backend.discard(m.qubit)
            return
        except (ExprError, ProtocolError, QuantumError) as exc:
            begin_rec.data["actions"] = actions_log
            self._halt(node, "protocol.error", f"transition '{tr.id}': {exc}")
            return
        begin_rec.data["actions"] = actions_log
        begin_rec.data["duration_fs"] = dur
        complete = t + dur
        begin_rec.explain = (
            f"{node.id} leaves '{tr.src}' via '{tr.id}' because {tr.describe_trigger()}"
            + (f" and guard `{tr.guard}` is true" if isinstance(tr.guard, str) else "")
            + f". Completion at {tu.fmt(complete)} = begin {tu.fmt(t)} + {dur_src}.")
        ev = self.scheduler.schedule(complete, "transition.complete", node=node.id,
                                     payload={"transition": tr.id}, label=f"{node.id}:{tr.id}")
        node.busy = Busy(tr, t, complete, ev.id, sends, verdict, begin_rec.seq)
        for m in sends:
            m.send_event = ev.id

    def _on_complete(self, ev: Event) -> None:
        node = self.nodes[ev.node]
        b = node.busy
        if b is None:
            return
        node.busy = None
        tr = b.transition
        t = ev.time
        node.state = tr.dst
        node.state_entered = t
        node.state_log.append({"state": tr.dst, "entered_fs": t, "exited_fs": None})
        hist = {"transition": tr.id, "from": tr.src, "to": tr.dst, "begin_fs": b.begin,
                "complete_fs": t, "begin_record": b.record_seq}
        node.history.append(hist)
        self._record(t, "transition.complete", node.id, {
            "transition": tr.id, "from": tr.src, "to": tr.dst, "begin_fs": b.begin,
            "begin_record": b.record_seq, "sent": [m.id for m in b.sends],
            "local_time_fs": node.local(t)},
            f"{node.id} enters '{tr.dst}' at {tu.fmt(t)} (transition '{tr.id}' began {tu.fmt(b.begin)}).")
        for m in b.sends:
            self._transmit(node, m, t)
        if b.verdict is not None:
            node.verdict = {**b.verdict, "time_fs": t, "transition": tr.id, "begin_record": b.record_seq}
            self._record(t, "verdict", node.id, node.verdict,
                         f"{node.id} records verdict '{b.verdict['outcome']}' at {tu.fmt(t)}"
                         f" (local {tu.fmt(node.local(t))}): {b.verdict.get('reason') or 'no reason given'}.")
        if node.automaton.is_terminal(tr.dst):
            node.finished = True
            node.outcome = node.automaton.outcome(tr.dst)
            for name, eid in list(node.timers.items()):
                self.scheduler.cancel(eid)
                self._record(t, "timer.cancel", node.id, {"name": name, "why": "terminal state"},
                             f"Timer '{name}' cancelled: {node.id} reached a terminal state.")
            node.timers.clear()
            self._record(t, "node.finish", node.id, {"state": tr.dst, "outcome": node.outcome},
                         f"{node.id} reached terminal state '{tr.dst}' (outcome: {node.outcome}).")
            return
        self._evaluate(node)

    def _halt(self, node: Node, kind: str, message: str, **extra) -> None:
        node.error = message
        node.finished = True
        node.outcome = "error"
        node.busy = None
        if kind == "capability.violation":
            self.counters["capability_violations"] += 1
        else:
            self.counters["protocol_errors"] += 1
        for name, eid in list(node.timers.items()):
            self.scheduler.cancel(eid)
        node.timers.clear()
        self._record(self.now, kind, node.id, {"message": message, "state": node.state, **extra},
                     f"{node.id} halted in state '{node.state}': {message}")

    # ------------------------------------------------------------ messaging
    def _new_message(self, node: Node, tr: Transition, kind: str, port: str, tag: str,
                     value: Any, qubit: Optional[int], t: int) -> Message:
        ol = self.out_links.get((node.id, port, kind))
        if ol is None:
            raise ProtocolError(f"no {kind} link on port '{port}' of {node.id}")
        m = Message(id=self._next_msg, kind=kind, tag=str(tag), value=value, qubit=qubit,
                    src=node.id, src_port=port, dst=ol.dst, dst_port=ol.dst_port,
                    link=ol.link["id"], sent_by_transition=tr.id, send_time=t,
                    causal_past=list(node.consumed))
        self._next_msg += 1
        self.messages[m.id] = m
        return m

    def _transmit(self, node: Node, m: Message, t: int) -> None:
        ol = self.out_links[(node.id, m.src_port, m.kind)]
        rng = self.link_rngs[ol.link["id"]]
        jitter = 0
        if ol.link.get("jitter_ns"):
            jitter = tu.ns(repr(float(rng.uniform(0, float(ol.link["jitter_ns"])))))
        m.depart_time = t
        m.distance_m = ol.distance_m
        m.speed_mps = ol.speed_mps
        m.latency_fs = ol.latency_fs
        m.jitter_fs = jitter
        m.delay_fs = ol.base_delay_fs + ol.latency_fs + jitter
        m.status = "in_flight"
        arrival = t + m.delay_fs
        p_survive = (1 - float(ol.link.get("loss_prob", 0))) * 10 ** (
            -float(ol.link.get("attenuation_db_per_km", 0)) * ol.distance_m / 1000 / 10)
        lost = p_survive < 1 and rng.random() >= p_survive
        self.counters["quantum_sent" if m.kind == "quantum" else "classical_sent"] += 1
        self._record(t, "msg.send", node.id, {
            "msg": m.id, "kind": m.kind, "tag": m.tag, "value": m.value, "to": m.dst,
            "port": m.src_port, "link": m.link, "arrival_fs": arrival,
            "causal_past": m.causal_past, "local_time_fs": node.local(t)},
            f"{node.id} transmits {m.kind} '{m.tag}' on port '{m.src_port}' at {tu.fmt(t)}; "
            f"scheduled arrival at {m.dst} {tu.fmt(arrival)} (delay {tu.fmt(m.delay_fs)}).")
        if lost:
            if m.qubit is not None:
                self.backend.discard(m.qubit)
            ev = self.scheduler.schedule(arrival, "msg.loss", node=m.dst,
                                         payload={"msg": m.id, "p_survive": p_survive},
                                         label=f"loss m{m.id}")
        else:
            ev = self.scheduler.schedule(arrival, "msg.deliver", node=m.dst, payload={"msg": m.id},
                                         label=f"m{m.id} {m.tag}→{m.dst}")
        m.deliver_event = ev.id

    def _apply_link_noise(self, m: Message) -> None:
        link = next(l for l in self.project["links"] if l["id"] == m.link)
        noise = link.get("noise") or {}
        chans = []
        if noise.get("depolarizing"):
            chans.append(qb.depolarizing_kraus(float(noise["depolarizing"])))
        if noise.get("dephasing"):
            chans.append(qb.dephasing_kraus(float(noise["dephasing"])))
        if noise.get("bitflip"):
            chans.append(qb.bitflip_kraus(float(noise["bitflip"])))
        if noise.get("amplitude_damping"):
            chans.append(qb.amplitude_damping_kraus(float(noise["amplitude_damping"])))
        for k in chans:
            self.backend.apply_channel([m.qubit], k)
            self.counters["quantum_ops"] += 1

    # ------------------------------------------------------------ qubits
    def _store_qubit(self, node: Node, slot: str, qid: int, t: int, origin: str) -> None:
        node.qubits[slot] = QubitSlot(qid, t, t, origin)

    def _qubit(self, node: Node, slot: str, t: int) -> int:
        if slot not in node.qubits:
            raise ProtocolError(f"{node.id} has no qubit in slot '{slot}'")
        qs = node.qubits[slot]
        dt = t - qs.last_update
        if dt > 0:
            t1 = node.noise.get("memory_t1_ns")
            t2 = node.noise.get("memory_t2_ns")
            for k in qb.memory_kraus(dt / tu.NS, t1, t2):
                self.backend.apply_channel([qs.qid], k)
            if node.caps.memory_ns is not None and (t - qs.stored_at) > tu.ns(node.caps.memory_ns):
                self.backend.apply_channel([qs.qid], qb.depolarizing_kraus(1.0))
                self._record(t, "qubit.decohered", node.id, {"slot": slot},
                             f"Qubit in slot '{slot}' exceeded the {node.caps.memory_ns} ns storage "
                             f"capability of {node.id} and is fully depolarised.")
            qs.last_update = t
        return qs.qid

    def _check_capacity(self, node: Node, slot: str) -> None:
        if node.caps.max_qubits is not None:
            held = len(node.qubits) - (1 if slot in node.qubits else 0)
            if held + 1 > node.caps.max_qubits:
                raise CapabilityViolation(node.id, "max_qubits",
                                          f"holding more than {node.caps.max_qubits} qubits")

    def _gate_noise(self, node: Node, qids: List[int]) -> None:
        p = node.noise.get("gate_depolarizing")
        if p:
            for q in qids:
                self.backend.apply_channel([q], qb.depolarizing_kraus(float(p)))

    def _measure(self, node: Node, qid: int, basis_m: np.ndarray) -> int:
        r = self.backend.measure(qid, basis_m)
        flip = node.noise.get("measurement_flip")
        if flip and node.rng.random() < float(flip):
            r ^= 1
        self.counters["measurements"] += 1
        return r

    # ------------------------------------------------------------ actions
    def _exec_action(self, node: Node, tr: Transition, a: Dict[str, Any], ctx: Dict[str, Any],
                     t: int, sends: List[Message]) -> Dict[str, Any]:
        op = a["op"]
        fns = self._functions(node)
        ev = lambda key, default=None: evaluate(a.get(key, default), ctx, fns)  # noqa: E731
        caps = node.caps
        out: Dict[str, Any] = {"op": op}

        def setvar(name: str, value: Any) -> None:
            if name in node.params:
                raise ProtocolError(f"cannot assign to parameter '{name}'")
            node.vars[name] = value
            ctx[name] = value

        if op == "set":
            val = ev("expr")
            setvar(a["var"], val)
            out.update(var=a["var"], value=val)
        elif op == "send":
            if not caps.classical_send:
                raise CapabilityViolation(node.id, "classical_send", "classical transmission")
            val = ev("value")
            m = self._new_message(node, tr, "classical", a["port"], a["tag"], _jsonable(val), None, t)
            sends.append(m)
            out.update(msg=m.id, port=a["port"], tag=a["tag"], value=m.value)
        elif op == "send_qubit":
            if not caps.quantum_send:
                raise CapabilityViolation(node.id, "quantum_send", "quantum transmission")
            slot = a["qubit"]
            qid = self._qubit(node, slot, t)
            m = self._new_message(node, tr, "quantum", a["port"], a["tag"], None, qid, t)
            del node.qubits[slot]
            sends.append(m)
            out.update(msg=m.id, port=a["port"], tag=a["tag"], slot=slot)
        elif op in ("prepare", "prepare_bb84"):
            if not caps.prepare:
                raise CapabilityViolation(node.id, "prepare", "qubit preparation")
            slot = a["qubit"]
            self._check_capacity(node, slot)
            if op == "prepare":
                label = str(a["state"])
                if label not in qb.KET:
                    raise ProtocolError(f"unknown state label {label!r}")
                ket = qb.KET[label]
                out.update(state=label)
            else:
                bit, basis = int(ev("bit")), int(ev("basis"))
                if bit not in (0, 1) or basis not in (0, 1):
                    raise ProtocolError("prepare_bb84 needs bit and basis in {0,1}")
                ket = qb.bb84_ket(bit, basis)
                out.update(bit=bit, basis=basis, state=["|0>", "|1>", "|+>", "|->"][2 * basis + bit])
            if slot in node.qubits:
                self.backend.discard(node.qubits[slot].qid)
            qid = self.backend.create(ket)
            self._store_qubit(node, slot, qid, t, origin=f"prepared by {tr.id}")
            self.counters["quantum_ops"] += 1
            out.update(slot=slot)
        elif op == "gate":
            g = str(a["gate"]).upper()
            if not caps.allows_gate(g):
                raise CapabilityViolation(node.id, "gates", f"gate {g}")
            slots = a["qubits"] if isinstance(a["qubits"], list) else [a["qubits"]]
            if len(slots) != qb.gate_arity(g):
                raise ProtocolError(f"gate {g} acts on {qb.gate_arity(g)} qubit(s)")
            angle = ev("angle") if "angle" in a else None
            qids = [self._qubit(node, s, t) for s in slots]
            self.backend.apply_unitary(qids, qb.gate_matrix(g, angle))
            self._gate_noise(node, qids)
            self.counters["quantum_ops"] += 1
            out.update(gate=g, qubits=slots, angle=angle)
        elif op == "measure":
            basis = ev("basis", "Z")
            angle = ev("angle") if "angle" in a else None
            bname = qb.basis_name(basis, angle)
            cap_name = "angle" if bname.startswith("angle") else bname
            if not caps.allows_basis(cap_name):
                raise CapabilityViolation(node.id, "measure_bases", f"measurement in basis {bname}")
            slot = a["qubit"]
            qid = self._qubit(node, slot, t)
            r = self._measure(node, qid, qb.basis_matrix(basis, angle))
            if a.get("discard", True):
                self.backend.discard(qid)
                del node.qubits[slot]
            setvar(a["result"], r)
            out.update(qubit=slot, basis=bname, result=r)
        elif op == "bell_measure":
            if not caps.bell_measure:
                raise CapabilityViolation(node.id, "bell_measure", "Bell-state measurement")
            s0, s1 = a["qubits"]
            q0, q1 = self._qubit(node, s0, t), self._qubit(node, s1, t)
            self.backend.apply_unitary([q0, q1], qb.CNOT)
            self.backend.apply_unitary([q0], qb.H)
            self._gate_noise(node, [q0, q1])
            m0 = self._measure(node, q0, qb.I2)
            m1 = self._measure(node, q1, qb.I2)
            for s, q in ((s0, q0), (s1, q1)):
                self.backend.discard(q)
                del node.qubits[s]
            setvar(a["results"][0], m0)
            setvar(a["results"][1], m1)
            self.counters["quantum_ops"] += 1
            out.update(qubits=[s0, s1], results=[m0, m1])
        elif op == "discard":
            slot = a["qubit"]
            if slot in node.qubits:
                self.backend.discard(node.qubits.pop(slot).qid)
            out.update(qubit=slot)
        elif op == "timer":
            name = a["name"]
            if "after_ns" in a:
                val = ev("after_ns")
                target_local = node.local(t) + tu.ns(repr(float(val)) if isinstance(val, float) else val)
                how = f"armed at {tu.fmt(t)} with after_ns `{a['after_ns']}` = {val} ns (local clock)"
            else:
                val = ev("at_ns")
                target_local = tu.ns(repr(float(val)) if isinstance(val, float) else val)
                how = f"armed at {tu.fmt(t)} for absolute local time `{a['at_ns']}` = {val} ns"
            fire = node.clock.to_global(target_local)
            if fire < t:
                how += f"; target already passed, fires immediately"
                fire = t
            if not node.clock.ideal:
                how += f"; local→global conversion ({node.clock.describe()}) gives {tu.fmt(fire)}"
            if name in node.timers:
                self.scheduler.cancel(node.timers[name])
            if name in node.expired_timers:
                node.expired_timers.remove(name)
            e = self.scheduler.schedule(fire, "timer.fire", node=node.id, payload={"name": name},
                                        label=f"{node.id} timer {name}")
            node.timers[name] = e.id
            node.timer_info[name] = {"set_fs": t, "target_local_fs": target_local, "how": how}
            self._record(t, "timer.set", node.id, {"name": name, "fire_fs": fire,
                                                    "target_local_fs": target_local}, how + ".")
            out.update(name=name, fire_fs=fire, target_local_fs=target_local)
        elif op == "cancel_timer":
            name = a["name"]
            eid = node.timers.pop(name, None)
            if eid is not None:
                self.scheduler.cancel(eid)
                node.timer_info.pop(name, None)
                self._record(t, "timer.cancel", node.id, {"name": name}, f"Timer '{name}' cancelled.")
            out.update(name=name, cancelled=eid is not None)
        elif op == "verdict":
            reason = ev("reason") if "reason" in a else ""
            out["verdict"] = {"outcome": a["outcome"], "reason": str(reason)}
        elif op == "record":
            val = ev("value")
            node.observations[a["key"]] = _jsonable(val)
            out.update(key=a["key"], value=_jsonable(val))
        elif op == "log":
            text = ev("text")
            self._record(t, "log", node.id, {"text": str(text)}, str(text))
            out.update(text=str(text))
        else:
            raise ProtocolError(f"unknown action {op!r}")
        return out

    # ------------------------------------------------------------ inspection
    def node_snapshot(self, node: Node) -> Dict[str, Any]:
        qubits = {}
        for slot, qs in node.qubits.items():
            try:
                d = self.backend.describe_qubit(qs.qid)
                d["entangled_with"] = [self._qubit_owner(q) for q in d["entangled_with"]]
            except QuantumError:
                d = {}
            qubits[slot] = {"stored_at_fs": qs.stored_at, "origin": qs.origin, **d}
        return {
            "id": node.id, "role": node.role, "automaton": node.automaton.name,
            "state": node.state, "state_entered_fs": node.state_entered,
            "busy": None if node.busy is None else {
                "transition": node.busy.transition.id, "begin_fs": node.busy.begin,
                "complete_fs": node.busy.complete},
            "started": node.started, "finished": node.finished, "outcome": node.outcome,
            "error": node.error, "vars": _jsonable(node.vars), "params": _jsonable(node.params),
            "mailbox": [m.id for m in node.mailbox], "expired_timers": list(node.expired_timers),
            "timers": {k: {"event": v, **_jsonable(node.timer_info.get(k, {}))} for k, v in node.timers.items()},
            "qubits": qubits, "verdict": node.verdict, "observations": _jsonable(node.observations),
            "local_time_fs": node.local(self.now), "clock": node.clock.describe(),
            "capabilities": node.caps.as_dict(), "history": node.history,
            "state_log": node.state_log, "position": node.position,
        }

    def _qubit_owner(self, qid: int) -> str:
        for n in self.nodes.values():
            for slot, qs in n.qubits.items():
                if qs.qid == qid:
                    return f"{n.id}.{slot}"
        for m in self.messages.values():
            if m.qubit == qid and m.status == "in_flight":
                return f"in flight (msg {m.id})"
        return f"q{qid}"

    def snapshot(self, since: int = 0) -> Dict[str, Any]:
        from .decision import decide
        return {
            "now_fs": self.now, "stopped": self.stopped, "stop_reason": self.stop_reason,
            "seed": self.seed, "events_executed": self.scheduler.executed_count,
            "nodes": {nid: self.node_snapshot(n) for nid, n in self.nodes.items()},
            "pending": [e.summary() for e in self.scheduler.pending()],
            "messages": [m.as_dict() for m in self.messages.values()],
            "trace": [r.as_dict() for r in self.trace[since:]],
            "trace_length": len(self.trace),
            "counters": dict(self.counters),
            "decision": decide(self),
        }

    def causal_chain(self, msg_id: int) -> List[Dict[str, Any]]:
        """All messages in the causal past of ``msg_id`` (inclusive), by departure."""
        seen = set()
        stack = [msg_id]
        while stack:
            mid = stack.pop()
            if mid in seen or mid not in self.messages:
                continue
            seen.add(mid)
            stack.extend(self.messages[mid].causal_past)
        msgs = sorted((self.messages[i] for i in seen),
                      key=lambda m: (m.depart_time if m.depart_time is not None else m.send_time, m.id))
        return [m.as_dict() for m in msgs]

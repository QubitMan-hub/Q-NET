"""Interactive console: a documented command grammar over :class:`Session`.

Every command returns a :class:`ConsoleResult`; ``ok`` is True only if the
engine/session call completed without raising.  Grammar (see ``help``)::

    command  := word {argument}
    argument := word | "quoted string" | key=value
    value    := JSON literal (number, true, [..], {..}, "str") or bare string

Times are given in nanoseconds of global simulation time.  Project paths may
start with a participant or link id (``P.processing_ns``, ``V0.tolerance_ns``,
``q0.noise.depolarizing``) as a shorthand for the full document path.
Commands are registered in display order under the current group; each may
offer a one-click ``starter`` and a ``view`` hint telling the UI how to render
its data, so the UI needs no list of command names.
"""

from __future__ import annotations

import difflib
import json
import math
import shlex
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import timeunits as tu
from .library import EXAMPLES, automaton_library
from .protocol.capabilities import PROFILES, ROLE_PROFILES, make_capabilities, profile_catalog
from .protocol.project import ROLES, get_path, participant
from .session import Session, SessionError, dump_json


@dataclass
class ConsoleResult:
    ok: bool
    output: str
    data: Any = None
    command: str = ""
    view: Optional[str] = None  # rendering hint for the UI ("help", "decision")

    def as_dict(self):
        return {"ok": self.ok, "output": self.output, "data": self.data, "command": self.command,
                "view": self.view}


@dataclass
class Command:
    name: str
    usage: str
    help: str
    fn: Callable[..., Tuple[str, Any]]
    aliases: List[str] = field(default_factory=list)
    category: str = "Other"
    examples: List[str] = field(default_factory=list)
    starter: Optional[str] = None  # label of a one-click button in the UI
    view: Optional[str] = None


def _value(s: str) -> Any:
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return s


def _split(args: List[str]) -> Tuple[List[str], Dict[str, str]]:
    pos, kw = [], {}
    for a in args:
        if "=" in a and not a.startswith("=") and a.split("=", 1)[0].replace("_", "").replace(".", "").replace("[", "").replace("]", "").isalnum():
            k, v = a.split("=", 1)
            kw[k] = v
        else:
            pos.append(a)
    return pos, kw


def _lines(rows: List[str], empty: str) -> str:
    return "\n".join(rows) or f"  ({empty})"


class Console:
    def __init__(self, session: Optional[Session] = None):
        self.session = session or Session()
        self.commands: Dict[str, Command] = {}
        self.history: List[str] = []
        self._group = "Other"
        self._register()

    # ------------------------------------------------------------ registry
    def _cmd(self, name, usage, help_, aliases=(), examples=(), starter=None, view=None):
        def deco(fn):
            c = Command(name, usage, help_, fn, list(aliases), self._group, list(examples), starter, view)
            for key in (name, *aliases):
                self.commands[key] = c
            return fn
        return deco

    def _unique(self) -> List[Command]:
        return list({id(c): c for c in self.commands.values()}.values())

    def catalog(self) -> List[Dict[str, Any]]:
        """Commands grouped by task, in registration order, for help screens and the UI's guide."""
        return [{"name": c.name, "usage": c.usage, "help": c.help, "aliases": c.aliases, "category": c.category,
                 "examples": c.examples, "starter": c.starter} for c in self._unique()]

    def _ids(self) -> List[str]:
        p = self.session.project
        return [x["id"] for x in p["participants"]] + [lk["id"] for lk in p["links"]]

    def complete(self, prefix: str) -> List[str]:
        parts = prefix.split()
        if len(parts) <= 1 and not prefix.endswith(" "):
            return sorted({c.name for c in self._unique() if c.name.startswith(prefix.strip())})
        word = "" if prefix.endswith(" ") else parts[-1]
        p = self.session.project
        pool = (self._ids() + sorted(EXAMPLES) + sorted(automaton_library()) + sorted(p["automata"])
                + sorted(PROFILES) + sorted(ROLES) + [e.get("id", "") for e in p["experiments"]])
        return sorted({x for x in pool if x and x.startswith(word)})

    def execute(self, line: str) -> ConsoleResult:
        line = line.strip()
        if not line or line.startswith("#"):
            return ConsoleResult(True, "", None, line)
        self.history.append(line)
        try:
            argv = shlex.split(line)
        except ValueError as exc:
            return ConsoleResult(False, f"parse error: {exc}", None, line)
        name, args = argv[0].lower(), argv[1:]
        cmd = self.commands.get(name)
        if cmd is None:
            near = difflib.get_close_matches(name, list(self.commands), n=3, cutoff=0.6)
            hint = f" Did you mean {' or '.join(near)}?" if near else ""
            return ConsoleResult(False, f"unknown command '{name}'.{hint} Type 'help' to see what you can do.", None, line)
        pos, kw = _split(args)
        try:
            out, data = cmd.fn(*pos, **kw)
            return ConsoleResult(True, out, data, line, cmd.view)
        except TypeError:
            return ConsoleResult(False, f"'{cmd.name}' needs different arguments.\nusage: {cmd.usage}\n{cmd.help}", None, line)
        except (SessionError, KeyError, ValueError, RuntimeError, IndexError, AttributeError) as exc:
            msg = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
            return ConsoleResult(False, f"{msg}", None, line)

    # ------------------------------------------------------------ path shorthand
    def resolve(self, path: str) -> str:
        """Expand ``<participant>.<field|param>`` and ``<link>.<field>`` to full project paths."""
        p = self.session.project
        head, _, rest = path.replace("[", ".").replace("]", "").partition(".")
        if head in p or not rest:
            return path
        if head == "sim":
            return f"simulation.{rest}"
        part = participant(p, head)
        if part is not None:
            key = rest.split(".", 1)[0]
            if key in part:
                return f"participants.{head}.{rest}"
            params = (p["automata"].get(part["automaton"]) or {}).get("params") or {}
            if key in params:
                return f"participants.{head}.params.{rest}"
            raise SessionError(f"{head} has no field or parameter {key!r}; fields: {', '.join(part)}"
                               + (f"; parameters: {', '.join(params)}" if params else ""))
        if any(lk["id"] == head for lk in p["links"]):
            return f"links.{head}.{rest}"
        return path

    # ------------------------------------------------------------ commands
    def _register(self):
        S = self.session
        cmd = self._cmd

        def sim():
            return S.require_sim()

        def node(nid):
            s = sim()
            if nid not in s.nodes:
                raise SessionError(f"no participant {nid!r}; participants: {', '.join(s.nodes)}")
            return s.nodes[nid]

        def speed() -> float:
            return S.project["physics"]["signal_speed_mps"]

        # .......................................................... run
        self._group = "Run the simulation"

        @cmd("run", "run [until=<t_ns>] [steps=<n>]", "Run to the end, or until a given time.",
             examples=["run", "run until=15"], starter="Run to the end")
        def _run(until=None, steps=None):
            s = S.run(None if until is None else float(until), None if steps is None else int(steps))
            return (f"now {tu.fmt(s.now)}; {s.scheduler.executed_count} events executed; "
                    f"{'stopped: ' + s.stop_reason if s.stopped else 'paused'}"), None

        @cmd("step", "step [n]", "Do the next event (or the next n).", starter="Take one step")
        def _step(n="1"):
            before = len(sim().trace)
            k = S.step(int(n))
            new = sim().trace[before:]
            lines = [f"  {tu.fmt(r.time):>16} {r.kind:<20} {r.node or '':<6} {r.explain}" for r in new]
            tail = f"\n(simulation stopped: {sim().stop_reason})" if sim().stopped else ""
            return f"executed {k} event(s); now {tu.fmt(sim().now)}\n" + "\n".join(lines) + tail, \
                [r.as_dict() for r in new]

        @cmd("advance", "advance <dt_ns>", "Move time forward by an interval.", examples=["advance 5"])
        def _advance(dt):
            s = S.advance(float(dt))
            return f"now {tu.fmt(s.now)}" + (f" (stopped: {s.stop_reason})" if s.stopped else ""), None

        @cmd("reset", "reset [seed]", "Start the run over (optionally with a different random seed).")
        def _reset(seed=None):
            s = S.reset(None if seed is None else int(seed))
            if s is None:
                raise SessionError(S.sim_error or "reset failed")
            return f"reset; seed {s.seed}; {len(s.scheduler)} pending events", None

        @cmd("next", "next [n]", "What will happen next, in order.", ["queue", "pending"],
             starter="What happens next?")
        def _next(n="20"):
            evs = sim().scheduler.pending()[: int(n)]
            rows = [f"  #{e.id:<4} {tu.fmt(e.time):>16} p{e.priority:<3} {e.kind:<20} {e.node or '':<6} {e.label}"
                    for e in evs]
            return _lines(rows, "no pending events"), [e.summary() for e in evs]

        @cmd("time", "time", "The simulation clock and each participant's own clock.", ["now"])
        def _time():
            s = sim()
            lines = [f"global {tu.fmt(s.now)} ({s.now} fs)"]
            lines += [f"  {n.id:<6} local {tu.fmt(n.local(s.now))}  [{n.clock.describe()}]" for n in s.nodes.values()]
            return "\n".join(lines), {"now_fs": s.now}

        # .......................................................... results
        self._group = "Understand the result"

        @cmd("decision", "decision", "Was the position accepted, and why.", ["why", "explain", "result"],
             starter="Why was it accepted or rejected?", view="decision")
        def _decision():
            d = sim().snapshot(since=len(sim().trace))["decision"]
            return d["summary"] + "\n" + "\n".join(f"  - {l}" for l in d["explanation"]), d

        @cmd("timing", "timing [verifier]",
             "Each verifier's challenges, answers and timers, with the margin of every answer.", ["deadlines"])
        def _timing(vid=None):
            s = sim()
            out, data = [], {}
            for v in [vid] if vid else s.verifiers:
                n = node(v)
                sent = sorted((m for m in s.messages.values() if m.src == v), key=lambda m: m.send_time)
                got = [m for m in s.messages.values() if m.dst == v and m.arrival_time is not None]
                first = sent[0].send_time if sent else None
                timers = [r for r in s.trace if r.node == v and r.kind == "timer.set"
                          and first is not None and r.time >= first]
                out.append(f"{v} ({n.state}{', ' + n.outcome if n.outcome else ''})")
                out += [f"  sent     '{m.tag}' to {m.dst} at {tu.fmt(m.depart_time)}" for m in sent]
                for m in got:
                    margins = ", ".join(f"{(r.data['fire_fs'] - m.arrival_time) / tu.NS:+.6f} ns vs timer "
                                        f"'{r.data['name']}'" for r in timers)
                    out.append(f"  received '{m.tag}'={m.value!r} from {m.src} at {tu.fmt(m.arrival_time)}"
                               + (f"  (margin {margins})" if margins else ""))
                out += [f"  timer    '{r.data['name']}' due {tu.fmt(r.data['fire_fs'])}" for r in timers]
                if n.verdict:
                    out.append(f"  verdict  {n.verdict['outcome']} at {tu.fmt(n.verdict['time_fs'])}: "
                               f"{n.verdict.get('reason') or ''}")
                data[v] = {"sent": [m.id for m in sent], "received": [m.id for m in got],
                           "timers": [r.data for r in timers], "verdict": n.verdict}
            return _lines(out, "no verifiers"), data

        @cmd("events", "events [node=<id>] [kind=<k>] [grep=<text>] [last=<n>]", "Search what has happened so far.",
             ["trace", "log"], examples=["events node=V0", "events kind=msg last=10"])
        def _events(node=None, kind=None, grep=None, last="40"):
            recs = [r for r in sim().trace
                    if (node is None or r.node == node) and (kind is None or r.kind.startswith(kind))
                    and (grep is None or grep.lower() in (r.explain + json.dumps(r.data, default=str)).lower())]
            recs = recs[-int(last):]
            lines = [f"  [{r.seq:>4}] {tu.fmt(r.time):>16} {r.kind:<20} {r.node or '':<6} {r.explain}" for r in recs]
            return _lines(lines, "no matching records"), [r.as_dict() for r in recs]

        @cmd("event", "event <seq>", "Full detail of one event (the number in [brackets] from 'events').")
        def _event(seq):
            r = sim().trace[int(seq)]
            return json.dumps(r.as_dict(), indent=2, default=str), r.as_dict()

        @cmd("messages", "messages [participant]", "Messages sent so far, with send and arrival times.", ["msgs"])
        def _messages(who=None):
            ms = [m for m in sim().messages.values() if who is None or who in (m.src, m.dst)]
            lines = [f"  m{m.id:<3} {m.kind:<9} {m.src}.{m.src_port} -> {m.dst}.{m.dst_port} '{m.tag}'="
                     f"{m.value!r:<6} depart {tu.fmt(m.depart_time)} arrive {tu.fmt(m.arrival_time)} [{m.status}]"
                     for m in ms]
            return _lines(lines, "no messages"), [m.as_dict() for m in ms]

        @cmd("causes", "causes <message>", "Which earlier messages a message depends on (challenge to answer).",
             ["chain", "path"], examples=["causes m6"])
        def _causes(mid):
            chain = sim().causal_chain(int(str(mid).lstrip("m")))
            lines = [f"  m{m['id']}: {m['src']} -> {m['dst']} '{m['tag']}' depart {tu.fmt(m['depart_time_fs'])} "
                     f"arrive {tu.fmt(m['arrival_time_fs'])} (delay {tu.fmt(m['delay_fs'])})" for m in chain]
            return _lines(lines, "no such message"), chain

        @cmd("check", "check", "Check the run obeyed timing, causality and state-machine rules.", ["invariants"])
        def _check():
            r = S.invariants()
            if r["ok"]:
                return f"all {len(r['checked'])} invariants hold: {', '.join(r['checked'])}", r
            return "VIOLATIONS:\n" + "\n".join(f"  {v['invariant']}: {v['message']}" for v in r["violations"]), r

        # .......................................................... participants
        self._group = "Look at the setup"

        @cmd("participants", "participants", "Everyone in the protocol, where they are and what state they are in.",
             ["who", "nodes", "ls"], starter="Who is taking part?")
        def _participants():
            s = sim()
            rows = []
            for n in s.nodes.values():
                busy = f" busy({n.busy.transition.id})" if n.busy else ""
                rows.append(f"  {n.id:<6} {n.role:<10} x={n.position} state={n.state}{busy}"
                            f" outcome={n.outcome} caps={n.caps.profile}")
            return "\n".join(rows), [s.node_snapshot(n) for n in s.nodes.values()]

        @cmd("inspect", "inspect <participant>", "Everything one participant knows and holds right now.", ["node"])
        def _inspect(nid):
            s = sim()
            snap = s.node_snapshot(node(nid))
            lines = [f"{nid} ({snap['role']}, automaton {snap['automaton']}) state={snap['state']} "
                     f"since {tu.fmt(snap['state_entered_fs'])}",
                     f"  vars: {snap['vars']}", f"  params: {snap['params']}",
                     f"  mailbox: {snap['mailbox']}  timers: {list(snap['timers'])}",
                     f"  qubits: {list(snap['qubits'])}  verdict: {snap['verdict']}",
                     f"  clock: {snap['clock']}  local now: {tu.fmt(snap['local_time_fs'])}"]
            if snap["error"]:
                lines.append(f"  ERROR: {snap['error']}")
            return "\n".join(lines), snap

        @cmd("automaton", "automaton <participant>", "A participant's state machine and the steps it has taken.",
             ["fsm", "states"])
        def _automaton(nid):
            n = node(nid)
            lines = [f"automaton {n.automaton.name}; current state '{n.state}'"]
            for st in n.automaton.spec["states"]:
                mark = "*" if st["id"] == n.state else " "
                lines.append(f" {mark} [{st.get('kind', 'normal')}] {st['id']}" +
                             (f" -> outcome {st['outcome']}" if st.get("outcome") else ""))
            for t in n.automaton.transitions:
                g = f" if `{t.guard}`" if isinstance(t.guard, str) else ""
                lines.append(f"     {t.src} --{t.id}: {t.describe_trigger()}{g}--> {t.dst}")
            lines.append("history:")
            for h in n.history:
                lines.append(f"     {tu.fmt(h['begin_fs'])} .. {tu.fmt(h['complete_fs'])}  {h['transition']}: "
                             f"{h['from']} -> {h['to']}")
            return "\n".join(lines), {"spec": n.automaton.spec, "history": n.history, "state": n.state}

        @cmd("links", "links", "Channels between participants, with length and delay.")
        def _links():
            s = sim()
            rows = [f"  {ol.link['id']:<6} {kind:<9} {node_}.{port} -> {ol.dst}.{ol.dst_port}  "
                    f"{ol.distance_m:.6g} m  delay {tu.fmt(ol.base_delay_fs + ol.latency_fs)}"
                    for (node_, port, kind), ol in s.out_links.items()]
            return _lines(rows, "no links"), list(S.project["links"])

        @cmd("geometry", "geometry", "Where everyone is, and how long light takes between them and to the claim.",
             ["distances", "where"])
        def _geometry():
            p = S.project
            people = p["participants"]
            claim = p["claim"]["position"]

            def light(a, b):
                try:
                    return tu.propagation_fs(math.dist(a, b), speed())
                except ValueError:  # coordinates of different dimension
                    return None
            rows = [f"claim at {claim}" + (f" (prover {p['claim']['prover']})" if p["claim"].get("prover") else "")]
            rows += [f"  {q['id']:<6} {q['role']:<10} at {q['position']}  to claim {tu.fmt(light(q['position'], claim))}"
                     for q in people]
            ids = [q["id"] for q in people]
            matrix = {a["id"]: {b["id"]: light(a["position"], b["position"]) for b in people} for a in people}
            rows.append("light travel time (ns):")
            rows.append("         " + "".join(f"{i:>12}" for i in ids))
            rows += [f"  {a:<6} " + "".join(f"{'—' if matrix[a][b] is None else matrix[a][b] / tu.NS:>12.6f}"
                                            if a != b else f"{'·':>12}" for b in ids) for a in ids]
            return "\n".join(rows), {"claim": claim, "light_fs": matrix}

        @cmd("info", "info", "What this project models, its assumptions and limits.", ["project"])
        def _info():
            p = S.project
            m = p["meta"]
            lines = [f"{m['name']} — protocol {m['protocol'].get('name')} v{m['protocol'].get('version')}",
                     m.get("description", ""), f"backend {p['simulation']['backend']}, seed {p['simulation']['seed']}",
                     f"claim: {p['claim']}", "assumptions:"]
            lines += [f"  - {a}" for a in m.get("assumptions", [])]
            lines += ["limitations:"] + [f"  - {a}" for a in m.get("limitations", [])]
            return "\n".join(lines), m

        # .......................................................... editing
        self._group = "Change the setup"

        @cmd("set", "set <path> <value>", "Change a setting (restarts the run). Paths may start with a participant "
             "or link id.", examples=["set P.processing_ns 0.3", "set V0.tolerance_ns 1",
                                      "set q0.noise.depolarizing 0.1", "set sim.seed 5"])
        def _set(path, value):
            full = self.resolve(path)
            S.edit(full, _value(value))
            iss = [i for i in S.validate() if i["level"] == "error"]
            msg = f"{full} = {json.dumps(_value(value))}; simulation reset"
            if iss:
                msg += "\nproject now has errors:\n" + "\n".join(f"  {i['path']}: {i['message']}" for i in iss)
            return msg, None

        @cmd("get", "get <path>", "Read one setting of the project.", examples=["get P", "get V0.tolerance_ns"])
        def _get(path):
            v = S.get(self.resolve(path))
            return json.dumps(v, indent=2, default=str), v

        @cmd("strategy", "strategy <participant> [automaton]",
             "Show a participant's strategy and the alternatives for its role, or switch to another one.")
        def _strategy(pid, name=None):
            part = participant(S.project, pid)
            if part is None:
                raise SessionError(f"no participant {pid!r}")
            if name:
                S.use_strategy(pid, name)
                return f"{pid} now runs '{name}'; simulation reset", None
            lib = {**automaton_library(), **S.project["automata"]}
            alts = sorted(n for n, a in lib.items() if a.get("role") == part["role"] and n != part["automaton"])
            desc = (lib.get(part["automaton"]) or {}).get("description", "")
            return (f"{pid} runs '{part['automaton']}': {desc}\nother {part['role']} strategies: "
                    + (", ".join(alts) or "none")), {"current": part["automaton"], "alternatives": alts}

        @cmd("strategies", "strategies [role]", "Every available strategy (automaton), optionally for one role.",
             ["automata", "library"])
        def _strategies(role=None):
            lib = {**automaton_library(), **S.project["automata"]}
            users: Dict[str, List[str]] = {}
            for q in S.project["participants"]:
                users.setdefault(q["automaton"], []).append(q["id"])
            items = sorted((a.get("role", "other"), n) for n, a in lib.items() if role in (None, a.get("role")))
            rows = [f"  {r:<10} {n:<34} {('used by ' + ', '.join(users[n])) if n in users else ''}" for r, n in items]
            return _lines(rows, "no strategies"), {n: lib[n].get("description", "") for _, n in items}

        @cmd("profile", "profile <participant> [name]", "Show or change what a participant is allowed to do.",
             ["caps", "capabilities"], examples=["profile E0", "profile E0 bounded_entanglement"])
        def _profile(pid, name=None):
            if name:
                S.edit(f"participants.{pid}.capabilities", name)
                return f"{pid} capability profile = {name}; simulation reset", None
            return json.dumps(make_capabilities(S.get(f"participants.{pid}.capabilities")).as_dict(), indent=2), None

        @cmd("profiles", "profiles", "Every capability profile and what it allows.")
        def _profiles():
            cat = profile_catalog()
            return "\n".join(f"  {n:<22} {c['description']}" for n, c in cat.items()), cat

        @cmd("add", "add participant <id> <role> | add link <id.port> <id.port>",
             "Add a participant [x= strategy= profile=] or a channel [kind= id=] (restarts the run).",
             examples=["add participant E2 adversary x=1 profile=classical_only",
                       "add link V0.prover E2.verifier kind=quantum"])
        def _add(what, *args, **kw):
            if what == "participant":
                return _add_participant(*args, **kw)
            if what == "link":
                return _add_link(*args, **kw)
            raise SessionError("add what? participant | link")

        def _add_participant(pid, role, x="0", strategy=None, profile=None):
            if role not in ROLES:
                raise SessionError(f"role must be one of {', '.join(sorted(ROLES))}")
            lib = automaton_library()
            pool = {**lib, **S.project["automata"]}
            strategy = strategy or next((n for n, a in pool.items() if a.get("role") == role), None)
            if strategy not in pool:
                raise SessionError(f"no strategy {strategy!r} for role {role}; see 'strategies {role}'")
            dims = len(S.project["claim"]["position"])

            def apply(doc):
                doc["automata"].setdefault(strategy, lib.get(strategy))
                doc["participants"].append({"id": pid, "role": role, "label": pid,
                                            "position": [float(x)] + [0.0] * (dims - 1), "automaton": strategy,
                                            "capabilities": profile or ROLE_PROFILES[role]})
            S.modify(apply)
            return f"added {role} {pid} at x={float(x)} m running '{strategy}'; simulation reset", None

        def _add_link(a, b, kind="classical", id=None):
            (na, _, pa), (nb, _, pb) = a.partition("."), b.partition(".")
            if not (pa and pb):
                raise SessionError("link ends are written <participant>.<port>, e.g. V0.prover")
            ids = {lk["id"] for lk in S.project["links"]}
            lid = id or next(f"{kind[0]}{i}" for i in range(len(ids) + 1) if f"{kind[0]}{i}" not in ids)
            S.modify(lambda doc: doc["links"].append(
                {"id": lid, "kind": kind, "a": {"node": na, "port": pa}, "b": {"node": nb, "port": pb}}))
            return f"added {kind} link {lid}: {a} <-> {b}; simulation reset", None

        @cmd("remove", "remove <participant-or-link>", "Remove a participant (with its links) or a link.",
             ["delete", "rm"])
        def _remove(rid):
            if rid not in self._ids():
                raise SessionError(f"no participant or link {rid!r}")

            def apply(doc):
                doc["participants"] = [q for q in doc["participants"] if q["id"] != rid]
                doc["links"] = [lk for lk in doc["links"] if rid not in (lk["id"], lk["a"]["node"], lk["b"]["node"])]
                doc["resources"] = [r for r in doc["resources"] if not any(
                    (h if isinstance(h, str) else h.get("node")) == rid for h in r.get("holders") or [])]
                if doc["verification"].get("verifiers"):
                    doc["verification"]["verifiers"] = [v for v in doc["verification"]["verifiers"] if v != rid]
            S.modify(apply)
            return f"removed {rid}; simulation reset", None

        @cmd("validate", "validate", "Check the project for mistakes before running.")
        def _validate():
            iss = S.validate()
            if not iss:
                return "project is valid (no errors or warnings)", iss
            return "\n".join(f"  [{i['level']}] {i['path']}: {i['message']}" for i in iss), iss

        # .......................................................... experiments
        self._group = "Experiments"

        @cmd("repeat", "repeat <runs> [seed=<s>] [vary=<path>:v1,v2[;<path>:v1,v2]] [workers=<n>]",
             "Repeat the run many times and report acceptance rates, optionally varying settings.",
             ["batch", "sweep"], examples=["repeat 200", "repeat 100 vary=E0.processing_ns:0,0.3,0.6"])
        def _repeat(runs, seed=None, vary=None, sweep=None, workers="1"):
            exp: Dict[str, Any] = {"id": "console", "name": "console batch", "runs": int(runs),
                                   "seed": int(seed) if seed is not None else S.project["simulation"]["seed"],
                                   "workers": int(workers)}
            axes = [ax for ax in (vary or sweep or "").split(";") if ax]
            if axes:
                exp["sweep"] = []
                for ax in axes:
                    path, vals = ax.split(":", 1)
                    exp["sweep"].append({"path": self.resolve(path), "values": [_value(v) for v in vals.split(",")]})
            res = S.experiment(exp)
            return _format_results(res), _strip_runs(res)

        @cmd("experiment", "experiment [id]", "Run an experiment saved in the project, or list them.")
        def _experiment(eid=None):
            if eid is None:
                exps = S.project.get("experiments", [])
                return _lines([f"  {e.get('id'):<20} {e.get('name', '')} ({e.get('runs')} runs)" for e in exps],
                              "no saved experiments"), exps
            res = S.experiment(S.saved_experiment(eid))
            return _format_results(res), _strip_runs(res)

        # .......................................................... files
        self._group = "Files"

        @cmd("examples", "examples", "Bundled example scenarios you can load.")
        def _examples():
            return "\n".join(f"  {n}" for n in EXAMPLES), sorted(EXAMPLES)

        @cmd("load", "load <path> | load example <name>", "Open a project file or a bundled example.",
             examples=["load example qpv_bb84_honest"])
        def _load(a, b=None):
            src = f"example:{b}" if a == "example" else a
            doc = S.load(src)
            return f"loaded '{doc['meta']['name']}'" + (f"\n{S.sim_error}" if S.sim_error else ""), None

        @cmd("save", "save [path]", "Save the project file.")
        def _save(path=None):
            return f"saved to {S.save(path)}", None

        @cmd("export", "export trace|results|project <path>", "Save the trace, the last experiment results or the project as JSON.")
        def _export(what, path):
            if what == "trace":
                dump_json(S.export_trace(), path)
            elif what == "results":
                if not S.results:
                    raise SessionError("no experiment results yet")
                dump_json(S.results[-1], path)
            elif what == "project":
                S.save(path)
            else:
                raise SessionError("export what? trace | results | project")
            return f"wrote {what} to {path}", None

        @cmd("checkpoint", "checkpoint <name>", "Remember the current moment of the run.")
        def _checkpoint(name):
            S.checkpoint(name)
            return f"checkpoint '{name}' at {tu.fmt(sim().now)}", None

        @cmd("restore", "restore <name>", "Go back to a remembered moment.")
        def _restore(name):
            S.restore(name)
            return f"restored '{name}'; now {tu.fmt(sim().now)}", None

        # .......................................................... scripting
        self._group = "Scripting"

        @cmd("expect", "expect <what> <value>",
             "Fail unless a value of the current run equals the expected one (for scripts).", ["assert"],
             examples=["expect outcome accept", "expect V0.state accepted", "expect counters.lost 0"])
        def _expect(what, expected):
            s = sim()
            snap = s.snapshot(since=len(s.trace))
            head, _, rest = what.partition(".")
            path = ("decision.outcome" if what == "outcome" else f"nodes.{rest}" if head == "node"
                    else f"nodes.{what}" if head in s.nodes else what)
            actual = get_path(snap, path)
            if str(actual) != str(_value(expected)):
                raise SessionError(f"assertion failed: {what} = {actual!r}, expected {expected!r}")
            return f"ok: {what} == {actual!r}", actual

        @cmd("help", "help [command]", "Show this list, or details and examples for one command.", ["?"],
             starter="Show all commands", view="help")
        def _help(name=None):
            if name:
                c = self.commands.get(name)
                if not c:
                    raise SessionError(f"no command {name!r}")
                lines = [c.usage, f"  {c.help}"]
                if c.aliases:
                    lines.append(f"  also: {', '.join(c.aliases)}")
                lines += [f"  e.g. {e}" for e in c.examples]
                return "\n".join(lines), None
            lines = ["Commands by task (times are in nanoseconds). Type 'help <command>' for details.", ""]
            current = None
            for c in self.catalog():
                if c["category"] != current:
                    current = c["category"]
                    lines.append(current)
                lines.append(f"  {c['usage']:<46} {c['help']}")
            return "\n".join(lines), self.catalog()



def _strip_runs(res: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(res)
    out["points"] = [{k: v for k, v in p.items() if k != "runs"} for p in res["points"]]
    return out


def _format_results(res: Dict[str, Any]) -> str:
    lines = [f"{len(res['points'])} point(s), {res['points'][0]['summary']['n']} runs each, "
             f"{res['wall_time_s']:.2f} s"]
    for p in res["points"]:
        s = p["summary"]
        a = s["acceptance"]
        assign = ", ".join(f"{k}={v}" for k, v in p["assignment"].items()) or "(base)"
        cats = {vid: v["categories"] for vid, v in s["verifiers"].items()}
        lines.append(f"  {assign}: accept {a['p']:.4f} [95% CI {a['lo']:.4f}, {a['hi']:.4f}]  {cats}")
    lines.append(res["interpretation"])
    return "\n".join(lines)

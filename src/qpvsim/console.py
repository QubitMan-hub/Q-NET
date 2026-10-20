"""Interactive console: a documented command grammar over :class:`Session`.

Every command returns a :class:`ConsoleResult`; ``ok`` is True only if the
engine/session call completed without raising.  Grammar (see ``help``)::

    command  := word {argument}
    argument := word | "quoted string" | key=value
    value    := JSON literal (number, true, [..], {..}, "str") or bare string

Times are given in nanoseconds of global simulation time.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import timeunits as tu
from .library import EXAMPLES, automaton_library
from .protocol.capabilities import PROFILES, profile_catalog
from .session import Session, SessionError, dump_json


@dataclass
class ConsoleResult:
    ok: bool
    output: str
    data: Any = None
    command: str = ""

    def as_dict(self):
        return {"ok": self.ok, "output": self.output, "data": self.data, "command": self.command}


@dataclass
class Command:
    name: str
    usage: str
    help: str
    fn: Callable[..., Tuple[str, Any]]
    aliases: List[str] = field(default_factory=list)


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


class Console:
    def __init__(self, session: Optional[Session] = None):
        self.session = session or Session()
        self.commands: Dict[str, Command] = {}
        self.history: List[str] = []
        self._register()

    # ------------------------------------------------------------ registry
    def _cmd(self, name, usage, help_, aliases=()):
        def deco(fn):
            c = Command(name, usage, help_, fn, list(aliases))
            self.commands[name] = c
            for a in aliases:
                self.commands[a] = c
            return fn
        return deco

    def complete(self, prefix: str) -> List[str]:
        parts = prefix.split()
        if len(parts) <= 1 and not prefix.endswith(" "):
            return sorted({c.name for c in self.commands.values() if c.name.startswith(prefix.strip())})
        sim = self.session.sim
        ids = list(sim.nodes) if sim else [p["id"] for p in self.session.project["participants"]]
        word = "" if prefix.endswith(" ") else parts[-1]
        pool = ids + sorted(EXAMPLES) + sorted(automaton_library()) + sorted(PROFILES)
        return sorted({x for x in pool if x.startswith(word)})

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
            near = [c for c in sorted({c.name for c in self.commands.values()}) if c.startswith(name[:2])]
            hint = f" Did you mean: {', '.join(near)}?" if near else " Type 'help'."
            return ConsoleResult(False, f"unknown command '{name}'.{hint}", None, line)
        pos, kw = _split(args)
        try:
            out, data = cmd.fn(*pos, **kw)
            return ConsoleResult(True, out, data, line)
        except TypeError as exc:
            return ConsoleResult(False, f"usage: {cmd.usage}\n({exc})", None, line)
        except (SessionError, KeyError, ValueError, RuntimeError) as exc:
            msg = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
            return ConsoleResult(False, f"error: {msg}", None, line)

    # ------------------------------------------------------------ commands
    def _register(self):
        S = self.session

        def sim():
            return S.require_sim()

        @self._cmd("help", "help [command]", "List commands or show help for one.", ["?"])
        def _help(name=None):
            if name:
                c = self.commands.get(name)
                if not c:
                    raise SessionError(f"no command {name!r}")
                return f"{c.usage}\n  {c.help}", None
            seen, lines = set(), []
            for c in self.commands.values():
                if c.name in seen:
                    continue
                seen.add(c.name)
                lines.append(f"  {c.usage:<44} {c.help}")
            return "Commands (times in ns):\n" + "\n".join(lines), None

        @self._cmd("examples", "examples", "List bundled example projects.")
        def _examples():
            return "\n".join(f"  {n}" for n in EXAMPLES), sorted(EXAMPLES)

        @self._cmd("load", "load <path> | load example <name>", "Load a project and reset the simulation.")
        def _load(a, b=None):
            src = f"example:{b}" if a == "example" else a
            doc = S.load(src)
            return f"loaded '{doc['meta']['name']}'" + (f"\n{S.sim_error}" if S.sim_error else ""), None

        @self._cmd("save", "save [path]", "Save the project (JSON).")
        def _save(path=None):
            return f"saved to {S.save(path)}", None

        @self._cmd("info", "info", "Project summary, assumptions and limitations.", ["project"])
        def _info():
            p = S.project
            m = p["meta"]
            lines = [f"{m['name']} — protocol {m['protocol'].get('name')} v{m['protocol'].get('version')}",
                     m.get("description", ""), f"backend {p['simulation']['backend']}, seed {p['simulation']['seed']}",
                     f"claim: {p['claim']}", "assumptions:"]
            lines += [f"  - {a}" for a in m.get("assumptions", [])]
            lines += ["limitations:"] + [f"  - {a}" for a in m.get("limitations", [])]
            return "\n".join(lines), m

        @self._cmd("validate", "validate", "Validate the project; report errors and warnings.")
        def _validate():
            iss = S.validate()
            if not iss:
                return "project is valid (no errors or warnings)", iss
            return "\n".join(f"  [{i['level']}] {i['path']}: {i['message']}" for i in iss), iss

        @self._cmd("participants", "participants", "List participants with state and position.", ["nodes", "ls"])
        def _nodes():
            s = sim()
            rows = []
            for n in s.nodes.values():
                busy = f" busy({n.busy.transition.id})" if n.busy else ""
                rows.append(f"  {n.id:<6} {n.role:<10} x={n.position} state={n.state}{busy}"
                            f" outcome={n.outcome} caps={n.caps.profile}")
            return "\n".join(rows), [s.node_snapshot(n) for n in s.nodes.values()]

        @self._cmd("node", "node <id>", "Show a participant's full runtime state.")
        def _node(nid):
            s = sim()
            if nid not in s.nodes:
                raise SessionError(f"no participant {nid!r}")
            snap = s.node_snapshot(s.nodes[nid])
            lines = [f"{nid} ({snap['role']}, automaton {snap['automaton']}) state={snap['state']} "
                     f"since {tu.fmt(snap['state_entered_fs'])}",
                     f"  vars: {snap['vars']}", f"  params: {snap['params']}",
                     f"  mailbox: {snap['mailbox']}  timers: {list(snap['timers'])}",
                     f"  qubits: {list(snap['qubits'])}  verdict: {snap['verdict']}",
                     f"  clock: {snap['clock']}  local now: {tu.fmt(snap['local_time_fs'])}"]
            if snap["error"]:
                lines.append(f"  ERROR: {snap['error']}")
            return "\n".join(lines), snap

        @self._cmd("fsm", "fsm <id>", "Show a participant's automaton and transition history.")
        def _fsm(nid):
            s = sim()
            n = s.nodes.get(nid)
            if n is None:
                raise SessionError(f"no participant {nid!r}")
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

        @self._cmd("links", "links", "List links with lengths and delays.")
        def _links():
            s = sim()
            rows, seen = [], set()
            for (node, port, kind), ol in s.out_links.items():
                lid = ol.link["id"]
                rows.append(f"  {lid:<6} {kind:<9} {node}.{port} -> {ol.dst}.{ol.dst_port}  "
                            f"{ol.distance_m:.6g} m  delay {tu.fmt(ol.base_delay_fs + ol.latency_fs)}")
                seen.add(lid)
            return "\n".join(rows), [l for l in S.project["links"]]

        @self._cmd("queue", "queue [n]", "Show pending events in execution order.", ["pending"])
        def _queue(n="20"):
            evs = sim().scheduler.pending()[: int(n)]
            rows = [f"  #{e.id:<4} {tu.fmt(e.time):>16} p{e.priority:<3} {e.kind:<20} {e.node or '':<6} {e.label}"
                    for e in evs]
            return ("\n".join(rows) or "  (no pending events)"), [e.summary() for e in evs]

        @self._cmd("reset", "reset [seed]", "Rebuild the simulation from the project (optionally with a seed).")
        def _reset(seed=None):
            s = S.reset(None if seed is None else int(seed))
            if s is None:
                raise SessionError(S.sim_error or "reset failed")
            return f"reset; seed {s.seed}; {len(s.scheduler)} pending events", None

        @self._cmd("step", "step [n]", "Execute the next n events (default 1).")
        def _step(n="1"):
            before = len(sim().trace)
            k = S.step(int(n))
            new = sim().trace[before:]
            lines = [f"  {tu.fmt(r.time):>16} {r.kind:<20} {r.node or '':<6} {r.explain}" for r in new]
            tail = f"\n(simulation stopped: {sim().stop_reason})" if sim().stopped else ""
            return f"executed {k} event(s); now {tu.fmt(sim().now)}\n" + "\n".join(lines) + tail, \
                [r.as_dict() for r in new]

        @self._cmd("run", "run [until=<t_ns>] [steps=<n>]", "Run to completion, to a time, or for n events.")
        def _run(until=None, steps=None):
            s = S.run(None if until is None else float(until), None if steps is None else int(steps))
            return (f"now {tu.fmt(s.now)}; {s.scheduler.executed_count} events executed; "
                    f"{'stopped: ' + s.stop_reason if s.stopped else 'paused'}"), None

        @self._cmd("advance", "advance <dt_ns>", "Advance simulation time by an interval.")
        def _advance(dt):
            s = S.advance(float(dt))
            return f"now {tu.fmt(s.now)}" + (f" (stopped: {s.stop_reason})" if s.stopped else ""), None

        @self._cmd("time", "time", "Current global and local clock readings.", ["now"])
        def _time():
            s = sim()
            lines = [f"global {tu.fmt(s.now)} ({s.now} fs)"]
            lines += [f"  {n.id:<6} local {tu.fmt(n.local(s.now))}  [{n.clock.describe()}]" for n in s.nodes.values()]
            return "\n".join(lines), {"now_fs": s.now}

        @self._cmd("events", "events [node=<id>] [kind=<k>] [grep=<text>] [last=<n>]", "Search the event trace.",
                   ["trace", "log"])
        def _events(node=None, kind=None, grep=None, last="40"):
            recs = [r for r in sim().trace
                    if (node is None or r.node == node) and (kind is None or r.kind.startswith(kind))
                    and (grep is None or grep.lower() in (r.explain + json.dumps(r.data, default=str)).lower())]
            recs = recs[-int(last):]
            lines = [f"  [{r.seq:>4}] {tu.fmt(r.time):>16} {r.kind:<20} {r.node or '':<6} {r.explain}" for r in recs]
            return ("\n".join(lines) or "  (no matching records)"), [r.as_dict() for r in recs]

        @self._cmd("event", "event <seq>", "Show one trace record in full.")
        def _event(seq):
            r = sim().trace[int(seq)]
            return json.dumps(r.as_dict(), indent=2, default=str), r.as_dict()

        @self._cmd("messages", "messages [node]", "List messages (sent/received by a node).", ["msgs"])
        def _messages(node=None):
            ms = [m for m in sim().messages.values() if node is None or node in (m.src, m.dst)]
            lines = [f"  m{m.id:<3} {m.kind:<9} {m.src}.{m.src_port} -> {m.dst}.{m.dst_port} '{m.tag}'="
                     f"{m.value!r:<6} depart {tu.fmt(m.depart_time)} arrive {tu.fmt(m.arrival_time)} [{m.status}]"
                     for m in ms]
            return ("\n".join(lines) or "  (no messages)"), [m.as_dict() for m in ms]

        @self._cmd("chain", "chain <msg_id>", "Trace a message's causal past (challenge -> response path).", ["path"])
        def _chain(mid):
            chain = sim().causal_chain(int(str(mid).lstrip("m")))
            lines = [f"  m{m['id']}: {m['src']} -> {m['dst']} '{m['tag']}' depart {tu.fmt(m['depart_time_fs'])} "
                     f"arrive {tu.fmt(m['arrival_time_fs'])} (delay {tu.fmt(m['delay_fs'])})" for m in chain]
            return "\n".join(lines), chain

        @self._cmd("decision", "decision", "Verification decision with an explanation.", ["explain"])
        def _decision():
            d = sim().snapshot(since=len(sim().trace))["decision"]
            return d["summary"] + "\n" + "\n".join(f"  - {l}" for l in d["explanation"]), d

        @self._cmd("invariants", "invariants", "Check trace invariants (ordering, causality, FSM consistency).",
                   ["check"])
        def _inv():
            r = S.invariants()
            if r["ok"]:
                return f"all {len(r['checked'])} invariants hold: {', '.join(r['checked'])}", r
            return "VIOLATIONS:\n" + "\n".join(f"  {v['invariant']}: {v['message']}" for v in r["violations"]), r

        @self._cmd("set", "set <path> <json-value>", "Edit the project (e.g. set participants.P.processing_ns 0.3); resets.")
        def _set(path, value):
            S.edit(path, _value(value))
            iss = [i for i in S.validate() if i["level"] == "error"]
            msg = f"{path} = {json.dumps(_value(value))}; simulation reset"
            if iss:
                msg += "\nproject now has errors:\n" + "\n".join(f"  {i['path']}: {i['message']}" for i in iss)
            return msg, None

        @self._cmd("get", "get <path>", "Read a project value.")
        def _get(path):
            v = S.get(path)
            return json.dumps(v, indent=2, default=str), v

        @self._cmd("strategy", "strategy <participant> <automaton>", "Swap a participant's automaton (strategy).")
        def _strategy(pid, name):
            S.use_strategy(pid, name)
            return f"{pid} now runs '{name}'; simulation reset", None

        @self._cmd("caps", "caps <participant> [profile]", "Show or set a capability profile.", ["capabilities"])
        def _caps(pid, profile=None):
            if profile:
                S.edit(f"participants.{pid}.capabilities", profile)
                return f"{pid} capability profile = {profile}; simulation reset", None
            return json.dumps(profile_catalog().get(
                S.get(f"participants.{pid}.capabilities") if isinstance(S.get(f"participants.{pid}.capabilities"), str)
                else "unrestricted"), indent=2), None

        @self._cmd("batch", "batch <runs> [seed=<s>] [sweep=<path>:v1,v2,...] [workers=<n>]",
                   "Run an experiment batch on the current project.", ["sweep"])
        def _batch(runs, seed=None, sweep=None, workers="1"):
            exp: Dict[str, Any] = {"id": "console", "name": "console batch", "runs": int(runs),
                                   "seed": int(seed) if seed is not None else S.project["simulation"]["seed"],
                                   "workers": int(workers)}
            if sweep:
                path, vals = sweep.split(":", 1)
                exp["sweep"] = [{"path": path, "values": [_value(v) for v in vals.split(",")]}]
            res = S.experiment(exp)
            return _format_results(res), _strip_runs(res)

        @self._cmd("experiment", "experiment <id>", "Run an experiment saved in the project.")
        def _experiment(eid):
            res = S.experiment(S.saved_experiment(eid))
            return _format_results(res), _strip_runs(res)

        @self._cmd("export", "export trace|results|project <path>", "Export data as JSON (results: last experiment).")
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

        @self._cmd("checkpoint", "checkpoint <name>", "Snapshot the current simulation state.")
        def _checkpoint(name):
            S.checkpoint(name)
            return f"checkpoint '{name}' at {tu.fmt(sim().now)}", None

        @self._cmd("restore", "restore <name>", "Restore a checkpoint.")
        def _restore(name):
            S.restore(name)
            return f"restored '{name}'; now {tu.fmt(sim().now)}", None

        @self._cmd("assert", "assert <path-or-expr> <expected>",
                   "Assert decision.outcome / node.<id>.state / node.<id>.outcome equals a value.")
        def _assert(what, expected):
            s = sim()
            if what == "decision.outcome":
                actual = s.snapshot(since=len(s.trace))["decision"]["outcome"]
            elif what.startswith("node."):
                _, nid, field_ = what.split(".", 2)
                actual = getattr(s.nodes[nid], field_)
            else:
                raise SessionError("assertable: decision.outcome | node.<id>.state | node.<id>.outcome")
            if str(actual) != str(_value(expected)):
                raise SessionError(f"assertion failed: {what} = {actual!r}, expected {expected!r}")
            return f"ok: {what} == {actual!r}", actual


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

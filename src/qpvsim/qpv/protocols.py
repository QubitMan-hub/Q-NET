"""More position-verification protocols on the same geometry, verifiers and engine.

* ``bb84``      -- the BB84 family (one qubit, basis from the classical verifiers' shares); see :mod:`.scenario`.
* ``qudit``     -- a qudit of dimension d = 2, 4 or 8 (carried by log2 d qubits) in one of d + 1 mutually unbiased
                   bases; d = 2 is the six-state protocol.  Guessing the basis gets harder as d grows.
* ``bb84f``     -- QPV_BB84^f with two verifiers: V0 sends the qubit and an n-bit string x, V1 an n-bit string y, and
                   the basis is f(x, y) for a public function f (xor of parities, inner product, or a random table).
                   The honest prover handles one qubit and 2n bits whatever n is (Bluhm, Christandl & Speelman 2022).
* ``classical`` -- classical position verification: every verifier sends a random bit and the answer is their xor.
                   Two colluders with no quantum resources pass every round (Chandran, Goyal, Moriarty & Ostrovsky 2009).

Every protocol is built by :func:`build` as an ordinary project; ``meta.qpv`` records which protocol and settings,
so attacks can be switched (:func:`switch`) and theory looked up (:func:`reference`).
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Optional

import numpy as np

from ..protocol.project import normalize, verifier_ids
from . import automata as qa
from . import mub
from .scenario import _ui, autowire, build as build_bb84, participant

BREIDBART = math.cos(math.pi / 8) ** 2
F_FUNCTIONS = ("xor", "inner_product", "random")

PROTOCOLS: Dict[str, Dict[str, Any]] = {
    "bb84": {"label": "BB84 (qubit, basis from shares)",
             "answerers": ["honest", "displaced", "unentangled", "teleport", "guess", "split", "lossy"]},
    "qudit": {"label": "Qudit with d + 1 mutually unbiased bases",
              "answerers": ["honest", "displaced", "unentangled", "teleport", "guess"]},
    "bb84f": {"label": "BB84 with basis f(x, y) (QPV_BB84^f)",
              "answerers": ["honest", "displaced", "unentangled", "budget", "linear", "guess"]},
    "classical": {"label": "Classical position verification (no qubit)",
                  "answerers": ["honest", "displaced", "relay", "guess"]},
}
LABELS = {"budget": "teleportation attack with an entanglement budget", "linear": "one-pair teleportation attack (xor f)",
          "relay": "colluders relaying the challenges"}


def protocol_of(doc: Dict[str, Any]) -> str:
    return ((doc.get("meta") or {}).get("qpv") or {}).get("protocol", "bb84")


# ================================================================ automata
def _states():
    return [qa._state("intercept", "initial", "Intercept challenge", 0), qa._state("relayed", "normal", "Await partners", 130),
            qa._state("done", "terminal", "Answered", 260, outcome="done")]


def _answer(ports, value):
    return [qa.KEY_PICK] + qa._send_all(ports, "answer", qa.keyed(value))


def qudit_slots(d: int, stem: str = "q") -> List[str]:
    return [stem] + [f"{stem}{i}" for i in range(1, mub.qubits_for(d))]


def qudit_verifier(d: int) -> Dict[str, Any]:
    slots = qudit_slots(d)
    v = qa._verifier("quantum_qudit", [
        {"op": "prepare_mub", "qubits": slots, "value": "x", "basis": "sum(shares) % (dim + 1)", "dim": "dim"},
        *[{"op": "send_qubit", "port": "prover", "tag": s, "qubit": s} for s in slots],
    ], f"Quantum verifier sending a qudit of dimension {d} (on {len(slots)} qubits): value x in mutually unbiased basis "
       f"b = sum of the shares mod {d + 1}.",
        {"dim": {"default": d, "description": "Qudit dimension (2, 4 or 8)."}})
    v["name"] = f"qpv_verifier_quantum_qudit{d}"
    return v


def qudit_prover(n: int, d: int) -> Dict[str, Any]:
    ports, slots = [f"v{j}" for j in range(n)], qudit_slots(d)
    return qa._automaton(
        f"qpv_prover_{n}v_qudit{d}", "prover",
        f"Honest prover: waits for the {d}-level qudit and all shares, measures in the shares' basis and answers.",
        ports,
        [{"id": "respond", "from": "waiting", "to": "done", "label": "measure & answer",
          "trigger": {"type": "receive", "tags": slots + ["theta"] * (n - 1)},
          "actions": [{"op": "measure_mub", "qubits": slots, "basis": "sum(received.theta) % (dim + 1)", "dim": "dim",
                       "result": "answer"}] + _answer(ports, "answer")}],
        [qa._state("waiting", "initial", "Await challenges", 0), qa._state("done", "terminal", "Answered", 160, outcome="done")],
        params={"dim": {"default": d, "description": "Qudit dimension."}, **qa.KEY_PARAM},
        variables={"answer": 0, "key": [], "k": []})


def qudit_unentangled(j: int, n: int, d: int) -> Dict[str, Any]:
    """E0 guesses one of the d + 1 bases, measures at once and shares the result; the others relay shares."""
    if j:
        a = qa.adv_unentangled(1, n)
        a["name"] = f"qpv_adv_unentangled_qudit_c"
        return a
    partners, slots = [f"p{i}" for i in range(1, n)], qudit_slots(d)
    return qa._attacker(
        f"qpv_adv_unentangled_qudit{d}_{n}v",
        "Unentangled colluder next to the quantum verifier: guesses one of the d + 1 bases, measures the qudit at once "
        "and sends the outcome to its partners.", partners,
        [{"id": "measure", "from": "intercept", "to": "relayed", "label": "guess a basis, measure & broadcast",
          "trigger": {"type": "receive", "tags": slots, "port": "verifier"},
          "actions": [{"op": "set", "var": "g", "expr": "rand_int(0, dim)"},
                      {"op": "measure_mub", "qubits": slots, "basis": "g", "dim": "dim", "result": "m"}]
          + qa._send_all(partners, "m", "m")},
         {"id": "answer", "from": "relayed", "to": "done", "label": "answer",
          "trigger": {"type": "receive", "tags": ["theta"] * (n - 1)}, "actions": qa._send_all(["verifier"], "answer", "m")}],
        _states(), params={"dim": {"default": d, "description": "Qudit dimension."}}, variables={"m": 0, "g": 0})


def qudit_teleport(j: int, d: int) -> Dict[str, Any]:
    """Two colluders, log2(d) EPR pairs: E0 teleports the qudit's qubits at once; E1 measures its halves in the
    right basis; the Bell results then tell both how the outcome was permuted."""
    k, slots = mub.qubits_for(d), qudit_slots(d)
    params = {"dim": {"default": d, "description": "Qudit dimension."}}
    if j == 0:
        bell = [{"op": "bell_measure", "qubits": [s, f"out{i}"], "results": [f"a{i}", f"b{i}"]} for i, s in enumerate(slots)]
        frame = "[" + ", ".join(f"a{i}, b{i}" for i in range(k)) + "]"
        return qa._attacker(
            f"qpv_adv_teleport_qudit{d}_0", f"Teleports the {d}-level qudit ({k} qubits) into the shared pairs at once.",
            ["p1"],
            [{"id": "teleport", "from": "intercept", "to": "relayed", "label": "teleport",
              "trigger": {"type": "receive", "tags": slots, "port": "verifier"},
              "actions": bell + [{"op": "set", "var": "frame", "expr": frame}] + qa._send_all(["p1"], "e0", "frame")},
             {"id": "decode", "from": "relayed", "to": "done", "label": "decode & answer",
              "trigger": {"type": "receive", "tags": ["e1"]},
              "actions": qa._send_all(["verifier"], "answer",
                                      "mub_unscramble(dim, msgs.e1.value[0], msgs.e1.value[1], frame)")}],
            _states(), params=params, variables={"frame": [], **{f"{c}{i}": 0 for i in range(k) for c in "ab"}})
    halves = [f"in{i}" for i in range(k)]
    return qa._attacker(
        f"qpv_adv_teleport_qudit{d}_1", "Measures its halves of the shared pairs in the basis its verifier announces.",
        ["p0"],
        [{"id": "measure", "from": "intercept", "to": "relayed", "label": "measure in the right basis",
          "trigger": {"type": "receive", "tags": ["theta"], "port": "verifier"},
          "actions": [{"op": "set", "var": "s", "expr": "msg.value"},
                      {"op": "measure_mub", "qubits": halves, "basis": "s", "dim": "dim", "result": "r"}]
          + qa._send_all(["p0"], "e1", "[s, r]")},
         {"id": "decode", "from": "relayed", "to": "done", "label": "decode & answer",
          "trigger": {"type": "receive", "tags": ["e0"]},
          "actions": qa._send_all(["verifier"], "answer", "mub_unscramble(dim, s, r, msgs.e0.value)")}],
        _states(), params=params, variables={"s": 0, "r": 0})


def guess_value(expr: str, name: str) -> Dict[str, Any]:
    a = qa.adv_guess()
    a["name"] = name
    for t in a["transitions"]:
        for act in t["actions"]:
            if act.get("var") == "g":
                act["expr"] = expr
    return a


# ---- QPV_BB84^f
def f_table(f: str, n_bits: int, seed: int = 1) -> List[int]:
    size = 2 ** n_bits
    if f == "xor":
        return [(bin(x).count("1") + bin(y).count("1")) % 2 for x in range(size) for y in range(size)]
    if f == "inner_product":
        return [bin(x & y).count("1") % 2 for x in range(size) for y in range(size)]
    if f == "random":
        return [int(b) for b in np.random.default_rng(seed).integers(0, 2, size * size)]
    raise ValueError(f"f must be one of {', '.join(F_FUNCTIONS)}")


def f_verifier(table: List[int], size: int) -> Dict[str, Any]:
    v = qa._verifier("quantum_f", [
        {"op": "prepare_bb84", "qubit": "q", "bit": "x", "basis": "table[xs * size + shares[0]]"},
        {"op": "send_qubit", "port": "prover", "tag": "q", "qubit": "q"},
        {"op": "send", "port": "prover", "tag": "xstr", "value": "xs"},
    ], "Quantum verifier of QPV_BB84^f: sends the qubit H^f(x,y)|bit> and the string x (an integer < size); the "
       "other verifier sends y.",
        {"table": {"default": table, "description": "f as a table: f(x, y) = table[x * size + y]."},
         "size": {"default": size, "description": "Number of possible strings (2^n)."}})
    v["name"] = "qpv_verifier_quantum_f"
    v["variables"]["xs"] = 0
    return v


def f_prover(table: List[int], size: int) -> Dict[str, Any]:
    ports = ["v0", "v1"]
    return qa._automaton(
        "qpv_prover_f", "prover",
        "Honest prover of QPV_BB84^f: waits for the qubit, x and y, measures in basis f(x, y) and answers.", ports,
        [{"id": "respond", "from": "waiting", "to": "done", "label": "measure & answer",
          "trigger": {"type": "receive", "tags": ["q", "xstr", "theta"]},
          "actions": [{"op": "measure", "qubit": "q", "basis": "table[msgs.xstr.value * size + msgs.theta.value]",
                       "result": "answer"}] + _answer(ports, "answer")}],
        [qa._state("waiting", "initial", "Await challenges", 0), qa._state("done", "terminal", "Answered", 160, outcome="done")],
        params={"table": {"default": table, "description": "f(x, y) = table[x * size + y]."},
                "size": {"default": size, "description": "Number of possible strings."}, **qa.KEY_PARAM},
        variables={"answer": 0, "key": [], "k": []})


def f_budget(j: int, table: List[int], size: int, pairs: int) -> Dict[str, Any]:
    """The generic attack on any f with an entanglement budget of `pairs` EPR pairs (at most size = 2^n).

    E0 sees x at once: if x < pairs it teleports the qubit into pair x, otherwise it measures in the Breidbart basis.
    E1 sees y at once and measures its half of every pair j in basis f(j, y).  After one exchange both know x; the
    outcome of pair x, corrected by the teleportation frame, is the answer.  With 2^n pairs this wins every round."""
    params = {"table": {"default": table, "description": "f(x, y) = table[x * size + y]."},
              "size": {"default": size, "description": "Number of possible strings."},
              "pairs": {"default": pairs, "min": 0, "description": "EPR pairs the attackers share (0..size)."}}
    if j == 0:
        tele = [{"id": f"teleport{i}", "from": "intercept", "to": "relayed", "label": f"x = {i}: teleport into pair {i}",
                 "guard": f"msgs.xstr.value == {i} and {i} < pairs",
                 "trigger": {"type": "receive", "tags": ["q", "xstr"], "port": "verifier"},
                 "actions": [{"op": "set", "var": "xv", "expr": "msgs.xstr.value"},
                             {"op": "bell_measure", "qubits": ["q", f"out{i}"], "results": ["b0", "b1"]}]
                 + qa._send_all(["p1"], "e0", "[xv, b0, b1, 0]")} for i in range(size)]
        breid = {"id": "breidbart", "from": "intercept", "to": "relayed", "label": "x has no pair: Breidbart measurement",
                 "trigger": {"type": "receive", "tags": ["q", "xstr"], "port": "verifier"},
                 "actions": [{"op": "set", "var": "xv", "expr": "msgs.xstr.value"},
                             {"op": "measure", "qubit": "q", "basis": "'angle'", "angle": "pi / 8", "result": "mb"}]
                 + qa._send_all(["p1"], "e0", "[xv, 0, 0, mb]")}
        decode = ("(msgs.e1.value[1][xv] ^ (b0 if table[xv * size + msgs.e1.value[0]] else b1)) if xv < pairs else mb")
        return qa._attacker(
            f"qpv_adv_budget_f_0", "Budget attacker next to V0: teleports the qubit into the pair named by x, if there is one.",
            ["p1"], tele + [breid, {"id": "decode", "from": "relayed", "to": "done", "label": "decode & answer",
                                    "trigger": {"type": "receive", "tags": ["e1"]},
                                    "actions": qa._send_all(["verifier"], "answer", decode)}],
            _states(), params=params, variables={"xv": 0, "b0": 0, "b1": 0, "mb": 0})
    meas = []
    for m in range(size + 1):
        acts = [{"op": "set", "var": "y", "expr": "msg.value"}]
        acts += [{"op": "measure", "qubit": f"in{i}", "basis": f"table[{i} * size + y]", "result": f"r{i}"} for i in range(m)]
        acts += [{"op": "set", "var": "r", "expr": "[" + ", ".join(f"r{i}" for i in range(m)) + "]"}]
        meas.append({"id": f"measure{m}", "from": "intercept", "to": "relayed", "label": f"measure all {m} halves",
                     "guard": f"pairs == {m}", "trigger": {"type": "receive", "tags": ["theta"], "port": "verifier"},
                     "actions": acts + qa._send_all(["p0"], "e1", "[y, r]")})
    decode = ("(r[msgs.e0.value[0]] ^ (msgs.e0.value[1] if table[msgs.e0.value[0] * size + y] else msgs.e0.value[2])) "
              "if msgs.e0.value[0] < pairs else msgs.e0.value[3]")
    return qa._attacker(
        "qpv_adv_budget_f_1", "Budget attacker next to V1: measures its half of each pair j in basis f(j, y).", ["p0"],
        meas + [{"id": "decode", "from": "relayed", "to": "done", "label": "decode & answer",
                 "trigger": {"type": "receive", "tags": ["e0"]}, "actions": qa._send_all(["verifier"], "answer", decode)}],
        _states(), params=params, variables={"y": 0, "r": [], **{f"r{i}": 0 for i in range(size)}})


def f_linear(j: int, table: List[int], size: int) -> Dict[str, Any]:
    """One EPR pair beats f = parity(x) xor parity(y): E0 applies H^parity(x) and teleports; E1 measures in parity(y)."""
    params = {"table": {"default": table, "description": "f(x, y) = table[x * size + y]."},
              "size": {"default": size, "description": "Number of possible strings."}}
    if j == 0:
        return qa._attacker(
            "qpv_adv_linear_f_0", "Applies H^parity(x) to the qubit and teleports it to its partner.", ["p1"],
            [{"id": "teleport_h", "from": "intercept", "to": "relayed", "label": "H, then teleport",
              "guard": "table[msgs.xstr.value * size] == 1",
              "trigger": {"type": "receive", "tags": ["q", "xstr"], "port": "verifier"},
              "actions": [{"op": "gate", "gate": "H", "qubits": "q"},
                          {"op": "bell_measure", "qubits": ["q", "out0"], "results": ["b0", "b1"]}]
              + qa._send_all(["p1"], "e0", "[b0, b1]")},
             {"id": "teleport", "from": "intercept", "to": "relayed", "label": "teleport",
              "trigger": {"type": "receive", "tags": ["q", "xstr"], "port": "verifier"},
              "actions": [{"op": "bell_measure", "qubits": ["q", "out0"], "results": ["b0", "b1"]}]
              + qa._send_all(["p1"], "e0", "[b0, b1]")},
             {"id": "decode", "from": "relayed", "to": "done", "label": "decode & answer",
              "trigger": {"type": "receive", "tags": ["e1"]},
              "actions": qa._send_all(["verifier"], "answer",
                                      "msgs.e1.value[1] ^ (b0 if table[msgs.e1.value[0]] else b1)")}],
            _states(), params=params, variables={"b0": 0, "b1": 0})
    return qa._attacker(
        "qpv_adv_linear_f_1", "Measures its half of the pair in basis parity(y).", ["p0"],
        [{"id": "measure", "from": "intercept", "to": "relayed", "label": "measure in basis parity(y)",
          "trigger": {"type": "receive", "tags": ["theta"], "port": "verifier"},
          "actions": [{"op": "set", "var": "y", "expr": "msg.value"},
                      {"op": "measure", "qubit": "in0", "basis": "table[y]", "result": "r"}]
          + qa._send_all(["p0"], "e1", "[y, r]")},
         {"id": "decode", "from": "relayed", "to": "done", "label": "decode & answer",
          "trigger": {"type": "receive", "tags": ["e0"]},
          "actions": qa._send_all(["verifier"], "answer", "r ^ (msgs.e0.value[0] if table[y] else msgs.e0.value[1])")}],
        _states(), params=params, variables={"y": 0, "r": 0})


# ---- classical position verification
def classical_pv_verifier() -> Dict[str, Any]:
    v = qa.classical_verifier()
    v["name"] = "qpv_verifier_classical_pv"
    v["description"] = ("Classical position verification: sends a random bit; accepts the xor of all verifiers' bits "
                        "if it arrives in time. " + v["description"])
    arm = next(t for t in v["transitions"] if t["id"] == "arm")
    for a in arm["actions"]:
        if a.get("var") == "expected":
            a["expr"] = "(sum(shares) % 2) if key_bits == 0 else [sum(shares) % 2, key]"
    return v


def classical_prover(n: int) -> Dict[str, Any]:
    ports = [f"v{j}" for j in range(n)]
    return qa._automaton(
        f"qpv_prover_{n}v_classical", "prover", "Honest prover: xors every verifier's bit and answers all.", ports,
        [{"id": "respond", "from": "waiting", "to": "done", "label": "xor & answer",
          "trigger": {"type": "receive", "tags": ["theta"] * n},
          "actions": [{"op": "set", "var": "answer", "expr": "sum(received.theta) % 2"}] + _answer(ports, "answer")}],
        [qa._state("waiting", "initial", "Await challenges", 0), qa._state("done", "terminal", "Answered", 160, outcome="done")],
        params=dict(qa.KEY_PARAM), variables={"answer": 0, "key": [], "k": []})


def classical_relay(j: int, n: int) -> Dict[str, Any]:
    partners = [f"p{i}" for i in range(n) if i != j]
    return qa._attacker(
        f"qpv_adv_relay{j}_{n}v", "Colluder: forwards its verifier's bit to the others at light speed and answers the xor "
        "as soon as it has every bit.", partners,
        [{"id": "share", "from": "intercept", "to": "relayed", "label": "broadcast my bit",
          "trigger": {"type": "receive", "tags": ["theta"], "port": "verifier"},
          "actions": [{"op": "set", "var": "s", "expr": "msg.value"}] + qa._send_all(partners, f"e{j}", "s")},
         {"id": "answer", "from": "relayed", "to": "done", "label": "xor & answer",
          "trigger": {"type": "receive", "tags": [f"e{i}" for i in range(n) if i != j]},
          "actions": qa._send_all(["verifier"], "answer",
                                  "(s + " + " + ".join(f"msgs.e{i}.value" for i in range(n) if i != j) + ") % 2")}],
        _states(), variables={"s": 0})


# ================================================================ building
def _add(doc, pid, role, label, pos, aut, caps, radius, params=None, processing_ns=0.0, group=None):
    doc["automata"][aut["name"]] = aut
    claim = doc["claim"]["position"]
    row = 210 if all(abs(x) < 1e-12 for p in doc["participants"] if p["role"] == "verifier" for x in p["position"][1:]) else 0
    doc["participants"].append(participant(pid, role, label, pos, aut["name"], caps,
                                           _ui(claim, pos, radius, 0 if role == "prover" else row), params or {},
                                           processing_ns=processing_ns, **({"group": group} if group else {})))


def _answerers(doc, who: str, processing_ns: float = 0.2, displacement_m: float = 1.0):
    proto, cfg = protocol_of(doc), doc["meta"]["qpv"]
    if who not in PROTOCOLS[proto]["answerers"]:
        raise ValueError(f"{PROTOCOLS[proto]['label']}: choose who answers from {', '.join(PROTOCOLS[proto]['answerers'])}")
    vs = [p for p in doc["participants"] if p["id"] in verifier_ids(doc)]
    n, claim = len(vs), doc["claim"]["position"]
    radius = max(math.dist(v["position"], claim) for v in vs) or 1.0
    doc["claim"]["prover"] = "P" if who in ("honest", "displaced") else None
    if who in ("honest", "displaced"):
        honest = who == "honest"
        pos = claim if honest else [claim[0] - displacement_m] + list(claim[1:])
        aut = (qudit_prover(n, cfg["d"]) if proto == "qudit" else f_prover(cfg["table"], cfg["size"]) if proto == "bb84f"
               else classical_prover(n))
        _add(doc, "P", "prover" if honest else "adversary", "Prover P" if honest else "Dishonest prover P'", pos, aut,
             "honest_prover" if honest else "no_entanglement", radius, processing_ns=processing_ns)
        return
    two = {"teleport", "budget", "linear", "unentangled"} if proto != "qudit" else {"teleport"}
    if proto in ("bb84f",) and n != 2 or (who in two and n != 2 and proto == "qudit"):
        raise ValueError("this attack is built for two verifiers (a 1D setup)")
    if who == "linear" and cfg.get("f") != "xor":
        raise ValueError("the one-pair attack only works when f is xor of parities; use the budget attack")
    caps = "unrestricted" if who in ("teleport", "budget", "linear") else "no_entanglement"
    for j, v in enumerate(vs):
        if who == "guess":
            aut = (guess_value("rand_int(0, %d)" % (cfg["d"] - 1), f"qpv_adv_guess_qudit{cfg['d']}") if proto == "qudit"
                   else qa.adv_guess())
        elif proto == "qudit":
            aut = qudit_unentangled(j, n, cfg["d"]) if who == "unentangled" else qudit_teleport(j, cfg["d"])
        elif proto == "bb84f":
            aut = (qa.adv_unentangled(j, 2) if who == "unentangled" else
                   f_budget(j, cfg["table"], cfg["size"], cfg["pairs"]) if who == "budget" else f_linear(j, cfg["table"], cfg["size"]))
        else:
            aut = classical_relay(j, n)
        pos = [round((c + p) / 2, 12) for c, p in zip(claim, v["position"])]
        _add(doc, f"E{j}", "adversary", f"Adversary E{j}", pos, aut, caps, radius,
             params={"policy": "breidbart"} if who == "unentangled" and proto == "bb84f" and j == 0 else {},
             group="coalition")
    pairs = (mub.qubits_for(cfg["d"]) if proto == "qudit" and who == "teleport" else
             cfg["pairs"] if proto == "bb84f" and who == "budget" else 1 if proto == "bb84f" and who == "linear" else 0)
    doc["resources"] += [{"id": f"epr{i}", "type": "epr", "state": "phi+", "werner_p": 0,
                          "holders": [{"node": "E0", "slot": f"out{i}"}, {"node": "E1", "slot": f"in{i}"}]}
                         for i in range(pairs)]


def build(protocol: str = "qudit", who: str = "honest", d: int = 4, n_bits: int = 2, f: str = "inner_product",
          pairs: Optional[int] = None, processing_ns: float = 0.2, displacement_m: float = 1.0, **geometry) -> Dict[str, Any]:
    """A runnable project for one of the protocols; ``geometry`` is passed to the BB84 builder
    (dim, verifiers, radius_m, claim, tolerance_ns, seed)."""
    if protocol == "bb84":
        attack = "none" if who in ("honest", "displaced") else who
        return build_bb84(prover=who if who in ("honest", "displaced") else "honest", attack=attack,
                          processing_ns=processing_ns, displacement_m=displacement_m, **geometry)
    if protocol not in PROTOCOLS:
        raise ValueError(f"protocol must be one of {', '.join(PROTOCOLS)}")
    if protocol == "bb84f" and geometry.get("dim", 1) != 1:
        raise ValueError("QPV_BB84^f is built for two verifiers on a line (dim 1)")
    doc = build_bb84(prover="none", attack="none", **geometry)
    vids = verifier_ids(doc)
    n = len(vids)
    shared = next(r for r in doc["resources"] if r["type"] == "shared_random")
    cfg: Dict[str, Any] = {"protocol": protocol}
    if protocol == "qudit":
        mub.qubits_for(int(d))
        cfg["d"] = int(d)
        v0 = qudit_verifier(cfg["d"])
        shared["vars"] = {"x": f"rand_int(0, {cfg['d'] - 1})", "shares": "[" + ", ".join([f"rand_int(0, {cfg['d']})"] * (n - 1)) + "]"}
        name = f"Qudit QPV, d = {cfg['d']} ({cfg['d'] + 1} bases)"
    elif protocol == "bb84f":
        n_bits = int(n_bits)
        if not 1 <= n_bits <= 4:
            raise ValueError("n (bits per string) must be between 1 and 4")
        size = 2 ** n_bits
        cfg.update(n_bits=n_bits, size=size, f=f, table=f_table(f, n_bits, geometry.get("seed", 7)),
                   pairs=size if pairs is None else max(0, min(size, int(pairs))))
        v0 = f_verifier(cfg["table"], size)
        shared["vars"] = {"x": "rand_bit()", "xs": f"rand_int(0, {size - 1})", "shares": f"[rand_int(0, {size - 1})]"}
        name = f"QPV_BB84^f, f = {f}, n = {n_bits}"
    else:
        v0 = classical_pv_verifier()
        shared["vars"] = {"x": "0", "shares": "[" + ", ".join(["rand_bit()"] * n) + "]"}
        name = f"Classical position verification, {n} verifiers"
    doc["automata"] = {}
    for p in doc["participants"]:
        if p["id"] == vids[0]:
            p["automaton"] = v0["name"]
            p["verifier_type"] = "classical" if protocol == "classical" else "quantum"
            p["label"] = f"Verifier {p['id']}" + ("" if protocol == "classical" else " (qubit)")
            if protocol == "classical":
                p["params"]["share_index"] = n - 1
        else:
            p["automaton"] = "qpv_verifier_classical" if protocol != "classical" else v0["name"]
    doc["automata"][v0["name"]] = v0
    if protocol != "classical":
        cv = qa.classical_verifier()
        doc["automata"][cv["name"]] = cv
    doc["meta"]["qpv"] = cfg
    doc["meta"]["name"] = name
    doc["meta"]["protocol"]["name"] = {"qudit": "QPV qudit MUB", "bb84f": "QPV_BB84^f", "classical": "classical PV"}[protocol]
    _answerers(doc, who, processing_ns, displacement_m)
    return autowire(normalize(doc))


def switch(project: Dict[str, Any], who: str) -> Dict[str, Any]:
    """Replace whoever answers (prover or attackers), keeping the verifiers and the protocol settings."""
    doc = normalize(copy.deepcopy(project))
    keep = set(verifier_ids(doc))
    gone = {p["id"] for p in doc["participants"] if p["id"] not in keep}
    doc["participants"] = [p for p in doc["participants"] if p["id"] in keep]
    doc["resources"] = [r for r in doc["resources"] if r["type"] != "epr"]
    doc["links"] = [lk for lk in doc["links"] if not {lk["a"]["node"], lk["b"]["node"]} & gone]
    used = {p["automaton"] for p in doc["participants"]}
    doc["automata"] = {k: v for k, v in doc["automata"].items() if k in used}
    _answerers(doc, who)
    return autowire(doc)


def set_pairs(project: Dict[str, Any], pairs: int) -> Dict[str, Any]:
    """The QPV_BB84^f budget attack with a different number of EPR pairs."""
    doc = normalize(copy.deepcopy(project))
    if protocol_of(doc) != "bb84f":
        raise ValueError("the pairs setting belongs to the QPV_BB84^f protocol")
    doc["meta"]["qpv"]["pairs"] = max(0, min(doc["meta"]["qpv"]["size"], int(round(float(pairs)))))
    return switch(doc, "budget")


def reference(project: Dict[str, Any], who: str) -> Optional[Dict[str, Any]]:
    """Theory for a noise-free round of a non-BB84 protocol (None where no simple formula applies)."""
    proto, cfg = protocol_of(project), (project.get("meta") or {}).get("qpv") or {}
    n = len(verifier_ids(project))
    if who not in PROTOCOLS.get(proto, {}).get("answerers", []):
        return None
    if who == "honest":
        return {"value": 1.0, "source": "a noise-free honest prover always answers correctly in time"}
    if who == "displaced":
        return {"value": 0.0, "source": "the timing check rejects a prover away from the claim"}
    if proto == "qudit":
        d = cfg["d"]
        return {"guess": {"value": (1 / d) ** n, "source": f"(1/{d})^{n}: an independent guess for each verifier"},
                "unentangled": {"value": 2 / (d + 1), "source": f"guess one of {d + 1} bases: 1/{d + 1} + {d}/{d + 1} x 1/{d} "
                                "(this simple strategy, not a proven optimum)"},
                "teleport": {"value": 1.0, "source": f"teleporting the qudit with {mub.qubits_for(d)} EPR pair(s)"}}[who]
    if proto == "bb84f":
        size, pairs = cfg["size"], cfg["pairs"]
        return {"guess": {"value": 0.25, "source": "(1/2)^2: a random bit for each verifier"},
                "unentangled": {"value": BREIDBART, "source": "cos^2(pi/8), Breidbart measurement (Tomamichel et al. 2013)"},
                "budget": {"value": pairs / size + (1 - pairs / size) * BREIDBART,
                           "source": f"{pairs} of {size} strings x are covered by a pair; the rest fall back to Breidbart"},
                "linear": {"value": 1.0, "source": "one EPR pair: f = parity(x) xor parity(y) is linear"}}[who]
    return {"guess": {"value": 0.5 ** n, "source": f"(1/2)^{n}: a random bit for each verifier"},
            "relay": {"value": 1.0, "source": "colluders without any quantum resources (Chandran et al. 2009)"}}[who]


def entanglement_budget(n_bits: int) -> Dict[str, Any]:
    """What QPV_BB84^f asks of the honest prover and of the generic attack, for strings of n bits."""
    size = 2 ** n_bits
    return {"n_bits": n_bits, "honest_qubits": 1, "honest_classical_bits": 2 * n_bits, "generic_attack_pairs": size,
            "note": "The generic teleportation attack needs one EPR pair per possible string x (2^n). Bluhm, Christandl "
                    "& Speelman (2022) prove that for most functions f, attackers need a number of qubits that grows "
                    "linearly in n; no attack with that little entanglement is known."}


# ================================================================ side-by-side comparison
def _cell(base: Dict[str, Any], who: str) -> Dict[str, Any]:
    return {"recipe": {"base": {"dim": 1, **base, "who": who}, "twists": []}, "who": who}


COMPARISON: Dict[str, Any] = {
    "columns": [{"id": "honest", "label": "Honest prover"},
                {"id": "guess", "label": "Cheaters who guess"},
                {"id": "unentangled", "label": "Cheaters without entanglement"},
                {"id": "entangled", "label": "Cheaters with entanglement"}],
    "rows": [
        {"label": "BB84 (2 bases)", "cells": {"honest": _cell({}, "honest"), "guess": _cell({}, "guess"),
                                              "unentangled": _cell({}, "unentangled"), "entangled": _cell({}, "teleport")}},
        {"label": "Six-state (qudit d = 2, 3 bases)", "cells": {
            c: _cell({"protocol": "qudit", "qudit_d": 2}, w) for c, w in
            (("honest", "honest"), ("guess", "guess"), ("unentangled", "unentangled"), ("entangled", "teleport"))}},
        {"label": "Qudit d = 4 (5 bases)", "cells": {
            c: _cell({"protocol": "qudit", "qudit_d": 4}, w) for c, w in
            (("honest", "honest"), ("guess", "guess"), ("unentangled", "unentangled"), ("entangled", "teleport"))}},
        {"label": "Qudit d = 8 (9 bases)", "cells": {
            c: _cell({"protocol": "qudit", "qudit_d": 8}, w) for c, w in
            (("honest", "honest"), ("guess", "guess"), ("unentangled", "unentangled"), ("entangled", "teleport"))}},
        {"label": "BB84^f, f = xor, n = 3 (attack: 1 pair)", "cells": {
            c: _cell({"protocol": "bb84f", "f": "xor", "f_bits": 3}, w) for c, w in
            (("honest", "honest"), ("guess", "guess"), ("unentangled", "unentangled"), ("entangled", "linear"))}},
        {"label": "BB84^f, random f, n = 3 (attack: 1 of 8 pairs)", "cells": {
            c: _cell({"protocol": "bb84f", "f": "random", "f_bits": 3, "pairs": 1}, w) for c, w in
            (("honest", "honest"), ("guess", "guess"), ("unentangled", "unentangled"), ("entangled", "budget"))}},
        {"label": "Classical position verification", "cells": {
            "honest": _cell({"protocol": "classical"}, "honest"), "guess": _cell({"protocol": "classical"}, "guess"),
            "unentangled": _cell({"protocol": "classical"}, "relay"), "entangled": None}},
    ],
    "note": "Each cell is a one-dimensional setup with two verifiers, run many times. 'With entanglement' is the "
            "attack the workbench has for that protocol: teleportation for BB84 and qudits, one EPR pair for a linear "
            "f, and the budget attack with a single pair for a random f (with 2^n pairs it wins every round). Classical "
            "colluders need no quantum resources at all.",
}


def compare_cell(recipe: Dict[str, Any], rounds: int = 300, seed: int = 21) -> Dict[str, Any]:
    from ..experiments import run_experiment
    from .presets import answerer, reference as preset_reference
    from .recipe import compose
    doc = compose(recipe)
    s = run_experiment(doc, {"runs": int(rounds), "seed": int(seed)})["points"][0]["summary"]
    who = answerer(doc)
    ref = preset_reference(doc, who) if who else None
    return {"n": s["n"], "accepted": s["accepted"], **{k: s["acceptance"][k] for k in ("p", "lo", "hi")},
            "theory": ref["value"] if ref else None, "source": ref["source"] if ref else ""}

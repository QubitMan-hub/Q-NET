"""The n-verifier QPV_BB84^f protocol family and its attacks, as automata (plain JSON data).

Protocol.  One quantum verifier sends the BB84 qubit H^b|x>; k classical verifiers each send a share
s_i of the basis, so b = f(s_1, ..., s_k) only exists where all shares meet: the claimed position.
Every verifier times its emission so all signals reach the claim at the same instant and accepts iff
the answer equals x and arrives by its light-speed deadline.  With k = 1 and f = identity this is
QPV_BB84 (Kent, Munro & Spiller, PRA 84, 012326, 2011; Lau & Lo, PRA 83, 012322, 2011); the classical
function generalisation is QPV_BB84^f (Bluhm, Christandl & Speelman, "A single-qubit position
verification protocol that is secure against multi-qubit attacks", Nature Physics 18, 623, 2022).

f is pluggable (``combine`` parameter): ``xor`` (shares are bits) or ``inner_product`` (shares are
n-bit strings, b = sum_j prod_i s_i[j] mod 2).  XOR is breakable with k EPR pairs by the
teleportation chain below and does NOT inherit the Bluhm-Christandl-Speelman security guarantee:
they prove security against attackers holding a linear number of qubits for most functions f
(e.g. a random f), not for every f, and certainly not for XOR.

Attacks (one attacker E_j on each verifier's segment to the claim):
* unentangled -- E_0 measures the qubit at once (Breidbart basis by default) and broadcasts the bit;
  the others forward their shares to E_0, and everyone answers the bit once it has its partners'
  message, so answers arrive exactly when an honest prover's would; colluders without entanglement win at most cos^2(pi/8) of QPV_BB84 rounds (Tomamichel,
  Fehr, Kaniewski & Wehner, NJP 15, 103002, 2013);
* teleportation chain (xor only) -- the Clifford teleportation attack (Buhrman et al., "Position-based
  quantum cryptography: impossibility and constructions", SIAM J. Comput. 43(1), 2014), extended to
  low-T-depth circuits by Speelman (TQC 2016): E_j and E_j+1 share an EPR pair; E_0 teleports the
  qubit into the chain, E_j applies H^{s_j} on its half and teleports on, the last attacker measures in
  Z; after one round of broadcast everyone corrects with the propagated Pauli frame.  It always wins;
  with zero processing it lands exactly on the deadline in 1D and has slack in 2D and 3D;
* guess -- answer a random bit (succeeds with probability (1/2)^n).

Conventions used by the scenario builder, timing analysis and auto-wiring: verifiers talk on port
``prover`` and arm a timer named ``deadline``; the shared random variables are ``x`` and ``shares``;
share messages are tagged ``theta``; the honest prover answers verifier j on port ``v{j}``; attacker
E_j talks to its verifier on ``verifier`` and to attacker E_i on ``p{i}``.
"""

from __future__ import annotations

from typing import Any, Dict, List

REF_BB84 = [
    "A. Kent, W. J. Munro, T. P. Spiller, 'Quantum tagging: authenticating location via quantum "
    "information and relativistic signalling constraints', Phys. Rev. A 84, 012326 (2011); arXiv:1008.2147",
    "H.-K. Lau, H.-K. Lo, 'Insecurity of position-based quantum-cryptography protocols against "
    "entanglement attacks', Phys. Rev. A 83, 012322 (2011); arXiv:1009.2256",
    "H. Buhrman, N. Chandran, S. Fehr, R. Gelles, V. Goyal, R. Ostrovsky, C. Schaffner, "
    "'Position-based quantum cryptography: impossibility and constructions', SIAM J. Comput. 43(1) "
    "(2014); arXiv:1009.2490",
    "M. Tomamichel, S. Fehr, J. Kaniewski, S. Wehner, 'A monogamy-of-entanglement game with "
    "applications to device-independent quantum cryptography', New J. Phys. 15, 103002 (2013); "
    "arXiv:1210.4359",
    "A. Bluhm, M. Christandl, F. Speelman, 'A single-qubit position verification protocol that is secure "
    "against multi-qubit attacks', Nature Physics 18, 623 (2022); arXiv:2104.06301",
]

COMBINES = ("xor", "inner_product")
POLICY_BASIS = "'angle' if policy == 'breidbart' else (rand_choice(['Z', 'X']) if policy == 'random' else policy)"


def _state(sid, kind, label, y, x=0, outcome=None):
    s = {"id": sid, "kind": kind, "label": label, "ui": {"x": x, "y": y}}
    return {**s, "outcome": outcome} if outcome else s


def _automaton(name, role, description, ports, transitions, states, params=None, variables=None,
               port_kinds=None) -> Dict[str, Any]:
    spec = {"name": name, "role": role, "description": description, "ports": ports,
            "params": params or {}, "variables": variables or {}, "initial": states[0]["id"],
            "states": states, "transitions": transitions}
    return {**spec, "port_kinds": port_kinds} if port_kinds else spec


def _send_all(ports: List[str], tag: str, value: str) -> List[Dict[str, Any]]:
    return [{"op": "send", "port": p, "tag": tag, "value": value} for p in ports]


# ================================================================ verifiers
def _verifier(kind: str, emit: List[Dict[str, Any]], description: str, params: Dict[str, Any]) -> Dict[str, Any]:
    deadline_ns = "str(round(deadline_fs / 1e6, 6))"
    record = [{"op": "cancel_timer", "name": "deadline"},
              {"op": "record", "key": "response_ns", "value": "msg.time"},
              {"op": "record", "key": "rtt_ns", "value": "msg.time - sent_at"}]
    return _automaton(
        f"qpv_verifier_{kind}", "verifier",
        description + " Times its signal to reach the claimed position at t_ref and accepts iff the answer "
                      "equals x and arrives by t_ref + d(V, claim)/c + tolerance (local clock, integer fs).",
        ["prover"],
        [
            {"id": "arm", "from": "idle", "to": "armed", "trigger": {"type": "start"}, "label": "schedule challenge",
             "duration_ns": 0, "actions": [
                 {"op": "set", "var": "deadline_fs", "expr": "fs(t_ref_ns) + claim_travel_fs + fs(tolerance_ns)"},
                 {"op": "timer", "name": "emit", "at_fs": "fs(t_ref_ns) - claim_travel_fs"}]},
            {"id": "emit", "from": "armed", "to": "waiting", "trigger": {"type": "timer", "name": "emit"},
             "label": "send challenge", "duration_ns": 0, "actions": emit + [
                 {"op": "set", "var": "sent_at", "expr": "now"},
                 {"op": "record", "key": "challenge_sent_ns", "value": "now"},
                 {"op": "record", "key": "deadline_ns", "value": "deadline_fs / 1e6"},
                 {"op": "timer", "name": "deadline", "at_fs": "deadline_fs"}]},
            {"id": "accept", "from": "waiting", "to": "accepted",
             "trigger": {"type": "receive", "tags": ["answer"], "port": "prover"},
             "guard": "msg.value == x and msg.time_fs <= deadline_fs", "label": "correct & on time",
             "duration_ns": 0, "actions": record + [
                 {"op": "verdict", "outcome": "accept",
                  "reason": "'correct answer ' + str(msg.value) + ' received at ' + str(round(msg.time, 6)) + "
                            f"' ns <= deadline ' + {deadline_ns} + ' ns'"}]},
            {"id": "wrong", "from": "waiting", "to": "rejected",
             "trigger": {"type": "receive", "tags": ["answer"], "port": "prover"}, "label": "wrong answer",
             "duration_ns": 0, "actions": record + [
                 {"op": "verdict", "outcome": "reject",
                  "reason": "'wrong answer ' + str(msg.value) + ' (expected ' + str(x) + ')'"}]},
            {"id": "timeout", "from": "waiting", "to": "rejected", "trigger": {"type": "timer", "name": "deadline"},
             "label": "deadline passed", "duration_ns": 0, "actions": [
                 {"op": "verdict", "outcome": "reject",
                  "reason": f"'no answer by the deadline ' + {deadline_ns} + ' ns'"}]},
        ],
        [_state("idle", "initial", "Idle", 0), _state("armed", "normal", "Armed", 140),
         _state("waiting", "normal", "Awaiting answer", 290),
         _state("accepted", "terminal", "Accept", 470, -300, "accept"),
         _state("rejected", "terminal", "Reject", 470, 300, "reject")],
        params={"t_ref_ns": {"default": 20.0, "description": "Agreed time at which all challenges reach the claimed position."},
                "tolerance_ns": {"default": 0.5, "description": "Allowed processing time of the prover (deadline slack)."},
                **params},
        variables={"x": 0, "shares": [0], "deadline_fs": 0, "sent_at": 0.0},
        port_kinds={"prover": ["quantum", "classical"] if kind == "quantum" else ["classical"]})


def quantum_verifier() -> Dict[str, Any]:
    return _verifier("quantum", [
        {"op": "prepare_bb84", "qubit": "q", "bit": "x", "basis": "combine(combine, shares)"},
        {"op": "send_qubit", "port": "prover", "tag": "q", "qubit": "q"},
    ], "Quantum verifier: sends the BB84 qubit H^b|x>, with b = combine(shares).",
        {"combine": {"default": "xor", "description": "How the classical shares form the basis: xor | inner_product."}})


def classical_verifier() -> Dict[str, Any]:
    return _verifier("classical", [
        {"op": "send", "port": "prover", "tag": "theta", "value": "shares[share_index]"},
    ], "Classical verifier: sends its share of the basis.",
        {"share_index": {"default": 0, "description": "Which of the shared basis shares this verifier sends."}})


# ================================================================ honest prover
def honest_prover(n: int) -> Dict[str, Any]:
    ports = [f"v{j}" for j in range(n)]
    return _automaton(
        f"qpv_prover_{n}v", "prover",
        f"Honest prover for {n} verifiers: waits for the qubit and all {n - 1} basis shares, measures the "
        "qubit in basis combine(shares) and sends the outcome to every verifier.",
        ports,
        [{"id": "respond", "from": "waiting", "to": "done", "label": "measure & answer",
          "trigger": {"type": "receive", "tags": ["q"] + ["theta"] * (n - 1)},
          "actions": [{"op": "measure", "qubit": "q", "basis": "combine(combine, received.theta)", "result": "answer"}]
          + _send_all(ports, "answer", "answer")}],
        [_state("waiting", "initial", "Await challenges", 0), _state("done", "terminal", "Answered", 160, outcome="done")],
        params={"combine": {"default": "xor", "description": "Must match the verifiers' combine function."}},
        variables={"answer": 0})


# ================================================================ attacks
def _attacker(name, description, ports, transitions, states, **kw):
    return _automaton(name, "adversary", description, ["verifier"] + ports, transitions, states, **kw)


def adv_unentangled(j: int, n: int) -> Dict[str, Any]:
    """E_0 measures the qubit immediately and broadcasts; the others forward their shares and repeat it."""
    states = [_state("intercept", "initial", "Intercept challenge", 0), _state("relayed", "normal", "Await partners", 130),
              _state("done", "terminal", "Answered", 260, outcome="done")]
    if j == 0:
        partners = [f"p{i}" for i in range(1, n)]
        return _attacker(
            f"qpv_adv_unentangled_q_{n}v",
            "Unentangled colluder next to the quantum verifier: measures the qubit at once with the configured "
            "policy, sends the outcome to its partners and answers it once their shares arrive.", partners,
            [{"id": "measure", "from": "intercept", "to": "relayed", "label": "measure & broadcast",
              "trigger": {"type": "receive", "tags": ["q"], "port": "verifier"},
              "actions": [{"op": "measure", "qubit": "q", "basis": POLICY_BASIS, "angle": "pi / 8", "result": "m"}]
              + _send_all(partners, "m", "m")},
             {"id": "answer", "from": "relayed", "to": "done", "label": "answer",
              "trigger": {"type": "receive", "tags": ["theta"] * (n - 1)},
              "actions": _send_all(["verifier"], "answer", "m")}],
            states,
            params={"policy": {"default": "breidbart",
                               "description": "breidbart | Z | X | random (basis for measuring the qubit)"}},
            variables={"m": 0})
    return _attacker(
        "qpv_adv_unentangled_c",
        "Unentangled colluder next to a classical verifier: forwards its share to its partner and answers the "
        "partner's measurement outcome.", ["p0"],
        [{"id": "forward", "from": "intercept", "to": "relayed", "label": "forward share",
          "trigger": {"type": "receive", "tags": ["theta"], "port": "verifier"},
          "actions": _send_all(["p0"], "theta", "msg.value")},
         {"id": "answer", "from": "relayed", "to": "done", "label": "answer",
          "trigger": {"type": "receive", "tags": ["m"], "port": "p0"},
          "actions": _send_all(["verifier"], "answer", "msg.value")}],
        states)


def adv_chain(j: int, n: int) -> Dict[str, Any]:
    """Member j of the teleportation chain E_0 .. E_k (k = n - 1, xor shares only)."""
    k = n - 1
    partners = [f"p{i}" for i in range(n) if i != j]
    tag = f"e{j}"

    def info(i):  # (b0, b1) of teleport i, s_i, and the final outcome m, as seen by E_j
        if i == j:
            return {"b": ("b0", "b1"), "s": "s", "m": "m"}
        v = f"msgs.e{i}.value"
        return {"b": (f"{v}[0]", f"{v}[1]") if i == 0 else (f"{v}[1]", f"{v}[2]"), "s": f"{v}[0]", "m": f"{v}[1]"}

    decode = [{"op": "set", "var": "fx", "expr": "0"}, {"op": "set", "var": "fz", "expr": "0"}]
    for i in range(k):  # teleport i adds X^b1 Z^b0; H^{s_i+1} then swaps the X and Z parts of the frame
        b0, b1 = info(i)["b"]
        s = info(i + 1)["s"]
        decode += [{"op": "set", "var": "fx", "expr": f"fx ^ {b1}"}, {"op": "set", "var": "fz", "expr": f"fz ^ {b0}"},
                   {"op": "set", "var": "t", "expr": "fx"}, {"op": "set", "var": "fx", "expr": f"fz if {s} else fx"},
                   {"op": "set", "var": "fz", "expr": f"t if {s} else fz"}]
    decode += _send_all(["verifier"], "answer", f"{info(k)['m']} ^ fx")

    if j == 0:
        steps = [("teleport", None, ["q"], [{"op": "bell_measure", "qubits": ["q", "out"], "results": ["b0", "b1"]}],
                  "[b0, b1]")]
    elif j < k:
        bell = [{"op": "bell_measure", "qubits": ["in", "out"], "results": ["b0", "b1"]}]
        steps = [("teleport_h", "msg.value == 1", ["theta"], [{"op": "gate", "gate": "H", "qubits": "in"}] + bell,
                  "[s, b0, b1]"),
                 ("teleport", None, ["theta"], bell, "[s, b0, b1]")]
    else:
        steps = [("measure", None, ["theta"], [{"op": "measure", "qubit": "in", "basis": "s", "result": "m"}], "[s, m]")]
    first = [{"id": tid, "from": "intercept", "to": "relayed", "label": tid.replace("_", " "), "guard": guard,
              "trigger": {"type": "receive", "tags": tags, "port": "verifier"},
              "actions": ([] if j == 0 else [{"op": "set", "var": "s", "expr": "msg.value"}]) + acts
              + _send_all(partners, tag, value)}
             for tid, guard, tags, acts, value in steps]
    for t in first:
        if t["guard"] is None:
            del t["guard"]
    return _attacker(
        f"qpv_adv_chain{j}_{n}v",
        f"Teleportation-chain attacker {j} of {k}: " + ("teleports the intercepted qubit into the chain" if j == 0
        else "applies H^share to its EPR half and teleports it on" if j < k else "measures its EPR half in basis share")
        + "; after one round of broadcast it decodes x from the Pauli frame and answers its verifier.",
        partners,
        first + [{"id": "decode", "from": "relayed", "to": "done", "label": "decode & answer",
                  "trigger": {"type": "receive", "tags": [f"e{i}" for i in range(n) if i != j]}, "actions": decode}],
        [_state("intercept", "initial", "Intercept challenge", 0), _state("relayed", "normal", "Await partners", 130),
         _state("done", "terminal", "Answered", 260, outcome="done")],
        variables={v: 0 for v in ("s", "b0", "b1", "m", "fx", "fz", "t")})


def adv_guess() -> Dict[str, Any]:
    done = _state("done", "terminal", "Answered", 140, outcome="done")
    guess = [{"op": "set", "var": "g", "expr": "rand_bit()"}] + _send_all(["verifier"], "answer", "g")
    return _attacker(
        "qpv_adv_guess", "Guessing attacker: answers a random bit as soon as its verifier's challenge arrives.", [],
        [{"id": "guess_q", "from": "idle", "to": "done", "trigger": {"type": "receive", "tags": ["q"]}, "label": "guess",
          "actions": [{"op": "discard", "qubit": "q"}] + guess},
         {"id": "guess_share", "from": "idle", "to": "done", "trigger": {"type": "receive", "tags": ["theta"]},
          "label": "guess", "actions": guess}],
        [_state("idle", "initial", "Idle", 0), done], variables={"g": 0})

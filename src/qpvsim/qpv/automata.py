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

import copy
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


def keyed(value: str) -> str:
    """An answer expression that carries the shared key when verifiers demand one (key_bits > 0); use it after
    :data:`KEY_PICK`, which sets ``k`` to the key, or to one guess of it for a party without the key."""
    return f"{value} if key_bits == 0 else [{value}, k]"


KEY_PICK = {"op": "set", "var": "k", "expr": "key if key else rand_bits(key_bits)"}


KEY_PARAM = {"key_bits": {"default": 0, "min": 0,
                          "description": "Bits of shared key to attach to each answer; set with the verifiers'."}}


# ================================================================ verifiers
def _verifier(kind: str, emit: List[Dict[str, Any]], description: str, params: Dict[str, Any]) -> Dict[str, Any]:
    deadline_ns = "str(round(deadline_fs / 1e6, 6))"
    record = [{"op": "cancel_timer", "name": "deadline"},
              {"op": "record", "key": "response_ns", "value": "msg.time"},
              {"op": "record", "key": "rtt_ns", "value": "msg.time - sent_at"}]
    return _automaton(
        f"qpv_verifier_{kind}", "verifier",
        description + " Times its signal to reach the claimed position at the meeting time t_meet and accepts "
                      "iff the answer equals x (with the shared key, when key_bits > 0) and arrives by t_meet + d(V, claim)/c + tolerance (local clock, "
                      "integer fs). t_meet is t_ref, moved later when the farthest verifier could only make "
                      "t_ref by sending before t = 0. extra_delay_ns compensates a slower path; with allow_loss_reports a "
                      "'nophoton' reply ends the round as lost.",
        ["prover"],
        [
            {"id": "arm", "from": "idle", "to": "armed", "trigger": {"type": "start"}, "label": "schedule challenge",
             "duration_ns": 0, "actions": [
                 {"op": "set", "var": "t_meet_fs", "expr": "max(fs(t_ref_ns), max_claim_travel_fs + fs(1))"},
                 {"op": "set", "var": "expected", "expr": "x if key_bits == 0 else [x, key]"},
                 {"op": "record", "key": "meeting_ns", "value": "t_meet_fs / 1e6"},
                 {"op": "set", "var": "deadline_fs",
                  "expr": "t_meet_fs + claim_travel_fs + fs(extra_delay_ns) + fs(tolerance_ns)"},
                 {"op": "timer", "name": "emit", "at_fs": "t_meet_fs - claim_travel_fs - fs(extra_delay_ns)"}]},
            {"id": "emit", "from": "armed", "to": "waiting", "trigger": {"type": "timer", "name": "emit"},
             "label": "send challenge", "duration_ns": 0, "actions": emit + [
                 {"op": "set", "var": "sent_at", "expr": "now"},
                 {"op": "record", "key": "challenge_sent_ns", "value": "now"},
                 {"op": "record", "key": "deadline_ns", "value": "deadline_fs / 1e6"},
                 {"op": "timer", "name": "deadline", "at_fs": "deadline_fs"}]},
            {"id": "accept", "from": "waiting", "to": "accepted",
             "trigger": {"type": "receive", "tags": ["answer"], "port": "prover"},
             "guard": "msg.value == expected and msg.time_fs <= deadline_fs",
             "label": "correct & on time",
             "duration_ns": 0, "actions": record + [
                 {"op": "verdict", "outcome": "accept",
                  "reason": "'correct answer ' + str(msg.value) + ' received at ' + str(round(msg.time, 6)) + "
                            f"' ns <= deadline ' + {deadline_ns} + ' ns'"}]},
            {"id": "wrong", "from": "waiting", "to": "rejected",
             "trigger": {"type": "receive", "tags": ["answer"], "port": "prover"}, "label": "wrong answer",
             "duration_ns": 0, "actions": record + [
                 {"op": "verdict", "outcome": "reject",
                  "reason": "'wrong answer ' + str(msg.value) + ' (expected ' + str(x) + ')'"}]},
            {"id": "lost", "from": "waiting", "to": "rejected",
             "trigger": {"type": "receive", "tags": ["nophoton"], "port": "prover"}, "guard": "allow_loss_reports",
             "label": "no photon reported", "duration_ns": 0, "actions": [
                 {"op": "cancel_timer", "name": "deadline"}, {"op": "record", "key": "lost", "value": "1"},
                 {"op": "verdict", "outcome": "reject", "reason": "'the prover reported that no photon arrived'"}]},
            {"id": "timeout", "from": "waiting", "to": "rejected", "trigger": {"type": "timer", "name": "deadline"},
             "label": "deadline passed", "duration_ns": 0, "actions": [
                 {"op": "verdict", "outcome": "reject",
                  "reason": f"'no answer by the deadline ' + {deadline_ns} + ' ns'"}]},
        ],
        [_state("idle", "initial", "Idle", 0), _state("armed", "normal", "Armed", 140),
         _state("waiting", "normal", "Awaiting answer", 290),
         _state("accepted", "terminal", "Accept", 470, -300, "accept"),
         _state("rejected", "terminal", "Reject", 470, 300, "reject")],
        params={"t_ref_ns": {"default": 20.0, "description": "Agreed time at which all challenges reach the claimed "
                                                            "position; moved later if a verifier is too far away to make it."},
                "tolerance_ns": {"default": 0.5, "min": 0,
                                 "description": "Allowed processing time of the prover (deadline slack)."},
                "extra_delay_ns": {"default": 0.0, "min": 0,
                                   "description": "Extra one-way delay of this verifier's path to the claim beyond "
                                                  "straight-line light speed (fibre, electronics): it sends that much "
                                                  "earlier and waits that much longer."},
                "allow_loss_reports": {"default": False,
                                       "description": "Accept a 'nophoton' reply as a lost round instead of waiting "
                                                      "for an answer."},
                "key_bits": {"default": 0, "min": 0,
                             "description": "Answers must carry the round's shared secret key of this many bits "
                                          "(0 = no key). The key is shared out of band with the genuine prover."},
                **params},
        variables={"x": 0, "shares": [0], "t_meet_fs": 0, "deadline_fs": 0, "sent_at": 0.0, "key": [], "expected": 0},
        port_kinds={"prover": ["quantum", "classical"] if kind.startswith("quantum") else ["classical"]})


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
def basis_measure(shares: str, bases: int = 2) -> Dict[str, Any]:
    """The measure action an honest party uses once it holds all basis shares."""
    if bases == 2:
        return {"op": "measure", "qubit": "q", "basis": f"combine(combine, {shares})", "result": "answer"}
    return {"op": "measure", "qubit": "q", "basis": "'angle'", "angle": f"pi * (sum({shares}) % bases) / (2 * bases)",
            "result": "answer"}


def honest_prover(n: int, bases: int = 2, report_loss: bool = False) -> Dict[str, Any]:
    """Waits for the qubit and all basis shares, measures and answers every verifier.

    ``bases > 2``: the basis is one of ``bases`` equally spaced bases in the X-Z plane (index = sum of the shares
    mod bases).  ``report_loss``: if the shares arrive and no photon is detected within a short window, the prover
    answers 'nophoton' instead of staying silent."""
    ports = [f"v{j}" for j in range(n)]
    name = f"qpv_prover_{n}v" + (f"_{bases}b" if bases != 2 else "") + ("_reports_loss" if report_loss else "")
    params = {"combine": {"default": "xor", "description": "Must match the verifiers' combine function."}, **KEY_PARAM}
    if bases != 2:
        params["bases"] = {"default": bases, "min": 2, "description": "Number of measurement bases (must match V0)."}
    answer = [KEY_PICK] + _send_all(ports, "answer", keyed("answer"))
    transitions = [{"id": "respond", "from": "waiting", "to": "done", "label": "measure & answer",
                    "trigger": {"type": "receive", "tags": ["q"] + ["theta"] * (n - 1)},
                    "actions": [basis_measure("received.theta", bases)] + answer}]
    states = [_state("waiting", "initial", "Await challenges", 0), _state("done", "terminal", "Answered", 160, outcome="done")]
    variables = {"answer": 0, "key": [], "k": []}
    if report_loss:
        params["click_window_ns"] = {"default": 0.01, "min": 0,
                                     "description": "How long after the shares the detector may still click."}
        variables["sh"] = [0]
        transitions += [
            {"id": "shares_first", "from": "waiting", "to": "listening", "label": "shares here, photon not yet",
             "trigger": {"type": "receive", "tags": ["theta"] * (n - 1)}, "duration_ns": 0,
             "actions": [{"op": "set", "var": "sh", "expr": "received.theta"},
                         {"op": "timer", "name": "click_window", "after_ns": "click_window_ns"}]},
            {"id": "photon", "from": "listening", "to": "done", "label": "photon clicks: measure & answer",
             "trigger": {"type": "receive", "tags": ["q"]},
             "actions": [{"op": "cancel_timer", "name": "click_window"}, basis_measure("sh", bases)] + answer},
            {"id": "no_click", "from": "listening", "to": "done", "label": "no click: report no photon",
             "trigger": {"type": "timer", "name": "click_window"}, "actions": _send_all(ports, "nophoton", "0")}]
        states.insert(1, _state("listening", "normal", "Listening for the photon", 80, x=200))
    return _automaton(
        name, "prover",
        f"Honest prover for {n} verifiers: waits for the qubit and all {n - 1} basis shares, measures the qubit in "
        + ("basis combine(shares)" if bases == 2 else f"the shares' basis (one of {bases})")
        + " and sends the outcome to every verifier" + ("; reports 'nophoton' when nothing clicks." if report_loss else "."),
        ports, transitions, states, params=params, variables=variables)


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


def _shares_expr(n: int, own: int = 0, own_var: str = "s") -> str:
    """The basis shares as E_own sees them after the broadcast: its own share plus its partners' messages."""
    return "[" + ", ".join(own_var if i == own else f"msgs.e{i}.value" for i in range(1, n)) + "]"


def adv_split(j: int, n: int) -> Dict[str, Any]:
    """Photon-splitting colluders: with an n-photon pulse each attacker gets its own copy of the BB84 state."""
    partners = [f"p{i}" for i in range(n) if i != j]
    states = [_state("intercept", "initial", "Intercept challenge", 0), _state("relayed", "normal", "Await partners", 130),
              _state("done", "terminal", "Answered", 260, outcome="done")]
    kinds = {"verifier": ["quantum", "classical"], **{p: ["quantum", "classical"] for p in partners}}
    if j == 0:
        copies = ["q"] + [f"q{i + 1}" for i in range(1, n)]
        return _attacker(
            f"qpv_adv_split_q_{n}v",
            "Photon-splitting colluder next to the quantum verifier: keeps one photon of a multi-photon pulse, hands "
            "one copy to each partner, and measures its own once all basis shares have arrived.", partners,
            [{"id": "split", "from": "intercept", "to": "relayed", "label": "keep one, pass copies on",
              "trigger": {"type": "receive", "tags": copies, "port": "verifier"},
              "actions": [{"op": "send_qubit", "port": f"p{i}", "tag": f"c{i}", "qubit": f"q{i + 1}"} for i in range(1, n)]},
             {"id": "answer", "from": "relayed", "to": "done", "label": "measure & answer",
              "trigger": {"type": "receive", "tags": [f"e{i}" for i in range(1, n)]},
              "actions": [{"op": "measure", "qubit": "q", "basis": f"combine(combine, {_shares_expr(n, -1)})",
                           "result": "m"}] + _send_all(["verifier"], "answer", "m")}],
            states, params={"combine": {"default": "xor", "description": "Must match the verifiers' combine function."}},
            variables={"m": 0}, port_kinds=kinds)
    return _attacker(
        f"qpv_adv_split{j}_{n}v",
        f"Photon-splitting colluder {j}: broadcasts its verifier's share, then measures the copy it was handed in the "
        "full basis.", partners,
        [{"id": "share", "from": "intercept", "to": "relayed", "label": "broadcast share",
          "trigger": {"type": "receive", "tags": ["theta"], "port": "verifier"},
          "actions": [{"op": "set", "var": "s", "expr": "msg.value"}] + _send_all(partners, f"e{j}", "s")},
         {"id": "answer", "from": "relayed", "to": "done", "label": "measure the copy & answer",
          "trigger": {"type": "receive", "tags": [f"c{j}"] + [f"e{i}" for i in range(1, n) if i != j]},
          "actions": [{"op": "measure", "qubit": f"c{j}", "basis": f"combine(combine, {_shares_expr(n, j)})",
                       "result": "m"}] + _send_all(["verifier"], "answer", "m")}],
        states, params={"combine": {"default": "xor", "description": "Must match the verifiers' combine function."}},
        variables={"s": 0, "m": 0}, port_kinds=kinds)


def adv_lossy(j: int, n: int, bases: int = 2) -> Dict[str, Any]:
    """Selective-loss colluders: guess the basis, and report 'no photon' whenever the guess was wrong.
    With more than two bases the guess is right only 1/bases of the time."""
    partners = [f"p{i}" for i in range(n) if i != j]
    states = [_state("intercept", "initial", "Intercept challenge", 0), _state("relayed", "normal", "Await partners", 130),
              _state("done", "terminal", "Answered", 260, outcome="done")]
    kinds = {"verifier": ["quantum", "classical"] if j == 0 else ["classical"], **{p: ["classical"] for p in partners}}
    others = [f"e{i}" for i in range(n) if i != j]
    true_basis = (lambda own: f"combine(combine, {_shares_expr(n, own)})") if bases == 2 else \
        (lambda own: f"sum({_shares_expr(n, own)}) % bases")
    if j == 0:
        basis, guess, bit = true_basis(-1), "g", "m"
        measure = ({"op": "measure", "qubit": "q", "basis": "g", "result": "m"} if bases == 2 else
                   {"op": "measure", "qubit": "q", "basis": "'angle'", "angle": "pi * g / (2 * bases)", "result": "m"})
        first = {"id": "guess", "from": "intercept", "to": "relayed", "label": "guess basis & measure",
                 "trigger": {"type": "receive", "tags": ["q"], "port": "verifier"},
                 "actions": [{"op": "set", "var": "g", "expr": "rand_bit()" if bases == 2 else "rand_int(0, bases - 1)"},
                             measure] + _send_all(partners, "e0", "[g, m]")}
    else:
        basis, guess, bit = true_basis(j), "msgs.e0.value[0]", "msgs.e0.value[1]"
        first = {"id": "share", "from": "intercept", "to": "relayed", "label": "broadcast share",
                 "trigger": {"type": "receive", "tags": ["theta"], "port": "verifier"},
                 "actions": [{"op": "set", "var": "s", "expr": "msg.value"}] + _send_all(partners, f"e{j}", "s")}
    params = {"combine": {"default": "xor", "description": "Must match the verifiers' combine function."}}
    if bases != 2:
        params["bases"] = {"default": bases, "min": 2, "description": "Number of bases (must match V0)."}
    return _attacker(
        f"qpv_adv_lossy{j}_{n}v" + (f"_{bases}b" if bases != 2 else ""),
        "Selective-loss colluder: the attacker next to the quantum verifier guesses the basis and measures at once; "
        "once all shares are known, everyone answers if the guess was right and reports 'no photon' otherwise.",
        partners,
        [first,
         {"id": "answer", "from": "relayed", "to": "done", "label": "guess was right: answer",
          "trigger": {"type": "receive", "tags": others}, "guard": f"{guess} == {basis}",
          "actions": _send_all(["verifier"], "answer", bit)},
         {"id": "claim_loss", "from": "relayed", "to": "done", "label": "guess was wrong: report no photon",
          "trigger": {"type": "receive", "tags": others}, "actions": _send_all(["verifier"], "nophoton", "0")}],
        states, params=params, variables={"s": 0, "g": 0, "m": 0}, port_kinds=kinds)


def quantum_verifier_bases(bases: int) -> Dict[str, Any]:
    """Quantum verifier choosing one of ``bases`` equally spaced bases in the X-Z plane of the Bloch sphere:
    basis j holds the states RY(j pi / bases)|x>, measured in the real basis at angle j pi / (2 bases)."""
    v = _verifier("quantum_bases", [
        {"op": "prepare_bb84", "qubit": "q", "bit": "x", "basis": "0"},
        {"op": "gate", "gate": "RY", "qubits": "q", "angle": "pi * (sum(shares) % bases) / bases"},
        {"op": "send_qubit", "port": "prover", "tag": "q", "qubit": "q"},
    ], f"Quantum verifier with {bases} bases: sends RY(j pi / {bases})|x>, j = sum of the shares mod {bases}.",
        {"bases": {"default": bases, "min": 2, "description": "Number of bases; the classical verifiers send shares "
                                                             "in 0..bases-1."},
         "combine": {"default": "xor", "description": "Unused with more than two bases (the shares are summed)."}})
    v["name"] = f"qpv_verifier_quantum_{bases}b"
    return v


def _photon_block(v: Dict[str, Any]) -> tuple:
    emit = next(t for t in v["transitions"] if t["id"] == "emit")
    k = next(i for i, a in enumerate(emit["actions"]) if a.get("var") == "sent_at")
    return emit, k


def _copies(block: List[Dict[str, Any]], k: int) -> List[Dict[str, Any]]:
    """The photon-making actions repeated for photons 2..k (slot and tag q2, q3, ...)."""
    out = []
    for i in range(2, k + 1):
        for a in block:
            b = dict(a)
            if b.get("qubit") == "q" or b.get("qubits") == "q":
                b["qubit" if "qubit" in b else "qubits"] = f"q{i}"
            if b.get("tag") == "q":
                b["tag"] = f"q{i}"
            out.append(b)
    return out


def multi_photon_verifier(k: int, base: Dict[str, Any] = None) -> Dict[str, Any]:
    """The quantum verifier with a source that emits k identical photons per pulse (tags q, q2, ..., qk)."""
    v = copy.deepcopy(base) if base else quantum_verifier()
    v["name"] = f"{v['name']}_{k}ph"
    v["description"] = f"Quantum verifier whose source emits {k} identical photons per pulse. " + v["description"]
    emit, n = _photon_block(v)
    emit["actions"][n:n] = _copies(emit["actions"][:n], k)
    return v


def source_verifier(k: int, mean_photons: float, base: Dict[str, Any] = None) -> Dict[str, Any]:
    """A weak laser: each pulse holds Poisson(mean_photons) photons; 0, 1, or k identical photons are sent
    (k copies stand for 'two or more', which is all a photon-splitting attack needs)."""
    v = copy.deepcopy(base) if base else quantum_verifier()
    v["name"] = f"{v['name']}_laser"
    v["description"] = ("Quantum verifier with a weak laser source: each pulse holds a Poisson number of photons "
                        "(mean 'mean_photons'); empty pulses send nothing. " + v["description"])
    v["params"]["mean_photons"] = {"default": mean_photons, "min": 0,
                                   "description": "Average photons per pulse (Poisson); 2 or more are copies."}
    v["variables"].update({"n_ph": 1, "u": 0.0})
    arm = next(t for t in v["transitions"] if t["id"] == "arm")
    arm["actions"][:0] = [
        {"op": "set", "var": "u", "expr": "rand_uniform()"},
        {"op": "set", "var": "n_ph", "expr": "0 if u < exp(-mean_photons) else (1 if u < exp(-mean_photons) * "
                                             "(1 + mean_photons) else 2)"},
        {"op": "record", "key": "photons", "value": "n_ph"}]
    emit, n = _photon_block(v)
    block, rest = emit["actions"][:n], emit["actions"][n:]
    i = v["transitions"].index(emit)
    variants = [("emit_empty", "n_ph == 0", rest, "empty pulse"), ("emit", "n_ph == 1", block + rest, "send one photon"),
                ("emit_many", "n_ph >= 2", block + _copies(block, k) + rest, f"send {k} photons")]
    v["transitions"][i:i + 1] = [{**copy.deepcopy(emit), "id": tid, "guard": g, "label": lab, "actions": copy.deepcopy(acts)}
                                 for tid, g, acts, lab in variants]
    return v

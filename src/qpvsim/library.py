"""Reference protocols, strategies and scenarios.

Everything here is *data*: automata and projects in the documented JSON
format, executed by the generic engine.  Nothing in the engine is specific to
these protocols.

Protocols
---------
QPV_BB84 (1-D, two verifiers).  Kent, Munro & Spiller (PRA 84, 012326, 2011);
Lau & Lo (PRA 83, 012322, 2011); analysed by Buhrman et al. (SIAM J. Comput.
43(1), 2014) and Tomamichel, Fehr, Kaniewski & Wehner (NJP 15, 103002, 2013).
Verifiers V0, V1 share random bits x, theta.  V0 sends the BB84 qubit
H^theta|x>, V1 sends theta, timed to arrive simultaneously at the claimed
position.  The prover measures in basis theta and returns x to both verifiers,
who accept iff both answers are correct and arrive by the light-speed deadline.

Known attacks reproduced here (statements from the cited literature):
* colluding adversaries **without** entanglement win a single round with
  probability at most cos^2(pi/8) ~= 0.854 (Tomamichel et al. 2013); the
  measure-in-the-Breidbart-basis-and-broadcast strategy attains it;
* guessing the basis (or measuring in a fixed basis) gives 3/4;
* with **one pre-shared EPR pair** the teleportation attack wins with
  probability 1 (Kent-Munro-Spiller 2011; Lau-Lo 2011; Buhrman et al. 2014),
  provided the adversaries' processing fits inside the verifiers' tolerance.

Classical PV (Chandran, Goyal, Moriarty & Ostrovsky, CRYPTO 2009): verifiers
send random bits x0, x1; the prover returns x0 XOR x1.  Two colluding
adversaries break it by copying and forwarding, which the scenarios show.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
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
]
REF_CPV = [
    "N. Chandran, V. Goyal, R. Moriarty, R. Ostrovsky, 'Position based cryptography', CRYPTO 2009, "
    "LNCS 5677; ePrint 2009/364",
]

COMMON_ASSUMPTIONS = [
    "One spatial dimension in effect: all participants lie on the x axis; signals travel on "
    "straight lines at the configured speed (default: vacuum speed of light).",
    "Verifiers are trusted, know their own positions and the claimed position exactly, share "
    "private randomness (x, theta) established before t=0, and have synchronised clocks unless "
    "clock offsets/drift are configured.",
    "Verifiers decide offline after the round; the final decision combines both verdicts "
    "with the rule 'all must accept'.",
    "One simulation run = one protocol round; acceptance probabilities are estimated over many "
    "independent runs (experiments).",
]
COMMON_LIMITATIONS = [
    "Simulation results are evidence about the modelled behaviour only; they are not security proofs.",
    "No special/general-relativistic effects beyond a finite signal speed; no clock-synchronisation "
    "protocol is modelled (offsets/drift are fixed parameters).",
    "Qubit loss makes QPV_BB84 attackable by provers who may claim loss; this model treats a "
    "missing answer as a rejection and does not model loss-tolerant variants.",
    "Adversary strategies are the specific automata supplied; the simulator does not search over "
    "all strategies, so observed success rates are lower bounds on what attackers can achieve.",
]


# ================================================================ automata
def _verifier(kind: str) -> Dict[str, Any]:
    """QPV_BB84 verifier; kind 'quantum' sends the qubit, 'classical' sends theta."""
    if kind == "quantum":
        emit = [
            {"op": "prepare_bb84", "qubit": "q", "bit": "x", "basis": "theta"},
            {"op": "send_qubit", "port": "prover", "tag": "q", "qubit": "q"},
        ]
        desc = "QPV_BB84 verifier that sends the BB84 qubit H^theta|x>."
    else:
        emit = [{"op": "send", "port": "prover", "tag": "theta", "value": "theta"}]
        desc = "QPV_BB84 verifier that sends the basis bit theta classically."
    return {
        "name": f"qpv_bb84_verifier_{kind}",
        "role": "verifier",
        "description": desc + " Accepts iff the answer equals x and arrives by the deadline "
                              "t_ref + d(V, claim)/c + tolerance (local clock).",
        "ports": ["prover"],
        "params": {
            "t_ref_ns": {"default": 20.0, "description": "Agreed time at which both challenges reach the claimed position."},
            "tolerance_ns": {"default": 0.5, "description": "Allowed processing time of the prover (deadline slack)."},
        },
        "variables": {"x": 0, "theta": 0, "send_at": 0.0, "deadline": 0.0, "sent_at": 0.0},
        "initial": "idle",
        "states": [
            {"id": "idle", "kind": "initial", "label": "Idle", "ui": {"x": 0, "y": 0}},
            {"id": "armed", "kind": "normal", "label": "Armed", "ui": {"x": 0, "y": 140},
             "description": "Waiting for the emission instant."},
            {"id": "waiting", "kind": "normal", "label": "Awaiting answer", "ui": {"x": 0, "y": 290}},
            {"id": "accepted", "kind": "terminal", "outcome": "accept", "label": "Accept", "ui": {"x": -300, "y": 470}},
            {"id": "rejected", "kind": "terminal", "outcome": "reject", "label": "Reject", "ui": {"x": 300, "y": 470}},
        ],
        "transitions": [
            {"id": "arm", "from": "idle", "to": "armed", "trigger": {"type": "start"},
             "label": "schedule challenge",
             "duration_ns": 0,
             "actions": [
                 {"op": "set", "var": "send_at", "expr": "fs_round(t_ref_ns - claim_travel_ns)"},
                 {"op": "set", "var": "deadline", "expr": "fs_round(t_ref_ns + claim_travel_ns + tolerance_ns)"},
                 {"op": "timer", "name": "emit", "at_ns": "send_at"},
             ]},
            {"id": "emit", "from": "armed", "to": "waiting", "trigger": {"type": "timer", "name": "emit"},
             "label": "send challenge", "duration_ns": 0,
             "actions": emit + [
                 {"op": "set", "var": "sent_at", "expr": "now"},
                 {"op": "record", "key": "challenge_sent_ns", "value": "now"},
                 {"op": "record", "key": "deadline_ns", "value": "deadline"},
                 {"op": "timer", "name": "deadline", "at_ns": "deadline"},
             ]},
            {"id": "accept", "from": "waiting", "to": "accepted",
             "trigger": {"type": "receive", "tags": ["answer"], "port": "prover"},
             "guard": "msg.value == x and msg.time <= deadline",
             "label": "correct & on time", "duration_ns": 0,
             "actions": [
                 {"op": "cancel_timer", "name": "deadline"},
                 {"op": "record", "key": "response_ns", "value": "msg.time"},
                 {"op": "record", "key": "rtt_ns", "value": "msg.time - sent_at"},
                 {"op": "verdict", "outcome": "accept",
                  "reason": "'correct answer ' + str(msg.value) + ' received at ' + str(round(msg.time, 6)) + "
                            "' ns <= deadline ' + str(round(deadline, 6)) + ' ns'"},
             ]},
            {"id": "wrong", "from": "waiting", "to": "rejected",
             "trigger": {"type": "receive", "tags": ["answer"], "port": "prover"},
             "label": "wrong answer", "duration_ns": 0,
             "actions": [
                 {"op": "cancel_timer", "name": "deadline"},
                 {"op": "record", "key": "response_ns", "value": "msg.time"},
                 {"op": "record", "key": "rtt_ns", "value": "msg.time - sent_at"},
                 {"op": "verdict", "outcome": "reject",
                  "reason": "'wrong answer ' + str(msg.value) + ' (expected ' + str(x) + ')'"},
             ]},
            {"id": "timeout", "from": "waiting", "to": "rejected",
             "trigger": {"type": "timer", "name": "deadline"},
             "label": "deadline passed", "duration_ns": 0,
             "actions": [
                 {"op": "verdict", "outcome": "reject",
                  "reason": "'no answer by the deadline ' + str(round(deadline, 6)) + ' ns'"},
             ]},
        ],
    }


def bb84_honest_prover() -> Dict[str, Any]:
    return {
        "name": "qpv_bb84_honest_prover",
        "role": "prover",
        "description": "Honest QPV_BB84 prover: waits for both the qubit and theta, measures the "
                       "qubit in basis theta and broadcasts the outcome to both verifiers.",
        "ports": ["left", "right"],
        "params": {},
        "variables": {"answer": 0},
        "initial": "waiting",
        "states": [
            {"id": "waiting", "kind": "initial", "label": "Await challenges", "ui": {"x": 0, "y": 0}},
            {"id": "done", "kind": "terminal", "outcome": "done", "label": "Answered", "ui": {"x": 0, "y": 160}},
        ],
        "transitions": [
            {"id": "respond", "from": "waiting", "to": "done",
             "trigger": {"type": "receive", "tags": ["q", "theta"]},
             "label": "measure & answer",
             "actions": [
                 {"op": "measure", "qubit": "q", "basis": "msgs.theta.value", "result": "answer"},
                 {"op": "send", "port": "left", "tag": "answer", "value": "answer"},
                 {"op": "send", "port": "right", "tag": "answer", "value": "answer"},
             ]},
        ],
    }


def bb84_adv_near_unentangled() -> Dict[str, Any]:
    """Adversary next to the quantum verifier: measures, broadcasts, answers its outcome."""
    return {
        "name": "qpv_bb84_adv_measure_broadcast",
        "role": "adversary",
        "description": "Colluding adversary near the qubit-sending verifier (no entanglement). "
                       "Measures the intercepted qubit immediately with the configured policy, "
                       "sends the outcome to its partner, and answers the outcome once theta "
                       "arrives from the partner (simultaneous-message model).",
        "ports": ["verifier", "partner"],
        "params": {
            "policy": {"default": "breidbart",
                       "description": "breidbart | Z | X | random (basis choice for measuring the qubit)"},
        },
        "variables": {"m": 0},
        "initial": "intercept",
        "states": [
            {"id": "intercept", "kind": "initial", "label": "Intercept qubit", "ui": {"x": 0, "y": 0}},
            {"id": "measured", "kind": "normal", "label": "Await theta", "ui": {"x": 0, "y": 130}},
            {"id": "done", "kind": "terminal", "outcome": "done", "label": "Answered", "ui": {"x": 0, "y": 260}},
        ],
        "transitions": [
            {"id": "measure", "from": "intercept", "to": "measured",
             "trigger": {"type": "receive", "tags": ["q"], "port": "verifier"},
             "label": "measure & broadcast",
             "actions": [
                 {"op": "measure", "qubit": "q",
                  "basis": "'angle' if policy == 'breidbart' else (rand_choice(['Z', 'X']) if policy == 'random' else policy)",
                  "angle": "pi / 8", "result": "m"},
                 {"op": "send", "port": "partner", "tag": "m", "value": "m"},
             ]},
            {"id": "answer", "from": "measured", "to": "done",
             "trigger": {"type": "receive", "tags": ["theta"], "port": "partner"},
             "label": "answer",
             "actions": [{"op": "send", "port": "verifier", "tag": "answer", "value": "m"}]},
        ],
    }


def bb84_adv_far_unentangled() -> Dict[str, Any]:
    return {
        "name": "qpv_bb84_adv_forward_basis",
        "role": "adversary",
        "description": "Colluding adversary near the classical verifier (no entanglement): forwards "
                       "theta to its partner and answers with the partner's measurement outcome.",
        "ports": ["verifier", "partner"],
        "params": {},
        "variables": {},
        "initial": "intercept",
        "states": [
            {"id": "intercept", "kind": "initial", "label": "Intercept theta", "ui": {"x": 0, "y": 0}},
            {"id": "forwarded", "kind": "normal", "label": "Await outcome", "ui": {"x": 0, "y": 130}},
            {"id": "done", "kind": "terminal", "outcome": "done", "label": "Answered", "ui": {"x": 0, "y": 260}},
        ],
        "transitions": [
            {"id": "forward", "from": "intercept", "to": "forwarded",
             "trigger": {"type": "receive", "tags": ["theta"], "port": "verifier"},
             "label": "forward theta",
             "actions": [{"op": "send", "port": "partner", "tag": "theta", "value": "msg.value"}]},
            {"id": "answer", "from": "forwarded", "to": "done",
             "trigger": {"type": "receive", "tags": ["m"], "port": "partner"},
             "label": "answer",
             "actions": [{"op": "send", "port": "verifier", "tag": "answer", "value": "msg.value"}]},
        ],
    }


def bb84_adv_teleport_near() -> Dict[str, Any]:
    return {
        "name": "qpv_bb84_adv_teleport_sender",
        "role": "adversary",
        "description": "Teleportation attack, adversary near the qubit-sending verifier: Bell-measures "
                       "the intercepted qubit with its EPR half 'e' (teleporting it to the partner), "
                       "sends both outcomes, and corrects the partner's result once (theta, m) arrives. "
                       "x = m XOR (b1 if theta == 0 else b0).",
        "ports": ["verifier", "partner"],
        "params": {},
        "variables": {"b0": 0, "b1": 0},
        "initial": "intercept",
        "states": [
            {"id": "intercept", "kind": "initial", "label": "Intercept qubit", "ui": {"x": 0, "y": 0}},
            {"id": "teleported", "kind": "normal", "label": "Await (theta, m)", "ui": {"x": 0, "y": 130}},
            {"id": "done", "kind": "terminal", "outcome": "done", "label": "Answered", "ui": {"x": 0, "y": 260}},
        ],
        "transitions": [
            {"id": "teleport", "from": "intercept", "to": "teleported",
             "trigger": {"type": "receive", "tags": ["q"], "port": "verifier"},
             "label": "Bell measurement",
             "actions": [
                 {"op": "bell_measure", "qubits": ["q", "e"], "results": ["b0", "b1"]},
                 {"op": "send", "port": "partner", "tag": "corr", "value": "[b0, b1]"},
             ]},
            {"id": "answer", "from": "teleported", "to": "done",
             "trigger": {"type": "receive", "tags": ["tm"], "port": "partner"},
             "label": "correct & answer",
             "actions": [
                 {"op": "send", "port": "verifier", "tag": "answer",
                  "value": "msg.value[1] ^ (b1 if msg.value[0] == 0 else b0)"},
             ]},
        ],
    }


def bb84_adv_teleport_far() -> Dict[str, Any]:
    return {
        "name": "qpv_bb84_adv_teleport_receiver",
        "role": "adversary",
        "description": "Teleportation attack, adversary near the classical verifier: on theta, "
                       "measures its EPR half 'e' in basis theta, sends (theta, m) to its partner, "
                       "and corrects with the partner's Bell outcomes.",
        "ports": ["verifier", "partner"],
        "params": {},
        "variables": {"th": 0, "m": 0},
        "initial": "intercept",
        "states": [
            {"id": "intercept", "kind": "initial", "label": "Intercept theta", "ui": {"x": 0, "y": 0}},
            {"id": "measured", "kind": "normal", "label": "Await corrections", "ui": {"x": 0, "y": 130}},
            {"id": "done", "kind": "terminal", "outcome": "done", "label": "Answered", "ui": {"x": 0, "y": 260}},
        ],
        "transitions": [
            {"id": "measure", "from": "intercept", "to": "measured",
             "trigger": {"type": "receive", "tags": ["theta"], "port": "verifier"},
             "label": "measure EPR half",
             "actions": [
                 {"op": "set", "var": "th", "expr": "msg.value"},
                 {"op": "measure", "qubit": "e", "basis": "th", "result": "m"},
                 {"op": "send", "port": "partner", "tag": "tm", "value": "[th, m]"},
             ]},
            {"id": "answer", "from": "measured", "to": "done",
             "trigger": {"type": "receive", "tags": ["corr"], "port": "partner"},
             "label": "correct & answer",
             "actions": [
                 {"op": "send", "port": "verifier", "tag": "answer",
                  "value": "m ^ (msg.value[1] if th == 0 else msg.value[0])"},
             ]},
        ],
    }


def bb84_adv_guess() -> Dict[str, Any]:
    return {
        "name": "qpv_bb84_adv_guess",
        "role": "adversary",
        "description": "Fabricating adversary: answers a uniformly random bit as soon as it sees any "
                       "challenge, without using the qubit (expected success 1/2 per verifier).",
        "ports": ["verifier"],
        "params": {},
        "variables": {"g": 0},
        "initial": "idle",
        "states": [
            {"id": "idle", "kind": "initial", "label": "Idle", "ui": {"x": 0, "y": 0}},
            {"id": "done", "kind": "terminal", "outcome": "done", "label": "Answered", "ui": {"x": 0, "y": 140}},
        ],
        "transitions": [
            {"id": "guess_q", "from": "idle", "to": "done",
             "trigger": {"type": "receive", "tags": ["q"]}, "label": "guess",
             "actions": [{"op": "discard", "qubit": "q"}, {"op": "set", "var": "g", "expr": "rand_bit()"},
                         {"op": "send", "port": "verifier", "tag": "answer", "value": "g"}]},
            {"id": "guess_theta", "from": "idle", "to": "done",
             "trigger": {"type": "receive", "tags": ["theta"]}, "label": "guess",
             "actions": [{"op": "set", "var": "g", "expr": "rand_bit()"},
                         {"op": "send", "port": "verifier", "tag": "answer", "value": "g"}]},
        ],
    }


# ---------------------------------------------------------------- classical PV
def cpv_verifier() -> Dict[str, Any]:
    return {
        "name": "cpv_verifier",
        "role": "verifier",
        "description": "Classical position verification (Chandran et al. 2009, 1-D): sends its random "
                       "bit and accepts iff the answer x0 XOR x1 arrives by the light-speed deadline.",
        "ports": ["prover"],
        "params": {
            "t_ref_ns": {"default": 20.0, "description": "Agreed arrival time of both challenges at the claim."},
            "tolerance_ns": {"default": 0.5, "description": "Deadline slack."},
            "my_bit": {"default": "x0", "description": "Which shared bit this verifier sends: x0 or x1."},
        },
        "variables": {"x0": 0, "x1": 0, "deadline": 0.0, "sent_at": 0.0},
        "initial": "idle",
        "states": [
            {"id": "idle", "kind": "initial", "label": "Idle", "ui": {"x": 0, "y": 0}},
            {"id": "armed", "kind": "normal", "label": "Armed", "ui": {"x": 0, "y": 140}},
            {"id": "waiting", "kind": "normal", "label": "Awaiting answer", "ui": {"x": 0, "y": 290}},
            {"id": "accepted", "kind": "terminal", "outcome": "accept", "label": "Accept", "ui": {"x": -300, "y": 470}},
            {"id": "rejected", "kind": "terminal", "outcome": "reject", "label": "Reject", "ui": {"x": 300, "y": 470}},
        ],
        "transitions": [
            {"id": "arm", "from": "idle", "to": "armed", "trigger": {"type": "start"}, "duration_ns": 0,
             "label": "schedule challenge",
             "actions": [
                 {"op": "set", "var": "deadline", "expr": "fs_round(t_ref_ns + claim_travel_ns + tolerance_ns)"},
                 {"op": "timer", "name": "emit", "at_ns": "fs_round(t_ref_ns - claim_travel_ns)"}]},
            {"id": "emit", "from": "armed", "to": "waiting", "trigger": {"type": "timer", "name": "emit"},
             "duration_ns": 0, "label": "send bit",
             "actions": [
                 {"op": "send", "port": "prover", "tag": "bit", "value": "x0 if my_bit == 'x0' else x1"},
                 {"op": "set", "var": "sent_at", "expr": "now"},
                 {"op": "record", "key": "challenge_sent_ns", "value": "now"},
                 {"op": "record", "key": "deadline_ns", "value": "deadline"},
                 {"op": "timer", "name": "deadline", "at_ns": "deadline"}]},
            {"id": "accept", "from": "waiting", "to": "accepted",
             "trigger": {"type": "receive", "tags": ["answer"], "port": "prover"},
             "guard": "msg.value == (x0 ^ x1) and msg.time <= deadline", "duration_ns": 0,
             "label": "correct & on time",
             "actions": [
                 {"op": "cancel_timer", "name": "deadline"},
                 {"op": "record", "key": "response_ns", "value": "msg.time"},
                 {"op": "record", "key": "rtt_ns", "value": "msg.time - sent_at"},
                 {"op": "verdict", "outcome": "accept", "reason": "'correct XOR received on time'"}]},
            {"id": "wrong", "from": "waiting", "to": "rejected",
             "trigger": {"type": "receive", "tags": ["answer"], "port": "prover"}, "duration_ns": 0,
             "label": "wrong answer",
             "actions": [
                 {"op": "cancel_timer", "name": "deadline"},
                 {"op": "record", "key": "response_ns", "value": "msg.time"},
                 {"op": "verdict", "outcome": "reject", "reason": "'wrong answer ' + str(msg.value)"}]},
            {"id": "timeout", "from": "waiting", "to": "rejected",
             "trigger": {"type": "timer", "name": "deadline"}, "duration_ns": 0, "label": "deadline passed",
             "actions": [{"op": "verdict", "outcome": "reject", "reason": "'no answer by the deadline'"}]},
        ],
    }


def cpv_prover_ports() -> Dict[str, Any]:
    """Honest classical-PV prover distinguishing the two bits by port."""
    return {
        "name": "cpv_prover",
        "role": "prover",
        "description": "Honest classical-PV prover: waits for one bit on each port and returns their "
                       "XOR to both verifiers.",
        "ports": ["left", "right"],
        "params": {},
        "variables": {"left_bit": 0, "r": 0},
        "initial": "waiting",
        "states": [
            {"id": "waiting", "kind": "initial", "label": "Await left bit", "ui": {"x": 0, "y": 0}},
            {"id": "half", "kind": "normal", "label": "Await right bit", "ui": {"x": 0, "y": 130}},
            {"id": "done", "kind": "terminal", "outcome": "done", "label": "Answered", "ui": {"x": 0, "y": 260}},
        ],
        "transitions": [
            {"id": "left", "from": "waiting", "to": "half",
             "trigger": {"type": "receive", "tags": ["bit"], "port": "left"}, "duration_ns": 0,
             "label": "store left bit",
             "actions": [{"op": "set", "var": "left_bit", "expr": "msg.value"}]},
            {"id": "respond", "from": "half", "to": "done",
             "trigger": {"type": "receive", "tags": ["bit"], "port": "right"}, "label": "xor & answer",
             "actions": [
                 {"op": "set", "var": "r", "expr": "left_bit ^ msg.value"},
                 {"op": "send", "port": "left", "tag": "answer", "value": "r"},
                 {"op": "send", "port": "right", "tag": "answer", "value": "r"}]},
        ],
    }


def cpv_adversary() -> Dict[str, Any]:
    return {
        "name": "cpv_adv_copy_forward",
        "role": "adversary",
        "description": "Colluding classical adversary: copies the intercepted bit to its partner, and "
                       "answers the XOR once the partner's copy arrives (Chandran et al. 2009 attack).",
        "ports": ["verifier", "partner"],
        "params": {},
        "variables": {"mine": 0},
        "initial": "intercept",
        "states": [
            {"id": "intercept", "kind": "initial", "label": "Intercept bit", "ui": {"x": 0, "y": 0}},
            {"id": "forwarded", "kind": "normal", "label": "Await copy", "ui": {"x": 0, "y": 130}},
            {"id": "done", "kind": "terminal", "outcome": "done", "label": "Answered", "ui": {"x": 0, "y": 260}},
        ],
        "transitions": [
            {"id": "copy", "from": "intercept", "to": "forwarded",
             "trigger": {"type": "receive", "tags": ["bit"], "port": "verifier"}, "label": "copy & forward",
             "actions": [
                 {"op": "set", "var": "mine", "expr": "msg.value"},
                 {"op": "send", "port": "partner", "tag": "copy", "value": "msg.value"}]},
            {"id": "answer", "from": "forwarded", "to": "done",
             "trigger": {"type": "receive", "tags": ["copy"], "port": "partner"}, "label": "xor & answer",
             "actions": [{"op": "send", "port": "verifier", "tag": "answer", "value": "mine ^ msg.value"}]},
        ],
    }


# ================================================================ projects
def _participant(pid, role, label, x, automaton, caps, ui, params=None, processing_ns=0.0, **extra):
    d = {"id": pid, "role": role, "label": label, "position": [float(x), 0.0], "automaton": automaton,
         "params": params or {}, "processing_ns": processing_ns, "start_ns": 0,
         "clock": {"offset_ns": 0, "drift_ppm": 0}, "capabilities": caps, "noise": {},
         "group": None, "ui": ui}
    d.update(extra)
    return d


def _link(lid, kind, a, ap, b, bp, **extra):
    d = {"id": lid, "kind": kind, "a": {"node": a, "port": ap}, "b": {"node": b, "port": bp},
         "directed": False, "length_m": None, "speed_mps": None, "latency_ns": 0, "jitter_ns": 0,
         "loss_prob": 0, "attenuation_db_per_km": 0, "noise": {}}
    d.update(extra)
    return d


def _base(name: str, description: str, protocol: str, refs: List[str]) -> Dict[str, Any]:
    return {
        "format": "qpvsim-project",
        "version": 1,
        "meta": {
            "name": name, "description": description,
            "protocol": {"name": protocol, "version": "1.0", "references": refs},
            "assumptions": list(COMMON_ASSUMPTIONS),
            "limitations": list(COMMON_LIMITATIONS),
        },
        "physics": {"signal_speed_mps": 299_792_458, "allow_superluminal": False},
        "simulation": {"seed": 7, "backend": "density_matrix", "max_time_ns": 1000,
                       "max_events": 100_000, "stop_when": "verifiers_decided", "priorities": {}},
        "claim": {"prover": "P", "position": [0.0, 0.0]},
        "participants": [],
        "links": [],
        "resources": [],
        "automata": {},
        "verification": {"rule": "all", "verifiers": ["V0", "V1"]},
        "experiments": [],
    }


VERIFIER_PARAMS = {"t_ref_ns": 20.0, "tolerance_ns": 0.5}
V_DIST = 3.0  # metres from the claimed position to each verifier
ADV_DIST = 1.5


def _bb84_verifiers(doc: Dict[str, Any]) -> None:
    doc["automata"]["qpv_bb84_verifier_quantum"] = _verifier("quantum")
    doc["automata"]["qpv_bb84_verifier_classical"] = _verifier("classical")
    doc["participants"] += [
        _participant("V0", "verifier", "Verifier V0 (qubit)", -V_DIST, "qpv_bb84_verifier_quantum",
                     "verifier", {"x": 40, "y": 220}, dict(VERIFIER_PARAMS)),
        _participant("V1", "verifier", "Verifier V1 (basis)", V_DIST, "qpv_bb84_verifier_classical",
                     "verifier", {"x": 860, "y": 220}, dict(VERIFIER_PARAMS)),
    ]
    doc["resources"].append({"id": "vshared", "type": "shared_random", "holders": ["V0", "V1"],
                             "vars": {"x": "rand_bit()", "theta": "rand_bit()"}})


def bb84_honest(prover_x: float = 0.0, name: str = "QPV_BB84 — honest prover",
                prover_processing_ns: float = 0.2) -> Dict[str, Any]:
    displaced = prover_x != 0.0
    doc = _base(name,
                "Two verifiers on a line challenge a prover claiming position x = 0. "
                + ("The prover is actually at x = %g m (not at the claim) and follows the honest "
                   "procedure; timing reveals the displacement." % prover_x if displaced else
                   "The prover is honest and located at the claimed position."),
                "QPV_BB84", REF_BB84)
    _bb84_verifiers(doc)
    doc["automata"]["qpv_bb84_honest_prover"] = bb84_honest_prover()
    doc["participants"].append(
        _participant("P", "prover" if not displaced else "adversary",
                     "Prover P" if not displaced else "Dishonest prover P'", prover_x,
                     "qpv_bb84_honest_prover", "honest_prover" if not displaced else "no_entanglement",
                     {"x": 450, "y": 220}, processing_ns=prover_processing_ns))
    doc["links"] += [
        _link("q0", "quantum", "V0", "prover", "P", "left"),
        _link("c0", "classical", "V0", "prover", "P", "left"),
        _link("c1", "classical", "V1", "prover", "P", "right"),
    ]
    return doc


def bb84_collusion(strategy: str = "breidbart", adv_processing_ns: float = 0.0,
                   name: str | None = None) -> Dict[str, Any]:
    """Two colluding adversaries replace the prover.

    strategy: 'breidbart' | 'Z' | 'X' | 'random' (unentangled) | 'teleport' (one EPR pair).
    """
    teleport = strategy == "teleport"
    doc = _base(name or f"QPV_BB84 — colluding adversaries ({strategy})",
                "No prover is at the claimed position x = 0.  Adversary E0 sits between V0 and the "
                "claim, E1 between the claim and V1; they communicate classically at light speed. "
                + ("They pre-share one EPR pair and run the teleportation attack."
                   if teleport else
                   f"They share no entanglement; E0 measures the qubit with policy '{strategy}'."),
                "QPV_BB84", REF_BB84)
    doc["claim"]["prover"] = None
    _bb84_verifiers(doc)
    if teleport:
        a0, a1 = bb84_adv_teleport_near(), bb84_adv_teleport_far()
        caps = "bounded_entanglement"
        params0: Dict[str, Any] = {}
    else:
        a0, a1 = bb84_adv_near_unentangled(), bb84_adv_far_unentangled()
        caps = "no_entanglement"
        params0 = {"policy": strategy}
    doc["automata"][a0["name"]] = a0
    doc["automata"][a1["name"]] = a1
    doc["participants"] += [
        _participant("E0", "adversary", "Adversary E0", -ADV_DIST, a0["name"], caps,
                     {"x": 245, "y": 380}, params0, processing_ns=adv_processing_ns, group="coalition"),
        _participant("E1", "adversary", "Adversary E1", ADV_DIST, a1["name"], caps,
                     {"x": 655, "y": 380}, {}, processing_ns=adv_processing_ns, group="coalition"),
    ]
    doc["links"] += [
        _link("q0", "quantum", "V0", "prover", "E0", "verifier"),
        _link("c0", "classical", "V0", "prover", "E0", "verifier"),
        _link("c1", "classical", "V1", "prover", "E1", "verifier"),
        _link("cE", "classical", "E0", "partner", "E1", "partner"),
    ]
    if teleport:
        doc["resources"].append({"id": "epr", "type": "epr", "state": "phi+", "werner_p": 0,
                                 "holders": [{"node": "E0", "slot": "e"}, {"node": "E1", "slot": "e"}]})
    doc["meta"]["assumptions"] = doc["meta"]["assumptions"] + [
        "Adversaries control all channels between the verifiers and the claimed position.",
        "Adversary capabilities: " + ("pre-shared entanglement allowed (one EPR pair)." if teleport
                                      else "no pre-shared entanglement (profile 'no_entanglement')."),
    ]
    return doc


def cpv_honest() -> Dict[str, Any]:
    doc = _base("Classical PV — honest prover",
                "Classical 1-D position verification: verifiers send random bits x0, x1 timed to meet "
                "at the claim; the prover answers x0 XOR x1.", "Classical-PV", REF_CPV)
    _cpv_verifiers(doc)
    a = cpv_prover_ports()
    doc["automata"][a["name"]] = a
    doc["participants"].append(_participant("P", "prover", "Prover P", 0.0, a["name"], "honest_prover",
                                            {"x": 450, "y": 220}, processing_ns=0.2))
    doc["links"] += [_link("c0", "classical", "V0", "prover", "P", "left"),
                     _link("c1", "classical", "V1", "prover", "P", "right")]
    return doc


def cpv_collusion(adv_processing_ns: float = 0.0) -> Dict[str, Any]:
    doc = _base("Classical PV — colluding adversaries",
                "Two colluding adversaries copy-and-forward the verifiers' bits and answer the XOR; "
                "classical PV is insecure against such coalitions (Chandran et al. 2009).",
                "Classical-PV", REF_CPV)
    doc["claim"]["prover"] = None
    _cpv_verifiers(doc)
    a = cpv_adversary()
    doc["automata"][a["name"]] = a
    doc["participants"] += [
        _participant("E0", "adversary", "Adversary E0", -ADV_DIST, a["name"], "classical_only",
                     {"x": 245, "y": 380}, processing_ns=adv_processing_ns, group="coalition"),
        _participant("E1", "adversary", "Adversary E1", ADV_DIST, a["name"], "classical_only",
                     {"x": 655, "y": 380}, processing_ns=adv_processing_ns, group="coalition"),
    ]
    doc["links"] += [_link("c0", "classical", "V0", "prover", "E0", "verifier"),
                     _link("c1", "classical", "V1", "prover", "E1", "verifier"),
                     _link("cE", "classical", "E0", "partner", "E1", "partner")]
    return doc


def _cpv_verifiers(doc):
    doc["automata"]["cpv_verifier"] = cpv_verifier()
    doc["participants"] += [
        _participant("V0", "verifier", "Verifier V0", -V_DIST, "cpv_verifier", "verifier",
                     {"x": 40, "y": 220}, {**VERIFIER_PARAMS, "my_bit": "x0"}),
        _participant("V1", "verifier", "Verifier V1", V_DIST, "cpv_verifier", "verifier",
                     {"x": 860, "y": 220}, {**VERIFIER_PARAMS, "my_bit": "x1"}),
    ]
    doc["resources"].append({"id": "vshared", "type": "shared_random", "holders": ["V0", "V1"],
                             "vars": {"x0": "rand_bit()", "x1": "rand_bit()"}})


def _with_experiments(doc: Dict[str, Any], exps: List[Dict[str, Any]]) -> Dict[str, Any]:
    doc["experiments"] = exps
    return doc


EXAMPLES = {
    "qpv_bb84_honest": lambda: _with_experiments(bb84_honest(), [
        {"id": "noise_sweep", "name": "Acceptance vs. channel depolarisation", "runs": 400, "seed": 11,
         "sweep": [{"path": "links.q0.noise.depolarizing", "values": [0.0, 0.05, 0.1, 0.2, 0.4]}]},
        {"id": "processing_sweep", "name": "Acceptance vs. prover processing time", "runs": 50, "seed": 12,
         "sweep": [{"path": "participants.P.processing_ns", "values": [0.0, 0.25, 0.5, 0.75, 1.0]}]},
    ]),
    "qpv_bb84_displaced_prover": lambda: bb84_honest(prover_x=-1.0, name="QPV_BB84 — dishonest prover at the wrong position"),
    "qpv_bb84_collusion_unentangled": lambda: _with_experiments(bb84_collusion("breidbart"), [
        {"id": "strategies", "name": "Unentangled strategies compared", "runs": 2000, "seed": 21,
         "sweep": [{"path": "participants.E0.params.policy", "values": ["breidbart", "Z", "X", "random"]}]},
    ]),
    "qpv_bb84_teleportation_attack": lambda: _with_experiments(bb84_collusion("teleport"), [
        {"id": "timing", "name": "Teleportation attack vs. adversary processing time", "runs": 200, "seed": 31,
         "sweep": [{"path": "participants.E0.processing_ns", "values": [0.0, 0.2, 0.4, 0.6, 0.8]}]},
    ]),
    "cpv_honest": cpv_honest,
    "cpv_collusion": cpv_collusion,
}


def example(name: str) -> Dict[str, Any]:
    try:
        return copy.deepcopy(EXAMPLES[name]())
    except KeyError:
        raise KeyError(f"unknown example {name!r}; available: {sorted(EXAMPLES)}") from None


def automaton_library() -> Dict[str, Dict[str, Any]]:
    """All reusable automata (for the editor's strategy palette)."""
    out = {}
    for fn in (lambda: _verifier("quantum"), lambda: _verifier("classical"), bb84_honest_prover,
               bb84_adv_near_unentangled, bb84_adv_far_unentangled, bb84_adv_teleport_near,
               bb84_adv_teleport_far, bb84_adv_guess, cpv_verifier, cpv_prover_ports, cpv_adversary):
        a = fn()
        out[a["name"]] = a
    return out


def write_examples(directory: Path) -> List[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in EXAMPLES:
        p = directory / f"{name}.json"
        p.write_text(json.dumps(example(name), indent=2) + "\n")
        paths.append(p)
    return paths

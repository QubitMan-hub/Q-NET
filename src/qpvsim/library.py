"""Bundled example projects and the automaton library.

Everything here is *data*: automata and projects in the documented JSON format, executed by the
generic engine.  The QPV_BB84 examples are 1D instances of the n-verifier QPV_BB84^f family built by
:func:`qpvsim.qpv.scenario.build` (protocol, attacks and citations in :mod:`qpvsim.qpv.automata`).

Classical PV (Chandran, Goyal, Moriarty & Ostrovsky, CRYPTO 2009): verifiers send random bits x0, x1;
the prover returns x0 XOR x1.  Two colluding adversaries break it by copying and forwarding.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

from .qpv import automata as qa
from .qpv.scenario import base_project, build, link, participant

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


# ================================================================ classical PV automata
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

# ================================================================ projects
CPV_PARAMS = {"t_ref_ns": 20.0, "tolerance_ns": 0.5}


def _cpv(name: str, description: str) -> Dict[str, Any]:
    doc = base_project(name, description, "Classical-PV", REF_CPV)
    doc["meta"].update(assumptions=list(COMMON_ASSUMPTIONS), limitations=list(COMMON_LIMITATIONS))
    doc["verification"]["verifiers"] = ["V0", "V1"]
    doc["automata"]["cpv_verifier"] = cpv_verifier()
    doc["participants"] += [
        participant("V0", "verifier", "Verifier V0", [-3.0, 0.0], "cpv_verifier", "verifier",
                    {"x": 0, "y": 220}, {**CPV_PARAMS, "my_bit": "x0"}),
        participant("V1", "verifier", "Verifier V1", [3.0, 0.0], "cpv_verifier", "verifier",
                    {"x": 1040, "y": 220}, {**CPV_PARAMS, "my_bit": "x1"}),
    ]
    doc["resources"].append({"id": "vshared", "type": "shared_random", "holders": ["V0", "V1"],
                             "vars": {"x0": "rand_bit()", "x1": "rand_bit()"}})
    return doc


def cpv_honest() -> Dict[str, Any]:
    doc = _cpv("Classical PV — honest prover",
               "Classical 1-D position verification: verifiers send random bits x0, x1 timed to meet "
               "at the claim; the prover answers x0 XOR x1.")
    a = cpv_prover_ports()
    doc["automata"][a["name"]] = a
    doc["participants"].append(participant("P", "prover", "Prover P", [0.0, 0.0], a["name"], "honest_prover",
                                           {"x": 520, "y": 220}, processing_ns=0.2))
    doc["links"] += [link("c0", "classical", "V0", "prover", "P", "left"),
                     link("c1", "classical", "V1", "prover", "P", "right")]
    return doc


def cpv_collusion() -> Dict[str, Any]:
    doc = _cpv("Classical PV — colluding adversaries",
               "Two colluding adversaries copy-and-forward the verifiers' bits and answer the XOR; "
               "classical PV is insecure against such coalitions (Chandran et al. 2009).")
    doc["claim"]["prover"] = None
    a = cpv_adversary()
    doc["automata"][a["name"]] = a
    doc["participants"] += [
        participant(f"E{i}", "adversary", f"Adversary E{i}", [x, 0.0], a["name"], "classical_only",
                    {"x": ux, "y": 430}, group="coalition") for i, x, ux in ((0, -1.5, 300), (1, 1.5, 740))]
    doc["links"] += [link("c0", "classical", "V0", "prover", "E0", "verifier"),
                     link("c1", "classical", "V1", "prover", "E1", "verifier"),
                     link("cE", "classical", "E0", "partner", "E1", "partner")]
    return doc


def _bb84(name: str, description: str, experiments=(), extra_assumptions=(), **build_args) -> Dict[str, Any]:
    doc = build(dim=1, name=name, **build_args)
    doc["meta"].update(description=description, protocol={"name": "QPV_BB84", "version": "1.0", "references": qa.REF_BB84},
                       assumptions=COMMON_ASSUMPTIONS + list(extra_assumptions), limitations=list(COMMON_LIMITATIONS))
    doc["experiments"] = list(experiments)
    return doc


LINE = "Two verifiers on a line challenge a prover claiming position x = 0. "
COLLUDE = ("No prover is at the claimed position x = 0.  Adversary E0 sits between V0 and the claim, E1 between "
           "the claim and V1; they communicate classically at light speed. ")
CONTROL = "Adversaries control all channels between the verifiers and the claimed position."

EXAMPLES = {
    "qpv_bb84_honest": lambda: _bb84(
        "QPV_BB84 — honest prover", LINE + "The prover is honest and located at the claimed position.", [
            {"id": "noise_sweep", "name": "Acceptance vs. channel depolarisation", "runs": 400, "seed": 11,
             "sweep": [{"path": "links.q0.noise.depolarizing", "values": [0.0, 0.05, 0.1, 0.2, 0.4]}]},
            {"id": "processing_sweep", "name": "Acceptance vs. prover processing time", "runs": 50, "seed": 12,
             "sweep": [{"path": "participants.P.processing_ns", "values": [0.0, 0.25, 0.5, 0.75, 1.0]}]}]),
    "qpv_bb84_displaced_prover": lambda: _bb84(
        "QPV_BB84 — dishonest prover at the wrong position",
        LINE + "The prover is actually at x = -1 m (not at the claim) and follows the honest procedure; timing "
               "reveals the displacement.", prover="displaced"),
    "qpv_bb84_collusion_unentangled": lambda: _bb84(
        "QPV_BB84 — colluding adversaries (breidbart)",
        COLLUDE + "They share no entanglement; E0 measures the qubit with policy 'breidbart'.", [
            {"id": "strategies", "name": "Unentangled strategies compared", "runs": 2000, "seed": 21,
             "sweep": [{"path": "participants.E0.params.policy", "values": ["breidbart", "Z", "X", "random"]}]}],
        [CONTROL, "Adversary capabilities: no pre-shared entanglement (profile 'no_entanglement')."],
        attack="unentangled"),
    "qpv_bb84_teleportation_attack": lambda: _bb84(
        "QPV_BB84 — colluding adversaries (teleport)",
        COLLUDE + "They pre-share one EPR pair and run the teleportation attack.", [
            {"id": "timing", "name": "Teleportation attack vs. adversary processing time", "runs": 200, "seed": 31,
             "sweep": [{"path": "participants.E0.processing_ns", "values": [0.0, 0.2, 0.4, 0.6, 0.8]}]}],
        [CONTROL, "Adversary capabilities: pre-shared entanglement allowed (one EPR pair)."], attack="teleport"),
    "cpv_honest": cpv_honest,
    "cpv_collusion": cpv_collusion,
}


def example(name: str) -> Dict[str, Any]:
    try:
        return copy.deepcopy(EXAMPLES[name]())
    except KeyError:
        raise KeyError(f"unknown example {name!r}; available: {sorted(EXAMPLES)}") from None


def automaton_library() -> Dict[str, Dict[str, Any]]:
    """All reusable automata (for the editor's strategy palette): the QPV family for 2-4 verifiers and CPV."""
    autos = [qa.quantum_verifier(), qa.classical_verifier(), qa.adv_guess(), qa.adv_unentangled(1, 2)]
    for n in (2, 3, 4):
        autos += [qa.honest_prover(n), qa.adv_unentangled(0, n)] + [qa.adv_chain(j, n) for j in range(n)]
    autos += [cpv_verifier(), cpv_prover_ports(), cpv_adversary()]
    return {a["name"]: a for a in autos}


def write_examples(directory: Path) -> List[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in EXAMPLES:
        p = directory / f"{name}.json"
        p.write_text(json.dumps(example(name), indent=2) + "\n")
        paths.append(p)
    return paths

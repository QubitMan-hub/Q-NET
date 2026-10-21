"""Ready-to-run QPV scenarios: verifier geometry, prover or attackers, links and resources.

``build`` places one quantum and k classical verifiers regularly around the claimed position (1D: on a
line; 2D: a regular polygon; 3D: a regular tetrahedron, or a Fibonacci sphere beyond 4 verifiers), so
the claim is inside their convex hull, and puts either a prover or one attacker per verifier (halfway
along its segment to the claim) in place.  ``switch_attack`` swaps whoever answers while keeping the
verifiers, and ``autowire`` derives every link from the participants (see the conventions in
:mod:`qpvsim.qpv.automata`).
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Optional

from .. import timeunits as tu
from ..protocol.automaton import port_kinds
from ..protocol.project import normalize, verifier_ids
from . import automata as qa

PROVERS = ("honest", "displaced", "none")
ATTACKS = ("none", "unentangled", "teleport", "guess")
ANSWERERS = ("honest", "displaced", "unentangled", "teleport", "guess")
POLICIES = ("breidbart", "Z", "X", "random")
ATTACKER_PROFILE = {"unentangled": "no_entanglement", "guess": "no_entanglement",
                    "teleport": "bounded_entanglement", "displaced": "no_entanglement"}
LABELS = {"honest": "honest prover", "displaced": "prover at the wrong position",
          "unentangled": "unentangled attack", "teleport": "teleportation attack", "guess": "guessing attack"}
CANVAS = 520  # editor canvas units from the claim to a verifier


def participant(pid, role, label, position, automaton, caps, ui, params=None, processing_ns=0.0, **extra):
    return {"id": pid, "role": role, "label": label, "position": [float(x) for x in position],
            "automaton": automaton, "params": params or {}, "processing_ns": processing_ns, "start_ns": 0,
            "clock": {"offset_ns": 0, "drift_ppm": 0}, "capabilities": caps, "noise": {}, "group": None,
            "ui": ui, **extra}


def link(lid, kind, a, ap, b, bp, **extra):
    return {"id": lid, "kind": kind, "a": {"node": a, "port": ap}, "b": {"node": b, "port": bp}, "directed": False,
            "length_m": None, "speed_mps": None, "latency_ns": 0, "jitter_ns": 0, "loss_prob": 0,
            "attenuation_db_per_km": 0, "noise": {}, **extra}


def base_project(name: str, description: str, protocol: str, refs: List[str], max_time_ns: float = 1000,
                 seed: int = 7) -> Dict[str, Any]:
    return {
        "format": "qpvsim-project", "version": 1,
        "meta": {"name": name, "description": description,
                 "protocol": {"name": protocol, "version": "1.0", "references": refs},
                 "assumptions": [], "limitations": [
                     "Simulation results are evidence about the modelled behaviour only; they are not security proofs.",
                     "Adversary strategies are the specific automata supplied; observed success rates are lower "
                     "bounds on what attackers can achieve."]},
        "physics": {"signal_speed_mps": tu.SPEED_OF_LIGHT_MPS, "allow_superluminal": False},
        "simulation": {"seed": seed, "backend": "density_matrix", "max_time_ns": max_time_ns,
                       "max_events": 100_000, "stop_when": "verifiers_decided", "priorities": {}},
        "claim": {"prover": "P", "position": [0.0, 0.0]},
        "participants": [], "links": [], "resources": [], "automata": {},
        "verification": {"rule": "all", "verifiers": []}, "experiments": [],
    }


# ---------------------------------------------------------------- geometry
def directions(dim: int, n: int) -> List[List[float]]:
    """Unit vectors from the claim to n verifiers (the first points along -x)."""
    if dim == 1:
        return [[-1.0], [1.0]]
    if dim == 2:
        return [[math.cos(math.pi + 2 * math.pi * j / n), math.sin(math.pi + 2 * math.pi * j / n)] for j in range(n)]
    if n == 4:
        s = 1 / math.sqrt(3)
        return [[-s * a, s * b, s * c] for a, b, c in ((1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1))]
    golden = math.pi * (3 - math.sqrt(5))
    out = []
    for j in range(n):
        z = 1 - 2 * (j + 0.5) / n
        r = math.sqrt(1 - z * z)
        out.append([-r * math.cos(golden * j), r * math.sin(golden * j), z])
    return out


def _at(claim, direction, r):
    return [round(c + r * d, 12) for c, d in zip(claim, direction + [0.0] * (len(claim) - len(direction)))]


def _ui(claim, pos, radius, row=0):
    dx, dy = pos[0] - claim[0], (pos[1] - claim[1]) if len(pos) > 1 else 0.0
    return {"x": round(CANVAS + dx * CANVAS / radius), "y": round(220 - dy * CANVAS / radius) + row}


# ---------------------------------------------------------------- answerers
def qpv_verifiers(doc) -> List[Dict[str, Any]]:
    vs = [p for p in doc["participants"] if p["id"] in verifier_ids(doc)]
    kinds = [p["automaton"] for p in vs]
    if not vs or kinds[0] != "qpv_verifier_quantum" or any(k != "qpv_verifier_classical" for k in kinds[1:]):
        raise ValueError("this needs a QPV setup: a quantum verifier followed by classical verifiers from the "
                         "QPV library (build one with the scenario builder)")
    return vs


def _add_answerers(doc, answerer, policy, processing_ns, displacement_m):
    vs = qpv_verifiers(doc)
    n, claim = len(vs), doc["claim"]["position"]
    combine = vs[0]["params"].get("combine", "xor")
    radius = max(math.dist(v["position"], claim) for v in vs) or 1.0
    row = 210 if all(abs(x) < 1e-12 for v in vs for x in v["position"][1:]) else 0  # 1D: attackers below the line
    if answerer not in ANSWERERS:
        raise ValueError(f"unknown prover or attack {answerer!r}; choose from {', '.join(ANSWERERS)}")
    if answerer == "teleport" and combine != "xor":
        raise ValueError("the teleportation chain attack applies to xor shares only")
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {', '.join(POLICIES)}")
    doc["claim"]["prover"] = "P" if answerer in ("honest", "displaced") else None
    if answerer in ("honest", "displaced"):
        honest = answerer == "honest"
        pos = claim if honest else _at(claim, [-1.0], displacement_m)
        a = qa.honest_prover(n)
        doc["automata"][a["name"]] = a
        doc["participants"].append(participant(
            "P", "prover" if honest else "adversary", "Prover P" if honest else "Dishonest prover P'", pos,
            a["name"], "honest_prover" if honest else "no_entanglement", _ui(claim, pos, radius),
            {} if combine == "xor" else {"combine": combine}, processing_ns=processing_ns))
        return
    for j, v in enumerate(vs):
        a = (qa.adv_unentangled(j, n) if answerer == "unentangled" else qa.adv_chain(j, n) if answerer == "teleport"
             else qa.adv_guess())
        doc["automata"][a["name"]] = a
        pos = [round((c + p) / 2, 12) for c, p in zip(claim, v["position"])]
        doc["participants"].append(participant(
            f"E{j}", "adversary", f"Adversary E{j}", pos, a["name"], ATTACKER_PROFILE[answerer],
            _ui(claim, pos, radius, row),
            {"policy": policy} if answerer == "unentangled" and j == 0 else {}, group="coalition"))
    if answerer == "teleport":
        doc["resources"] += [{"id": f"epr{i}", "type": "epr", "state": "phi+", "werner_p": 0,
                              "holders": [{"node": f"E{i}", "slot": "out"}, {"node": f"E{i + 1}", "slot": "in"}]}
                             for i in range(n - 1)]


def build(dim: int = 2, verifiers: Optional[int] = None, radius_m: float = 3.0, claim: Optional[List[float]] = None,
          tolerance_ns: float = 0.5, combine: str = "xor", share_bits: int = 4, prover: str = "honest",
          attack: str = "none", policy: str = "breidbart", processing_ns: float = 0.2,
          displacement_m: float = 1.0, seed: int = 7, name: Optional[str] = None) -> Dict[str, Any]:
    """A complete, wired, runnable n-verifier QPV_BB84^f project (attack != none replaces the prover)."""
    n = verifiers or (2 if dim == 1 else dim + 1)
    if dim not in (1, 2, 3):
        raise ValueError("dimension must be 1, 2 or 3")
    if dim == 1 and n != 2:
        raise ValueError("a 1D setup uses exactly 2 verifiers")
    if n < 2 or radius_m <= 0:
        raise ValueError("need at least 2 verifiers and a positive radius")
    if prover not in PROVERS or attack not in ATTACKS:
        raise ValueError(f"prover must be one of {', '.join(PROVERS)} and attack one of {', '.join(ATTACKS)}")
    if combine not in qa.COMBINES or (combine == "inner_product" and n < 3):
        raise ValueError("combine must be xor, or inner_product with at least 3 verifiers")
    answerer = attack if attack != "none" else prover
    claim = [float(c) for c in claim or []]
    claim += [0.0] * (max(2, dim) - len(claim))
    travel_ns = radius_m / tu.SPEED_OF_LIGHT_MPS * 1e9
    t_ref = max(20.0, math.ceil(travel_ns + 1))  # challenges leave at t >= 0
    doc = base_project(name or f"QPV_BB84^f — {dim}D, {n} verifiers, {LABELS.get(answerer, 'no prover')}",
                       f"One quantum and {n - 1} classical verifiers around the claimed position; the basis is the "
                       f"{combine} of the classical shares.", "QPV_BB84^f", qa.REF_BB84,
                       max_time_ns=max(1000.0, 4 * t_ref), seed=seed)
    doc["claim"]["position"] = claim
    doc["meta"]["assumptions"] = [
        f"{dim}D geometry; signals travel on straight lines at the vacuum speed of light.",
        "Verifiers are trusted, know their positions and the claim, share private randomness (x and the basis "
        "shares) before t=0 and have synchronised clocks unless offsets or drift are configured.",
        "One simulation run = one protocol round."]
    for v in (qa.quantum_verifier(), qa.classical_verifier()):
        doc["automata"][v["name"]] = v
    for j, d in enumerate(directions(dim, n)):
        pos = _at(claim, d, radius_m)
        doc["participants"].append(participant(
            f"V{j}", "verifier", f"Verifier V{j} (qubit)" if j == 0 else f"Verifier V{j} ({'basis' if n == 2 else f'share {j}'})",
            pos, "qpv_verifier_quantum" if j == 0 else "qpv_verifier_classical", "verifier",
            _ui(claim, pos, radius_m), {"t_ref_ns": t_ref, "tolerance_ns": tolerance_ns,
                                        **({"combine": combine} if j == 0 and combine != "xor" else {}),
                                        **({"share_index": j - 1} if j > 1 else {})},
            verifier_type="quantum" if j == 0 else "classical"))
    doc["verification"]["verifiers"] = [f"V{j}" for j in range(n)]
    share = "rand_bit()" if combine == "xor" else f"rand_bits({int(share_bits)})"
    doc["resources"].append({"id": "vshared", "type": "shared_random", "holders": doc["verification"]["verifiers"],
                             "vars": {"x": "rand_bit()", "shares": "[" + ", ".join([share] * (n - 1)) + "]"}})
    doc["claim"]["prover"] = None
    if answerer != "none":
        _add_answerers(doc, answerer, policy, processing_ns, displacement_m)
    return autowire(doc)


def switch_attack(project: Dict[str, Any], attack: str, policy: str = "breidbart") -> Dict[str, Any]:
    """Replace whoever answers at the claim (prover or attackers) and rewire; verifiers stay as they are."""
    doc = normalize(copy.deepcopy(project))
    keep = {v["id"] for v in qpv_verifiers(doc)}
    gone = {p["id"] for p in doc["participants"] if p["id"] not in keep}
    doc["participants"] = [p for p in doc["participants"] if p["id"] in keep]
    doc["resources"] = [r for r in doc["resources"] if r["type"] != "epr"]
    doc["links"] = [lk for lk in doc["links"] if not {lk["a"]["node"], lk["b"]["node"]} & gone]
    used = {p["automaton"] for p in doc["participants"]}
    doc["automata"] = {k: v for k, v in doc["automata"].items() if k in used}
    _add_answerers(doc, attack, policy, 0.2 if attack in ("honest", "displaced") else 0.0, 1.0)
    return autowire(doc)


def autowire(project: Dict[str, Any]) -> Dict[str, Any]:
    """Derive every link: verifier j to whoever serves it, and the attackers' coalition channels.

    Settings of an existing link with the same id (noise, latency, ...) are kept."""
    doc = normalize(copy.deepcopy(project))
    old = {lk["id"]: lk for lk in doc["links"]}
    ports = {p["id"]: port_kinds(doc["automata"].get(p["automaton"]) or {}) for p in doc["participants"]}
    vids = verifier_ids(doc)
    others = [p for p in doc["participants"] if p["id"] not in vids]
    pos = {p["id"]: p["position"] for p in doc["participants"]}
    prover = next((p["id"] for p in others if p["id"] == doc["claim"].get("prover")), None)
    links = []

    def add(lid, kind, a, ap, b, bp):
        keep = {k: v for k, v in old.get(lid, {}).items() if k not in ("id", "kind", "a", "b")}
        links.append({**link(lid, kind, a, ap, b, bp), **keep})

    attackers = {}
    for j, v in enumerate(vids):
        if prover:
            target, port = prover, f"v{j}"
        else:
            cand = [p["id"] for p in others if p["id"] not in attackers.values() and "verifier" in ports[p["id"]]]
            if not cand:
                continue
            target, port = min(cand, key=lambda o: math.dist(pos[o], pos[v])), "verifier"
            attackers[j] = target
        kinds = ports[v].get("prover", set()) & ports[target].get(port, set())
        for kind in ("quantum", "classical"):
            if kind in kinds:
                add(f"{kind[0]}{j}", kind, v, "prover", target, port)
    for i, a in attackers.items():
        for j, b in attackers.items():
            if i < j and f"p{j}" in ports[a] and f"p{i}" in ports[b]:
                add(f"e{i}{j}", "classical", a, f"p{j}", b, f"p{i}")
    doc["links"] = links
    return doc


READY = [{"id": f"{d}d_{a}", "label": f"{d}D · {LABELS[a]}", "args": {"dim": d, "attack": "none" if a == "honest" else a}}
         for d in (1, 2, 3) for a in ("honest", "unentangled", "teleport")]

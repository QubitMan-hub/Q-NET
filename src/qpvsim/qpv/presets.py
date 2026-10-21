"""QPV sweep presets and theoretical reference values for comparing attacks.

A preset changes one QPV quantity across the whole setup; experiments use it as a sweep axis
``{"preset": name, "values": [...]}`` (assignment key ``preset:<name>``).
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict

from ..protocol.project import normalize, verifier_ids
from .scenario import ANSWERERS, LABELS, switch_attack

PRESETS: Dict[str, Dict[str, Any]] = {
    "distance": {"label": "Prover distance from the claim", "unit": "m", "range": [0.0, 1.0, 6]},
    "noise": {"label": "Qubit channel depolarisation", "unit": "p", "range": [0.0, 0.5, 6]},
    "drift": {"label": "Verifier clock drift", "unit": "ppm", "range": [0.0, 20000.0, 6]},
    "processing": {"label": "Prover or attacker processing time", "unit": "ns", "range": [0.0, 1.0, 6]},
    "entanglement": {"label": "EPR pair noise (Werner p)", "unit": "p", "range": [0.0, 1.0, 6]},
    "attack": {"label": "Who answers at the claim", "unit": "", "values": list(ANSWERERS)},
}


def apply(project: Dict[str, Any], name: str, value: Any) -> Dict[str, Any]:
    if name == "attack":
        return switch_attack(project, value)
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}; choose from {', '.join(PRESETS)}")
    doc = normalize(copy.deepcopy(project))
    vids = set(verifier_ids(doc))
    others = [p for p in doc["participants"] if p["id"] not in vids]
    if name == "distance":
        prover = next((p for p in others if p["id"] == doc["claim"].get("prover")), None)
        if prover is None:
            raise ValueError("the distance preset moves the claimed prover; this setup has none")
        claim = doc["claim"]["position"]
        prover["position"] = [claim[0] - float(value)] + [float(c) for c in claim[1:]]
    elif name == "noise":
        for lk in doc["links"]:
            if lk["kind"] == "quantum":
                lk["noise"] = {**lk["noise"], "depolarizing": value}
    elif name == "drift":
        for p in doc["participants"]:
            if p["id"] in vids:
                p["clock"] = {**p["clock"], "drift_ppm": value}
    elif name == "processing":
        for p in others:
            p["processing_ns"] = value
    else:
        for r in doc["resources"]:
            if r["type"] == "epr":
                r["werner_p"] = value
    return doc


def reference(project: Dict[str, Any], attack: str) -> Dict[str, Any]:
    """The known acceptance probability of a noise-free round, where theory gives one."""
    n = len(verifier_ids(project))
    e0 = next((p for p in project["participants"] if p["id"] == "E0"), {})
    fixed = (e0.get("params") or {}).get("policy", "breidbart") != "breidbart"
    value, source = {
        "honest": (1.0, "a noise-free honest prover always answers correctly in time"),
        "displaced": (0.0, "the timing check rejects a prover away from the claim"),
        "unentangled": (0.75 if fixed else math.cos(math.pi / 8) ** 2,
                        "fixed-basis measurement" if fixed else "cos²(π/8): best unentangled attack on QPV_BB84 "
                        "(Tomamichel, Fehr, Kaniewski & Wehner, NJP 2013; two-verifier game)"),
        "teleport": (1.0, "teleportation attack with k EPR pairs (Buhrman et al., SIAM J. Comput. 2014)"),
        "guess": (0.5 ** n, f"(1/2)^{n}: an independent random bit for each of the {n} verifiers"),
    }[attack]
    return {"value": value, "label": LABELS[attack], "source": source}

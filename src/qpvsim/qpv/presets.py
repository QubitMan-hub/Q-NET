"""QPV sweep presets and theoretical reference values for comparing attacks.

A preset changes one QPV quantity across the whole setup; experiments use it as a sweep axis
``{"preset": name, "values": [...]}`` (assignment key ``preset:<name>``).
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, List

from ..protocol.project import normalize, verifier_ids
from . import automata as qa
from .scenario import ANSWERERS, LABELS, bases_of, qpv_verifiers, switch_attack

BREIDBART = math.cos(math.pi / 8) ** 2

PRESETS: Dict[str, Dict[str, Any]] = {
    "distance": {"label": "Prover distance from the claim", "unit": "m", "range": [0.0, 1.0, 6]},
    "noise": {"label": "Qubit channel depolarisation", "unit": "p", "range": [0.0, 0.5, 6]},
    "drift": {"label": "Verifier clock drift", "unit": "ppm", "range": [0.0, 20000.0, 6]},
    "processing": {"label": "Prover or attacker processing time", "unit": "ns", "range": [0.0, 1.0, 6]},
    "entanglement": {"label": "EPR pair noise (Werner p)", "unit": "p", "range": [0.0, 1.0, 6]},
    "loss": {"label": "Photon loss on the quantum links", "unit": "p", "range": [0.0, 0.9, 6]},
    "photons": {"label": "Average photons per laser pulse", "unit": "photons", "range": [0.1, 2.0, 6]},
    "dark_count": {"label": "Detector false clicks (prover or attackers)", "unit": "p", "range": [0.0, 0.5, 6]},
    "pairs": {"label": "EPR pairs the attackers share (BB84^f budget attack)", "unit": "pairs", "range": [0.0, 4.0, 5]},
    "attack": {"label": "Who answers at the claim", "unit": "", "values": list(ANSWERERS)},
}


def apply(project: Dict[str, Any], name: str, value: Any) -> Dict[str, Any]:
    if name == "attack":
        return switch_attack(project, value)
    if name == "pairs":
        from .protocols import set_pairs
        return set_pairs(project, value)
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
    elif name == "loss":
        for lk in doc["links"]:
            if lk["kind"] == "quantum":
                lk["loss_prob"] = value
    elif name == "photons":
        v0 = qpv_verifiers(doc)[0]
        if not v0["automaton"].endswith("_laser"):
            bases = bases_of(doc)
            base = qa.quantum_verifier() if bases == 2 else qa.quantum_verifier_bases(bases)
            aut = qa.source_verifier(len(vids), float(value), base)
            doc["automata"][aut["name"]] = aut
            v0["automaton"] = aut["name"]
        v0["params"]["mean_photons"] = value
    elif name == "dark_count":
        for p in others:
            p["noise"] = {**(p.get("noise") or {}), "dark_count": value}
    else:
        for r in doc["resources"]:
            if r["type"] == "epr":
                r["werner_p"] = value
    return doc


def reference(project: Dict[str, Any], attack: str) -> Dict[str, Any]:
    """The known acceptance probability of a noise-free round, where theory gives one."""
    from .protocols import LABELS as PLABELS, protocol_of, reference as proto_reference
    if protocol_of(project) != "bb84":
        r = proto_reference(project, attack)
        return {"value": r["value"] if r else None, "label": LABELS.get(attack) or PLABELS.get(attack, attack),
                "source": r["source"] if r else "not available for this protocol"}
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
        "split": (1.0, "each attacker gets its own copy from a multi-photon pulse and measures it in the full basis"),
        "lossy": (0.5, "the basis guess is right half the time; the other rounds are reported as lost, never wrong"),
    }[attack]
    return {"value": value, "label": LABELS[attack], "source": source}


def answerer(project: Dict[str, Any]) -> str:
    """Who answers at the claim, from the strategies in use ('' when the setup is not a standard one)."""
    autos = " ".join(p["automaton"] for p in project["participants"] if p["id"] not in set(verifier_ids(project)))
    for key, who in (("qpv_adv_chain", "teleport"), ("qpv_adv_teleport_qudit", "teleport"), ("qpv_adv_budget", "budget"),
                     ("qpv_adv_linear", "linear"), ("qpv_adv_relay", "relay"),
                     ("qpv_adv_unentangled", "unentangled"), ("qpv_adv_guess", "guess"),
                     ("qpv_adv_split", "split"), ("qpv_adv_lossy", "lossy")):
        if key in autos:
            return who
    if "strategy_" in autos or "relay_" in autos:
        return ""
    prover = next((p for p in project["participants"] if p["id"] == project["claim"].get("prover")), None)
    return ("honest" if prover["role"] == "prover" else "displaced") if prover else ""


def theory(project: Dict[str, Any], name: str, values: List[Any]) -> Dict[str, Any]:
    """Per-round acceptance that theory predicts at each value of a preset, where a simple formula exists.

    The formulas assume the rest of the setup is ideal (no other noise, loss or timing error)."""
    from .protocols import protocol_of, reference as proto_reference
    who = answerer(project)
    n = len(verifier_ids(project))
    proto = protocol_of(project)
    if proto != "bb84":
        cfg = project["meta"]["qpv"]
        ref = proto_reference(project, who) if who else None
        base_v = ref["value"] if ref else None

        def g(v):
            v = float(v)
            if name == "pairs" and who == "budget":
                return v / cfg["size"] + (1 - v / cfg["size"]) * BREIDBART
            if name == "loss" and base_v is not None and who != "displaced":
                k = mub_qubits(cfg) if who in ("honest", "teleport", "unentangled") else 1
                return (1 - v) ** k * base_v if proto != "classical" else base_v
            return None
        pts = [g(v) for v in values]
        return {"answerer": who, "label": LABELS.get(who, who), "values": values, "theory": pts,
                "note": "Theory assumes the rest of the setup is ideal: no other noise, loss or timing error."
                if any(p is not None for p in pts) else "No simple formula for this combination."}
    m = bases_of(project) if who else 2
    e0 = next((p for p in project["participants"] if p["id"] == "E0"), {})
    breid = BREIDBART if (e0.get("params") or {}).get("policy", "breidbart") == "breidbart" else 0.75
    base = {"honest": 1.0, "teleport": 1.0, "unentangled": breid, "guess": 0.5 ** n, "lossy": 1 / m, "split": 1.0,
            "displaced": 0.0}.get(who)
    prover = next((p for p in project["participants"] if p["id"] == project["claim"].get("prover")), None)
    v0 = qpv_verifiers(project)[0] if who else {"params": {}}
    tol = float(v0["params"].get("tolerance_ns", 0.5))
    proc = float(prover["processing_ns"]) if prover else 0.0
    c_m_per_ns = project["physics"]["signal_speed_mps"] / 1e9

    def f(v):
        v = float(v)
        if name == "noise":  # depolarising strength q: the photon is replaced by noise with probability q
            return {"honest": 1 - v / 2, "teleport": 1 - v / 2, "unentangled": (1 - v) * breid + v / 2,
                    "lossy": (1 - v / 2) / m, "guess": 0.5 ** n}.get(who)
        if name == "loss":
            return None if who in ("split", "displaced", "") else (1 - v) * base
        if name == "photons":
            p1 = 1 - math.exp(-v)
            return {"split": 1 - math.exp(-v) * (1 + v)}.get(who, None if who in ("", "displaced") else p1 * base)
        if name == "dark_count":
            return {"honest": 1 - v / 2, "unentangled": (1 - v) * breid + v / 2, "guess": 0.5 ** n}.get(who)
        if name == "entanglement":
            return 1 - v / 2 if who == "teleport" and n == 2 else None
        if name == "processing" and who == "honest":
            return 1.0 if v <= tol + 1e-12 else 0.0
        if name == "distance" and who == "honest":
            return 1.0 if 2 * v / c_m_per_ns <= tol - proc + 1e-9 else 0.0
        if name == "attack":
            return reference(project, str(v))["value"] if m == 2 else None
        return None
    points = [f(v) for v in values]
    return {"answerer": who, "label": LABELS.get(who, ""), "values": values, "theory": points,
            "note": "Theory assumes the rest of the setup is ideal: no other noise, loss or timing error."
            if any(p is not None for p in points) else "No simple formula for this combination."}


def mub_qubits(cfg: Dict[str, Any]) -> int:
    """Qubits that carry one challenge photon: log2(d) for a qudit (each can be lost on its own), else 1."""
    return int(cfg["d"]).bit_length() - 1 if cfg.get("protocol") == "qudit" else 1

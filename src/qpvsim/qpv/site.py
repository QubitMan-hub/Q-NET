"""Real sites and real hardware: verifiers at map coordinates, fibre or free-space links, detector specifications.

A site places the claim and the verifiers at latitude/longitude, converted to local east/north metres around the
claim (accurate to well under a millimetre per kilometre at these distances).  ``hardware`` then describes how the
honest signals travel and are detected:

* ``links``: "free_space" (straight line at c) or "fibre" (a route ``route_factor`` times the straight distance, at
  ``fibre_speed`` x c, losing ``db_per_km``); the verifiers send early and wait longer to make up for the fibre.
* ``efficiency``: the detector's chance to click on an arriving photon; ``dark_count``: chance of a false click per
  measurement (the answer becomes a random bit); ``jitter_ns``: timing jitter added to every signal.

Cheaters are not bound to the verifiers' fibre: their links run straight at c, so a fibre detour hands them spare time
(see section B4/F3 of the write-up).  :func:`summary` puts numbers on that: how precisely the site can locate a
prover, and the photon loss an honest prover sees.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from ..protocol.project import normalize, verifier_ids
from ..timeunits import SPEED_OF_LIGHT_MPS
from .scenario import CANVAS

EARTH_M = 6_371_008.8
C_M_PER_NS = SPEED_OF_LIGHT_MPS / 1e9

HARDWARE_DEFAULTS = {"links": "fibre", "route_factor": 1.4, "fibre_speed": 0.68, "db_per_km": 0.2,
                     "efficiency": 0.8, "dark_count": 0.0, "jitter_ns": 0.0}

SITES: Dict[str, Dict[str, Any]] = {
    "lab": {"label": "Optical table (3 m)", "claim": [52.00000, 4.37000],
            "verifiers": [[52.000027, 4.370000], [51.9999865, 4.3700380], [51.9999865, 4.3699620]],
            "hardware": {"links": "free_space", "efficiency": 0.9, "dark_count": 0.0, "jitter_ns": 0.0}},
    "campus": {"label": "University campus, free-space links (about 400 m)", "claim": [52.00160, 4.37300],
               "verifiers": [[52.00520, 4.37300], [51.99980, 4.37806], [51.99980, 4.36794]],
               "hardware": {"links": "free_space", "efficiency": 0.8, "dark_count": 0.001, "jitter_ns": 0.05}},
    "city": {"label": "City centre over street fibre (about 5 km)", "claim": [52.37310, 4.89220],
             "verifiers": [[52.41806, 4.89220], [52.35062, 4.95601], [52.35062, 4.82839]],
             "hardware": {"links": "fibre", "route_factor": 1.5, "fibre_speed": 0.68, "db_per_km": 0.2,
                          "efficiency": 0.8, "dark_count": 0.001, "jitter_ns": 0.05}},
}


def to_local(latlon: List[float], origin: List[float]) -> List[float]:
    """East/north metres of a point from an origin (local tangent plane)."""
    lat0 = math.radians(origin[0])
    east = math.radians(latlon[1] - origin[1]) * EARTH_M * math.cos(lat0)
    north = math.radians(latlon[0] - origin[0]) * EARTH_M
    return [round(east, 4), round(north, 4)]


def place(doc: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Move the claim and the verifiers to a site (the project must have as many verifiers as the site)."""
    s = SITES.get(name)
    if s is None:
        raise ValueError(f"unknown site {name!r}; choose from {', '.join(SITES)}")
    vids = verifier_ids(doc)
    if len(vids) != len(s["verifiers"]) or len(doc["claim"]["position"]) != 2:
        raise ValueError(f"the {name} site needs a 2D setup with {len(s['verifiers'])} verifiers")
    pos = [to_local(ll, s["claim"]) for ll in s["verifiers"]]
    radius = max(math.hypot(*p) for p in pos)
    doc["claim"]["position"] = [0.0, 0.0]
    for p in doc["participants"]:
        if p["id"] in vids:
            p["position"] = pos[vids.index(p["id"])]
            p["ui"] = {"x": round(CANVAS + p["position"][0] * CANVAS / radius), "y": round(220 - p["position"][1] * CANVAS / radius)}
    doc["meta"]["site"] = {"name": name, "label": s["label"], "claim_latlon": s["claim"], "verifiers_latlon": s["verifiers"]}
    return hardware(doc, s["hardware"])


def hardware(doc: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    """Apply link and detector specifications to the verifiers' links to the claimed prover (or whoever stands at the
    claim); attackers keep straight links at c."""
    hw = {**HARDWARE_DEFAULTS, **(doc["meta"].get("site", {}).get("hardware") or {}), **spec}
    if hw["links"] not in ("fibre", "free_space"):
        raise ValueError("links must be 'fibre' or 'free_space'")
    for k in ("efficiency", "dark_count"):
        if not 0 <= float(hw[k]) <= 1:
            raise ValueError(f"{k} is a probability between 0 and 1")
    if float(hw["route_factor"]) < 1 or not 0 < float(hw["fibre_speed"]) <= 1:
        raise ValueError("route_factor must be at least 1 and fibre_speed in (0, 1]")
    vids = verifier_ids(doc)
    claim = doc["claim"]["position"]
    fibre = hw["links"] == "fibre"
    worst_travel = 0.0
    for v in (p for p in doc["participants"] if p["id"] in vids):
        d = math.dist(v["position"], claim)
        route = d * float(hw["route_factor"]) if fibre else d
        speed = float(hw["fibre_speed"]) if fibre else 1.0
        extra = route / (speed * C_M_PER_NS) - d / C_M_PER_NS
        v["params"]["extra_delay_ns"] = round(max(0.0, extra), 6)
        worst_travel = max(worst_travel, d / C_M_PER_NS + extra)
        for lk in doc["links"]:
            ends = {lk["a"]["node"], lk["b"]["node"]}
            if v["id"] not in ends:
                continue
            other = (ends - {v["id"]}).pop() if len(ends) > 1 else v["id"]
            at_claim = math.dist(next(p for p in doc["participants"] if p["id"] == other)["position"], claim) < 1e-9
            lk["jitter_ns"] = float(hw["jitter_ns"])
            if not at_claim:
                continue  # attackers away from the claim keep their straight links
            lk["length_m"] = round(route, 6) if fibre else None
            lk["speed_mps"] = speed * SPEED_OF_LIGHT_MPS if fibre else None
            if lk["kind"] == "quantum":
                lk["loss_prob"] = round(1 - float(hw["efficiency"]) * 10 ** (-float(hw["db_per_km"]) * route / 1000 / 10)
                                        if fibre else 1 - float(hw["efficiency"]), 6)
    for p in doc["participants"]:
        if p["id"] not in vids and float(hw["dark_count"]):
            p["noise"] = {**(p.get("noise") or {}), "dark_count": float(hw["dark_count"])}
    t_ref = max(20.0, math.ceil(worst_travel + 5))
    jitter_margin = 2 * float(hw["jitter_ns"])
    for v in (p for p in doc["participants"] if p["id"] in vids):
        v["params"]["t_ref_ns"] = t_ref
        v["params"]["tolerance_ns"] = max(float(v["params"].get("tolerance_ns", 0.5)), 0.5) + jitter_margin
    doc["simulation"]["max_time_ns"] = max(float(doc["simulation"]["max_time_ns"]), 4 * t_ref)
    site = doc["meta"].setdefault("site", {})
    site["hardware"] = hw
    site.update(summary(doc))
    return normalize(doc)


def summary(doc: Dict[str, Any]) -> Dict[str, Any]:
    """How precisely the site locates a prover, and what loss an honest prover sees."""
    vids = verifier_ids(doc)
    vs = [p for p in doc["participants"] if p["id"] in vids]
    claim = doc["claim"]["position"]
    tol = max(float(v["params"].get("tolerance_ns", 0.5)) for v in vs)
    gain = max(float(v["params"].get("extra_delay_ns", 0.0)) for v in vs)
    losses = [lk["loss_prob"] for lk in doc["links"] if lk["kind"] == "quantum" and doc["claim"].get("prover") in
              (lk["a"]["node"], lk["b"]["node"])]
    return {"distance_m": round(max(math.dist(v["position"], claim) for v in vs), 1),
            "precision_m": round(C_M_PER_NS * (tol + gain) / 2, 3),
            "fibre_gain_ns": round(gain, 3), "tolerance_ns": round(tol, 3),
            "photon_loss": round(max(losses), 4) if losses else None}

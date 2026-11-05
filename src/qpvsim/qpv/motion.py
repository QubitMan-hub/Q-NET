"""A moving prover across rounds.

Positions are fixed within one simulation run (one round lasts nanoseconds; at everyday speeds a party moves
nanometres in that time).  Across rounds a party can move: ``meta.motion`` says how, and round ``i`` happens
``i * round_interval_ms`` after round 0::

    {"party": "P", "velocity_mps": [1.4, 0, 0], "tracked": 1.0, "round_interval_ms": 1.0}

In round ``i`` the party stands at ``position + velocity * t``; the verifiers aim each round at
``claim + tracked * velocity * t`` (``tracked`` = 1: they predict the path exactly, 0: they assume it stands
still).  Experiments apply this to their i-th run (:func:`at_round`); a single interactive run is round 0.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional


def spec(project: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return (project.get("meta") or {}).get("motion") or None


def issues(project: Dict[str, Any]) -> List[str]:
    m = spec(project)
    if not m:
        return []
    out = []
    ids = {p.get("id") for p in project.get("participants", [])}
    if m.get("party") not in ids:
        out.append(f"motion: no participant {m.get('party')!r}")
    v = m.get("velocity_mps")
    if not isinstance(v, list) or not all(isinstance(x, (int, float)) for x in v):
        out.append("motion: velocity_mps must be a list of numbers (m/s)")
    elif any(abs(x) >= 299_792_458 for x in v):
        out.append("motion: a party cannot move at or above the speed of light")
    if not isinstance(m.get("round_interval_ms", 1.0), (int, float)) or m.get("round_interval_ms", 1.0) <= 0:
        out.append("motion: round_interval_ms must be positive")
    if not isinstance(m.get("tracked", 0.0), (int, float)):
        out.append("motion: tracked must be a number (1 = the verifiers follow the path exactly)")
    return out


def _shift(pos: List[float], v: List[float], t: float) -> List[float]:
    v = (list(v) + [0.0] * len(pos))[:len(pos)]
    return [round(p + vi * t, 12) for p, vi in zip(pos, v)]


def at_round(project: Dict[str, Any], i: int) -> Dict[str, Any]:
    """The project as it stands in round ``i`` (the same object when nothing moves)."""
    m = spec(project)
    if not m or i == 0:
        return project
    t = i * float(m.get("round_interval_ms", 1.0)) * 1e-3
    doc = copy.deepcopy(project)
    v = [float(x) for x in m.get("velocity_mps") or []]
    for p in doc["participants"]:
        if p["id"] == m.get("party"):
            p["position"] = _shift(p["position"], v, t)
    tracked = float(m.get("tracked", 0.0))
    if tracked:
        doc["claim"]["position"] = _shift(doc["claim"]["position"], [tracked * x for x in v], t)
    return doc

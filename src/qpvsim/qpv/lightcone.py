"""Light-cone checker: could a lone adversary at a point beat every verifier's deadline?

A worst-case adversary at p collects every challenge, at t_in(p) = max_i(send_i + L(V_i, p)), works
for tau and answers; its answer reaches V_j at t_in + tau + L(p, V_j).  slack(p) = min_j(deadline_j -
that).  Adversary paths use the vacuum speed of light whatever the links' speed or latency; send times
and deadlines are the engine's actual scheduled global times.  Points with slack >= 0 are where a lone
impostor passes the timing checks; colluding attackers on the verifier-to-claim segments always do,
which is why QPV relies on the quantum part of the protocol, not on timing alone.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .. import timeunits as tu
from ..protocol.capabilities import make_capabilities
from ..protocol.project import setup_key
from .cache import memo
from .geometry import vec
from .timing import schedule

C = tu.SPEED_OF_LIGHT_MPS


def default_tau_ns(project: Dict[str, Any]) -> float:
    mins = [make_capabilities(p["capabilities"]).min_processing_ns for p in project["participants"]
            if p["role"] == "adversary"]
    return float(min(mins)) if mins else 0.0


def point(project: Dict[str, Any], p: Sequence[float], tau_ns: Optional[float] = None) -> Dict[str, Any]:
    s = schedule(project)
    tau = default_tau_ns(project) if tau_ns is None else float(tau_ns)
    if s["reason"]:
        return {"point": list(p), "tau_ns": tau, "reason": s["reason"]}
    vs = s["verifiers"]
    light = [tu.propagation_fs(float(math.dist(vec(v["position"]), vec(p))), C) for v in vs]
    t_in = max(v["send_fs"] + lt for v, lt in zip(vs, light)) + tu.ns(tau)
    per = [{"id": v["id"], "arrival_fs": t_in + lt, "deadline_fs": v["deadline_fs"],
            "slack_fs": v["deadline_fs"] - t_in - lt} for v, lt in zip(vs, light)]
    worst = min(per, key=lambda r: r["slack_fs"])
    return {"point": list(p), "tau_ns": tau, "slack_fs": worst["slack_fs"], "binding": worst["id"],
            "can_answer": worst["slack_fs"] >= 0, "per_verifier": per, "reason": None}


def grid(project: Dict[str, Any], n: int = 96, tau_ns: Optional[float] = None, z: Optional[float] = None,
         bounds: Optional[List[List[float]]] = None) -> Dict[str, Any]:
    """Slack (ns, float, display only) on an n x n grid of the x-y plane at height z, cached per setup."""
    tau = default_tau_ns(project) if tau_ns is None else float(tau_ns)
    claim = vec(project["claim"]["position"])
    z = float(claim[2] if z is None else z)
    if bounds is None:
        pts = np.array([vec(p["position"]) for p in project["participants"]] + [claim])[:, :2]
        lo, hi = pts.min(0), pts.max(0)
        half = max((hi - lo).max() * 0.6, 1.0)
        mid = (lo + hi) / 2
        bounds = [[mid[0] - half, mid[0] + half], [mid[1] - half, mid[1] + half]]
    key = (setup_key(project), n, tau, z, tuple(map(tuple, bounds)))
    return _grid(key, project, n, tau, z, bounds)


@memo()
def _grid(project, n, tau, z, bounds):
    s = schedule(project)
    out = {"bounds": bounds, "n": n, "z": z, "tau_ns": tau, "reason": s["reason"], "slack_ns": []}
    if s["reason"]:
        return out
    xs, ys = np.linspace(*bounds[0], n), np.linspace(*bounds[1], n)
    X, Y = np.meshgrid(xs, ys)  # row i = y index, column j = x index
    vs = s["verifiers"]
    light = np.array([np.sqrt((X - q[0]) ** 2 + (Y - q[1]) ** 2 + (z - q[2]) ** 2) / C * 1e15
                      for q in (vec(v["position"]) for v in vs)])
    sends = np.array([v["send_fs"] for v in vs], dtype=float)[:, None, None]
    deadlines = np.array([v["deadline_fs"] for v in vs], dtype=float)[:, None, None]
    t_in = (sends + light).max(0) + tau * tu.NS
    slack = (deadlines - t_in - light).min(0) / tu.NS
    out["slack_ns"] = np.round(slack, 6).tolist()
    return out

"""Positions, dimension and convex-hull checks.

Secure positioning in d dimensions needs at least d + 1 verifiers with the claimed position inside
their convex hull (Chandran, Goyal, Moriarty & Ostrovsky, CRYPTO 2009).  The dimension of a setup is
the affine rank of all positions (participants and claim) unless ``physics.dimension`` overrides it.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any, Dict, List, Sequence

import numpy as np

TOL = 1e-9


def vec(p: Sequence[float], d: int = 3) -> np.ndarray:
    """Position as a length-``d`` float vector (missing coordinates are 0)."""
    out = np.zeros(d)
    out[: min(d, len(p))] = [float(x) for x in p[:d]]
    return out


def affine_rank(points: Sequence[Sequence[float]]) -> int:
    pts = np.array([vec(p) for p in points])
    return int(np.linalg.matrix_rank(pts[1:] - pts[0], TOL)) if len(pts) > 1 else 0


def dimension(project: Dict[str, Any]) -> int:
    if project["physics"].get("dimension"):
        return int(project["physics"]["dimension"])
    pts = [p["position"] for p in project["participants"]] + [project["claim"]["position"]]
    return max(1, affine_rank(pts))


def in_hull(p: Sequence[float], points: Sequence[Sequence[float]]) -> bool:
    """Is ``p`` in the convex hull of ``points`` (boundary included)?"""
    pts = np.array([vec(q) for q in points])
    x = vec(p) - pts[0]
    rel = pts[1:] - pts[0]
    r = int(np.linalg.matrix_rank(rel, TOL)) if len(rel) else 0
    if r == 0:
        return bool(np.allclose(x, 0, atol=TOL))
    basis = np.linalg.svd(rel)[2][:r]  # orthonormal basis of the affine span
    if np.linalg.norm(x - basis.T @ (basis @ x)) > TOL:
        return False
    local = rel @ basis.T
    xl = basis @ x
    for idx in combinations(range(len(pts)), r + 1):  # some simplex of the points contains p
        verts = np.vstack([np.zeros(r), local])[list(idx)]
        m = (verts[1:] - verts[0]).T
        if abs(np.linalg.det(m)) < TOL:
            continue
        lam = np.linalg.solve(m, xl - verts[0])
        if lam.min() >= -TOL and lam.sum() <= 1 + TOL:
            return True
    return False


def geometry_issues(project: Dict[str, Any], verifiers: List[str]) -> List[tuple]:
    """(path, message) warnings about verifier placement."""
    pos = {p["id"]: p["position"] for p in project["participants"]}
    vpos = [pos[v] for v in verifiers if v in pos]
    if not vpos:
        return []
    d, claim, out = dimension(project), project["claim"]["position"], []
    if len(vpos) < d + 1:
        out.append(("verification.verifiers", f"a {d}D setup needs at least {d + 1} verifiers for secure "
                                              f"positioning; it has {len(vpos)}"))
    if not in_hull(claim, vpos):
        out.append(("claim.position", "the claimed position is outside the convex hull of the verifiers, "
                                      "so a party at the nearest hull point is closer to every verifier and can always answer in time"))
    return out

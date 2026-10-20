"""Experiment orchestration: repeated runs, parameter sweeps, statistics.

An experiment definition::

    {"id": "...", "name": "...", "runs": 1000, "seed": 1,
     "sweep": [{"path": "participants.E0.params.policy", "values": ["breidbart", "Z"]}],
     "patch": {"simulation.backend": "state_vector"},   # optional fixed overrides
     "workers": 1}

Several sweep axes form a Cartesian grid.  Run ``i`` of grid point ``k`` uses
the seed ``SeedSequence([seed, k, i]).generate_state(1, uint64)[0]``, which is
recorded with the run, so any single run can be reproduced exactly with
``Simulation(project_with_patch, seed=run_seed)``.

Raw per-run records (``runs``) are kept separate from derived statistics
(``points``); :func:`summarize` recomputes the latter from the former.
Binomial proportions are reported with Wilson score intervals (95 %).
"""

from __future__ import annotations

import copy
import itertools
import math
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from . import timeunits as tu
from .decision import decide
from .engine import ENGINE_VERSION, Simulation
from .protocol.project import normalize, set_path, validate_project, errors, ProjectError

Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> Dict[str, float]:
    if n == 0:
        return {"p": float("nan"), "lo": 0.0, "hi": 1.0}
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    lo = 0.0 if k == 0 else max(0.0, centre - half)
    hi = 1.0 if k == n else min(1.0, centre + half)
    return {"p": p, "lo": lo, "hi": hi}


def run_seed(master: int, point: int, i: int) -> int:
    return int(np.random.SeedSequence([int(master), int(point), int(i)]).generate_state(1, np.uint64)[0]
               & 0x7FFF_FFFF_FFFF_FFFF)


def grid(sweep: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not sweep:
        return [{}]
    axes = [[(ax["path"], v) for v in ax["values"]] for ax in sweep]
    return [dict(combo) for combo in itertools.product(*axes)]


def apply_patch(project: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    doc = copy.deepcopy(project)
    for path, value in patch.items():
        set_path(doc, path, copy.deepcopy(value))
    return normalize(doc)


def run_once(project: Dict[str, Any], seed: int) -> Dict[str, Any]:
    """Execute one run and extract a compact raw record."""
    sim = Simulation(project, seed=seed, validate=False, copy_project=False)
    sim.run()
    snap_dec = decide(sim)
    verifiers = {}
    for v in snap_dec["verifiers"]:
        verifiers[v["id"]] = {"verdict": v["verdict"], "category": v["category"], "reason": v["reason"],
                              "decided_at_fs": v["decided_at_fs"], "observations": v["observations"]}
    return {
        "seed": seed, "outcome": snap_dec["outcome"], "verifiers": verifiers,
        "end_fs": sim.now, "events": sim.scheduler.executed_count, "stop_reason": sim.stop_reason,
        "counters": dict(sim.counters),
        "errors": {n.id: n.error for n in sim.nodes.values() if n.error},
    }


def _run_chunk(args):
    project, seeds = args
    return [run_once(project, s) for s in seeds]


def _stats(values: List[float]) -> Optional[Dict[str, float]]:
    if not values:
        return None
    arr = np.asarray(values, dtype=float)
    return {"n": int(arr.size), "mean": float(arr.mean()), "std": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
            "min": float(arr.min()), "max": float(arr.max()),
            "p05": float(np.percentile(arr, 5)), "p50": float(np.percentile(arr, 50)),
            "p95": float(np.percentile(arr, 95))}


def summarize_point(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(runs)
    acc = sum(1 for r in runs if r["outcome"] == "accept")
    per_verifier: Dict[str, Any] = {}
    vids = sorted({v for r in runs for v in r["verifiers"]})
    for vid in vids:
        cats: Dict[str, int] = {}
        rtts, resp = [], []
        vacc = 0
        for r in runs:
            v = r["verifiers"].get(vid)
            if not v:
                continue
            cats[v["category"]] = cats.get(v["category"], 0) + 1
            vacc += v["verdict"] == "accept"
            obs = v.get("observations") or {}
            if isinstance(obs.get("rtt_ns"), (int, float)):
                rtts.append(obs["rtt_ns"])
            if isinstance(obs.get("response_ns"), (int, float)):
                resp.append(obs["response_ns"])
        per_verifier[vid] = {"accept": wilson(vacc, n), "categories": cats,
                             "rtt_ns": _stats(rtts), "response_ns": _stats(resp),
                             "rtt_values": rtts[:5000]}
    counters: Dict[str, float] = {}
    for r in runs:
        for k, v in r["counters"].items():
            counters[k] = counters.get(k, 0) + v
    return {
        "n": n, "accepted": acc, "acceptance": wilson(acc, n),
        "outcomes": {o: sum(1 for r in runs if r["outcome"] == o) for o in ("accept", "reject", "pending")},
        "verifiers": per_verifier,
        "mean_counters": {k: v / n for k, v in counters.items()} if n else {},
        "errors": sum(1 for r in runs if r["errors"]),
    }


def run_experiment(project: Dict[str, Any], exp: Dict[str, Any],
                   progress: Optional[Callable[[int, int], None]] = None,
                   cancel: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    project = normalize(copy.deepcopy(project))
    runs = int(exp.get("runs", 100))
    if runs < 1 or runs > 1_000_000:
        raise ValueError("runs must be between 1 and 1e6")
    master = int(exp.get("seed", project["simulation"]["seed"]))
    base_patch = exp.get("patch") or {}
    points = grid(exp.get("sweep") or [])
    workers = max(1, int(exp.get("workers", 1)))
    total = runs * len(points)
    done = 0
    t0 = time.perf_counter()
    out_points = []
    for k, assignment in enumerate(points):
        doc = apply_patch(project, {**base_patch, **assignment})
        issues = validate_project(doc)
        if errors(issues):
            raise ProjectError(errors(issues))
        seeds = [run_seed(master, k, i) for i in range(runs)]
        raw: List[Dict[str, Any]] = []
        if workers > 1 and runs >= 50:
            chunks = [seeds[i::workers] for i in range(workers)]
            with ProcessPoolExecutor(max_workers=workers) as pool:
                for res in pool.map(_run_chunk, [(doc, c) for c in chunks]):
                    raw.extend(res)
            raw.sort(key=lambda r: seeds.index(r["seed"]))
            done += runs
            if progress:
                progress(done, total)
        else:
            for s in seeds:
                if cancel and cancel():
                    raise RuntimeError("experiment cancelled")
                raw.append(run_once(doc, s))
                done += 1
                if progress and done % 25 == 0:
                    progress(done, total)
        out_points.append({"index": k, "assignment": assignment, "runs": raw,
                           "summary": summarize_point(raw)})
    wall = time.perf_counter() - t0
    return {
        "experiment": copy.deepcopy(exp),
        "provenance": provenance(project, exp),
        "points": out_points,
        "wall_time_s": wall,
        "runs_per_second": total / wall if wall > 0 else None,
        "interpretation": (
            "Acceptance rates are Monte-Carlo estimates over independent runs (one protocol round each) "
            "with 95% Wilson score intervals. They describe the modelled protocol, adversary strategy and "
            "physical parameters only; they are not security proofs."),
    }


def provenance(project: Dict[str, Any], exp: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    import platform
    return {
        "engine_version": ENGINE_VERSION,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "project_name": project["meta"]["name"],
        "protocol": project["meta"].get("protocol"),
        "backend": project["simulation"]["backend"],
        "base_seed": project["simulation"]["seed"],
        "experiment_seed": (exp or {}).get("seed"),
        "assumptions": project["meta"].get("assumptions"),
        "limitations": project["meta"].get("limitations"),
        "participants": [{"id": p["id"], "role": p["role"], "position": p["position"],
                          "automaton": p["automaton"], "capabilities": p["capabilities"],
                          "processing_ns": p["processing_ns"], "clock": p["clock"]}
                         for p in project["participants"]],
        "links": project["links"],
        "verification": project["verification"],
        "claim": project["claim"],
        "physics": project["physics"],
    }


def results_to_csv(result: Dict[str, Any]) -> str:
    """Flatten derived statistics (one row per grid point and verifier)."""
    rows = ["point,assignment,n,accepted,acceptance,ci_lo,ci_hi,verifier,v_accept,timeouts,wrong,errors,rtt_mean_ns,rtt_std_ns"]
    for pt in result["points"]:
        s = pt["summary"]
        a = ";".join(f"{k}={v}" for k, v in pt["assignment"].items())
        for vid, v in s["verifiers"].items():
            rtt = v["rtt_ns"] or {}
            rows.append(",".join(str(x) for x in [
                pt["index"], f'"{a}"', s["n"], s["accepted"], f'{s["acceptance"]["p"]:.6f}',
                f'{s["acceptance"]["lo"]:.6f}', f'{s["acceptance"]["hi"]:.6f}', vid,
                f'{v["accept"]["p"]:.6f}', v["categories"].get("timeout", 0),
                v["categories"].get("wrong_answer", 0), v["categories"].get("error", 0),
                rtt.get("mean", ""), rtt.get("std", "")]))
    return "\n".join(rows) + "\n"

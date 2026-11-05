"""Many-round tests: from the pass rate of one round to the verdict over n rounds.

One simulation run is one protocol round.  Real verifiers run many rounds and accept the prover only if
enough of them come back right.  A test is::

    {"rounds": n, "min_correct": 1.0, "min_answered": 0.0}

and passes when at least ``ceil(min_answered * n)`` rounds were answered (not reported lost) and at least
``ceil(min_correct * answered)`` of the answered rounds were correct.  Rounds are independent, so with
per-round probabilities ``correct``, ``lost`` and ``wrong = 1 - correct - lost`` the chance of passing is
exact: answered ~ Binomial(n, 1 - lost), correct | answered ~ Binomial(answered, correct / (1 - lost)).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np

DEFAULT_TEST = {"rounds": 88, "min_correct": 1.0, "min_answered": 0.0}
MAX_ROUNDS = 100_000


def normalize_test(test: Dict[str, Any]) -> Dict[str, Any]:
    t = {**DEFAULT_TEST, **(test or {})}
    t["rounds"] = int(t["rounds"])
    t["min_correct"], t["min_answered"] = float(t["min_correct"]), float(t["min_answered"])
    if not 1 <= t["rounds"] <= MAX_ROUNDS:
        raise ValueError(f"a test needs between 1 and {MAX_ROUNDS} rounds")
    if not (0 <= t["min_correct"] <= 1 and 0 <= t["min_answered"] <= 1):
        raise ValueError("min_correct and min_answered are fractions between 0 and 1")
    return t


def _log_binom_pmf(n: int, p: float) -> np.ndarray:
    k = np.arange(n + 1)
    logfact = np.concatenate([[0.0], np.cumsum(np.log(np.arange(1, n + 1)))])
    with np.errstate(divide="ignore", invalid="ignore"):
        lp, lq = (math.log(p) if p > 0 else -np.inf), (math.log1p(-p) if p < 1 else -np.inf)
        t1 = np.where(k > 0, k * lp, 0.0) if p == 0 else k * lp
        t2 = np.where(n - k > 0, (n - k) * lq, 0.0) if p == 1 else (n - k) * lq
    return logfact[n] - logfact[k] - logfact[n - k] + t1 + t2


def binom_tail(n: int, k: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    pmf = np.exp(_log_binom_pmf(n, min(1.0, max(0.0, p))))
    return float(min(1.0, pmf[k:].sum()))


def pass_probability(test: Dict[str, Any], correct: float, lost: float = 0.0) -> float:
    """Chance that n independent rounds pass the test, given the per-round rates."""
    t = normalize_test(test)
    n = t["rounds"]
    correct, lost = min(1.0, max(0.0, correct)), min(1.0, max(0.0, lost))
    answered_p = 1.0 - lost
    if answered_p <= 0:
        return 1.0 if t["min_answered"] == 0 and t["min_correct"] == 0 else 0.0
    q = min(1.0, correct / answered_p)
    pa = np.exp(_log_binom_pmf(n, answered_p))
    need_a = math.ceil(t["min_answered"] * n - 1e-9)
    total = 0.0
    for a in range(need_a, n + 1):
        if pa[a] < 1e-300:
            continue
        need_c = math.ceil(t["min_correct"] * a - 1e-9)
        total += pa[a] * (1.0 if need_c <= 0 else binom_tail(a, need_c, q))
    return float(min(1.0, total))


def rounds_needed(p_honest: float, p_cheat: float, risk: float = 1e-6, max_rounds: int = MAX_ROUNDS) -> Optional[Dict[str, Any]]:
    """Fewest rounds n, with a pass mark k, so that an honest prover fails and a cheater passes each with
    probability at most ``risk`` (no lost rounds).  None if no n up to ``max_rounds`` does it."""
    if p_honest <= p_cheat:
        return None

    def best(n: int) -> Optional[int]:
        lo, hi = 0, n + 1  # smallest k with cheater tail <= risk
        while lo < hi:
            mid = (lo + hi) // 2
            if binom_tail(n, mid, p_cheat) <= risk:
                hi = mid
            else:
                lo = mid + 1
        k = lo
        return k if k <= n and 1 - binom_tail(n, k, p_honest) <= risk else None

    n = 1
    while n <= max_rounds and best(n) is None:
        n *= 2
    if n > max_rounds and best(max_rounds) is None:
        return None
    lo, hi = max(1, n // 2), min(n, max_rounds)
    while lo < hi:  # the property is monotone in n up to small wiggles; refine below
        mid = (lo + hi) // 2
        if best(mid) is not None:
            hi = mid
        else:
            lo = mid + 1
    while lo > 1 and best(lo - 1) is not None:
        lo -= 1
    k = best(lo)
    return {"rounds": lo, "pass_mark": k, "min_correct": k / lo, "risk": risk,
            "honest_fails": 1 - binom_tail(lo, k, p_honest), "cheater_passes": binom_tail(lo, k, p_cheat)}


def round_outcome(run: Dict[str, Any]) -> str:
    """correct | lost | wrong for one recorded run (lost: a verifier was told no photon arrived)."""
    if run["outcome"] == "accept":
        return "correct"
    if any(v.get("category") == "lost" for v in run["verifiers"].values()):
        return "lost"
    return "wrong"


def evaluate(test: Dict[str, Any], runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The test verdict implied by recorded runs: exact pass probability at the measured rates (and at the
    ends of the 95% interval of the correct rate), plus how many whole blocks of n recorded rounds passed."""
    from ..experiments import wilson
    t = normalize_test(test)
    outs = [round_outcome(r) for r in runs]
    m = len(outs)
    c, lost = outs.count("correct"), outs.count("lost")
    rc, rl = (c / m, lost / m) if m else (0.0, 0.0)
    ci = wilson(c, m)
    n = t["rounds"]
    blocks = [outs[i:i + n] for i in range(0, m - n + 1, n)]

    def block_passes(b):
        answered = sum(o != "lost" for o in b)
        return (answered >= math.ceil(t["min_answered"] * n - 1e-9)
                and b.count("correct") >= math.ceil(t["min_correct"] * answered - 1e-9))
    return {**t, "per_round": {"correct": rc, "lost": rl, "wrong": 1 - rc - rl, "n": m},
            "pass_probability": pass_probability(t, rc, rl),
            "pass_range": [pass_probability(t, max(0.0, min(ci["lo"], 1 - rl)), rl),
                           pass_probability(t, min(ci["hi"], 1 - rl), rl)] if m else [0.0, 1.0],
            "blocks": len(blocks), "blocks_passed": sum(block_passes(b) for b in blocks)}


def describe(p: float) -> str:
    """A probability in words: '100%', '37%', 'about 1 in 830,000'."""
    if p >= 0.9995:
        return "100%" if p >= 1 - 1e-12 else f"{100 * p:.3f}%"
    if p >= 0.01:
        return f"{100 * p:.0f}%"
    if p <= 0:
        return "never"
    if p < 1e-15:
        return "practically never"
    return f"about 1 in {round(1 / p):,}"

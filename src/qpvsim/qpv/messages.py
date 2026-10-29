"""One round of QPV_BB84^f as plain Python functions, without the engine.

The same protocol as the automata in :mod:`qpvsim.qpv.automata`, written as five steps you can call
directly:

1. :func:`classical_verifier_message` -- a classical verifier's message to the prover (its basis share);
2. :func:`quantum_verifier_message` -- the quantum verifier's message to the prover (the qubit H^b|x>);
3. :func:`prover_measure` -- the prover combines the shares into the basis b and measures the qubit;
4. :func:`prover_response` -- the prover's answer messages to every verifier;
5. :func:`validate_response` -- a verifier checks an answer: correct (equals x) and on time (by its deadline).

Conventions match the automata: all times are integer femtoseconds (see :mod:`qpvsim.timeunits`); every
verifier times its emission so the challenges reach the claimed position together at ``t_ref_fs``; its
deadline is ``t_ref_fs + d(V, claim)/c + tolerance_fs``; propagation delays round up to fs.  The
position is verified only if every verifier accepts.

Example (1D, verifiers 3 m either side of the claim at the origin)::

    shares = [1]
    qv = quantum_verifier_message("V0", [-3, 0], [0, 0], x=1, shares=shares, t_ref_fs=tu.ns(20))
    cv = classical_verifier_message("V1", [3, 0], [0, 0], share=shares[0], t_ref_fs=tu.ns(20))
    m = prover_measure(qv, [cv])
    replies = prover_response("P", [0, 0], m["answer"], [qv, cv])
    validate_response(replies["V0"], [-3, 0], [0, 0], x=1, t_ref_fs=tu.ns(20), tolerance_fs=tu.ns(0.5))
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .. import timeunits as tu
from ..protocol.expr import _combine
from ..quantum import base as qb
from .geometry import vec

C = tu.SPEED_OF_LIGHT_MPS


def travel_fs(a: Sequence[float], b: Sequence[float], speed_mps: float = C) -> int:
    """Light-speed delay from ``a`` to ``b`` in fs (rounded up, as in the engine)."""
    return tu.propagation_fs(float(math.dist(vec(a), vec(b))), speed_mps)


def arrival_fs(msg: Dict[str, Any], at: Sequence[float], speed_mps: float = C) -> int:
    """When ``msg`` reaches position ``at`` (which need not be the claim)."""
    return msg["send_fs"] + travel_fs(msg["position"], at, speed_mps)


def _challenge(sender, position, claim, t_ref_fs, speed_mps, **body) -> Dict[str, Any]:
    send = t_ref_fs - travel_fs(position, claim, speed_mps)
    if send < 0:
        raise ValueError(f"{sender} would have to send before t=0; pick a later t_ref_fs")
    return {"from": sender, "to": "prover", "position": [float(p) for p in position], "send_fs": send,
            "at_claim_fs": t_ref_fs, **body}


# ---------------------------------------------------------------- 1. classical verifier -> prover
def classical_verifier_message(verifier_id: str, position: Sequence[float], claim: Sequence[float],
                               share: Any, t_ref_fs: int, speed_mps: float = C) -> Dict[str, Any]:
    """Classical message carrying this verifier's basis share, sent so it reaches the claim at ``t_ref_fs``.

    ``share`` is a bit for ``xor`` or a list of bits for ``inner_product``.
    """
    return _challenge(verifier_id, position, claim, t_ref_fs, speed_mps,
                      kind="classical", tag="theta", value=share)


# ---------------------------------------------------------------- 2. quantum verifier -> prover
def quantum_verifier_message(verifier_id: str, position: Sequence[float], claim: Sequence[float],
                             x: int, shares: Sequence[Any], t_ref_fs: int, combine: str = "xor",
                             speed_mps: float = C) -> Dict[str, Any]:
    """Quantum message carrying the BB84 qubit H^b|x>, with b = combine(shares).

    Only the qubit travels: ``x`` and ``b`` stay with the verifiers.
    """
    if x not in (0, 1):
        raise ValueError("x must be 0 or 1")
    basis = _combine(combine, list(shares))
    return _challenge(verifier_id, position, claim, t_ref_fs, speed_mps,
                      kind="quantum", tag="q", qubit=qb.bb84_ket(x, basis))


# ---------------------------------------------------------------- 3. prover measures
def prover_measure(quantum_msg: Dict[str, Any], classical_msgs: List[Dict[str, Any]], combine: str = "xor",
                   rng: Optional[random.Random] = None) -> Dict[str, Any]:
    """Combine the shares into the basis b, measure the qubit in that basis (Born rule) and return the bit."""
    rng = rng or random.Random()
    basis = _combine(combine, [m["value"] for m in classical_msgs])
    amps = qb.basis_matrix(basis).conj().T @ quantum_msg["qubit"]
    probs = np.abs(amps) ** 2
    probs = probs / probs.sum()
    answer = 0 if rng.random() < probs[0] else 1
    return {"basis": basis, "answer": answer, "probabilities": [float(p) for p in probs]}


# ---------------------------------------------------------------- 4. prover -> verifiers
def prover_response(prover_id: str, position: Sequence[float], answer: int, challenges: List[Dict[str, Any]],
                    processing_fs: int = 0, speed_mps: float = C) -> Dict[str, Dict[str, Any]]:
    """The answer message to every verifier, keyed by verifier id.

    The prover can only answer once all challenges have reached it, plus its processing time.
    """
    send = max(arrival_fs(m, position, speed_mps) for m in challenges) + processing_fs
    return {m["from"]: {"from": prover_id, "to": m["from"], "kind": "classical", "tag": "answer", "value": answer,
                        "position": [float(p) for p in position], "send_fs": send,
                        "arrival_fs": send + travel_fs(position, m["position"], speed_mps)}
            for m in challenges}


# ---------------------------------------------------------------- 5. verifier checks the answer
def validate_response(response: Optional[Dict[str, Any]], verifier_position: Sequence[float],
                      claim: Sequence[float], x: int, t_ref_fs: int, tolerance_fs: int = 0,
                      speed_mps: float = C) -> Dict[str, Any]:
    """Does this answer support the claimed position?  Accept iff it equals ``x`` and arrives by the deadline.

    The deadline is the earliest an honest prover at the claim could answer (the round trip through the
    claim) plus ``tolerance_fs``.  ``response`` of ``None`` means nothing arrived.
    """
    deadline = t_ref_fs + travel_fs(verifier_position, claim, speed_mps) + tolerance_fs
    if response is None:
        return {"accepted": False, "correct": False, "on_time": False, "deadline_fs": deadline,
                "arrival_fs": None, "slack_fs": None, "reason": f"no answer by the deadline {tu.fmt(deadline)}"}
    arrived, correct = response["arrival_fs"], response["value"] == x
    on_time = arrived <= deadline
    if not correct:
        reason = f"wrong answer {response['value']} (expected {x})"
    elif not on_time:
        reason = f"answer arrived at {tu.fmt(arrived)}, {tu.fmt(arrived - deadline)} after the deadline"
    else:
        reason = f"correct answer received at {tu.fmt(arrived)} <= deadline {tu.fmt(deadline)}"
    return {"accepted": correct and on_time, "correct": correct, "on_time": on_time, "deadline_fs": deadline,
            "arrival_fs": arrived, "slack_fs": deadline - arrived, "reason": reason}

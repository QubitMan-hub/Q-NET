"""One QPV_BB84^f round as plain functions (same timing and deadline as :mod:`qpvsim.qpv.automata`).

Times are integer fs.  Each verifier sends so its challenge reaches the claim at ``t_ref_fs``.
"""

from __future__ import annotations

import math
import random

import numpy as np

from .. import timeunits as tu
from ..protocol.expr import _combine
from ..quantum import base as qb

C = tu.SPEED_OF_LIGHT_MPS


def travel_fs(a, b, speed=C):
    return tu.propagation_fs(math.dist(a, b), speed)


def _challenge(vid, position, claim, t_ref_fs, speed, **payload):
    return {"from": vid, "position": position, "send_fs": t_ref_fs - travel_fs(position, claim, speed), **payload}


def classical_verifier_message(vid, position, claim, share, t_ref_fs, speed=C):
    """1. Classical verifier -> prover: its basis share."""
    return _challenge(vid, position, claim, t_ref_fs, speed, share=share)


def quantum_verifier_message(vid, position, claim, x, shares, t_ref_fs, combine="xor", speed=C):
    """2. Quantum verifier -> prover: the qubit H^b|x>, b = combine(shares)."""
    return _challenge(vid, position, claim, t_ref_fs, speed, qubit=qb.bb84_ket(x, _combine(combine, shares)))


def prover_measure(quantum_msg, classical_msgs, combine="xor", rng=random):
    """3. Prover: basis from the shares, then a Born-rule measurement of the qubit."""
    basis = _combine(combine, [m["share"] for m in classical_msgs])
    p0 = abs(np.vdot(qb.basis_matrix(basis)[:, 0], quantum_msg["qubit"])) ** 2
    return int(rng.random() >= p0)


def prover_response(pid, position, answer, challenges, processing_fs=0, speed=C):
    """4. Prover -> every verifier: the answer, sent once all challenges have arrived."""
    send = max(m["send_fs"] + travel_fs(m["position"], position, speed) for m in challenges) + processing_fs
    return {m["from"]: {"from": pid, "value": answer, "arrival_fs": send + travel_fs(position, m["position"], speed)}
            for m in challenges}


def validate_response(response, position, claim, x, t_ref_fs, tolerance_fs=0, speed=C):
    """5. Verifier: accept iff the answer equals x and arrives by t_ref + d(V, claim)/c + tolerance."""
    deadline = t_ref_fs + travel_fs(position, claim, speed) + tolerance_fs
    correct = response is not None and response["value"] == x
    on_time = response is not None and response["arrival_fs"] <= deadline
    return {"accepted": correct and on_time, "correct": correct, "on_time": on_time, "deadline_fs": deadline}

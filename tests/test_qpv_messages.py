"""The five plain-function steps of a QPV_BB84^f round (qpvsim.qpv.messages)."""

import random

import pytest

from qpvsim import Simulation, example
from qpvsim import timeunits as tu
from qpvsim.qpv.messages import (classical_verifier_message, prover_measure, prover_response,
                                 quantum_verifier_message, travel_fs, validate_response)

T_REF, TOL = tu.ns(20), tu.ns("0.5")
CLAIM = [0.0, 0.0]
V1D = {"V0": [-3.0, 0.0], "V1": [3.0, 0.0]}


def _round(verifiers, x, shares, prover_at=CLAIM, combine="xor", processing_fs=0, seed=0, flip=False):
    ids = list(verifiers)
    qv = quantum_verifier_message(ids[0], verifiers[ids[0]], CLAIM, x, shares, T_REF, combine)
    cvs = [classical_verifier_message(v, verifiers[v], CLAIM, s, T_REF) for v, s in zip(ids[1:], shares)]
    answer = prover_measure(qv, cvs, combine, random.Random(seed)) ^ int(flip)
    replies = prover_response("P", prover_at, answer, [qv] + cvs, processing_fs)
    return {v: validate_response(replies[v], verifiers[v], CLAIM, x, T_REF, TOL) for v in ids}


def test_challenges_meet_at_the_claim():
    qv = quantum_verifier_message("V0", V1D["V0"], CLAIM, 1, [1], T_REF)
    cv = classical_verifier_message("V1", V1D["V1"], CLAIM, 1, T_REF)
    assert qv["send_fs"] == cv["send_fs"] == T_REF - travel_fs(V1D["V0"], CLAIM) == T_REF - 10_006_923
    assert qv["qubit"] == pytest.approx([2 ** -0.5, -(2 ** -0.5)])  # H|1> = |->
    assert cv["share"] == 1


@pytest.mark.parametrize("x,b", [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_right_basis_is_deterministic(x, b):
    qv = quantum_verifier_message("V0", V1D["V0"], CLAIM, x, [b], T_REF)
    cv = classical_verifier_message("V1", V1D["V1"], CLAIM, b, T_REF)
    assert all(prover_measure(qv, [cv], rng=random.Random(s)) == x for s in range(20))


def test_wrong_basis_is_a_coin_flip():
    qv = quantum_verifier_message("V0", V1D["V0"], CLAIM, 0, [1], T_REF)  # |+>
    cv = classical_verifier_message("V1", V1D["V1"], CLAIM, 0, T_REF)  # prover told Z
    rng = random.Random(1)
    assert 400 < sum(prover_measure(qv, [cv], rng=rng) for _ in range(1000)) < 600


def test_honest_prover_is_accepted():
    for seed in range(20):
        rng = random.Random(seed)
        assert all(r["accepted"] for r in _round(V1D, rng.randint(0, 1), [rng.randint(0, 1)], seed=seed).values())


def test_2d_inner_product():
    vs = {"V0": [-3.0, 0.0], "V1": [1.5, 2.6], "V2": [1.5, -2.6]}
    assert all(r["accepted"] for r in _round(vs, 1, [[1, 0, 1], [1, 1, 1]], combine="inner_product").values())


def test_wrong_late_and_missing_answers_are_rejected():
    wrong = _round(V1D, 1, [0], flip=True)["V0"]
    assert not wrong["accepted"] and not wrong["correct"]
    late = _round(V1D, 1, [0], processing_fs=tu.ns(1))["V1"]
    assert late["correct"] and not late["on_time"]
    assert not validate_response(None, V1D["V0"], CLAIM, 1, T_REF, TOL)["accepted"]


def test_displaced_prover_misses_the_far_deadline():
    res = _round(V1D, 0, [0], prover_at=[-1.0, 0.0])
    assert res["V0"]["accepted"] and not res["V1"]["on_time"]


def test_deadline_matches_the_engine():
    sim = Simulation(example("qpv_bb84_honest")).run()
    v0 = next(p for p in sim.project["participants"] if p["id"] == "V0")
    expected = validate_response(None, v0["position"], sim.project["claim"]["position"], 0,
                                 tu.ns(v0["params"]["t_ref_ns"]), tu.ns(v0["params"]["tolerance_ns"]))["deadline_fs"]
    assert sim.nodes["V0"].observations["deadline_ns"] == expected / 1e6

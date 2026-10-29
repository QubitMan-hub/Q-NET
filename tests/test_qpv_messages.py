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
    m = prover_measure(qv, cvs, combine, random.Random(seed))
    answer = m["answer"] ^ int(flip)
    replies = prover_response("P", prover_at, answer, [qv] + cvs, processing_fs)
    return {v: validate_response(replies[v], verifiers[v], CLAIM, x, T_REF, TOL) for v in ids}


def test_challenges_meet_at_the_claim_and_carry_no_secrets():
    qv = quantum_verifier_message("V0", V1D["V0"], CLAIM, 1, [1], T_REF)
    cv = classical_verifier_message("V1", V1D["V1"], CLAIM, 1, T_REF)
    assert qv["send_fs"] == cv["send_fs"] == T_REF - travel_fs(V1D["V0"], CLAIM) == T_REF - 10_006_923
    assert "x" not in qv and "basis" not in qv
    assert qv["qubit"] == pytest.approx([2 ** -0.5, -(2 ** -0.5)])  # H|1> = |->
    assert cv["value"] == 1 and cv["tag"] == "theta"
    with pytest.raises(ValueError):
        classical_verifier_message("V1", [30.0, 0.0], CLAIM, 1, T_REF)  # would need to send before t=0


@pytest.mark.parametrize("x,b", [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_honest_measurement_in_the_right_basis_is_deterministic(x, b):
    qv = quantum_verifier_message("V0", V1D["V0"], CLAIM, x, [b], T_REF)
    cv = classical_verifier_message("V1", V1D["V1"], CLAIM, b, T_REF)
    m = prover_measure(qv, [cv])
    assert m["basis"] == b and m["answer"] == x and m["probabilities"][x] == pytest.approx(1)


def test_wrong_basis_is_a_coin_flip():
    qv = quantum_verifier_message("V0", V1D["V0"], CLAIM, 0, [1], T_REF)  # |+>
    cv = classical_verifier_message("V1", V1D["V1"], CLAIM, 0, T_REF)  # prover told Z
    assert prover_measure(qv, [cv])["probabilities"] == pytest.approx([0.5, 0.5])


def test_honest_prover_at_the_claim_is_accepted_by_every_verifier():
    for seed in range(20):
        rng = random.Random(seed)
        x, s = rng.randint(0, 1), rng.randint(0, 1)
        res = _round(V1D, x, [s], seed=seed)
        assert all(r["accepted"] and r["slack_fs"] == TOL for r in res.values())


def test_2d_three_verifiers_and_inner_product():
    vs = {"V0": [-3.0, 0.0], "V1": [1.5, 2.6], "V2": [1.5, -2.6]}
    shares = [[1, 0, 1], [1, 1, 1]]  # inner product = 1*1 + 0*1 + 1*1 = 0 mod 2
    res = _round(vs, 1, shares, combine="inner_product")
    assert all(r["accepted"] for r in res.values())


def test_wrong_answer_late_answer_and_no_answer_are_rejected():
    wrong = _round(V1D, 1, [0], flip=True)["V0"]
    assert not wrong["accepted"] and not wrong["correct"] and "wrong answer" in wrong["reason"]
    late = _round(V1D, 1, [0], processing_fs=tu.ns(1))["V1"]
    assert late["correct"] and not late["on_time"] and late["slack_fs"] == TOL - tu.ns(1)
    none = validate_response(None, V1D["V0"], CLAIM, 1, T_REF, TOL)
    assert not none["accepted"] and "no answer" in none["reason"]


def test_displaced_prover_misses_the_far_verifiers_deadline():
    res = _round(V1D, 0, [0], prover_at=[-1.0, 0.0])  # 1 m towards V0
    assert res["V0"]["accepted"] and not res["V1"]["on_time"]


def test_deadline_matches_the_engine():
    sim = Simulation(example("qpv_bb84_honest")).run()
    p = {q["id"]: q for q in sim.project["participants"]}
    claim, v0 = sim.project["claim"]["position"], p["V0"]
    expected = validate_response(None, v0["position"], claim, 0, tu.ns(v0["params"]["t_ref_ns"]),
                                 tu.ns(v0["params"]["tolerance_ns"]))["deadline_fs"]
    assert sim.nodes["V0"].observations["deadline_ns"] == expected / 1e6

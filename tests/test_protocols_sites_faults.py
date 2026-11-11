"""Qudits (mutually unbiased bases), QPV_BB84^f with an entanglement budget, classical PV, real sites, faulty verifiers."""

import math

import numpy as np
import pytest

from qpvsim import validate_project
from qpvsim.experiments import run_experiment, wilson
from qpvsim.qpv import mub, presets, protocols, recipe, site
from qpvsim.webapi import WebAPI

BREIDBART = math.cos(math.pi / 8) ** 2


def rate(doc, runs, seed=5):
    s = run_experiment(doc, {"runs": runs, "seed": seed})["points"][0]["summary"]
    return s["accepted"], s["n"]


def within(kn, p):
    ci = wilson(*kn)
    return ci["lo"] <= p <= ci["hi"]


# ---------------------------------------------------------------- mutually unbiased bases
@pytest.mark.parametrize("d", mub.DIMENSIONS)
def test_mub_sets_are_complete_and_unbiased(d):
    assert len(mub.bases(d)) == d + 1
    assert mub.check(d) < 1e-9


def test_six_state_bases_are_z_x_y():
    B = mub.bases(2)
    for b, axis in zip(B, (np.diag([1, -1]), np.array([[0, 1], [1, 0]]), np.array([[0, -1j], [1j, 0]]))):
        for c in range(2):  # every basis vector is an eigenvector of its Pauli
            v = b[:, c]
            assert abs(abs(v.conj() @ axis @ v) - 1) < 1e-9


# ---------------------------------------------------------------- qudits
@pytest.mark.parametrize("d", mub.DIMENSIONS)
def test_qudit_honest_teleport_and_guessing_the_basis(d):
    assert rate(protocols.build("qudit", "honest", d=d, dim=1), 30) == (30, 30)
    assert rate(protocols.build("qudit", "teleport", d=d, dim=1), 60) == (60, 60)
    assert within(rate(protocols.build("qudit", "unentangled", d=d, dim=1), 1500, seed=11), 2 / (d + 1))


def test_qudit_in_3d():
    doc = protocols.build("qudit", "honest", d=4, dim=3)
    assert not [i for i in validate_project(doc) if i.level == "error"]
    assert rate(doc, 15) == (15, 15)


# ---------------------------------------------------------------- QPV_BB84^f
@pytest.mark.parametrize("f", protocols.F_FUNCTIONS)
def test_f_honest_prover(f):
    assert rate(protocols.build("bb84f", "honest", f=f, n_bits=3, dim=1), 40) == (40, 40)


@pytest.mark.parametrize("pairs", [0, 2, 4])
def test_f_budget_attack_follows_its_formula(pairs):
    doc = protocols.build("bb84f", "budget", f="inner_product", n_bits=2, pairs=pairs, dim=1)
    assert within(rate(doc, 600), pairs / 4 + (1 - pairs / 4) * BREIDBART)


def test_f_linear_attack_needs_a_linear_f():
    assert rate(protocols.build("bb84f", "linear", f="xor", n_bits=3, dim=1), 60) == (60, 60)
    with pytest.raises(ValueError, match="xor"):
        protocols.build("bb84f", "linear", f="random", n_bits=3, dim=1)


def test_pairs_preset_and_theory():
    doc = protocols.build("bb84f", "budget", f="random", n_bits=2, pairs=1, dim=1)
    assert presets.theory(doc, "pairs", [0, 4])["theory"] == pytest.approx([BREIDBART, 1.0])
    res = run_experiment(doc, {"runs": 40, "seed": 2, "sweep": [{"preset": "pairs", "values": [4]}]})
    assert res["points"][0]["summary"]["accepted"] == 40


# ---------------------------------------------------------------- classical PV
@pytest.mark.parametrize("dim", [1, 2, 3])
def test_classical_colluders_always_win(dim):
    assert rate(protocols.build("classical", "honest", dim=dim), 20) == (20, 20)
    assert rate(protocols.build("classical", "relay", dim=dim), 20) == (20, 20)


def test_switch_keeps_protocol():
    doc = protocols.build("qudit", "honest", d=4, dim=1)
    assert presets.answerer(protocols.switch(doc, "teleport")) == "teleport"
    with pytest.raises(ValueError):
        protocols.switch(doc, "split")


# ---------------------------------------------------------------- sites
def test_site_coordinates_and_hardware():
    doc = recipe.compose({"base": {"site": "city", "who": "honest"}, "twists": []})
    vs = [p for p in doc["participants"] if p["role"] == "verifier"]
    assert all(4990 < math.hypot(*p["position"]) < 5010 for p in vs)
    s = doc["meta"]["site"]
    assert 0.4 < s["photon_loss"] < 0.5 and s["precision_m"] > 1000
    assert within(rate(doc, 1500, seed=9), 1 - s["photon_loss"])


def test_fibre_lets_a_distant_impostor_through():
    doc = recipe.compose({"base": {"site": "city", "who": "displaced"},
                          "twists": [{"type": "place", "party": "P", "x": -2000, "y": 0}]})
    assert rate(doc, 20) == (20, 20)


def test_free_space_campus_is_precise():
    doc = recipe.compose({"base": {"site": "campus", "who": "honest"}, "twists": []})
    assert doc["meta"]["site"]["precision_m"] < 0.2
    assert site.to_local([52.0016 + 1e-3, 4.373], [52.0016, 4.373])[1] == pytest.approx(111.2, abs=0.1)


# ---------------------------------------------------------------- faulty verifiers
@pytest.mark.parametrize("fault,rule,who,expected", [
    ("offline", None, "honest", 0.0), ("offline", 2, "honest", 1.0),
    ("always_accept", None, "guess", 0.25), ("always_accept", 2, "guess", 0.75), ("always_reject", None, "honest", 0.0)])
def test_verifier_faults(fault, rule, who, expected):
    twists = [{"type": "verifier_fault", "verifier": "V2", "fault": fault}]
    if rule:
        twists.append({"type": "rule", "rule": "k_of_n", "k": rule})
    doc = recipe.compose({"base": {"dim": 2, "who": who}, "twists": twists})
    assert within(rate(doc, 300), expected)


# ---------------------------------------------------------------- API
def test_compare_route_and_catalog():
    api = WebAPI(background_experiments=False, allow_parallel=False)
    st, cat, _ = api.handle("GET", "/api/qpv/scenarios")
    assert "qudit" in cat["protocols"] and cat["comparison"]["rows"]
    cell = cat["comparison"]["rows"][2]["cells"]["entangled"]
    st, r, _ = api.handle("POST", "/api/qpv/compare", {"recipe": cell["recipe"], "rounds": 20})
    assert st == 200 and r["p"] == 1.0 and r["theory"] == 1.0
    api.handle("POST", "/api/qpv/scenario", {"recipe": {"base": {"dim": 1, "protocol": "qudit", "who": "honest"}}})
    st, an, _ = api.handle("GET", "/api/qpv/analysis")
    assert an["protocol"] == "qudit" and an["references"]["honest"]["value"] == 1.0

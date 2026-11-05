"""Many-round tests, keyed answers, weak lasers and false clicks, moving provers, more bases, theory, reports."""

import math

import pytest

from qpvsim import validate_project
from qpvsim.experiments import run_experiment, wilson
from qpvsim.qpv import motion, presets, recipe, report, rounds, scenario
from qpvsim.webapi import WebAPI


def summary(doc, runs, seed=5):
    return run_experiment(doc, {"runs": runs, "seed": seed})["points"][0]["summary"]


def within(k, n, p):
    ci = wilson(k, n)
    return ci["lo"] <= p <= ci["hi"]


# ---------------------------------------------------------------- many rounds
def test_binomial_tail_and_pass_probability():
    assert rounds.binom_tail(10, 5, 0.5) == pytest.approx(638 / 1024)
    assert rounds.pass_probability({"rounds": 88}, math.cos(math.pi / 8) ** 2) == pytest.approx(0.8536 ** 88, rel=1e-2)
    # answered ~ Bin(n, 1 - lost); every answered round right: only the answered fraction matters
    t = {"rounds": 10, "min_correct": 1.0, "min_answered": 0.5}
    assert rounds.pass_probability(t, 0.5, 0.5) == pytest.approx(rounds.binom_tail(10, 5, 0.5))


def test_rounds_needed_matches_the_write_up():
    assert rounds.rounds_needed(1.0, 0.8536)["rounds"] == 88
    r = rounds.rounds_needed(0.98, 0.8536)
    assert r["honest_fails"] <= 1e-6 and r["cheater_passes"] <= 1e-6 and 300 < r["rounds"] < 400
    assert rounds.rounds_needed(0.8, 0.85) is None


def test_test_summary_counts_blocks():
    doc = recipe.compose({"base": {"dim": 1, "who": "honest"}, "twists": [{"type": "test", "rounds": 10}]})
    t = summary(doc, 30)["test"]
    assert t["blocks"] == 3 and t["blocks_passed"] == 3 and t["pass_probability"] == 1.0


def test_invalid_test_is_a_validation_error():
    doc = scenario.build(dim=1)
    doc["verification"]["test"] = {"rounds": 0}
    assert any(i.path == "verification.test" for i in validate_project(doc) if i.level == "error")


# ---------------------------------------------------------------- keys
@pytest.mark.parametrize("bits,holder,expected", [(8, "P", 1.0), (2, "none", 0.25)])
def test_keyed_answers(bits, holder, expected):
    doc = recipe.compose({"base": {"dim": 1}, "twists": [{"type": "authenticate", "bits": bits, "holder": holder}]})
    s = summary(doc, 400)
    assert within(s["accepted"], s["n"], expected)


def test_attackers_without_the_key_are_rejected():
    doc = recipe.compose({"base": {"dim": 1, "who": "teleport"},
                          "twists": [{"type": "authenticate", "bits": 8, "holder": "none"}]})
    assert summary(doc, 40)["accepted"] == 0


# ---------------------------------------------------------------- photon source and detectors
def test_weak_laser_honest_and_splitting():
    mu = 0.8
    honest = summary(recipe.compose({"base": {"dim": 1}, "twists": [{"type": "source", "mean_photons": mu}]}), 600)
    assert within(honest["accepted"], honest["n"], 1 - math.exp(-mu))
    split = summary(recipe.compose({"base": {"dim": 1, "who": "split"},
                                    "twists": [{"type": "source", "mean_photons": mu}]}), 600)
    assert within(split["accepted"], split["n"], 1 - math.exp(-mu) * (1 + mu))
    assert all("wrong_answer" not in v["categories"] for v in split["verifiers"].values())


def test_false_clicks_cost_half_their_rate():
    s = summary(recipe.compose({"base": {"dim": 1}, "twists": [{"type": "detector", "party": "P", "dark_count": 0.3}]}), 600)
    assert within(s["accepted"], s["n"], 0.85)


def test_honest_prover_reports_lost_photons():
    doc = recipe.compose({"base": {"dim": 1}, "twists": [{"type": "link", "verifier": "V0", "loss_prob": 0.5},
                                                          {"type": "loss_reports"}]})
    s = summary(doc, 300)
    assert set(s["verifiers"]["V0"]["categories"]) == {"accepted", "lost"}


# ---------------------------------------------------------------- moving prover
def test_motion_moves_party_and_claim():
    doc = recipe.compose({"base": {"dim": 2}, "twists": [{"type": "motion", "vx": 2.0, "vy": 1.0, "tracked": 0.5,
                                                           "interval_ms": 10}]})
    later = motion.at_round(doc, 5)
    p = next(q for q in later["participants"] if q["id"] == "P")
    assert p["position"] == pytest.approx([0.1, 0.05]) and later["claim"]["position"] == pytest.approx([0.05, 0.025])
    assert motion.at_round(doc, 0) is doc


def test_untracked_walk_fails_after_the_precision_is_used_up():
    d = recipe.demo("b1_walking_untracked")
    s = summary(report.compose_demo(d), d["runs"])
    assert s["accepted"] == 33


# ---------------------------------------------------------------- more bases
def test_more_bases():
    for who, expected in (("honest", 1.0), ("lossy", 0.25), ("guess", 0.25)):
        s = summary(scenario.build(dim=1, bases=4, **({"attack": who} if who != "honest" else {})), 400)
        assert within(s["accepted"], s["n"], expected), who
    with pytest.raises(ValueError, match="bases"):
        scenario.build(dim=1, bases=4, attack="teleport")
    assert summary(scenario.build(dim=3, bases=3), 20)["accepted"] == 20


# ---------------------------------------------------------------- theory, presets, report, API
@pytest.mark.parametrize("who,preset,value", [("honest", "loss", 0.4), ("unentangled", "noise", 0.3),
                                              ("split", "photons", 1.2), ("honest", "dark_count", 0.4)])
def test_theory_matches_simulation(who, preset, value):
    doc = scenario.build(dim=1, attack="none" if who == "honest" else who)
    th = presets.theory(doc, preset, [value])["theory"][0]
    pt = run_experiment(doc, {"runs": 800, "seed": 9, "sweep": [{"preset": preset, "values": [value]}]})["points"][0]
    assert within(pt["summary"]["accepted"], pt["summary"]["n"], th)


def test_report_rows_and_rendering():
    rows = [report.row("a1_midway", 20), report.row("b8_88_rounds", 50)]
    assert rows[0]["ok"] and rows[1]["test"]["rounds"] == 88
    for fmt, marker in (("md", "| Case |"), ("csv", "id,section"), ("html", "<table>")):
        assert marker in report.render(rows, fmt)


def test_every_demo_twist_type_is_described():
    used = {t["type"] for d in recipe.demos()["demos"] for t in d["recipe"]["twists"]}
    assert used <= set(recipe.schema()["twists"])


def test_api_routes():
    api = WebAPI(background_experiments=False, allow_parallel=False)
    st, row, _ = api.handle("POST", "/api/qpv/report", {"id": "a1_midway", "rounds": 10})
    assert st == 200 and row["n"] == 10
    st, text, kind = api.handle("POST", "/api/qpv/report/render", {"rows": [row], "format": "csv"})
    assert st == 200 and kind == "text" and "a1_midway" in text
    assert api.handle("POST", "/api/qpv/report", {"id": "nope"})[0] == 404
    api.handle("POST", "/api/qpv/scenario", {"id": "1d_honest"})
    st, th, _ = api.handle("POST", "/api/qpv/theory", {"preset": "noise", "values": [0, 0.2]})
    assert st == 200 and th["theory"] == pytest.approx([1.0, 0.9])
    st, r, _ = api.handle("POST", "/api/qpv/rounds", {"p_honest": 1.0, "p_cheat": 0.8536})
    assert r["needed"]["rounds"] == 88

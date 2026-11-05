"""Scenario recipes: every demo in demos.json behaves as its write-up says, and bad recipes fail clearly."""

import pytest

from qpvsim import Simulation, validate_project
from qpvsim.experiments import run_experiment
from qpvsim.invariants import check_trace
from qpvsim.qpv import recipe
from qpvsim.webapi import WebAPI

DEMOS = recipe.demos()["demos"]


@pytest.mark.parametrize("demo", DEMOS, ids=[d["id"] for d in DEMOS])
def test_demo_recipe_matches_its_expected_pass_rate(demo):
    doc = recipe.compose({**demo["recipe"], "title": demo["title"]})
    assert [i.message for i in validate_project(doc) if i.level == "error"] == []
    assert check_trace(Simulation(doc, seed=1).run())["ok"]
    lo, hi = demo["expect_rate"]
    p = run_experiment(doc, {"runs": demo.get("runs", 300), "seed": 11})["points"][0]["summary"]["acceptance"]["p"]
    assert lo - 1e-9 <= p <= hi + 1e-9, f"{demo['id']}: {p} not in {demo['expect_rate']}"


def test_every_twist_and_strategy_is_described_by_the_schema():
    s = recipe.schema()
    assert set(s["twists"]) == set(recipe.TWISTS) and set(s["strategies"]) == set(recipe.STRATEGIES)
    for t in s["twists"].values():
        assert t["label"] and all({"type", "label"} <= set(f) for f in t["fields"].values())


def test_demos_only_use_known_twists():
    for d in DEMOS:
        assert {t["type"] for t in d["recipe"]["twists"]} <= set(recipe.TWISTS), d["id"]


@pytest.mark.parametrize("bad, words", [
    ({"base": {"who": "nobody"}}, "unknown 'who'"),
    ({"base": {"dim": 1, "colour": "red"}}, "unknown base field"),
    ({"base": {"dim": 1}, "twists": [{"type": "warp"}]}, "unknown type 'warp'"),
    ({"base": {"dim": 1}, "twists": [{"type": "place", "party": "Q", "x": 1}]}, "no participant 'Q'"),
    ({"base": {"dim": 1}, "twists": [{"type": "clock", "verifier": "P", "offset_ns": 1}]}, "is not a verifier"),
])
def test_bad_recipes_fail_with_a_clear_message(bad, words):
    with pytest.raises(recipe.RecipeError, match=words):
        recipe.compose(bad)


def test_recipes_compose_in_any_dimension():
    # the same generic twists work beyond the 1D demos
    doc = recipe.compose({"base": {"dim": 3, "who": "lossy"}, "twists": [
        {"type": "loss_reports", "on": True}, {"type": "clock", "verifier": "V2", "offset_ns": 0.1},
        {"type": "intercept", "verifier": "V3", "action": "relay", "at": 0.3}]})
    assert not [i for i in validate_project(doc) if i.level == "error"]
    r = run_experiment(doc, {"runs": 100, "seed": 3})["points"][0]["summary"]
    cats = r["verifiers"]["V0"]["categories"]
    assert set(cats) <= {"accepted", "lost"} and cats.get("lost", 0) > 20


def test_api_builds_demos_and_recipes():
    api = WebAPI(background_experiments=False)
    status, body, _ = api.handle("GET", "/api/qpv/scenarios")
    assert status == 200 and len(body["demos"]["demos"]) == len(DEMOS) and "twists" in body["recipe"]
    status, body, _ = api.handle("POST", "/api/qpv/scenario", {"demo": "f1_selective_loss"})
    assert status == 200 and body["project"]["meta"]["demo"]["who"] == "cheat"
    status, body, _ = api.handle("POST", "/api/qpv/scenario", {"recipe": {"base": {"dim": 1}, "twists": [{"type": "warp"}]}})
    assert status == 400 and "warp" in body["detail"]
    status, _, _ = api.handle("POST", "/api/qpv/scenario", {"demo": "nope"})
    assert status == 404


def test_every_demo_says_who_answers():
    assert all(d["who"] in ("honest", "cheat") for d in DEMOS)


def test_cli_lists_and_runs_scenarios(capsys, tmp_path):
    from qpvsim.cli import main
    assert main(["scenarios"]) == 0
    assert "d1_teleport" in capsys.readouterr().out
    out = tmp_path / "p.json"
    assert main(["scenario", "a1_midway", "--rounds", "5", "--save", str(out)]) == 0
    assert "Passed 5 of 5 rounds" in capsys.readouterr().out and out.exists()
    assert main(["scenario", "no_such_case"]) == 1

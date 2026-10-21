"""Console commands: names, aliases, path shorthand, scenario editing and analysis views."""

import pytest

from qpvsim import example
from qpvsim import timeunits as tu
from qpvsim.console import Console
from qpvsim.session import Session


def con(name="qpv_bb84_honest"):
    return Console(Session(example(name)))


def ok(c, line):
    r = c.execute(line)
    assert r.ok, r.output
    return r


@pytest.mark.parametrize("old, new", [
    ("node P", "inspect P"), ("fsm V0", "automaton V0"), ("chain 1", "causes m1"), ("queue", "next"),
    ("invariants", "check"), ("caps P", "profile P"), ("why", "decision"), ("assert outcome accept", "expect outcome accept"),
])
def test_old_command_names_still_work(old, new):
    c = con()
    ok(c, "run")
    assert ok(c, old).output == ok(c, new).output


def test_catalog_drives_groups_starters_and_views():
    c = con()
    cat = c.catalog()
    assert len({x["name"] for x in cat}) == len(cat)  # each command once, aliases listed inside
    assert [x["name"] for x in cat if x["starter"]] == ["run", "step", "next", "decision", "participants", "help"]
    assert c.execute("why").view == "decision" and c.execute("help").view == "help"
    for x in cat:
        for alias in x["aliases"]:
            assert c.commands[alias].name == x["name"]


def test_set_and_get_accept_participant_and_link_shorthand():
    c = con()
    assert "participants.V0.params.tolerance_ns = 0.01" in ok(c, "set V0.tolerance_ns 0.01").output
    assert "participants.P.processing_ns" in ok(c, "set P.processing_ns 0.3").output
    assert "links.q0.noise.depolarizing" in ok(c, "set q0.noise.depolarizing 0.1").output
    assert ok(c, "get V0.tolerance_ns").data == 0.01
    assert ok(c, "get sim.seed").data == 7
    r = c.execute("set P.typo 1")
    assert not r.ok and "no field or parameter 'typo'" in r.output
    ok(c, "run")
    ok(c, "expect outcome reject")
    ok(c, "expect V0.state rejected")


def test_unknown_command_suggests_the_closest_name():
    r = con().execute("rnu")
    assert not r.ok and "Did you mean run?" in r.output


def test_timing_reports_answer_margin_against_the_deadline():
    c = con()
    ok(c, "run")
    r = ok(c, "timing V0")
    assert "margin +0.300000 ns vs timer 'deadline'" in r.output  # tolerance 0.5 - processing 0.2
    assert r.data["V0"]["verdict"]["outcome"] == "accept"


def test_geometry_gives_light_travel_times():
    r = ok(con(), "geometry")
    assert r.data["light_fs"]["V0"]["P"] == tu.propagation_fs(3, tu.SPEED_OF_LIGHT_MPS)
    assert "to claim 10.006923 ns" in r.output


def test_build_a_scenario_from_the_console():
    c = con("cpv_honest")
    ok(c, "remove P")
    assert c.session.project["links"] == []
    ok(c, "add participant P prover x=0 strategy=cpv_prover")
    assert "c0" in ok(c, "add link V0.prover P.left").output
    assert "c1" in ok(c, "add link V1.prover P.right").output
    assert not [i for i in c.session.validate() if i["level"] == "error"]
    ok(c, "run")
    ok(c, "expect outcome accept")
    p = c.session.project["participants"][-1]
    assert p["capabilities"] == "honest_prover" and p["position"] == [0.0, 0.0]


def test_strategy_lists_alternatives_and_strategies_filters_by_role():
    c = con()
    assert "cpv_prover" in ok(c, "strategy P").data["alternatives"]
    assert set(ok(c, "strategies verifier").data) == {"cpv_verifier", "qpv_verifier_quantum",
                                                      "qpv_verifier_classical"}


def test_repeat_varies_several_settings_with_shorthand_paths():
    r = ok(con(), "repeat 5 vary=P.processing_ns:0,0.4;V0.tolerance_ns:0.5,1")
    points = r.data["points"]
    assert len(points) == 4
    assert set(points[0]["assignment"]) == {"participants.P.processing_ns", "participants.V0.params.tolerance_ns"}


def test_experiment_without_id_lists_saved_experiments():
    assert "noise_sweep" in ok(con(), "experiment").output

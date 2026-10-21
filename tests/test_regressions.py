"""Regression tests for bugs found during the code review."""

from qpvsim import Simulation, example, validate_project, normalize
from qpvsim.console import Console
from qpvsim.experiments import run_experiment
from qpvsim.session import Session
from qpvsim.webapi import WebAPI


def _prover_actions(doc, actions):
    doc["automata"]["qpv_prover_2v"]["transitions"][0]["actions"] = actions
    return doc


def _halted_prover(actions):
    sim = Simulation(_prover_actions(example("qpv_bb84_honest"), actions)).run()
    p = sim.nodes["P"]
    assert p.outcome == "error" and sim.counters["protocol_errors"] == 1
    return p.error


def test_angle_measurement_without_angle_halts_instead_of_crashing():
    # used to raise TypeError out of Simulation.run() (formatting angle=None)
    err = _halted_prover([{"op": "measure", "qubit": "q", "basis": "'angle'", "result": "answer"}])
    assert "angle" in err


def test_non_numeric_timer_or_bb84_value_halts_instead_of_crashing():
    # used to raise TypeError/ValueError out of Simulation.run()
    assert "respond" in _halted_prover([{"op": "timer", "name": "t", "after_ns": "'soon'"}])
    assert "respond" in _halted_prover([{"op": "prepare_bb84", "qubit": "r", "bit": "None", "basis": "0"}])


def test_negative_link_delays_are_rejected():
    # a negative latency let signals arrive faster than light without any validation error
    for field in ("latency_ns", "jitter_ns", "attenuation_db_per_km"):
        doc = example("qpv_bb84_honest")
        doc["links"][1][field] = -5
        issues = validate_project(normalize(doc))
        assert any(i.level == "error" and i.path == f"links[c0].{field}" for i in issues), field


def test_mixed_position_dimensions_are_reported_by_validation():
    # used to pass validation and then fail inside math.dist when building the run
    doc = example("qpv_bb84_honest")
    doc["participants"][2]["position"] = [0.0]
    issues = validate_project(normalize(doc))
    assert any(i.level == "error" and "coordinates" in i.message for i in issues)


def test_console_bad_index_or_field_is_an_error_not_an_exception():
    con = Console(Session(example("qpv_bb84_honest")))
    con.execute("run")
    assert not con.execute("event 99999").ok          # used to raise IndexError (HTTP 500)
    assert not con.execute("assert node.P.nosuch 1").ok  # used to raise AttributeError


def test_console_caps_shows_profile_of_object_capabilities():
    doc = example("qpv_bb84_honest")
    doc["participants"][2]["capabilities"] = {"profile": "measure_only", "max_qubits": 1}
    r = Console(Session(doc)).execute("caps P")
    assert r.ok and '"profile": "measure_only"' in r.output and '"max_qubits": 1' in r.output


def test_experiment_job_runs_on_a_snapshot_of_the_project(monkeypatch):
    import qpvsim.webapi as webapi
    seen = {}
    monkeypatch.setattr(webapi, "run_experiment", lambda project, exp, **kw: seen.setdefault("p", project))
    api = WebAPI(background_experiments=False)
    api.handle("POST", "/api/experiments", {"runs": 1})
    assert seen["p"] == api.session.project and seen["p"] is not api.session.project


def test_parallel_results_keep_seed_order():
    exp = {"runs": 60, "seed": 3, "workers": 3}
    par = run_experiment(example("cpv_honest"), exp)["points"][0]["runs"]
    seq = run_experiment(example("cpv_honest"), {**exp, "workers": 1})["points"][0]["runs"]
    assert [r["seed"] for r in par] == [r["seed"] for r in seq]

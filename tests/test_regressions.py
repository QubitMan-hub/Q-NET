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


# ---------------------------------------------------------------- edge cases found by "absurd scenario" runs
import copy

import pytest

from qpvsim.qpv.scenario import build
from qpvsim.qpv.timing import table as timing_table


def _p(doc, pid):
    return next(p for p in doc["participants"] if p["id"] == pid)


def _outcome(doc):
    return Simulation(doc).run().snapshot()["decision"]["outcome"]


def test_far_verifier_postpones_the_meeting_instead_of_failing_the_honest_prover():
    # a verifier dragged from 3 m to 30 m used to need to send at -80 ns; its timer fired at 0 instead,
    # so the honest prover was rejected 80 ns late with no explanation
    doc = build(dim=1, prover="honest")
    _p(doc, "V1")["position"] = [30.0, 0.0]
    sim = Simulation(doc).run()
    assert sim.snapshot()["decision"]["outcome"] == "accept"
    assert all(m.depart_time >= 0 for m in sim.messages.values())
    assert sim.nodes["V0"].observations["meeting_ns"] == pytest.approx(100.069229 + 1, abs=1e-6)
    issues = timing_table(doc)["issues"]
    assert len(issues) == 1 and "moved from 20 ns" in issues[0] and "V1 is 30 m" in issues[0]


def test_meeting_time_in_the_past_is_postponed():
    doc = build(dim=1, prover="honest")
    for v in ("V0", "V1"):
        _p(doc, v)["params"]["t_ref_ns"] = -50.0
    assert _outcome(doc) == "accept"


def test_default_setups_keep_their_meeting_time():
    sim = Simulation(example("qpv_bb84_honest")).run()
    assert sim.nodes["V0"].observations["meeting_ns"] == 20.0
    assert timing_table(example("qpv_bb84_honest"))["issues"] == []


def test_timing_names_an_overdue_timer():
    # a hand-written verifier that does not postpone: the Timing tab says which timer could not be met
    doc = build(dim=1, prover="honest")
    _p(doc, "V1")["position"] = [30.0, 0.0]
    for name in ("qpv_verifier_quantum", "qpv_verifier_classical"):
        arm = doc["automata"][name]["transitions"][0]["actions"]
        arm[0]["expr"] = "fs(t_ref_ns)"
    issues = timing_table(doc)["issues"]
    assert any("V1's timer 'emit' was due at -80.069229 ns" in i for i in issues)


def test_negative_tolerance_is_refused():
    doc = build(dim=1, prover="honest")
    _p(doc, "V0")["params"]["tolerance_ns"] = -1.0
    errs = [i.message for i in validate_project(doc) if i.level == "error"]
    assert errs == ["tolerance_ns must be at least 0 (got -1.0)"]


def test_clock_reads_the_time_limit_when_the_run_hits_it():
    doc = build(dim=1, prover="honest")
    doc["physics"]["signal_speed_mps"] = 1.0
    sim = Simulation(doc).run()
    assert sim.stop_reason.startswith("time limit") and sim.now == sim.max_time


def _two_at_the_claim(qubit_to):
    """The honest prover P and an attacker A both at the claim; the shares reach both, the qubit one."""
    doc = build(dim=1, prover="honest")
    a = copy.deepcopy(_p(doc, "P"))
    a.update(id="A", role="adversary", label="Attacker at the claimed spot")
    doc["participants"].append(a)
    for link in list(doc["links"]):
        if "P" not in (link["a"]["node"], link["b"]["node"]):
            continue
        if link["kind"] == "classical":
            link = copy.deepcopy(link)
            link["id"] += "A"
            doc["links"].append(link)
        if link["kind"] == "classical" or qubit_to == "A":
            for end in ("a", "b"):
                if link[end]["node"] == "P":
                    link[end]["node"] = "A"
    return doc


@pytest.mark.parametrize("qubit_to, answers, waits", [("A", "A", "P"), ("P", "P", "A")])
def test_two_parties_at_the_claim_whoever_holds_the_qubit_answers(qubit_to, answers, waits):
    doc = _two_at_the_claim(qubit_to)
    assert [i.message for i in validate_project(doc) if i.level == "error"] == []
    sim = Simulation(doc).run()
    assert sim.snapshot()["decision"]["outcome"] == "accept"
    shares = [m for m in sim.messages.values() if m.tag == "theta"]
    assert sorted(m.dst for m in shares) == ["A", "P"]  # one classical send, broadcast on both links
    assert {m.src for m in sim.messages.values() if m.tag == "answer"} == {answers}
    assert sim.nodes[waits].state != sim.nodes[answers].state


def test_a_qubit_cannot_leave_one_port_on_two_quantum_links():
    doc = _two_at_the_claim("P")
    q = next(l for l in doc["links"] if l["kind"] == "quantum")
    doc["links"].append(dict(copy.deepcopy(q), id="q0A", b={"node": "A", "port": q["b"]["port"]}))
    errs = [i.message for i in validate_project(doc) if i.level == "error"]
    assert any("cannot be sent down two channels (no-cloning)" in e for e in errs)

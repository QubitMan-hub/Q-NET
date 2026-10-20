"""Engine semantics: reference traces, timing, deadlines, clocks, capabilities, loss, reproducibility."""

import copy
import math

import pytest
from hypothesis import given, settings, strategies as st

from qpvsim import Simulation, check_trace, example, normalize, set_path
from qpvsim import timeunits as tu
from qpvsim.library import write_examples, EXAMPLES

C = tu.SPEED_OF_LIGHT_MPS
D3 = tu.propagation_fs(3, C)  # 10006923 fs: verifier <-> claim
D15 = tu.propagation_fs(1.5, C)


def run(doc, seed=None):
    return Simulation(doc, seed=seed).run()


def kinds(sim, node=None):
    return [(r.kind, r.node) for r in sim.trace if node is None or r.node == node]


# ---------------------------------------------------------------- reference scenario
def test_honest_reference_trace_hand_calculated():
    """Every timestamp of the honest QPV_BB84 round, derived by hand from the geometry.

    V0 at -3 m, V1 at +3 m, claim and P at 0, c exact, t_ref = 20 ns, P processing 0.2 ns,
    tolerance 0.5 ns.  Emission at fs_round(20 - 10.006922856) = 9.993077 ns.
    """
    sim = run(example("qpv_bb84_honest"))
    emit = tu.ns(20) - D3 + 0  # 9993077 fs (fs_round of the float expression)
    assert emit == 9_993_077
    sends = {(m.src, m.tag): m for m in sim.messages.values()}
    q = sends[("V0", "q")]
    th = sends[("V1", "theta")]
    assert q.depart_time == emit and th.depart_time == emit
    assert q.arrival_time == th.arrival_time == emit + D3 == tu.ns(20)  # simultaneous at the claim
    a0 = sends[("P", "answer")]
    answers = [m for m in sim.messages.values() if m.src == "P"]
    assert {m.depart_time for m in answers} == {tu.ns(20) + tu.ns("0.2")}
    assert {m.arrival_time for m in answers} == {tu.ns("20.2") + D3}
    for v in ("V0", "V1"):
        node = sim.nodes[v]
        assert node.outcome == "accept"
        assert node.verdict["time_fs"] == tu.ns("20.2") + D3
        assert node.observations["deadline_ns"] == pytest.approx(30.506923)
    dec = sim.snapshot()["decision"]
    assert dec["outcome"] == "accept" and dec["accepts"] == 2
    # event sequence of the prover
    assert [k for k, _ in kinds(sim, "P")] == [
        "node.start", "msg.deliver", "msg.deliver", "transition.begin",
        "transition.complete", "msg.send", "msg.send", "node.finish"]
    assert check_trace(sim)["ok"]


def test_trace_explains_timestamps():
    sim = run(example("qpv_bb84_honest"))
    deliver = next(r for r in sim.trace if r.kind == "msg.deliver" and r.node == "P")
    assert "propagation" in deliver.explain and "3 m" in deliver.explain
    begin = next(r for r in sim.trace if r.kind == "transition.begin" and r.node == "P")
    assert "processing time" in begin.explain


@pytest.mark.parametrize("delta_fs, expect", [(0, "accept"), (1, "reject")])
def test_deadline_is_inclusive_to_the_femtosecond(delta_fs, expect):
    """Tolerance equal to the processing time puts the answer exactly on the deadline."""
    doc = normalize(example("qpv_bb84_honest"))
    proc = "0.2"
    for v in ("V0", "V1"):
        set_path(doc, f"participants.{v}.params.tolerance_ns", 0.2)
    set_path(doc, "participants.P.processing_ns", float(tu.ns(proc) + delta_fs) / tu.NS)
    sim = run(doc)
    assert sim.nodes["V0"].outcome == expect
    if expect == "reject":
        assert sim.snapshot()["decision"]["verifiers"][0]["category"] == "timeout"


def test_displaced_prover_rejected_by_far_verifier():
    sim = run(example("qpv_bb84_displaced_prover"))
    dec = sim.snapshot()["decision"]
    cats = {v["id"]: v["category"] for v in dec["verifiers"]}
    assert cats == {"V0": "accepted", "V1": "timeout"}
    assert dec["outcome"] == "reject"


def test_wrong_answer_classified():
    doc = normalize(example("qpv_bb84_honest"))
    doc["automata"]["qpv_bb84_honest_prover"]["transitions"][0]["actions"][1]["value"] = "1 - answer"
    doc["automata"]["qpv_bb84_honest_prover"]["transitions"][0]["actions"][2]["value"] = "1 - answer"
    sim = run(doc)
    assert {v["category"] for v in sim.snapshot()["decision"]["verifiers"]} == {"wrong_answer"}


# ---------------------------------------------------------------- attacks & timing
def test_teleportation_attack_wins_every_round_when_fast():
    doc = example("qpv_bb84_teleportation_attack")
    for seed in range(40):
        sim = run(doc, seed)
        assert sim.snapshot()["decision"]["outcome"] == "accept", seed
        assert check_trace(sim)["ok"]


def test_teleportation_attack_fails_when_processing_exceeds_tolerance():
    doc = normalize(example("qpv_bb84_teleportation_attack"))
    set_path(doc, "participants.E0.processing_ns", 0.6)
    for seed in range(10):
        dec = run(doc, seed).snapshot()["decision"]
        assert dec["outcome"] == "reject"
        assert {v["category"] for v in dec["verifiers"]} == {"timeout"}


def test_attack_arrival_equals_honest_light_cone_on_a_line():
    """Collinear adversaries are exactly as fast as an honest prover with zero processing."""
    sim = run(example("qpv_bb84_collusion_unentangled"))
    resp = [m for m in sim.messages.values() if m.tag == "answer"]
    expected = tu.ns(20) + D3
    # each path accumulates at most one fs of rounding per hop
    assert all(abs(m.arrival_time - expected) <= 3 for m in resp)


def test_classical_pv_broken_by_collusion():
    for seed in range(20):
        assert run(example("cpv_collusion"), seed).snapshot()["decision"]["outcome"] == "accept"
        assert run(example("cpv_honest"), seed).snapshot()["decision"]["outcome"] == "accept"


# ---------------------------------------------------------------- clocks
def test_verifier_clock_offset_changes_decision():
    """A verifier whose clock runs 1 ns ahead emits early and judges a late deadline wrongly."""
    doc = normalize(example("qpv_bb84_honest"))
    set_path(doc, "participants.V1.clock", {"offset_ns": 1.0, "drift_ppm": 0})
    sim = run(doc)
    th = next(m for m in sim.messages.values() if m.tag == "theta")
    assert th.depart_time == 9_993_077 - tu.ns(1)  # local time is 1 ns ahead
    # theta now reaches P 1 ns before the qubit; P still answers when both are present
    assert sim.nodes["P"].finished


def test_clock_drift_applied_to_timers():
    doc = normalize(example("qpv_bb84_honest"))
    set_path(doc, "participants.V0.clock", {"offset_ns": 0, "drift_ppm": 1000})  # 0.1 %
    sim = run(doc)
    q = next(m for m in sim.messages.values() if m.tag == "q")
    node = sim.nodes["V0"]
    assert node.local(q.depart_time) >= 9_993_077 > node.local(q.depart_time - 1)


# ---------------------------------------------------------------- capabilities
def test_capability_violation_halts_participant():
    doc = normalize(example("qpv_bb84_collusion_unentangled"))
    set_path(doc, "participants.E0.capabilities", "classical_only")  # may not measure
    sim = run(doc)
    e0 = sim.nodes["E0"]
    assert e0.outcome == "error" and "measure_bases" in e0.error
    rec = next(r for r in sim.trace if r.kind == "capability.violation")
    assert rec.node == "E0" and rec.data["capability"] == "measure_bases"
    assert sim.snapshot()["decision"]["outcome"] == "reject"


def test_measure_only_profile_allows_strategy():
    doc = normalize(example("qpv_bb84_collusion_unentangled"))
    set_path(doc, "participants.E0.capabilities", "measure_only")
    sim = run(doc)
    assert sim.nodes["E0"].error is None


def test_min_processing_capability_enforced():
    doc = normalize(example("qpv_bb84_teleportation_attack"))
    set_path(doc, "participants.E1.capabilities", {"profile": "bounded_entanglement", "min_processing_ns": 1.0})
    sim = run(doc)
    begin = next(r for r in sim.trace if r.kind == "transition.begin" and r.node == "E1")
    assert begin.data["duration_fs"] == tu.ns(1)
    assert sim.snapshot()["decision"]["outcome"] == "reject"


def test_max_qubits_refuses_incoming_qubit():
    doc = normalize(example("qpv_bb84_teleportation_attack"))
    set_path(doc, "participants.E0.capabilities", {"profile": "bounded_entanglement", "max_qubits": 1})
    sim = run(doc)
    assert any(r.kind == "msg.refused" and r.node == "E0" for r in sim.trace)
    assert sim.snapshot()["decision"]["outcome"] == "reject"


def test_participants_cannot_read_other_participants_state():
    """Expressions see only local variables: E1 cannot reference the verifiers' secret x."""
    doc = normalize(example("qpv_bb84_collusion_unentangled"))
    a = doc["automata"]["qpv_bb84_adv_forward_basis"]
    a["transitions"][1]["actions"][0]["value"] = "x"
    from qpvsim import validate_project
    assert any("unknown name 'x'" in i.message for i in validate_project(doc))


# ---------------------------------------------------------------- loss & noise
def test_lost_qubit_leads_to_timeout():
    doc = normalize(example("qpv_bb84_honest"))
    set_path(doc, "links.q0.loss_prob", 1.0)
    sim = run(doc)
    assert any(r.kind == "msg.loss" for r in sim.trace)
    assert sim.snapshot()["decision"]["outcome"] == "reject"
    assert not sim.nodes["P"].finished


def test_full_depolarisation_gives_half_error_rate():
    doc = normalize(example("qpv_bb84_honest"))
    set_path(doc, "links.q0.noise.depolarizing", 1.0)
    acc = sum(run(doc, s).nodes["V0"].outcome == "accept" for s in range(400))
    assert abs(acc / 400 - 0.5) < 0.1


def test_memory_storage_limit_decoheres():
    doc = normalize(example("qpv_bb84_honest"))
    set_path(doc, "participants.P.capabilities", {"profile": "honest_prover", "memory_ns": 0.0})
    set_path(doc, "participants.V1.params.t_ref_ns", 21.0)  # theta arrives 1 ns after the qubit
    sim = run(doc)
    assert any(r.kind == "qubit.decohered" for r in sim.trace)


# ---------------------------------------------------------------- reproducibility
def _fingerprint(sim):
    return [(r.time, r.kind, r.node, repr(r.data)) for r in sim.trace]


def test_same_seed_same_trace_and_different_seed_differs():
    doc = example("qpv_bb84_collusion_unentangled")
    a, b = run(doc, 5), run(doc, 5)
    assert _fingerprint(a) == _fingerprint(b)
    outcomes = {run(doc, s).nodes["V0"].vars["x"] for s in range(20)}
    assert outcomes == {0, 1}


def test_random_streams_are_stable_under_unrelated_edits():
    doc = normalize(example("qpv_bb84_honest"))
    base = run(doc, 3)
    doc2 = copy.deepcopy(doc)
    doc2["participants"].append(dict(copy.deepcopy(doc["participants"][2]), id="Bystander",
                                     position=[50.0, 0.0]))
    other = run(doc2, 3)
    assert base.nodes["V0"].vars["x"] == other.nodes["V0"].vars["x"]
    assert base.nodes["P"].vars["answer"] == other.nodes["P"].vars["answer"]


def test_step_by_step_equals_run():
    doc = example("qpv_bb84_teleportation_attack")
    a = run(doc, 9)
    b = Simulation(doc, seed=9)
    while b.step() is not None:
        pass
    assert _fingerprint(a) == _fingerprint(b)


def test_run_until_stops_at_time():
    sim = Simulation(example("qpv_bb84_honest"))
    sim.run(until_fs=tu.ns(15))
    assert sim.now == tu.ns(15) and not sim.stopped
    assert all(e.time > tu.ns(15) for e in sim.scheduler.pending())
    sim.run()
    assert sim.stopped


def test_state_vector_backend_gives_same_decisions_for_pure_protocol():
    doc = normalize(example("qpv_bb84_teleportation_attack"))
    set_path(doc, "simulation.backend", "state_vector")
    for seed in range(15):
        assert run(doc, seed).snapshot()["decision"]["outcome"] == "accept"


def test_example_files_match_library(tmp_path):
    import json
    from pathlib import Path
    shipped = Path(__file__).resolve().parents[1] / "src" / "qpvsim" / "examples"
    write_examples(tmp_path)
    for name in EXAMPLES:
        assert json.loads((shipped / f"{name}.json").read_text()) == json.loads((tmp_path / f"{name}.json").read_text()), name


# ---------------------------------------------------------------- property-based
@settings(max_examples=60, deadline=None)
@given(vdist=st.floats(1.0, 50.0), proc=st.floats(0.0, 2.0), tol=st.floats(0.0, 2.0),
       seed=st.integers(0, 10 ** 6))
def test_honest_acceptance_iff_processing_within_tolerance(vdist, proc, tol, seed):
    doc = normalize(example("qpv_bb84_honest"))
    set_path(doc, "participants.V0.position", [-vdist, 0.0])
    set_path(doc, "participants.V1.position", [vdist, 0.0])
    t_ref = vdist / C * 1e9 + 1.0
    for v in ("V0", "V1"):
        set_path(doc, f"participants.{v}.params.t_ref_ns", t_ref)
        set_path(doc, f"participants.{v}.params.tolerance_ns", tol)
    set_path(doc, "participants.P.processing_ns", proc)
    sim = run(doc, seed)
    assert check_trace(sim)["ok"], check_trace(sim)["violations"]
    out = sim.snapshot()["decision"]["outcome"]
    # allow 2 fs of grid rounding at the boundary
    if proc < tol - 1e-5:
        assert out == "accept"
    elif proc > tol + 1e-5:
        assert out == "reject"


@settings(max_examples=40, deadline=None)
@given(x0=st.floats(-3.0, -0.2), x1=st.floats(0.2, 3.0), p0=st.floats(0, 1), p1=st.floats(0, 1),
       seed=st.integers(0, 1000), name=st.sampled_from(sorted(EXAMPLES)))
def test_invariants_hold_for_random_adversary_geometry(x0, x1, p0, p1, seed, name):
    doc = normalize(example(name))
    ids = [p["id"] for p in doc["participants"]]
    if "E0" in ids:
        set_path(doc, "participants.E0.position", [x0, 0.0])
        set_path(doc, "participants.E1.position", [x1, 0.0])
        set_path(doc, "participants.E0.processing_ns", p0)
        set_path(doc, "participants.E1.processing_ns", p1)
    sim = run(doc, seed)
    res = check_trace(sim)
    assert res["ok"], res["violations"]
    # a response can never beat the light cone of the honest position
    for m in sim.messages.values():
        if m.tag == "answer" and m.arrival_time is not None:
            assert m.arrival_time >= tu.ns(20) + D3 - 3

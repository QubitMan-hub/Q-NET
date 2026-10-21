"""QPV core: exact-fs expressions, share combining, typed ports, verifier types, geometry checks."""

import pytest

from qpvsim import Simulation, example, normalize, validate_project
from qpvsim import timeunits as tu
from qpvsim.protocol.automaton import validate_automaton
from qpvsim.protocol.expr import ExprError, evaluate
from qpvsim.protocol.project import verifier_type
from qpvsim.qpv.geometry import affine_rank, dimension, in_hull

C = tu.SPEED_OF_LIGHT_MPS


def _with_actions(doc, node_automaton, transition, actions):
    t = next(t for t in doc["automata"][node_automaton]["transitions"] if t["id"] == transition)
    t["actions"] = actions + t["actions"]
    return doc


# ---------------------------------------------------------------- exact time, combine
def test_fs_builtins_are_exact():
    doc = _with_actions(example("qpv_bb84_honest"), "qpv_verifier_quantum", "arm", [
        {"op": "record", "key": "travel", "value": "claim_travel_fs"},
        {"op": "record", "key": "t", "value": "travel_fs(3)"},
        {"op": "record", "key": "ref", "value": "fs(t_ref_ns)"},
        {"op": "record", "key": "now", "value": "now_fs"},
    ])
    obs = Simulation(doc).run().nodes["V0"].observations
    assert obs["travel"] == obs["t"] == tu.propagation_fs(3, C) == 10_006_923
    assert obs["ref"] == 20_000_000 and obs["now"] == 0


def test_msg_time_fs_is_the_local_arrival():
    doc = _with_actions(example("qpv_bb84_honest"), "qpv_verifier_quantum", "accept",
                        [{"op": "record", "key": "arrived", "value": "msg.time_fs"}])
    sim = Simulation(doc).run()
    answer = next(m for m in sim.messages.values() if m.dst == "V0")
    assert sim.nodes["V0"].observations["arrived"] == answer.arrival_time


def test_timer_at_fs_fires_exactly():
    doc = example("qpv_bb84_honest")
    arm = doc["automata"]["qpv_verifier_quantum"]["transitions"][0]
    arm["actions"][-1] = {"op": "timer", "name": "emit", "at_fs": "fs(t_ref_ns) - claim_travel_fs"}
    sim = Simulation(doc).run()
    q = next(m for m in sim.messages.values() if m.tag == "q")
    assert q.depart_time == tu.ns(20) - tu.propagation_fs(3, C)
    assert sim.snapshot()["decision"]["outcome"] == "accept"


def test_timer_rejects_non_integer_fs():
    doc = example("qpv_bb84_honest")
    doc["automata"]["qpv_verifier_quantum"]["transitions"][0]["actions"][-1] = \
        {"op": "timer", "name": "emit", "at_fs": "1.5"}
    sim = Simulation(doc).run()
    assert sim.nodes["V0"].outcome == "error" and "integer" in sim.nodes["V0"].error


def test_timer_needs_exactly_one_time_field():
    spec = example("qpv_bb84_honest")["automata"]["qpv_verifier_quantum"]
    spec["transitions"][0]["actions"][-1] = {"op": "timer", "name": "emit", "at_fs": "1", "at_ns": "1"}
    assert any("exactly one" in i.message for i in validate_automaton("v", spec))


def test_combine_xor_and_inner_product():
    assert evaluate("combine('xor', [1, 0, 1])", {}) == 0
    assert evaluate("combine('xor', [[1, 1], [0, 1]])", {}) == 1
    assert evaluate("combine('inner_product', [[1, 1, 0], [1, 0, 1]])", {}) == 1
    assert evaluate("combine('inner_product', [[1, 1, 1], [1, 1, 1], [0, 1, 1]])", {}) == 0
    with pytest.raises(ExprError):
        evaluate("combine('inner_product', [[1, 1], [1]])", {})
    with pytest.raises(ExprError):
        evaluate("combine('and', [1])", {})


def test_rand_bits_draws_from_the_participant_stream():
    doc = _with_actions(example("qpv_bb84_honest"), "qpv_verifier_quantum", "arm",
                        [{"op": "record", "key": "bits", "value": "rand_bits(8)"}])
    bits = Simulation(doc).run().nodes["V0"].observations["bits"]
    assert len(bits) == 8 and set(bits) <= {0, 1}
    assert bits == Simulation(doc).run().nodes["V0"].observations["bits"]


# ---------------------------------------------------------------- ports, types, geometry

def _issues(doc, level=None):
    return [i for i in validate_project(normalize(doc)) if level in (None, i.level)]


def test_affine_rank_and_dimension_override():
    assert affine_rank([[0, 0], [1, 0], [-2, 0]]) == 1
    assert affine_rank([[0, 0], [1, 0], [0, 1]]) == 2
    assert affine_rank([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]) == 3
    assert affine_rank([[0, 0], [0.0, 0.0, 0.0]]) == 0  # mixed lengths are zero-padded
    doc = normalize(example("qpv_bb84_honest"))
    assert dimension(doc) == 1
    doc["physics"]["dimension"] = 2
    assert dimension(doc) == 2


def test_in_hull():
    square = [[-1, -1], [1, -1], [1, 1], [-1, 1]]
    assert in_hull([0, 0], square) and in_hull([1, 0], square)  # boundary counts
    assert not in_hull([2, 0], square)
    assert in_hull([0], [[-3], [3]]) and not in_hull([4], [[-3], [3]])
    tetra = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]
    assert in_hull([0.2, 0.2, 0.2], tetra) and not in_hull([0.2, 0.2, -0.1], tetra)


def test_hull_warnings():
    assert not _issues(example("qpv_bb84_honest"))
    doc = example("qpv_bb84_honest")
    doc["claim"]["position"] = [5.0, 0.0]
    doc["participants"][2]["position"] = [5.0, 0.0]
    assert any("convex hull" in i.message for i in _issues(doc, "warning"))
    doc = example("qpv_bb84_honest")
    doc["participants"][2]["position"] = [0.0, 1.0]  # prover off the axis: setup is 2D, 2 verifiers
    assert any("needs at least 3 verifiers" in i.message for i in _issues(doc, "warning"))


def test_port_kind_mismatch_is_an_error():
    doc = example("qpv_bb84_honest")
    doc["automata"]["qpv_verifier_classical"]["port_kinds"] = {"prover": ["classical"]}
    doc["links"][2]["kind"] = "quantum"
    errs = _issues(doc, "error")
    assert any("V1.prover carries only classical" in i.message for i in errs)


def test_unconnected_required_port_warns():
    doc = example("qpv_bb84_honest")
    doc["links"] = [l for l in doc["links"] if l["id"] != "c1"]
    warns = _issues(doc, "warning")
    assert any(i.path == "participants[V1]" and "prover" in i.message and "not connected" in i.message
               for i in warns)


def test_verifier_type_inferred_for_old_projects():
    doc = normalize(example("qpv_bb84_honest"))
    types = {p["id"]: verifier_type(doc, p) for p in doc["participants"] if p["role"] == "verifier"}
    assert types == {"V0": "quantum", "V1": "classical"}
    doc["participants"][0]["verifier_type"] = "photonic"
    assert any(i.path == "participants[V0].verifier_type" for i in validate_project(doc))

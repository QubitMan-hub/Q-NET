"""QPV core: exact-fs expressions, share combining, typed ports, verifier types, geometry checks."""

import pytest

from qpvsim import Simulation, example, normalize, validate_project
from qpvsim import timeunits as tu
from qpvsim.protocol.automaton import validate_automaton
from qpvsim.protocol.expr import ExprError, evaluate

C = tu.SPEED_OF_LIGHT_MPS


def _with_actions(doc, node_automaton, transition, actions):
    t = next(t for t in doc["automata"][node_automaton]["transitions"] if t["id"] == transition)
    t["actions"] = actions + t["actions"]
    return doc


# ---------------------------------------------------------------- task 1
def test_fs_builtins_are_exact():
    doc = _with_actions(example("qpv_bb84_honest"), "qpv_bb84_verifier_quantum", "arm", [
        {"op": "record", "key": "travel", "value": "claim_travel_fs"},
        {"op": "record", "key": "t", "value": "travel_fs(3)"},
        {"op": "record", "key": "ref", "value": "fs(t_ref_ns)"},
        {"op": "record", "key": "now", "value": "now_fs"},
    ])
    obs = Simulation(doc).run().nodes["V0"].observations
    assert obs["travel"] == obs["t"] == tu.propagation_fs(3, C) == 10_006_923
    assert obs["ref"] == 20_000_000 and obs["now"] == 0


def test_msg_time_fs_is_the_local_arrival():
    doc = _with_actions(example("qpv_bb84_honest"), "qpv_bb84_verifier_quantum", "accept",
                        [{"op": "record", "key": "arrived", "value": "msg.time_fs"}])
    sim = Simulation(doc).run()
    answer = next(m for m in sim.messages.values() if m.dst == "V0")
    assert sim.nodes["V0"].observations["arrived"] == answer.arrival_time


def test_timer_at_fs_fires_exactly():
    doc = example("qpv_bb84_honest")
    arm = doc["automata"]["qpv_bb84_verifier_quantum"]["transitions"][0]
    arm["actions"][-1] = {"op": "timer", "name": "emit", "at_fs": "fs(t_ref_ns) - claim_travel_fs"}
    sim = Simulation(doc).run()
    q = next(m for m in sim.messages.values() if m.tag == "q")
    assert q.depart_time == tu.ns(20) - tu.propagation_fs(3, C)
    assert sim.snapshot()["decision"]["outcome"] == "accept"


def test_timer_rejects_non_integer_fs():
    doc = example("qpv_bb84_honest")
    doc["automata"]["qpv_bb84_verifier_quantum"]["transitions"][0]["actions"][-1] = \
        {"op": "timer", "name": "emit", "at_fs": "1.5"}
    sim = Simulation(doc).run()
    assert sim.nodes["V0"].outcome == "error" and "integer" in sim.nodes["V0"].error


def test_timer_needs_exactly_one_time_field():
    spec = example("qpv_bb84_honest")["automata"]["qpv_bb84_verifier_quantum"]
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
    doc = _with_actions(example("qpv_bb84_honest"), "qpv_bb84_verifier_quantum", "arm",
                        [{"op": "record", "key": "bits", "value": "rand_bits(8)"}])
    bits = Simulation(doc).run().nodes["V0"].observations["bits"]
    assert len(bits) == 8 and set(bits) <= {0, 1}
    assert bits == Simulation(doc).run().nodes["V0"].observations["bits"]

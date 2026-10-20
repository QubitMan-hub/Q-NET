"""Expression sandbox, automaton validation and project validation."""

import copy

import pytest

from qpvsim import example, normalize, validate_project
from qpvsim.protocol.automaton import validate_automaton
from qpvsim.protocol.expr import ExprError, Record, evaluate


def test_expression_basics():
    ctx = {"x": 1, "msg": Record(value=1, tag="answer"), "lst": [1, 2, 3]}
    assert evaluate("msg.value == x and x ^ 1 == 0", ctx) is True
    assert evaluate("lst[1:] ", ctx) == [2, 3]
    assert evaluate("'a' if x else 'b'", ctx) == "a"
    assert evaluate("xor(1, 1, 1)", ctx) == 1
    assert evaluate("1 < x + 1 <= 2", ctx) is True
    assert evaluate(3, ctx) == 3  # literals pass through


@pytest.mark.parametrize("bad", [
    "__import__('os')", "(1).__class__", "msg.__class__", "lambda: 1", "[x for x in lst]",
    "open('f')", "x.y", "exec('1')", "x := 1",
])
def test_sandbox_rejects_unsafe_constructs(bad):
    ctx = {"x": 1, "msg": Record(value=1), "lst": [1]}
    with pytest.raises(ExprError):
        evaluate(bad, ctx)


def test_unknown_name_and_field_errors_are_reported():
    with pytest.raises(ExprError, match="unknown name"):
        evaluate("y + 1", {})
    with pytest.raises(ExprError, match="no field"):
        evaluate("msg.nope", {"msg": Record(value=1)})


def _aut():
    return copy.deepcopy(example("qpv_bb84_honest")["automata"]["qpv_bb84_verifier_quantum"])


def test_reference_automata_are_clean():
    issues = validate_automaton("v", _aut())
    assert issues == []


def test_automaton_validation_catches_errors():
    a = _aut()
    a["states"].append({"id": "orphan", "kind": "normal"})
    a["transitions"].append({"id": "bad", "from": "idle", "to": "nowhere", "trigger": {"type": "start"}})
    a["transitions"].append({"id": "g", "from": "waiting", "to": "accepted", "trigger": {"type": "auto"},
                             "guard": "undefined_var > 1", "actions": [{"op": "frobnicate"}]})
    a["transitions"].append({"id": "f", "from": "waiting", "to": "accepted", "trigger": {"type": "auto"},
                             "guard": "nosuchfn(1)"})
    msgs = [i.message for i in validate_automaton("v", a)]
    assert any("unknown state 'nowhere'" in m for m in msgs)
    assert any("unreachable" in m for m in msgs)
    assert any("unknown name 'undefined_var'" in m for m in msgs)
    assert any("unknown action op" in m for m in msgs)
    assert any("unknown function 'nosuchfn'" in m for m in msgs)
    assert any("deadlock" in m for m in msgs)


def test_project_validation_rejects_superluminal_links():
    p = normalize(example("qpv_bb84_honest"))
    p["links"][0]["speed_mps"] = 4e8
    assert any("superluminal" in i.message for i in validate_project(p))
    p = normalize(example("qpv_bb84_honest"))
    p["links"][0]["length_m"] = 1.0  # shorter than the 3 m straight line
    assert any("faster-than-light" in i.message for i in validate_project(p))


def test_entanglement_requires_capability():
    p = normalize(example("qpv_bb84_teleportation_attack"))
    p["participants"][2]["capabilities"] = "no_entanglement"
    errs = [i for i in validate_project(p) if i.level == "error"]
    assert any("forbids entanglement" in i.message for i in errs)


def test_strategy_capability_mismatch_is_warned():
    p = normalize(example("qpv_bb84_teleportation_attack"))
    p["participants"][2]["capabilities"] = "classical_only"
    msgs = [i.message for i in validate_project(p)]
    assert any("Bell measurements not permitted" in m for m in msgs)


def test_duplicate_port_and_unknown_participant():
    p = normalize(example("qpv_bb84_honest"))
    p["links"].append(dict(p["links"][1], id="dup"))
    p["links"].append(dict(p["links"][1], id="ghost", a={"node": "Nobody", "port": "x"}))
    msgs = [i.message for i in validate_project(p)]
    assert any("already has a classical link" in m for m in msgs)
    assert any("unknown participant 'Nobody'" in m for m in msgs)

"""n-verifier QPV_BB84^f: automata, scenario builder, attack switcher, auto-wiring, 1D compatibility."""

import json
import math
from pathlib import Path

import pytest

from qpvsim import Simulation, example, normalize, validate_project
from qpvsim import timeunits as tu
from qpvsim.experiments import run_experiment, wilson
from qpvsim.qpv import scenario

FIXTURES = Path(__file__).parent / "fixtures"
BREIDBART = math.cos(math.pi / 8) ** 2


def old(name):
    return json.loads((FIXTURES / f"old_{name}.json").read_text())


def fingerprint(sim):
    """What must not change between the old and new 1D examples (not ports or guard text)."""
    return {
        "events": [(r.kind, r.node, r.time) for r in sim.trace if r.kind not in ("sim.init",)],
        "messages": [(m.src, m.dst, m.tag, m.value, m.depart_time, m.arrival_time, m.status)
                     for m in sim.messages.values()],
        "observations": {n: v.observations for n, v in sim.nodes.items()},
        "verdicts": {n: (v.verdict or {}).get("outcome") for n, v in sim.nodes.items()},
        "decision": sim.snapshot()["decision"]["outcome"],
    }


def accept_rate(doc, runs, seed=3):
    pt = run_experiment(doc, {"runs": runs, "seed": seed})["points"][0]["summary"]
    return pt["accepted"], pt["n"]


# ---------------------------------------------------------------- 1D compatibility
@pytest.mark.parametrize("name", ["qpv_bb84_honest", "qpv_bb84_displaced_prover"])
@pytest.mark.parametrize("backend", ["density_matrix", "state_vector"])
def test_new_1d_honest_matches_old_trace(name, backend):
    for seed in (1, 7, 42):
        a, b = old(name), example(name)
        for d in (a, b):
            d["simulation"]["backend"] = backend
        assert fingerprint(Simulation(a, seed=seed).run()) == fingerprint(Simulation(b, seed=seed).run())


@pytest.mark.parametrize("name", ["qpv_bb84_collusion_unentangled", "qpv_bb84_teleportation_attack"])
def test_new_1d_attacks_same_verdicts(name):
    for seed in range(1, 41):
        a = Simulation(old(name), seed=seed).run().snapshot()["decision"]["outcome"]
        b = Simulation(example(name), seed=seed).run().snapshot()["decision"]["outcome"]
        assert a == b, seed


def test_old_saved_projects_still_run():
    for f in FIXTURES.glob("old_*.json"):
        sim = Simulation(json.loads(f.read_text())).run()
        assert sim.stopped and sim.snapshot()["decision"]["outcome"] in ("accept", "reject")


def _chain_lateness_fs(radius_m):
    sim = Simulation(scenario.build(dim=1, attack="teleport", tolerance_ns=0, radius_m=radius_m)).run()
    late = {m.depart_time + m.delay_fs - round(sim.nodes[m.dst].observations["deadline_ns"] * 1e6)
            for m in sim.messages.values() if m.tag == "answer"}
    return late, sim.snapshot()["decision"]["outcome"]


def test_zero_tolerance_chain_attack_lands_on_deadline_1d():
    # 10 light-ns: every hop is a whole number of fs, so the attack lands exactly on the deadline
    assert _chain_lateness_fs(tu.SPEED_OF_LIGHT_MPS * 1e-8) == ({0}, "accept")


def test_per_hop_rounding_only_ever_delays_attackers():
    # at 3 m each of the three hops (1.5 + 3 + 1.5 m) is rounded up separately: 1 fs late, never early
    assert _chain_lateness_fs(3.0) == ({1}, "reject")


# ---------------------------------------------------------------- scenario builder
@pytest.mark.parametrize("dim", [1, 2, 3])
def test_built_scenarios_are_valid_and_wired(dim):
    for attack in ("none", "unentangled", "teleport", "guess"):
        doc = scenario.build(dim=dim, attack=attack)
        assert not [i for i in validate_project(doc) if i.level in ("error", "warning")], (attack,
            [i.message for i in validate_project(doc)])


@pytest.mark.parametrize("dim", [1, 2, 3])
def test_honest_prover_always_accepted(dim):
    assert accept_rate(scenario.build(dim=dim), 30) == (30, 30)


@pytest.mark.parametrize("dim", [1, 2, 3])
def test_teleport_chain_always_wins(dim):
    doc = scenario.build(dim=dim, attack="teleport")
    assert accept_rate(doc, 40) == (40, 40)
    if dim > 1:  # the chain has slack beyond 1D: it still wins with zero tolerance
        assert accept_rate(scenario.build(dim=dim, attack="teleport", tolerance_ns=0), 20) == (20, 20)


@pytest.mark.parametrize("dim", [2, 3])
def test_unentangled_attack_matches_breidbart_bound(dim):
    k, n = accept_rate(scenario.build(dim=dim, attack="unentangled"), 1500)
    ci = wilson(k, n)
    assert ci["lo"] <= BREIDBART <= ci["hi"]


def test_guess_attack_succeeds_with_half_to_the_n():
    doc = scenario.build(dim=2, attack="guess")
    k, n = accept_rate(doc, 800)
    ci = wilson(k, n)
    assert ci["lo"] <= 0.5 ** 3 <= ci["hi"]


def test_displaced_prover_rejected():
    assert accept_rate(scenario.build(dim=2, prover="displaced"), 20) == (0, 20)


def test_inner_product_combine():
    doc = scenario.build(dim=2, combine="inner_product")
    assert accept_rate(doc, 30) == (30, 30)
    with pytest.raises(ValueError, match="xor"):
        scenario.build(dim=2, combine="inner_product", attack="teleport")


def test_builder_rejects_bad_requests():
    with pytest.raises(ValueError, match="2 verifiers"):
        scenario.build(dim=1, verifiers=3)
    with pytest.raises(ValueError, match="attack"):
        scenario.build(attack="laser")


def test_geometry_of_built_scenarios():
    doc = scenario.build(dim=3, radius_m=6.0, claim=[1.0, 2.0, 3.0])
    ver = [p for p in doc["participants"] if p["role"] == "verifier"]
    assert len(ver) == 4 and [p["verifier_type"] for p in ver] == ["quantum"] + ["classical"] * 3
    for p in ver:
        assert math.dist(p["position"], [1, 2, 3]) == pytest.approx(6.0)


# ---------------------------------------------------------------- switcher, auto-wiring
def test_switch_attack_keeps_verifiers():
    doc = scenario.build(dim=2, radius_m=5.0)
    doc["participants"][1]["clock"]["offset_ns"] = 0.25
    for attack in ("unentangled", "teleport", "guess", "displaced", "honest"):
        new = scenario.switch_attack(doc, attack)
        assert new["participants"][:3] == doc["participants"][:3]
        assert not [i for i in validate_project(new) if i.level == "error"]
    with pytest.raises(ValueError, match="QPV"):
        scenario.switch_attack(normalize(example("cpv_honest")), "guess")


def test_autowire_rebuilds_links():
    doc = scenario.build(dim=3, attack="teleport")
    want = sorted((l["id"], l["kind"], l["a"]["node"], l["b"]["node"]) for l in doc["links"])
    doc["links"][0]["noise"] = {"depolarizing": 0.1}
    noisy = doc["links"][0]["id"]
    stripped = {**doc, "links": []}
    rewired = scenario.autowire(stripped)
    assert sorted((l["id"], l["kind"], l["a"]["node"], l["b"]["node"]) for l in rewired["links"]) == want
    kept = scenario.autowire(doc)
    assert next(l for l in kept["links"] if l["id"] == noisy)["noise"] == {"depolarizing": 0.1}


def test_ready_scenarios_cover_dimensions_and_attacks():
    ids = {r["id"] for r in scenario.READY}
    assert {f"{d}d_{a}" for d in (1, 2, 3) for a in ("honest", "unentangled", "teleport")} <= ids

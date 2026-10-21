"""Timing analysis, light-cone checker, verdict explanations and sweep presets."""

import pytest

from qpvsim import example, normalize, set_path
from qpvsim import timeunits as tu
from qpvsim.qpv import lightcone, scenario, timing

C = tu.SPEED_OF_LIGHT_MPS
D3 = tu.propagation_fs(3, C)


def honest():
    return normalize(example("qpv_bb84_honest"))


# ---------------------------------------------------------------- timing
def test_schedule_uses_the_engines_send_times_and_deadlines():
    s = timing.schedule(honest())
    assert s["reason"] is None
    assert [(v["id"], v["send_fs"], v["deadline_fs"]) for v in s["verifiers"]] == [
        ("V0", tu.ns(20) - D3, tu.ns("20.5") + D3), ("V1", tu.ns(20) - D3, tu.ns("20.5") + D3)]


def test_schedule_includes_clock_offset():
    doc = honest()
    set_path(doc, "participants.V1.clock", {"offset_ns": 1.0, "drift_ppm": 0})
    v1 = timing.schedule(doc)["verifiers"][1]
    assert v1["send_fs"] == tu.ns(19) - D3 and v1["deadline_fs"] == tu.ns("19.5") + D3


def test_timing_table_rows_and_slack():
    t = timing.table(honest())
    assert not t["issues"]
    row = t["rows"][0]
    assert row["at_claim_fs"] == tu.ns(20) and row["distance_m"] == 3.0
    assert row["honest_answer_fs"] == tu.ns("20.2") + D3      # prover processing 0.2 ns
    assert row["slack_fs"] == tu.ns("0.3") and row["answer_fs"] == tu.ns("20.2") + D3


def test_timing_flags_inconsistent_send():
    doc = honest()
    set_path(doc, "participants.V1.clock", {"offset_ns": 1.0, "drift_ppm": 0})
    t = timing.table(doc)
    assert any("V1" in i and "1.000000 ns before" in i for i in t["issues"])
    assert t["rows"][1]["inconsistent"]


def test_no_deadline_reason():
    doc = honest()
    for t in doc["automata"]["qpv_verifier_quantum"]["transitions"]:
        for a in t["actions"]:
            if a.get("name") == "deadline":
                a["name"] = "late"
        if t["trigger"].get("name") == "deadline":
            t["trigger"]["name"] = "late"
    assert "V0 never armed a timer named 'deadline'" in timing.schedule(doc)["reason"]
    g = lightcone.grid(doc)
    assert g["slack_ns"] == [] and g["reason"]


# ---------------------------------------------------------------- light cone
def test_point_slack_exact_at_claim():
    doc = honest()
    at = lightcone.point(doc, [0.0, 0.0])
    assert at["tau_ns"] == 0 and at["slack_fs"] == tu.ns("0.5") and at["can_answer"]
    assert lightcone.point(doc, [0.0, 0.0], tau_ns=0.5)["slack_fs"] == 0
    off = lightcone.point(doc, [1.0, 0.0])
    assert off["slack_fs"] < 0 and off["binding"] == "V0" and not off["can_answer"]


def test_default_tau_is_the_adversaries_minimum_processing():
    doc = normalize(example("qpv_bb84_collusion_unentangled"))
    for i, t in ((2, 0.2), (3, 0.3)):  # the worst case is the fastest adversary
        doc["participants"][i]["capabilities"] = {"profile": "no_entanglement", "min_processing_ns": t}
    assert lightcone.point(doc, [0.0, 0.0])["tau_ns"] == 0.2


def test_grid_matches_point_queries():
    doc = scenario.build(dim=2)
    g = lightcone.grid(doc, n=21)
    (x0, x1), (y0, y1) = g["bounds"]
    for i, j in ((0, 0), (10, 10), (5, 17), (20, 3)):
        x, y = x0 + (x1 - x0) * j / 20, y0 + (y1 - y0) * i / 20
        assert g["slack_ns"][i][j] == pytest.approx(lightcone.point(doc, [x, y])["slack_fs"] / tu.NS, abs=1e-5)
    assert lightcone.grid(doc, n=21) is g  # cached until the setup changes


def test_lightcone_3d_slice():
    doc = scenario.build(dim=3)
    g = lightcone.grid(doc, n=11)
    assert g["z"] == 0.0 and g["slack_ns"][5][5] == pytest.approx(0.5, abs=1e-5)

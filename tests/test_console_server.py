"""Console commands, session API, HTTP server, persistence and experiments."""

import json
import math
import time

import pytest
from fastapi.testclient import TestClient

from qpvsim import Simulation, example, load_project, normalize, save_project
from qpvsim.console import Console
from qpvsim.experiments import run_experiment, run_once, run_seed, summarize_point, wilson, apply_patch
from qpvsim.server.app import create_app
from qpvsim.session import Session


# ---------------------------------------------------------------- console
def test_console_reports_only_engine_confirmed_results():
    con = Console(Session(example("qpv_bb84_honest")))
    r = con.execute("step 3")
    assert r.ok and "executed 3 event(s)" in r.output
    assert con.session.sim.scheduler.executed_count == 3
    r = con.execute("run")
    assert r.ok and con.session.sim.stopped
    r = con.execute("assert decision.outcome accept")
    assert r.ok
    r = con.execute("assert decision.outcome reject")
    assert not r.ok and "assertion failed" in r.output


@pytest.mark.parametrize("line, fragment", [
    ("frobnicate", "unknown command"),
    ("node", "usage"),
    ("node Nobody", "no participant"),
    ("load example nope", "unknown example"),
    ("set participants.Nobody.x 1", "no list item"),
    ("restore none", "no checkpoint"),
    ('step "unterminated', "parse error"),
])
def test_console_errors_are_reported_not_hidden(line, fragment):
    r = Console(Session()).execute(line)
    assert not r.ok and fragment in r.output


def test_console_edit_then_run_changes_outcome():
    con = Console(Session(example("qpv_bb84_honest")))
    assert con.execute("set participants.P.processing_ns 0.7").ok
    assert con.execute("run").ok
    assert con.execute("assert decision.outcome reject").ok
    assert con.execute("assert node.V0.outcome reject").ok


def test_checkpoint_restore_replays_identically():
    con = Console(Session(example("qpv_bb84_collusion_unentangled")))
    con.execute("run until=12")
    assert con.execute("checkpoint mid").ok
    con.execute("run")
    first = [(r.time, r.kind, r.node) for r in con.session.sim.trace]
    con.execute("restore mid")
    con.execute("run")
    second = [(r.time, r.kind, r.node) for r in con.session.sim.trace]
    assert first == second


def test_console_strategy_swap_and_completion():
    con = Console(Session(example("qpv_bb84_collusion_unentangled")))
    assert "strategy" in con.complete("str")
    assert "E0" in con.complete("node E")
    r = con.execute("strategy E0 qpv_bb84_adv_guess")
    assert r.ok and con.session.project["participants"][2]["automaton"] == "qpv_bb84_adv_guess"


def test_console_export(tmp_path):
    con = Console(Session(example("qpv_bb84_honest")))
    con.execute("run")
    p = tmp_path / "t.json"
    assert con.execute(f"export trace {p}").ok
    data = json.loads(p.read_text())
    assert data["format"] == "qpvsim-trace" and data["invariants"]["ok"]
    assert data["decision"]["outcome"] == "accept"


# ---------------------------------------------------------------- persistence
def test_project_roundtrip_reproduces_run(tmp_path):
    doc = example("qpv_bb84_collusion_unentangled")
    path = tmp_path / "p.qpv.json"
    save_project(normalize(doc), path)
    restored = load_project(path)
    assert restored == normalize(doc)
    a = Simulation(doc, seed=17).run()
    b = Simulation(restored, seed=17).run()
    assert [(r.time, r.kind, r.node) for r in a.trace] == [(r.time, r.kind, r.node) for r in b.trace]


def test_newer_format_version_rejected():
    doc = example("qpv_bb84_honest")
    doc["version"] = 99
    with pytest.raises(ValueError):
        normalize(doc)


# ---------------------------------------------------------------- experiments
def test_wilson_interval():
    w = wilson(85, 100)
    assert w["lo"] < 0.85 < w["hi"]
    assert wilson(0, 10)["lo"] == 0.0 and wilson(10, 10)["hi"] == 1.0


def test_experiment_runs_are_individually_reproducible():
    doc = normalize(example("qpv_bb84_collusion_unentangled"))
    res = run_experiment(doc, {"runs": 30, "seed": 5})
    for raw in res["points"][0]["runs"][:10]:
        again = run_once(doc, raw["seed"])
        assert again["outcome"] == raw["outcome"]
        assert again["verifiers"] == raw["verifiers"]
    assert res["points"][0]["runs"][3]["seed"] == run_seed(5, 0, 3)


def test_derived_metrics_recomputable_from_raw_runs():
    res = run_experiment(example("qpv_bb84_honest"), {"runs": 40, "seed": 2,
                                                       "sweep": [{"path": "links.q0.noise.depolarizing",
                                                                  "values": [0.0, 0.5]}]})
    for p in res["points"]:
        assert summarize_point(p["runs"]) == p["summary"]
    assert res["points"][0]["summary"]["acceptance"]["p"] == 1.0
    assert res["points"][1]["summary"]["acceptance"]["p"] < 1.0


def test_breidbart_attack_matches_monogamy_bound():
    """Fixed seed => deterministic; 3000 runs put cos^2(pi/8) inside the 99.9% band."""
    res = run_experiment(example("qpv_bb84_collusion_unentangled"), {"runs": 3000, "seed": 99})
    s = res["points"][0]["summary"]
    p = math.cos(math.pi / 8) ** 2
    assert abs(s["acceptance"]["p"] - p) < 3.3 * math.sqrt(p * (1 - p) / 3000)
    assert s["outcomes"]["accept"] + s["outcomes"]["reject"] == 3000


def test_parallel_workers_give_identical_results():
    doc = example("qpv_bb84_collusion_unentangled")
    a = run_experiment(doc, {"runs": 60, "seed": 8, "workers": 1})
    b = run_experiment(doc, {"runs": 60, "seed": 8, "workers": 2})
    assert a["points"][0]["runs"] == b["points"][0]["runs"]


# ---------------------------------------------------------------- HTTP API
@pytest.fixture
def client():
    return TestClient(create_app(Session(example("qpv_bb84_honest"))))


def test_api_step_and_state_come_from_engine(client):
    s = client.post("/api/sim/reset", json={}).json()
    assert s["events_executed"] == 0 and s["now_fs"] == 0
    s = client.post("/api/sim/step", json={"n": 4}).json()
    assert s["events_executed"] == 4
    s = client.post("/api/sim/run", json={"since": s["trace_length"]}).json()
    assert s["stopped"] and s["decision"]["outcome"] == "accept"
    full = client.get("/api/sim/state").json()
    assert full["trace_length"] == len(full["trace"])
    assert client.app.state.session.sim.scheduler.executed_count == full["events_executed"]


def test_api_project_edit_validation_and_examples(client):
    doc = client.get("/api/project").json()["project"]
    doc["participants"][0]["automaton"] = "missing"
    r = client.put("/api/project", json=doc).json()
    assert any(i["level"] == "error" for i in r["issues"]) and r["sim_error"]
    assert client.post("/api/sim/step", json={"n": 1}).status_code == 400
    r = client.post("/api/project/example/qpv_bb84_teleportation_attack").json()
    assert r["project"]["meta"]["protocol"]["name"] == "QPV_BB84" and r["sim_error"] is None
    assert client.post("/api/project/example/nope").status_code == 400


def test_api_console_and_meta(client):
    r = client.post("/api/console", json={"line": "run"}).json()
    assert r["result"]["ok"] and r["state"]["stopped"]
    r = client.post("/api/console", json={"line": "bogus"}).json()
    assert not r["result"]["ok"]
    meta = client.get("/api/meta").json()
    assert "density_matrix" in meta["backends"] and "no_entanglement" in meta["profiles"]
    assert "qpv_bb84_adv_teleport_sender" in meta["automata"]


def test_api_experiment_job(client):
    client.post("/api/project/example/qpv_bb84_collusion_unentangled")
    job = client.post("/api/experiments", json={"runs": 30, "seed": 1}).json()["id"]
    for _ in range(200):
        r = client.get(f"/api/experiments/{job}").json()
        if r["status"] != "running":
            break
        time.sleep(0.05)
    assert r["status"] == "done", r
    assert "runs" not in r["result"]["points"][0]
    csv = client.get(f"/api/experiments/{job}/csv").text
    assert csv.startswith("point,") and "V0" in csv
    raw = client.get(f"/api/experiments/{job}/raw").json()
    assert len(raw["points"][0]["runs"]) == 30


def test_api_trace_export_and_chain(client):
    client.post("/api/sim/run", json={})
    data = client.get("/api/sim/export").json()
    ans = next(m for m in data["messages"] if m["tag"] == "answer")
    chain = client.get(f"/api/sim/chain/{ans['id']}").json()
    assert {m["tag"] for m in chain} == {"q", "theta", "answer"}
    assert client.get("/api/sim/invariants").json()["ok"]


def test_patch_application_by_id():
    doc = apply_patch(example("qpv_bb84_honest"), {"participants.P.processing_ns": 0.3,
                                                   "links[q0].loss_prob": 0.1})
    assert doc["participants"][2]["processing_ns"] == 0.3
    assert doc["links"][0]["loss_prob"] == 0.1

"""QPV routes (HTTP and the in-browser handle_json transport) and console commands."""

import json

import pytest
from fastapi.testclient import TestClient

from qpvsim import example
from qpvsim.console import Console
from qpvsim.server.app import create_app
from qpvsim.session import Session
from qpvsim.webapi import WebAPI, handle_json


@pytest.fixture
def client():
    return TestClient(create_app(Session()))


def test_project_payload_has_port_kinds_and_verifier_types(client):
    r = client.get("/api/project").json()
    assert r["ports"]["V1"] == {"prover": ["classical"]}
    assert r["ports"]["P"]["v0"] == ["classical", "quantum"]
    assert r["verifier_types"] == {"V0": "quantum", "V1": "classical"}


def test_analysis_route(client):
    a = client.get("/api/qpv/analysis").json()
    assert a["dimension"] == 1 and a["timing"]["rows"][0]["slack_fs"] == 300000
    assert a["references"]["unentangled"]["value"] == pytest.approx(0.853553, abs=1e-6)
    client.post("/api/project/example/cpv_honest")
    a = client.get("/api/qpv/analysis").json()
    assert a["qpv"] is False and a["timing"]["rows"]  # CPV verifiers also arm a 'deadline' timer


def test_scenario_attack_autowire_routes(client):
    cat = client.get("/api/qpv/scenarios").json()
    assert {"2d_teleport", "3d_honest"} <= {r["id"] for r in cat["ready"]} and "noise" in cat["presets"]
    r = client.post("/api/qpv/scenario", json={"id": "2d_teleport"}).json()
    assert len(r["project"]["participants"]) == 6 and not [i for i in r["issues"] if i["level"] == "error"]
    r = client.post("/api/qpv/scenario", json={"dim": 3, "attack": "unentangled", "radius_m": 5}).json()
    assert [p["id"] for p in r["project"]["participants"]] == ["V0", "V1", "V2", "V3", "E0", "E1", "E2", "E3"]
    r = client.post("/api/qpv/attack", json={"attack": "honest"}).json()
    assert r["project"]["claim"]["prover"] == "P"
    client.put("/api/project", json={**r["project"], "links": []})
    assert len(client.post("/api/qpv/autowire").json()["project"]["links"]) == 5
    assert client.post("/api/qpv/scenario", json={"dim": 4}).status_code == 400
    assert client.post("/api/qpv/attack", json={"attack": "laser"}).status_code == 400


def test_lightcone_route_and_browser_transport():
    api = WebAPI(background_experiments=False)
    r = json.loads(handle_json("POST", "/api/qpv/lightcone", json.dumps({"point": [0, 0]})))
    assert r["status"] == 200 and r["body"]["slack_fs"] == 500000
    st, g, _ = api.handle("POST", "/api/qpv/lightcone", {"n": 8})
    assert st == 200 and len(g["slack_ns"]) == 8


# ---------------------------------------------------------------- console
def con():
    return Console(Session(example("qpv_bb84_honest")))


def test_console_scenario_and_attack():
    c = con()
    r = c.execute("scenario dim=2 verifiers=4 attack=teleport radius=4")
    assert r.ok and len(c.session.project["participants"]) == 8
    r = c.execute("attack guess")
    assert r.ok and "Position claim" in r.output and any(x["kind"] == "event" for x in r.refs)
    assert c.execute("scenario 3d_honest").ok and len(c.session.project["participants"]) == 5
    r = c.execute("attack lasers")
    assert not r.ok and "honest, displaced" in r.output


def test_console_timing_lightcone_autowire():
    c = con()
    r = c.execute("timing")
    assert r.ok and "slack" in r.output and "0.300000" in r.output
    r = c.execute("lightcone 1 0")
    assert r.ok and "misses V0's deadline" in r.output
    assert "meets every deadline" in c.execute("lightcone 0 0").output
    c.session.edit("links", [])
    assert c.execute("autowire").ok and len(c.session.project["links"]) == 3


def test_console_sweep_and_compare():
    c = con()
    r = c.execute("sweep noise 0 0.8 steps=2 runs=40")
    assert r.ok and "preset:noise=0.8" in r.output
    r = c.execute("compare runs=40")
    assert r.ok and "teleportation attack" in r.output and "reference" in r.output
    assert not c.execute("sweep humidity 0 1").ok


def test_decision_results_link_to_the_trace():
    c = con()
    c.execute("run")
    r = c.execute("decision")
    assert "Accepted: the correct answer" in r.output
    assert {x["kind"] for x in r.refs} == {"message", "event", "transition"}
    assert r.as_dict()["refs"] == r.refs

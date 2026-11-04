"""Scenario recipes: a base QPV setup plus an ordered list of generic twists.

A recipe is plain data::

    {"base": {"dim": 1, "who": "honest"},
     "twists": [{"type": "link", "verifier": "V1", "speed": 0.667, "compensate": true},
                {"type": "strategy", "party": "P", "strategy": "honest", "role": "cheater"},
                {"type": "place", "party": "P", "x": -0.7}]}

``base`` is passed to :func:`scenario.build` (``who`` names the prover or attack). Each twist is one
generic change (move a party, slow a link, offset a clock, insert someone mid-path, add a second party at
the claim, multi-photon pulses, a leaked basis, ...). :data:`TWISTS` describes every twist and its fields,
so an interface can offer them without knowing them in advance, and :func:`compose` applies them in order.
Nothing here is specific to one scenario: the demos are recipes kept as data (``demos.json``).
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Dict, List

from ..protocol.project import normalize, verifier_ids
from . import automata as qa
from .presets import apply as apply_preset
from .scenario import ANSWERERS, LABELS, POLICIES, PROVERS, build, link, qpv_verifiers

C = 299_792_458.0


class RecipeError(ValueError):
    pass


# ================================================================ single-party strategies
def _ports(n):
    return [f"v{j}" for j in range(n)]


def _done(*names):
    out = [qa._state(names[0], "initial", names[0].replace("_", " ").capitalize(), 0)]
    out += [qa._state(s, "normal", s.replace("_", " ").capitalize(), 130 * (i + 1)) for i, s in enumerate(names[1:-1])]
    return out + [qa._state(names[-1], "terminal", "Answered", 130 * (len(names) - 1), outcome="done")]


_COMBINE = {"combine": {"default": "xor", "description": "Must match the verifiers' combine function."}}


def measure_now(n: int) -> Dict[str, Any]:
    ports = _ports(n)
    basis = f"combine(combine, shares) if policy == 'leaked' else ({qa.POLICY_BASIS})"
    return qa._automaton(
        f"strategy_measure_now_{n}v", "adversary",
        "Measures the photon the moment it arrives, without waiting for the basis, and sends the outcome to every "
        "verifier. policy: breidbart (best guess, ~85%), random (guess Z or X), Z, X, or leaked (uses the "
        "verifiers' secret shares, which only a leak provides).",
        ports,
        [{"id": "measure", "from": "wait", "to": "done", "label": "measure on arrival & answer all",
          "trigger": {"type": "receive", "tags": ["q"], "port": "v0"},
          "actions": [{"op": "measure", "qubit": "q", "basis": basis, "angle": "pi / 8", "result": "m"}]
          + qa._send_all(ports, "answer", "m")}],
        _done("wait", "done"),
        params={"policy": {"default": "breidbart", "description": "breidbart | random | Z | X | leaked"}, **_COMBINE},
        variables={"m": 0, "shares": [0]})


def guess_first(n: int) -> Dict[str, Any]:
    ports = _ports(n)
    return qa._automaton(
        f"strategy_guess_first_{n}v", "adversary",
        "Gets the basis shares before the photon: answers the quantum verifier at once with a guess (it cannot wait "
        "for the photon and still be on time), then measures the photon in the right basis and answers the others.",
        ports,
        [{"id": "guess", "from": "wait", "to": "half", "label": "guess for the quantum verifier",
          "trigger": {"type": "receive", "tags": ["theta"] * (n - 1)},
          "actions": [{"op": "set", "var": "sh", "expr": "received.theta"}, {"op": "set", "var": "g", "expr": "rand_bit()"},
                      {"op": "send", "port": "v0", "tag": "answer", "value": "g"}]},
         {"id": "measure", "from": "half", "to": "done", "label": "measure & answer the rest",
          "trigger": {"type": "receive", "tags": ["q"], "port": "v0"},
          "actions": [{"op": "measure", "qubit": "q", "basis": "combine(combine, sh)", "result": "m"}]
          + qa._send_all(ports[1:], "answer", "m")}],
        _done("wait", "half", "done"), params=dict(_COMBINE), variables={"sh": [0], "g": 0, "m": 0})


def guess_all(n: int) -> Dict[str, Any]:
    ports = _ports(n)
    return qa._automaton(
        f"strategy_guess_{n}v", "adversary", "Ignores the photon and sends an independent random bit to every verifier.",
        ports,
        [{"id": "guess", "from": "wait", "to": "done", "label": "guess", "trigger": {"type": "receive", "tags": ["q"]},
          "actions": [{"op": "discard", "qubit": "q"}]
          + [x for p in ports for x in ({"op": "set", "var": "g", "expr": "rand_bit()"},
                                         {"op": "send", "port": p, "tag": "answer", "value": "g"})]}],
        _done("wait", "done"), variables={"g": 0})


STRATEGIES: Dict[str, Dict[str, Any]] = {
    "honest": {"label": "Wait for everything, then measure (honest)", "make": qa.honest_prover},
    "measure_now": {"label": "Measure on arrival (Breidbart, guessed or leaked basis)", "make": measure_now},
    "guess_first": {"label": "Guess for the quantum verifier, measure for the rest", "make": guess_first},
    "guess": {"label": "Guess every answer", "make": guess_all},
}


# ================================================================ relays (someone in the middle of a path)
def relay(action: str, kind: str) -> Dict[str, Any]:
    """read_and_resend (quantum), flip_basis (classical) or relay (either): sits between a verifier and the far end."""
    name = f"relay_{action}_{kind}"
    if action == "read_and_resend":
        transitions = [{"id": "read", "from": "wait", "to": "done", "label": "read & resend",
                        "trigger": {"type": "receive", "tags": ["q"], "port": "verifier"},
                        "actions": [{"op": "set", "var": "g", "expr": "rand_bit()"},
                                    {"op": "measure", "qubit": "q", "basis": "g", "result": "m"},
                                    {"op": "prepare_bb84", "qubit": "fresh", "bit": "m", "basis": "g"},
                                    {"op": "send_qubit", "port": "prover", "tag": "q", "qubit": "fresh"}]}]
        desc = "Reads the photon in a guessed basis and sends a fresh photon with the result onward."
    elif kind == "quantum":
        transitions = [{"id": "relay", "from": "wait", "to": "done", "label": "pass the photon on",
                        "trigger": {"type": "receive", "tags": ["q"], "port": "verifier"},
                        "actions": [{"op": "send_qubit", "port": "prover", "tag": "q", "qubit": "q"}]}]
        desc = "Passes the photon on unchanged (after its processing time)."
    else:
        value = "1 - msg.value" if action == "flip_basis" else "msg.value"
        transitions = [{"id": "forward", "from": "wait", "to": "relayed", "label": "flip the share" if action == "flip_basis"
                        else "pass the share on", "trigger": {"type": "receive", "tags": ["theta"], "port": "verifier"},
                        "actions": [{"op": "send", "port": "prover", "tag": "theta", "value": value}]},
                       {"id": "back", "from": "relayed", "to": "done", "label": "pass the answer back",
                        "trigger": {"type": "receive", "tags": ["answer"], "port": "prover"},
                        "actions": [{"op": "send", "port": "verifier", "tag": "answer", "value": "msg.value"}]},
                       {"id": "back_loss", "from": "relayed", "to": "done", "label": "pass a loss report back",
                        "trigger": {"type": "receive", "tags": ["nophoton"], "port": "prover"},
                        "actions": [{"op": "send", "port": "verifier", "tag": "nophoton", "value": "msg.value"}]}]
        desc = ("Flips the basis share on its way to the prover and passes the answer back." if action == "flip_basis"
                else "Passes the basis share on and the answer back (after its processing time).")
    states = _done("wait", "done") if len(transitions) == 1 else _done("wait", "relayed", "done")
    return qa._automaton(name, "adversary", desc, ["verifier", "prover"], transitions, states,
                         variables={"g": 0, "m": 0}, port_kinds={"verifier": [kind], "prover": [kind]})


# ================================================================ helpers
def _party(doc, pid: str) -> Dict[str, Any]:
    p = next((p for p in doc["participants"] if p["id"] == pid), None)
    if p is None:
        raise RecipeError(f"no participant {pid!r} in this setup (have {', '.join(q['id'] for q in doc['participants'])})")
    return p


def _verifier_list(doc, which: str) -> List[Dict[str, Any]]:
    vids = verifier_ids(doc)
    if which in ("all", "", None):
        return [_party(doc, v) for v in vids]
    if which not in vids:
        raise RecipeError(f"{which!r} is not a verifier (verifiers: {', '.join(vids)})")
    return [_party(doc, which)]


def _pos(doc, tw) -> List[float]:
    dims = len(doc["claim"]["position"])
    return [float(tw.get(k) or 0.0) for k in ("x", "y", "z")][:dims]


def _install(doc, aut):
    doc["automata"][aut["name"]] = aut
    return aut["name"]


def _make_cheater(doc, p):
    p["role"] = "adversary"
    if p["capabilities"] in ("honest_prover", "verifier"):
        p["capabilities"] = "no_entanglement"
    if doc["claim"].get("prover") == p["id"]:
        doc["claim"]["prover"] = None


def _use_strategy(doc, p, strategy: str, policy: str = "breidbart"):
    if strategy not in STRATEGIES:
        raise RecipeError(f"unknown strategy {strategy!r}; choose from {', '.join(STRATEGIES)}")
    n = len(verifier_ids(doc))
    p["automaton"] = _install(doc, STRATEGIES[strategy]["make"](n))
    params = {k: v for k, v in p.get("params", {}).items() if k == "combine"}
    if strategy == "measure_now":
        params["policy"] = policy
        if policy == "leaked":
            _leak(doc, {"to": p["id"]})
    p["params"] = params


def _uid(doc, stem):
    ids = {p["id"] for p in doc["participants"]}
    i = 1
    while f"{stem}{i}" in ids:
        i += 1
    return f"{stem}{i}"


# ================================================================ twists
def _place(doc, tw):
    _party(doc, tw["party"])["position"] = _pos(doc, tw)


def _claim(doc, tw):
    doc["claim"]["position"] = _pos(doc, tw)


def _strategy(doc, tw):
    p = _party(doc, tw.get("party") or "P")
    _use_strategy(doc, p, tw.get("strategy", "honest"), tw.get("policy", "breidbart"))
    if tw.get("role", "cheater") == "cheater":
        _make_cheater(doc, p)
    else:
        p["role"], p["capabilities"] = "prover", "honest_prover"
        doc["claim"]["prover"] = p["id"]


def _join(doc, tw):
    """A second party at the claimed spot: the basis shares reach both; the photon reaches the one that takes it."""
    host = _party(doc, tw.get("beside") or doc["claim"].get("prover") or "P")
    new = copy.deepcopy(host)
    new["id"] = tw.get("id") or _uid(doc, "A")
    new["label"] = tw.get("label") or f"Second party {new['id']}"
    new["ui"] = {"x": host["ui"]["x"], "y": host["ui"]["y"] + 200}
    doc["participants"].append(new)
    _use_strategy(doc, new, tw.get("strategy", "honest"), tw.get("policy", "breidbart"))
    if tw.get("role", "cheater") == "cheater":
        _make_cheater(doc, new)
    for lk in list(doc["links"]):
        ends = [e for e in ("a", "b") if lk[e]["node"] == host["id"]]
        if not ends:
            continue
        if lk["kind"] == "classical":
            twin = copy.deepcopy(lk)
            twin["id"] = f"{lk['id']}_{new['id']}"
            twin[ends[0]]["node"] = new["id"]
            doc["links"].append(twin)
        elif tw.get("takes_qubit", True):
            lk[ends[0]]["node"] = new["id"]


def _intercept(doc, tw):
    """Someone in the middle of a verifier's path: the chosen link is cut and routed through them."""
    v = _verifier_list(doc, tw.get("verifier") or "V0")[0]
    action = tw.get("action", "relay")
    kind = "quantum" if action == "read_and_resend" else tw.get("kind") or ("classical" if action == "flip_basis" else None)
    cands = [lk for lk in doc["links"] if v["id"] in (lk["a"]["node"], lk["b"]["node"])
             and (kind is None or lk["kind"] == kind)]
    if not cands:
        raise RecipeError(f"{v['id']} has no {kind or ''} link to intercept".replace("  ", " "))
    lk = cands[0]
    kind = lk["kind"]
    vend, fend = ("a", "b") if lk["a"]["node"] == v["id"] else ("b", "a")
    far = _party(doc, lk[fend]["node"])
    t = min(1.0, max(0.0, float(tw.get("at", 0.5))))
    mid = {**copy.deepcopy(far), "id": _uid(doc, "M"), "role": "adversary", "label": "Someone in the middle",
           "automaton": _install(doc, relay(action, kind)), "capabilities": "unrestricted", "params": {},
           "processing_ns": float(tw.get("delay_ns") or 0.0), "group": None,
           "position": [a + t * (b - a) for a, b in zip(v["position"], far["position"])],
           "ui": {"x": v["ui"]["x"] + t * (far["ui"]["x"] - v["ui"]["x"]), "y": far["ui"]["y"] + 180}}
    doc["participants"].append(mid)
    far_port = lk[fend]["port"]
    lk[fend] = {"node": mid["id"], "port": "verifier"}
    doc["links"].append(link(f"{lk['id']}_{mid['id']}", kind, mid["id"], "prover", far["id"], far_port))


def _link(doc, tw):
    speed = float(tw.get("speed") or 1.0)
    route = float(tw.get("route_m") or 0.0)
    latency = float(tw.get("latency_ns") or 0.0)
    fast = bool(tw.get("cheater_fast_path"))  # only the verifier's timing assumes the slow path
    for v in _verifier_list(doc, tw.get("verifier") or "all"):
        for lk in doc["links"]:
            if fast or v["id"] not in (lk["a"]["node"], lk["b"]["node"]):
                continue
            if speed < 1.0:
                lk["speed_mps"] = speed * C
            if route > 0:
                lk["length_m"] = route
            lk["latency_ns"] = latency
            if lk["kind"] == "quantum" and tw.get("loss_prob") is not None:
                lk["loss_prob"] = float(tw["loss_prob"])
            if lk["kind"] == "quantum" and tw.get("depolarizing"):
                lk["noise"] = {**lk.get("noise", {}), "depolarizing": float(tw["depolarizing"])}
        if tw.get("compensate"):
            d = math.dist(v["position"], doc["claim"]["position"])
            extra = ((route or d) / (speed * C) - d / C) * 1e9 + latency
            v["params"]["extra_delay_ns"] = round(max(0.0, extra), 6)


def _clock(doc, tw):
    for v in _verifier_list(doc, tw.get("verifier") or "all"):
        v["clock"] = {"offset_ns": float(tw.get("offset_ns") or 0.0), "drift_ppm": float(tw.get("drift_ppm") or 0.0)}


def _tolerance(doc, tw):
    for v in _verifier_list(doc, tw.get("verifier") or "all"):
        v["params"]["tolerance_ns"] = float(tw["ns"])


def _meeting(doc, tw):
    for v in _verifier_list(doc, "all"):
        v["params"]["t_ref_ns"] = float(tw["ns"])


def _loss_reports(doc, tw):
    for v in _verifier_list(doc, "all"):
        v["params"]["allow_loss_reports"] = bool(tw.get("on", True))


def _processing(doc, tw):
    _party(doc, tw["party"])["processing_ns"] = float(tw["ns"])


def _pulse(doc, tw):
    k = int(tw.get("photons") or 1)
    for v in qpv_verifiers(doc)[:1]:
        v["automaton"] = "qpv_verifier_quantum" if k <= 1 else _install(doc, qa.multi_photon_verifier(k))
        if v["automaton"] == "qpv_verifier_quantum":
            doc["automata"].setdefault("qpv_verifier_quantum", qa.quantum_verifier())


def _epr_noise(doc, tw):
    doc.update(apply_preset(doc, "entanglement", float(tw.get("noise") or 0.0)))


def _leak(doc, tw):
    shared = next((r for r in doc["resources"] if r["type"] == "shared_random"), None)
    if shared is None:
        raise RecipeError("this setup has no shared verifier secret to leak")
    _party(doc, tw["to"])
    shared["holders"] = sorted(set(shared["holders"]) | {tw["to"]}, key=list(shared["holders"] + [tw["to"]]).index)


def _f(kind, label, default=None, **extra):
    return {"type": kind, "label": label, "default": default, **extra}


POSITION = {"x": _f("number", "x (m)", 0.0), "y": _f("number", "y (m)", 0.0), "z": _f("number", "z (m)", 0.0, dims=3)}
STRATEGY_FIELDS = {"strategy": _f("choice", "Strategy", "honest", choices=list(STRATEGIES)),
                   "policy": _f("choice", "Basis (measure on arrival)", "breidbart", choices=list(POLICIES) + ["leaked"])}

TWISTS: Dict[str, Dict[str, Any]] = {
    "place": {"label": "Move a party", "apply": _place,
              "fields": {"party": _f("party", "Who", "P"), **POSITION}},
    "claim": {"label": "Move the claimed position", "apply": _claim, "fields": dict(POSITION)},
    "strategy": {"label": "Change how a party answers", "apply": _strategy,
                 "fields": {"party": _f("party", "Who", "P"), **STRATEGY_FIELDS,
                            "role": _f("choice", "Counts as", "cheater", choices=["cheater", "prover"])}},
    "join": {"label": "Add a second party at the claimed spot", "apply": _join,
             "fields": {**STRATEGY_FIELDS, "takes_qubit": _f("bool", "Gets the photon", True),
                        "role": _f("choice", "Counts as", "cheater", choices=["cheater", "prover"])}},
    "intercept": {"label": "Put someone in the middle of a path", "apply": _intercept,
                  "fields": {"verifier": _f("verifier", "Path from", "V0"),
                             "action": _f("choice", "What they do", "relay",
                                          choices=["relay", "read_and_resend", "flip_basis"]),
                             "at": _f("number", "Where (0 = verifier, 1 = far end)", 0.5),
                             "delay_ns": _f("number", "Holds it for (ns)", 0.0)}},
    "link": {"label": "Change a verifier's links", "apply": _link,
             "fields": {"verifier": _f("verifier", "Verifier", "all", allow_all=True),
                        "speed": _f("number", "Speed (fraction of c)", 1.0), "route_m": _f("number", "Route length (m, 0 = straight)", 0.0),
                        "latency_ns": _f("number", "Extra latency (ns)", 0.0), "loss_prob": _f("number", "Photon loss probability", 0.0),
                        "depolarizing": _f("number", "Photon noise (depolarising)", 0.0),
                        "compensate": _f("bool", "Verifier adjusts its timing for this", False),
                        "cheater_fast_path": _f("bool", "Only the verifier assumes this; cheaters take a straight path at c", False)}},
    "clock": {"label": "Put a verifier's clock off", "apply": _clock,
              "fields": {"verifier": _f("verifier", "Verifier", "V1", allow_all=True),
                         "offset_ns": _f("number", "Offset (ns)", 1.0), "drift_ppm": _f("number", "Drift (ppm)", 0.0)}},
    "tolerance": {"label": "Change the time allowance", "apply": _tolerance,
                  "fields": {"verifier": _f("verifier", "Verifier", "all", allow_all=True), "ns": _f("number", "Allowance (ns)", 0.5)}},
    "meeting": {"label": "Change the meeting time", "apply": _meeting, "fields": {"ns": _f("number", "Meeting time (ns)", 20.0)}},
    "loss_reports": {"label": "Let the prover report 'no photon'", "apply": _loss_reports,
                     "fields": {"on": _f("bool", "Allowed", True)}},
    "processing": {"label": "Change a party's processing time", "apply": _processing,
                   "fields": {"party": _f("party", "Who", "P"), "ns": _f("number", "Processing (ns)", 0.8)}},
    "pulse": {"label": "Photons per pulse", "apply": _pulse, "fields": {"photons": _f("number", "Photons", 2)}},
    "epr_noise": {"label": "Noise on shared entangled pairs", "apply": _epr_noise,
                  "fields": {"noise": _f("number", "Noise (0 = perfect)", 0.1)}},
    "leak": {"label": "Leak the verifiers' secret to a party", "apply": _leak, "fields": {"to": _f("party", "To", "P")}},
}

BASE_FIELDS = {
    "dim": _f("choice", "Dimension", 1, choices=[1, 2, 3]),
    "verifiers": _f("number", "Verifiers", None), "radius_m": _f("number", "Distance (m)", 3.0),
    "tolerance_ns": _f("number", "Allowance (ns)", 0.5), "who": _f("choice", "Who answers", "honest", choices=list(ANSWERERS)),
    "policy": _f("choice", "Measurement policy", "breidbart", choices=list(POLICIES)),
    "combine": _f("choice", "Basis from shares", "xor", choices=list(qa.COMBINES)),
}
_BUILD_KEYS = {"dim", "verifiers", "radius_m", "claim", "tolerance_ns", "combine", "share_bits", "policy",
               "processing_ns", "displacement_m", "seed"}


def schema() -> Dict[str, Any]:
    """Everything an interface needs to offer recipes: base fields, twists and their fields, strategies."""
    return {"base": BASE_FIELDS,
            "twists": {k: {"label": t["label"], "fields": t["fields"]} for k, t in TWISTS.items()},
            "strategies": {k: s["label"] for k, s in STRATEGIES.items()},
            "answerers": {a: LABELS[a] for a in ANSWERERS}}


def compose(recipe: Dict[str, Any]) -> Dict[str, Any]:
    """Build the project a recipe describes; ``meta.recipe`` keeps the recipe, ``meta.demo`` its texts."""
    if not isinstance(recipe, dict):
        raise RecipeError("a recipe is an object with 'base' and 'twists'")
    base = dict(recipe.get("base") or {})
    who = base.pop("who", "honest")
    args = {k: v for k, v in base.items() if k in _BUILD_KEYS and v is not None}
    unknown = set(base) - _BUILD_KEYS
    if unknown:
        raise RecipeError(f"unknown base field(s): {', '.join(sorted(unknown))}")
    if who in PROVERS:
        args["prover"] = who
    elif who in ANSWERERS:
        args["attack"] = who
    else:
        raise RecipeError(f"unknown 'who' {who!r}; choose from {', '.join(ANSWERERS)}")
    doc = build(**args)
    for i, tw in enumerate(recipe.get("twists") or []):
        spec = TWISTS.get((tw or {}).get("type"))
        if spec is None:
            raise RecipeError(f"twist {i + 1}: unknown type {tw.get('type')!r}; choose from {', '.join(TWISTS)}")
        try:
            spec["apply"](doc, {k: v for k, v in tw.items() if k != "type"})
        except (KeyError, TypeError, ValueError) as exc:
            raise RecipeError(f"twist {i + 1} ({tw['type']}): {exc}") from None
    honest = bool(doc["claim"].get("prover")) and any(
        p["id"] == doc["claim"]["prover"] and p["role"] == "prover" for p in doc["participants"])
    title = recipe.get("title") or "Custom scenario"
    doc["meta"]["name"] = title
    if recipe.get("watch"):
        doc["meta"]["description"] = recipe["watch"]
    doc["meta"]["recipe"] = copy.deepcopy(recipe)
    doc["meta"]["demo"] = {"id": recipe.get("id"), "section": recipe.get("section"), "title": title,
                           "who": recipe.get("who") or ("honest" if honest else "cheat"), "expect": recipe.get("expect", ""),
                           "watch": recipe.get("watch", "")}
    return normalize(doc)


# ================================================================ the demo gallery (data)
DEMO_FILE = Path(__file__).with_name("demos.json")


def demos() -> Dict[str, Any]:
    return json.loads(DEMO_FILE.read_text())


def demo(demo_id: str) -> Dict[str, Any]:
    d = next((d for d in demos()["demos"] if d["id"] == demo_id), None)
    if d is None:
        raise KeyError(f"unknown demo {demo_id!r}")
    return d

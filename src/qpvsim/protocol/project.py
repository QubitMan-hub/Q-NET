"""Versioned project format: loading, defaults, validation and path editing.

A project is a plain JSON document (``format: "qpvsim-project"``,
``version: 1``) that fully determines a simulation: participants, geometry,
links, resources, automata, verification rule, backend and seed.  The UI edits
this document; the engine compiles and executes it.
"""

from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ..quantum import BACKENDS
from ..timeunits import SPEED_OF_LIGHT_MPS
from ..qpv.geometry import geometry_issues
from .automaton import (LINK_KINDS, Issue, automaton_operations, port_kinds, required_ports,
                        validate_automaton)
from .capabilities import make_capabilities
from .expr import validate_syntax

FORMAT = "qpvsim-project"
VERSION = 1
ROLES = {"verifier", "prover", "adversary", "other"}
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,63}$")

DEFAULT_SIM = {
    "seed": 1,
    "backend": "density_matrix",
    "max_time_ns": 1_000_000,
    "max_events": 200_000,
    "stop_when": "verifiers_decided",  # | "quiescent"
    "priorities": {},
}
STOP_MODES = {"verifiers_decided", "quiescent"}


class ProjectError(ValueError):
    def __init__(self, issues: List[Issue]):
        self.issues = issues
        msgs = "; ".join(f"{i.path}: {i.message}" for i in issues if i.level == "error")
        super().__init__(f"invalid project: {msgs}")


def load_project(src: Union[str, Path, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(src, dict):
        doc = copy.deepcopy(src)
    else:
        doc = json.loads(Path(src).read_text())
    return normalize(doc)


def save_project(project: Dict[str, Any], path: Union[str, Path]) -> None:
    Path(path).write_text(json.dumps(project, indent=2, sort_keys=False) + "\n")


def migrate(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Upgrade older format versions (none exist yet; hook for the future)."""
    v = doc.get("version", VERSION)
    if v > VERSION:
        raise ProjectError([Issue("error", "version",
                                  f"project version {v} is newer than supported {VERSION}")])
    return doc


def normalize(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Fill defaults so that every consumer sees the same explicit document."""
    doc = migrate(doc)
    doc.setdefault("format", FORMAT)
    doc.setdefault("version", VERSION)
    meta = doc.setdefault("meta", {})
    meta.setdefault("name", "Untitled project")
    meta.setdefault("description", "")
    meta.setdefault("assumptions", [])
    meta.setdefault("limitations", [])
    meta.setdefault("protocol", {"name": "custom", "version": "0", "references": []})
    phys = doc.setdefault("physics", {})
    phys.setdefault("signal_speed_mps", SPEED_OF_LIGHT_MPS)
    phys.setdefault("allow_superluminal", False)
    sim = doc.setdefault("simulation", {})
    for k, v in DEFAULT_SIM.items():
        sim.setdefault(k, copy.deepcopy(v))
    doc.setdefault("claim", {"prover": None, "position": [0.0, 0.0]})
    doc.setdefault("participants", [])
    doc.setdefault("links", [])
    doc.setdefault("resources", [])
    doc.setdefault("automata", {})
    doc.setdefault("verification", {"rule": "all", "verifiers": None})
    doc.setdefault("experiments", [])
    for p in doc["participants"]:
        p.setdefault("role", "other")
        p.setdefault("label", p.get("id"))
        p.setdefault("params", {})
        p.setdefault("position", [0.0, 0.0])
        p.setdefault("processing_ns", 0)
        p.setdefault("start_ns", 0)
        p.setdefault("clock", {"offset_ns": 0, "drift_ppm": 0})
        p.setdefault("capabilities", "unrestricted")
        p.setdefault("noise", {})
        p.setdefault("group", None)
        p.setdefault("ui", {})
    for link in doc["links"]:
        link.setdefault("directed", False)
        link.setdefault("length_m", None)
        link.setdefault("speed_mps", None)
        link.setdefault("latency_ns", 0)
        link.setdefault("jitter_ns", 0)
        link.setdefault("loss_prob", 0)
        link.setdefault("attenuation_db_per_km", 0)
        link.setdefault("noise", {})
        for end in ("a", "b"):
            if isinstance(link.get(end), list):
                link[end] = {"node": link[end][0], "port": link[end][1]}
    return doc


# ---------------------------------------------------------------- helpers
def participant(project: Dict[str, Any], pid: str) -> Optional[Dict[str, Any]]:
    return next((p for p in project["participants"] if p.get("id") == pid), None)


def link_length_m(project: Dict[str, Any], link: Dict[str, Any]) -> float:
    if link.get("length_m") is not None:
        return float(link["length_m"])
    a = participant(project, link["a"]["node"])
    b = participant(project, link["b"]["node"])
    return math.dist(a["position"], b["position"])


def verifier_type(project: Dict[str, Any], p: Dict[str, Any]) -> Optional[str]:
    """'quantum' if the participant's automaton prepares or sends qubits, else 'classical'."""
    if p.get("verifier_type"):
        return p["verifier_type"]
    spec = (project.get("automata") or {}).get(p.get("automaton")) or {}
    ops = automaton_operations(spec)["ops"] if spec.get("transitions") else set()
    return "quantum" if ops & {"prepare", "prepare_bb84", "send_qubit"} else "classical"


def verifier_ids(project: Dict[str, Any]) -> List[str]:
    v = project["verification"].get("verifiers")
    if v:
        return list(v)
    return [p["id"] for p in project["participants"] if p["role"] == "verifier"]


# ---------------------------------------------------------------- validation
def validate_project(project: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    err = lambda path, msg: issues.append(Issue("error", path, msg))  # noqa: E731
    warn = lambda path, msg: issues.append(Issue("warning", path, msg))  # noqa: E731

    if project.get("format") != FORMAT:
        err("format", f"expected format {FORMAT!r}")
    sim = project["simulation"]
    if sim.get("backend") not in BACKENDS:
        err("simulation.backend", f"unknown backend {sim.get('backend')!r}; use one of {sorted(BACKENDS)}")
    if not isinstance(sim.get("seed"), int) or isinstance(sim.get("seed"), bool) or sim["seed"] < 0:
        err("simulation.seed", "seed must be a non-negative integer")
    if sim.get("stop_when") not in STOP_MODES:
        err("simulation.stop_when", f"must be one of {sorted(STOP_MODES)}")
    speed = project["physics"].get("signal_speed_mps")
    if not isinstance(speed, (int, float)) or speed <= 0:
        err("physics.signal_speed_mps", "signal speed must be positive")
    allow_ftl = bool(project["physics"].get("allow_superluminal"))

    automata = project["automata"]
    for name, spec in automata.items():
        issues.extend(validate_automaton(name, spec))

    ids = set()
    ports_linked: Dict[tuple, Dict[str, Any]] = {}
    for i, p in enumerate(project["participants"]):
        pid = p.get("id")
        pp = f"participants[{pid or i}]"
        if not isinstance(pid, str) or not ID_RE.match(pid):
            err(pp, "participant id must match [A-Za-z][A-Za-z0-9_-]*")
            continue
        if pid in ids:
            err(pp, "duplicate participant id")
        ids.add(pid)
        if p.get("role") not in ROLES:
            err(f"{pp}.role", f"role must be one of {sorted(ROLES)}")
        if p.get("verifier_type") not in (None, "quantum", "classical"):
            err(f"{pp}.verifier_type", "verifier_type must be 'quantum' or 'classical'")
        pos = p.get("position")
        if (not isinstance(pos, list) or not 1 <= len(pos) <= 3
                or not all(isinstance(x, (int, float)) for x in pos)):
            err(f"{pp}.position", "position must be a list of 1-3 numbers (metres)")
        for fld in ("processing_ns", "start_ns"):
            v = p.get(fld)
            if not isinstance(v, (int, float)) or v < 0:
                err(f"{pp}.{fld}", "must be a non-negative number of ns")
        try:
            caps = make_capabilities(p.get("capabilities"))
        except ValueError as exc:
            err(f"{pp}.capabilities", str(exc))
            caps = None
        clock = p.get("clock") or {}
        if not isinstance(clock.get("offset_ns", 0), (int, float)) or not isinstance(clock.get("drift_ppm", 0), (int, float)):
            err(f"{pp}.clock", "offset_ns and drift_ppm must be numbers")
        aname = p.get("automaton")
        spec = automata.get(aname)
        if spec is None:
            err(f"{pp}.automaton", f"automaton {aname!r} is not defined in this project")
            continue
        declared = spec.get("params", {}) or {}
        for k in p.get("params", {}):
            if k not in declared:
                warn(f"{pp}.params.{k}", f"parameter not declared by automaton {aname!r}")
        for k, d in declared.items():
            if (not isinstance(d, dict) or "default" not in d) and k not in p.get("params", {}):
                err(f"{pp}.params.{k}", "required parameter has no value")
        for k, v in p.get("params", {}).items():
            msg = validate_syntax(v) if isinstance(v, str) and (declared.get(k) or {}).get("type") == "expr" else None
            if msg:
                err(f"{pp}.params.{k}", msg)
        if caps is not None:
            used = automaton_operations(spec)
            if not caps.prepare and used["ops"] & {"prepare", "prepare_bb84"}:
                warn(pp, f"strategy prepares qubits but capability profile '{caps.profile}' forbids it")
            for g in sorted(used["gates"]):
                if not caps.allows_gate(g):
                    warn(pp, f"strategy uses gate {g} not permitted by profile '{caps.profile}'")
            for b in sorted(used["bases"] - {"?dynamic"}):
                if not caps.allows_basis(b):
                    warn(pp, f"strategy measures in basis {b} not permitted by profile '{caps.profile}'")
            if "bell_measure" in used["ops"] and not caps.bell_measure:
                warn(pp, f"strategy performs Bell measurements not permitted by profile '{caps.profile}'")
            if "send_qubit" in used["ops"] and not caps.quantum_send:
                warn(pp, f"strategy sends qubits but profile '{caps.profile}' forbids quantum_send")
            if caps.min_processing_ns > p.get("processing_ns", 0):
                warn(f"{pp}.processing_ns",
                     f"below the profile minimum {caps.min_processing_ns} ns; the minimum is enforced")

    link_ids = set()
    for i, link in enumerate(project["links"]):
        lid = link.get("id") or f"#{i}"
        lp = f"links[{lid}]"
        if lid in link_ids:
            err(lp, "duplicate link id")
        link_ids.add(lid)
        if link.get("kind") not in ("classical", "quantum"):
            err(f"{lp}.kind", "kind must be 'classical' or 'quantum'")
        ends = []
        for end in ("a", "b"):
            e = link.get(end) or {}
            if e.get("node") not in ids:
                err(f"{lp}.{end}", f"unknown participant {e.get('node')!r}")
            if not e.get("port"):
                err(f"{lp}.{end}", "endpoint needs a port name")
            ends.append((e.get("node"), e.get("port")))
        if len(ends) == 2 and ends[0][0] == ends[1][0] and ends[0][0] is not None:
            err(lp, "a link cannot connect a participant to itself")
        for end_i, (node, port) in enumerate(ends):
            if link.get("directed"):
                dirs = ("out",) if end_i == 0 else ("in",)
            else:
                dirs = ("out", "in")
            for direction in dirs:
                k2 = (node, port, link.get("kind"), direction)
                if k2 in ports_linked and ports_linked[k2] is not link:
                    err(lp, f"port {node}.{port} already has a {link.get('kind')} link "
                            f"({ports_linked[k2].get('id')}) in direction '{direction}'")
                ports_linked[k2] = link
            pspec = participant(project, node)
            if pspec:
                aspec = automata.get(pspec.get("automaton")) or {}
                aports = aspec.get("ports")
                if aports is not None and port not in aports:
                    warn(f"{lp}", f"port {port!r} is not used by {node}'s automaton")
                kinds = port_kinds(aspec).get(port)
                if kinds and link.get("kind") in LINK_KINDS and link["kind"] not in kinds:
                    err(f"{lp}.kind", f"{node}.{port} carries only {' and '.join(sorted(kinds))} signals; "
                                      f"a {link['kind']} link needs a {link['kind']} port at both ends")
        sp = link.get("speed_mps")
        if sp is not None:
            if not isinstance(sp, (int, float)) or sp <= 0:
                err(f"{lp}.speed_mps", "speed must be positive")
            elif sp > SPEED_OF_LIGHT_MPS and not allow_ftl:
                err(f"{lp}.speed_mps", "superluminal signalling (> c) violates the relativistic "
                                        "assumption of QPV; set physics.allow_superluminal to override")
        if link.get("length_m") is not None:
            if not isinstance(link["length_m"], (int, float)) or link["length_m"] < 0:
                err(f"{lp}.length_m", "length must be a non-negative number")
            elif all(e[0] in ids for e in ends):
                straight = link_length_m(project, {**link, "length_m": None})
                if link["length_m"] + 1e-9 < straight and not allow_ftl:
                    err(f"{lp}.length_m", f"length {link['length_m']} m is shorter than the straight-line "
                                           f"distance {straight:.6g} m (implies faster-than-light signalling)")
        v = link.get("loss_prob", 0)
        if not isinstance(v, (int, float)) or not 0 <= v <= 1:
            err(f"{lp}.loss_prob", "must be a probability in [0, 1]")
        for fld in ("latency_ns", "jitter_ns", "attenuation_db_per_km"):
            v = link.get(fld, 0)
            if not isinstance(v, (int, float)) or v < 0:
                err(f"{lp}.{fld}", "must be a non-negative number")
        for k, v in (link.get("noise") or {}).items():
            if k not in ("depolarizing", "dephasing", "amplitude_damping", "bitflip"):
                err(f"{lp}.noise.{k}", "unknown noise channel")
            elif not isinstance(v, (int, float)) or not 0 <= v <= 1:
                err(f"{lp}.noise.{k}", "must be a probability in [0, 1]")
        if link.get("kind") == "classical" and link.get("noise"):
            warn(f"{lp}.noise", "quantum noise parameters on a classical link are ignored")

    linked = {(e["node"], e["port"], lk.get("kind")) for lk in project["links"]
              for e in (lk.get("a"), lk.get("b")) if isinstance(e, dict)}
    for p in project["participants"]:
        spec = automata.get(p.get("automaton")) or {}
        for port, kind in sorted(required_ports(spec), key=str):
            if not any((p.get("id"), port, k) in linked for k in ([kind] if kind else LINK_KINDS)):
                warn(f"participants[{p.get('id')}]", f"port {port!r} is not connected"
                     + (f" to a {kind} link" if kind else "") + f"; {p.get('id')} uses it")

    # resources
    for i, r in enumerate(project["resources"]):
        rp = f"resources[{r.get('id', i)}]"
        rtype = r.get("type")
        if rtype == "epr":
            holders = r.get("holders") or []
            if len(holders) != 2:
                err(rp, "an EPR resource needs exactly two holders")
            for h in holders:
                node = h.get("node")
                if node not in ids:
                    err(rp, f"unknown holder {node!r}")
                    continue
                try:
                    caps = make_capabilities(participant(project, node).get("capabilities"))
                    if not caps.entanglement:
                        err(rp, f"{node} holds pre-shared entanglement but its capability profile "
                                f"'{caps.profile}' forbids entanglement")
                except ValueError:
                    pass
            if r.get("state", "phi+") not in ("phi+", "phi-", "psi+", "psi-"):
                err(f"{rp}.state", "state must be one of phi+, phi-, psi+, psi-")
            f = r.get("werner_p", 0)
            if not isinstance(f, (int, float)) or not 0 <= f <= 1:
                err(f"{rp}.werner_p", "must be in [0, 1]")
        elif rtype == "shared_random":
            for node in r.get("holders") or []:
                if node not in ids:
                    err(rp, f"unknown holder {node!r}")
            for k, e in (r.get("vars") or {}).items():
                msg = validate_syntax(e)
                if msg:
                    err(f"{rp}.vars.{k}", msg)
        else:
            err(rp, f"unknown resource type {rtype!r} (epr | shared_random)")

    claim = project.get("claim") or {}
    if claim.get("prover") and claim["prover"] not in ids:
        warn("claim.prover", f"claimed prover {claim['prover']!r} is not a participant "
                             "(acceptable when simulating an attack without an honest prover)")
    cpos = claim.get("position")
    if not isinstance(cpos, list) or not cpos:
        err("claim.position", "claimed position must be a list of coordinates")
    if project["physics"].get("dimension") not in (None, 1, 2, 3):
        err("physics.dimension", "dimension must be 1, 2 or 3 (or absent to detect it)")
    dims = {len(p["position"]) for p in project["participants"] if isinstance(p.get("position"), list)}
    if isinstance(cpos, list):
        dims.add(len(cpos))
    if len(dims) > 1:
        err("participants", "all positions (and the claim) must have the same number of coordinates")
    elif not errors(issues):
        for path, msg in geometry_issues(project, [v for v in verifier_ids(project) if v in ids]):
            warn(path, msg)

    ver = project["verification"]
    if ver.get("rule", "all") not in ("all", "any", "k_of_n"):
        err("verification.rule", "rule must be all | any | k_of_n")
    vids = verifier_ids(project)
    if not vids:
        err("verification.verifiers", "at least one verifier is required")
    for v in vids:
        if v not in ids:
            err("verification.verifiers", f"unknown verifier {v!r}")
    if ver.get("rule") == "k_of_n":
        k = ver.get("k")
        if not isinstance(k, int) or not 1 <= k <= len(vids):
            err("verification.k", "k must be an integer between 1 and the number of verifiers")
    return issues


def errors(issues: List[Issue]) -> List[Issue]:
    return [i for i in issues if i.level == "error"]


# ---------------------------------------------------------------- path editing
_SEG = re.compile(r"[^.\[\]]+|\[[^\]]*\]")


def _split_path(path: str) -> List[str]:
    out = []
    for m in _SEG.finditer(path):
        s = m.group(0)
        out.append(s[1:-1] if s.startswith("[") else s)
    return out


def _step(obj: Any, key: str, create: bool = False):
    if isinstance(obj, list):
        if key.lstrip("-").isdigit():
            return obj[int(key)]
        for item in obj:
            if isinstance(item, dict) and item.get("id") == key:
                return item
        raise KeyError(f"no list item with id {key!r}")
    if isinstance(obj, dict):
        if key not in obj:
            if create:
                obj[key] = {}
            else:
                raise KeyError(f"no field {key!r}")
        return obj[key]
    raise KeyError(f"cannot index into {type(obj).__name__} with {key!r}")


def get_path(doc: Dict[str, Any], path: str) -> Any:
    obj: Any = doc
    for seg in _split_path(path):
        obj = _step(obj, seg)
    return obj


def set_path(doc: Dict[str, Any], path: str, value: Any) -> None:
    """Set a value; list items may be addressed by index or by ``id``.

    Example: ``participants.E0.processing_ns`` or ``links[L0].noise.depolarizing``.
    """
    segs = _split_path(path)
    if not segs:
        raise KeyError("empty path")
    obj: Any = doc
    for seg in segs[:-1]:
        obj = _step(obj, seg, create=True)
    last = segs[-1]
    if isinstance(obj, list):
        if last.lstrip("-").isdigit():
            obj[int(last)] = value
            return
        for i, item in enumerate(obj):
            if isinstance(item, dict) and item.get("id") == last:
                obj[i] = value
                return
        raise KeyError(f"no list item with id {last!r}")
    if not isinstance(obj, dict):
        raise KeyError(f"cannot set {last!r} on {type(obj).__name__}")
    obj[last] = value

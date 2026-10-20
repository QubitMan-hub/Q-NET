"""Participant capability profiles.

Capabilities describe *what a participant is physically/permitted able to do*;
the automaton (strategy) describes *what it chooses to do*.  Keeping them
separate allows comparing strategies under identical resource assumptions.
The engine checks every action against the executing participant's
capabilities at run time (:meth:`Capabilities.check`), and the validator
checks automata statically so mismatches are reported before running.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, FrozenSet, Optional

ALL_GATES = frozenset({"I", "X", "Y", "Z", "H", "S", "SDG", "T", "CNOT", "CX", "CZ", "SWAP",
                       "RX", "RY", "RZ"})
ALL_BASES = frozenset({"Z", "X", "Y", "angle"})


class CapabilityViolation(RuntimeError):
    def __init__(self, node: str, capability: str, detail: str):
        super().__init__(f"{node}: capability '{capability}' denied: {detail}")
        self.node = node
        self.capability = capability
        self.detail = detail


@dataclass(frozen=True)
class Capabilities:
    profile: str = "unrestricted"
    description: str = "No restrictions beyond the physics model."
    prepare: bool = True                 # may create/prepare qubits
    gates: Optional[FrozenSet[str]] = None   # None = all gates
    measure_bases: Optional[FrozenSet[str]] = None  # None = all bases
    bell_measure: bool = True
    quantum_send: bool = True
    quantum_receive: bool = True
    classical_send: bool = True
    entanglement: bool = True            # may hold pre-shared entangled resources
    max_qubits: Optional[int] = None     # simultaneous qubits held in memory
    memory_ns: Optional[float] = None    # max storage time before a qubit is fully decohered
    min_processing_ns: float = 0.0       # lower bound on every transition duration

    def allows_gate(self, g: str) -> bool:
        return self.gates is None or g.upper() in self.gates

    def allows_basis(self, b: str) -> bool:
        return self.measure_bases is None or b in self.measure_bases

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k in ("gates", "measure_bases"):
            d[k] = None if d[k] is None else sorted(d[k])
        return d


PROFILES: Dict[str, Dict[str, Any]] = {
    "unrestricted": {},
    "verifier": {
        "description": "Trusted verifier: prepares BB84/basis states, measures, sends.",
    },
    "honest_prover": {
        "description": "Honest prover at the claimed position; no pre-shared entanglement.",
        "entanglement": False,
    },
    "no_entanglement": {
        "description": "Adversary with arbitrary local quantum operations and classical "
                       "communication but no pre-shared entanglement (the setting of the "
                       "Tomamichel et al. 2013 bound for QPV_BB84).",
        "entanglement": False,
    },
    "bounded_entanglement": {
        "description": "Adversary allowed pre-shared entanglement but at most 2 qubits in memory.",
        "entanglement": True,
        "max_qubits": 2,
    },
    "classical_only": {
        "description": "Classical adversary: may relay/read classical data and forward "
                       "received qubits unchanged, but may not prepare, transform or "
                       "measure qubits, nor hold entanglement.",
        "prepare": False,
        "gates": frozenset(),
        "measure_bases": frozenset(),
        "bell_measure": False,
        "entanglement": False,
    },
    "measure_only": {
        "description": "May measure received qubits in Z/X/angle bases; no gates, no entanglement.",
        "prepare": False,
        "gates": frozenset(),
        "bell_measure": False,
        "entanglement": False,
    },
}


def make_capabilities(spec: Any) -> Capabilities:
    """Build from a profile name, or a dict ``{"profile": name, **overrides}``."""
    if spec is None:
        spec = "unrestricted"
    if isinstance(spec, str):
        spec = {"profile": spec}
    if not isinstance(spec, dict):
        raise ValueError("capabilities must be a profile name or an object")
    name = spec.get("profile", "unrestricted")
    if name not in PROFILES:
        raise ValueError(f"unknown capability profile {name!r}; known: {sorted(PROFILES)}")
    values: Dict[str, Any] = {"profile": name}
    values.update(PROFILES[name])
    valid = {f.name for f in fields(Capabilities)}
    for k, v in spec.items():
        if k == "profile":
            continue
        if k not in valid:
            raise ValueError(f"unknown capability field {k!r}")
        values[k] = v
    for k in ("gates", "measure_bases"):
        if values.get(k) is not None:
            values[k] = frozenset(str(x).upper() if k == "gates" else str(x) for x in values[k])
    if values.get("measure_bases") is not None:
        values["measure_bases"] = frozenset("angle" if b.lower() == "angle" else b.upper()
                                            for b in values["measure_bases"])
    return Capabilities(**values)


def profile_catalog() -> Dict[str, Dict[str, Any]]:
    return {name: make_capabilities(name).as_dict() for name in PROFILES}

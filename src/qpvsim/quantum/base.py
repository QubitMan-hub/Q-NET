"""Quantum backend interface.

The engine never manipulates amplitudes directly; it talks to a
:class:`QuantumBackend` through opaque integer qubit handles.  A backend
documents its own semantics (``capabilities``), and must raise
:class:`UnsupportedOperation` rather than silently approximating an operation
it cannot represent.

Notation: single-qubit bases are given as a 2x2 unitary ``B`` whose *columns*
are the basis vectors; outcome ``k`` corresponds to projector
``B[:,k] B[:,k]^dagger``.  Multi-qubit operators act on the listed qubits with
the first listed qubit as the most significant tensor factor.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

SQ2 = 1 / math.sqrt(2)


class QuantumError(RuntimeError):
    pass


class UnsupportedOperation(QuantumError):
    pass


class ResourceLimit(QuantumError):
    pass


# ---------------------------------------------------------------- gates
I2 = np.eye(2, dtype=complex)
X = np.array([[0, 1], [1, 0]], dtype=complex)
Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
Z = np.array([[1, 0], [0, -1]], dtype=complex)
H = np.array([[1, 1], [1, -1]], dtype=complex) * SQ2
S = np.array([[1, 0], [0, 1j]], dtype=complex)
SDG = S.conj().T
T = np.array([[1, 0], [0, np.exp(1j * math.pi / 4)]], dtype=complex)
CNOT = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], dtype=complex)
CZ = np.diag([1, 1, 1, -1]).astype(complex)
SWAP = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=complex)


def RX(theta: float) -> np.ndarray:
    c, s = math.cos(theta / 2), math.sin(theta / 2)
    return np.array([[c, -1j * s], [-1j * s, c]], dtype=complex)


def RY(theta: float) -> np.ndarray:
    c, s = math.cos(theta / 2), math.sin(theta / 2)
    return np.array([[c, -s], [s, c]], dtype=complex)


def RZ(theta: float) -> np.ndarray:
    return np.array([[np.exp(-0.5j * theta), 0], [0, np.exp(0.5j * theta)]], dtype=complex)


FIXED_GATES: Dict[str, np.ndarray] = {
    "I": I2, "X": X, "Y": Y, "Z": Z, "H": H, "S": S, "SDG": SDG, "T": T,
    "CNOT": CNOT, "CX": CNOT, "CZ": CZ, "SWAP": SWAP,
}
PARAM_GATES = {"RX": RX, "RY": RY, "RZ": RZ}
GATE_ARITY = {"CNOT": 2, "CX": 2, "CZ": 2, "SWAP": 2}


def gate_matrix(name: str, angle: float | None = None) -> np.ndarray:
    key = name.upper()
    if key in FIXED_GATES:
        return FIXED_GATES[key]
    if key in PARAM_GATES:
        if angle is None:
            raise QuantumError(f"gate {name} requires an angle")
        return PARAM_GATES[key](float(angle))
    raise UnsupportedOperation(f"unknown gate {name!r}")


def gate_arity(name: str) -> int:
    return GATE_ARITY.get(name.upper(), 1)


# ---------------------------------------------------------------- states & bases
KET = {
    "0": np.array([1, 0], dtype=complex),
    "1": np.array([0, 1], dtype=complex),
    "+": np.array([1, 1], dtype=complex) * SQ2,
    "-": np.array([1, -1], dtype=complex) * SQ2,
    "+i": np.array([1, 1j], dtype=complex) * SQ2,
    "-i": np.array([1, -1j], dtype=complex) * SQ2,
}

BELL = {
    "phi+": np.array([1, 0, 0, 1], dtype=complex) * SQ2,
    "phi-": np.array([1, 0, 0, -1], dtype=complex) * SQ2,
    "psi+": np.array([0, 1, 1, 0], dtype=complex) * SQ2,
    "psi-": np.array([0, 1, -1, 0], dtype=complex) * SQ2,
}


def basis_matrix(basis: str | int, angle: float | None = None) -> np.ndarray:
    """Return the 2x2 unitary whose columns are the measurement basis vectors.

    ``basis`` may be ``"Z"``/``0``, ``"X"``/``1``, ``"Y"``, or ``"angle"`` (real
    basis rotated by ``angle`` radians in the X-Z plane of the Bloch sphere's
    state space: |b0> = cos(a)|0> + sin(a)|1>, |b1> = -sin(a)|0> + cos(a)|1>).
    The Breidbart basis is ``angle = pi/8``.
    """
    if isinstance(basis, bool):
        basis = int(basis)
    if basis in (0, "Z", "z", "0"):
        return I2.copy()
    if basis in (1, "X", "x", "1"):
        return H.copy()
    if basis in ("Y", "y"):
        return np.column_stack([KET["+i"], KET["-i"]])
    if basis in ("angle", "A", "a"):
        if angle is None:
            raise QuantumError("angle basis requires an angle")
        c, s = math.cos(angle), math.sin(angle)
        return np.array([[c, -s], [s, c]], dtype=complex)
    raise UnsupportedOperation(f"unknown measurement basis {basis!r}")


def basis_name(basis, angle=None) -> str:
    if isinstance(basis, bool):
        basis = int(basis)
    if basis in (0, "Z", "z", "0"):
        return "Z"
    if basis in (1, "X", "x", "1"):
        return "X"
    if basis in ("Y", "y"):
        return "Y"
    return f"angle({angle:.6g})"


def bb84_ket(bit: int, basis: int) -> np.ndarray:
    """H^basis |bit>  (basis 0 = computational, 1 = Hadamard)."""
    v = KET[str(int(bit))]
    return H @ v if int(basis) else v.copy()


# ---------------------------------------------------------------- noise (Kraus)
def depolarizing_kraus(p: float) -> List[np.ndarray]:
    """rho -> (1-p) rho + p I/2  (p = probability of full depolarisation)."""
    _check_prob(p)
    a = math.sqrt(1 - 3 * p / 4)
    b = math.sqrt(p / 4)
    return [a * I2, b * X, b * Y, b * Z]


def dephasing_kraus(p: float) -> List[np.ndarray]:
    """rho -> (1-p) rho + p Z rho Z."""
    _check_prob(p)
    return [math.sqrt(1 - p) * I2, math.sqrt(p) * Z]


def bitflip_kraus(p: float) -> List[np.ndarray]:
    _check_prob(p)
    return [math.sqrt(1 - p) * I2, math.sqrt(p) * X]


def amplitude_damping_kraus(gamma: float) -> List[np.ndarray]:
    _check_prob(gamma)
    k0 = np.array([[1, 0], [0, math.sqrt(1 - gamma)]], dtype=complex)
    k1 = np.array([[0, math.sqrt(gamma)], [0, 0]], dtype=complex)
    return [k0, k1]


def _check_prob(p: float) -> None:
    if not (0.0 <= p <= 1.0):
        raise QuantumError(f"probability out of range: {p}")


def memory_kraus(dt_ns: float, t1_ns: float | None, t2_ns: float | None) -> List[List[np.ndarray]]:
    """Channels for idle storage of duration ``dt`` with T1/T2 times.

    Uses the standard composition: amplitude damping with
    gamma = 1 - exp(-dt/T1), then pure dephasing so that coherences decay as
    exp(-dt/T2) overall (requires T2 <= 2 T1).  Returns a list of channels.
    """
    chans: List[List[np.ndarray]] = []
    if dt_ns <= 0:
        return chans
    if t1_ns:
        chans.append(amplitude_damping_kraus(1 - math.exp(-dt_ns / t1_ns)))
    if t2_ns:
        # coherence decay from T1 alone is exp(-dt/(2 T1)); remaining factor:
        rate = 1 / t2_ns - (1 / (2 * t1_ns) if t1_ns else 0.0)
        if rate < -1e-15:
            raise QuantumError("unphysical memory model: T2 > 2*T1")
        lam = math.exp(-dt_ns * max(rate, 0.0))  # remaining coherence factor
        p = (1 - lam) / 2
        if p > 0:
            chans.append(dephasing_kraus(p))
    return chans


# ---------------------------------------------------------------- interface
@dataclass
class BackendInfo:
    name: str
    formalism: str
    exact_mixed_states: bool
    max_qubits_per_group: int
    notes: List[str] = field(default_factory=list)

    def as_dict(self):
        return {
            "name": self.name,
            "formalism": self.formalism,
            "exact_mixed_states": self.exact_mixed_states,
            "max_qubits_per_group": self.max_qubits_per_group,
            "notes": list(self.notes),
        }


class QuantumBackend(ABC):
    """Abstract quantum backend.  All randomness comes from the supplied rng."""

    info: BackendInfo

    def __init__(self, rng: np.random.Generator, max_group: int = 12):
        self.rng = rng
        self.max_group = max_group
        self._next = 1
        self.op_count = 0

    def _new_id(self) -> int:
        q = self._next
        self._next += 1
        return q

    # lifecycle
    @abstractmethod
    def create(self, ket: np.ndarray) -> int:
        """Create one fresh qubit in the given normalised single-qubit pure state."""

    @abstractmethod
    def create_entangled(self, ket: np.ndarray, n: int) -> Tuple[int, ...]:
        """Create ``n`` qubits jointly in the given n-qubit pure state."""

    @abstractmethod
    def discard(self, q: int) -> None:
        """Remove a qubit (partial trace).  Other qubits keep their reduced state."""

    @abstractmethod
    def exists(self, q: int) -> bool: ...

    # dynamics
    @abstractmethod
    def apply_unitary(self, qubits: Sequence[int], U: np.ndarray) -> None: ...

    @abstractmethod
    def apply_channel(self, qubits: Sequence[int], kraus: Iterable[np.ndarray]) -> None: ...

    @abstractmethod
    def measure(self, q: int, basis: np.ndarray) -> int:
        """Projective measurement; returns outcome 0/1 and collapses the state."""

    # inspection (simulation-only: never available to protocol participants)
    @abstractmethod
    def reduced_density(self, qubits: Sequence[int]) -> np.ndarray: ...

    @abstractmethod
    def group_of(self, q: int) -> Tuple[int, ...]: ...

    def describe_qubit(self, q: int) -> dict:
        rho = self.reduced_density([q])
        bloch = [
            float(np.real(np.trace(rho @ X))),
            float(np.real(np.trace(rho @ Y))),
            float(np.real(np.trace(rho @ Z))),
        ]
        purity = float(np.real(np.trace(rho @ rho)))
        return {
            "qubit": q,
            "bloch": bloch,
            "purity": purity,
            "entangled_with": [g for g in self.group_of(q) if g != q],
            "rho": [[[float(np.real(v)), float(np.imag(v))] for v in row] for row in rho],
        }


# ---------------------------------------------------------------- tensor helpers
def apply_matrix_to_axes(tensor: np.ndarray, M: np.ndarray, axes: Sequence[int]) -> np.ndarray:
    """Apply a 2^k x 2^k matrix to ``k`` tensor axes (each of dim 2)."""
    k = len(axes)
    Mt = M.reshape([2] * (2 * k))
    # contract M's input indices (last k) with tensor's axes
    out = np.tensordot(Mt, tensor, axes=(list(range(k, 2 * k)), list(axes)))
    # output axes of M are now first k; move them back to original positions
    return np.moveaxis(out, list(range(k)), list(axes))

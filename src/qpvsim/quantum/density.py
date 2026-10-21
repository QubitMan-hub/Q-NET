"""Exact density-matrix backend.

Qubits are kept in *groups*: each group holds the joint density matrix of the
qubits that have interacted.  Independent groups are implicitly in a tensor
product state, so memory is ``O(sum 4^n_g)`` rather than ``4^N``.  Groups are
merged (Kronecker product) when a multi-qubit operation touches several, and a
measured qubit is split off again (it is in a product state after a
projective measurement).  This mirrors the state-merging strategy described for
NetSquid's ``QState`` and SeQUeNCe's quantum manager.

Semantics: exact Born-rule sampling for measurements, exact CPTP maps for
channels (Kraus sum), exact partial trace for discards.  Limits: a single group
may not exceed ``max_group`` qubits (default 12, i.e. a 4096x4096 matrix).
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

from .base import (BackendInfo, QuantumBackend, QuantumError, ResourceLimit,
                   apply_matrix_to_axes)


class _Group:
    __slots__ = ("qubits", "rho")

    def __init__(self, qubits: List[int], rho: np.ndarray):
        self.qubits = qubits
        self.rho = rho  # matrix (2^n, 2^n)

    @property
    def n(self):
        return len(self.qubits)


def _ptrace_axis(rho: np.ndarray, n: int, idx: int) -> np.ndarray:
    t = rho.reshape([2] * (2 * n))
    t = np.trace(t, axis1=idx, axis2=n + idx)
    d = 2 ** (n - 1)
    return t.reshape(d, d)


class DensityMatrixBackend(QuantumBackend):
    info = BackendInfo(
        name="density_matrix",
        formalism="mixed-state density matrices (exact, NumPy complex128)",
        exact_mixed_states=True,
        max_qubits_per_group=12,
        notes=[
            "Exact Born-rule sampling and Kraus-sum channels.",
            "Cost per operation grows as 4^n for an n-qubit entangled group.",
        ],
    )

    def __init__(self, rng: np.random.Generator, max_group: int = 12):
        super().__init__(rng, max_group)
        self._group_of: Dict[int, _Group] = {}

    # -- lifecycle --------------------------------------------------------
    def create(self, ket: np.ndarray) -> int:
        return self.create_entangled(ket, 1)[0]

    def create_entangled(self, ket: np.ndarray, n: int) -> Tuple[int, ...]:
        ket = np.asarray(ket, dtype=complex).reshape(-1)
        if ket.shape[0] != 2 ** n:
            raise QuantumError("state dimension does not match qubit count")
        norm = np.linalg.norm(ket)
        if abs(norm - 1) > 1e-9:
            raise QuantumError("state is not normalised")
        if n > self.max_group:
            raise ResourceLimit(f"{n} qubits exceed group limit {self.max_group}")
        qs = [self._new_id() for _ in range(n)]
        g = _Group(qs, np.outer(ket, ket.conj()))
        for q in qs:
            self._group_of[q] = g
        return tuple(qs)

    def exists(self, q: int) -> bool:
        return q in self._group_of

    def _g(self, q: int) -> _Group:
        try:
            return self._group_of[q]
        except KeyError:
            raise QuantumError(f"qubit {q} does not exist (lost, measured-and-discarded, or never created)") from None

    def discard(self, q: int) -> None:
        g = self._g(q)
        idx = g.qubits.index(q)
        if g.n == 1:
            del self._group_of[q]
            return
        g.rho = _ptrace_axis(g.rho, g.n, idx)
        g.qubits.pop(idx)
        del self._group_of[q]

    def _merge(self, qubits: Sequence[int]) -> _Group:
        groups: List[_Group] = []
        for q in qubits:
            g = self._g(q)
            if all(g is not h for h in groups):
                groups.append(g)
        if len(groups) == 1:
            return groups[0]
        total = sum(g.n for g in groups)
        if total > self.max_group:
            raise ResourceLimit(
                f"entangled group of {total} qubits exceeds backend limit {self.max_group}")
        rho = groups[0].rho
        qs = list(groups[0].qubits)
        for g in groups[1:]:
            rho = np.kron(rho, g.rho)
            qs.extend(g.qubits)
        merged = _Group(qs, rho)
        for q in qs:
            self._group_of[q] = merged
        return merged

    # -- dynamics ---------------------------------------------------------
    def apply_unitary(self, qubits: Sequence[int], U: np.ndarray) -> None:
        if len(set(qubits)) != len(qubits):
            raise QuantumError("repeated qubit in operation")
        U = np.asarray(U, dtype=complex)
        if U.shape != (2 ** len(qubits),) * 2:
            raise QuantumError("operator dimension mismatch")
        g = self._merge(qubits)
        n = g.n
        axes = [g.qubits.index(q) for q in qubits]
        t = g.rho.reshape([2] * (2 * n))
        t = apply_matrix_to_axes(t, U, axes)
        t = apply_matrix_to_axes(t, U.conj(), [n + a for a in axes])
        g.rho = t.reshape(2 ** n, 2 ** n)

    def apply_channel(self, qubits: Sequence[int], kraus: Iterable[np.ndarray]) -> None:
        kraus = [np.asarray(k, dtype=complex) for k in kraus]
        g = self._merge(qubits)
        n = g.n
        axes = [g.qubits.index(q) for q in qubits]
        t0 = g.rho.reshape([2] * (2 * n))
        acc = np.zeros_like(t0)
        for K in kraus:
            t = apply_matrix_to_axes(t0, K, axes)
            t = apply_matrix_to_axes(t, K.conj(), [n + a for a in axes])
            acc = acc + t
        g.rho = acc.reshape(2 ** n, 2 ** n)

    def measure(self, q: int, basis: np.ndarray) -> int:
        g = self._g(q)
        n = g.n
        idx = g.qubits.index(q)
        rho_q = self.reduced_density([q])
        b0 = basis[:, 0]
        p0 = float(np.real(b0.conj() @ rho_q @ b0))
        p0 = min(1.0, max(0.0, p0))
        outcome = 0 if self.rng.random() < p0 else 1
        p = p0 if outcome == 0 else 1.0 - p0
        if p <= 1e-15:
            raise QuantumError("sampled a zero-probability outcome (numerical error)")
        b = basis[:, outcome]
        P = np.outer(b, b.conj())
        t = g.rho.reshape([2] * (2 * n))
        t = apply_matrix_to_axes(t, P, [idx])
        t = apply_matrix_to_axes(t, P.conj(), [n + idx])
        rho = t.reshape(2 ** n, 2 ** n) / p
        # split off the measured qubit: it is now exactly |b><b| (x) rho_rest
        if n > 1:
            rest = _ptrace_axis(rho, n, idx)
            rest = rest / np.real(np.trace(rest))
            g.rho = rest
            g.qubits.pop(idx)
            self._group_of[q] = _Group([q], P.copy())
        else:
            g.rho = P.copy()
        return outcome

    # -- inspection -------------------------------------------------------
    def group_of(self, q: int) -> Tuple[int, ...]:
        return tuple(self._g(q).qubits)

    def reduced_density(self, qubits: Sequence[int]) -> np.ndarray:
        result = None
        order: List[int] = []
        seen = set()
        for q in qubits:
            g = self._g(q)
            if id(g) in seen:
                continue
            seen.add(id(g))
            keep = [x for x in g.qubits if x in qubits]
            rho = g.rho
            current = list(g.qubits)
            for x in list(current):
                if x not in keep:
                    i = current.index(x)
                    rho = _ptrace_axis(rho, len(current), i)
                    current.pop(i)
            result = rho if result is None else np.kron(result, rho)
            order.extend(current)
        # permute to the requested order
        k = len(order)
        perm = [order.index(q) for q in qubits]
        t = result.reshape([2] * (2 * k))
        t = np.transpose(t, perm + [k + p for p in perm])
        return t.reshape(2 ** k, 2 ** k)

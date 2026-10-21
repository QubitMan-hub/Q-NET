"""Pure-state (state-vector) backend with quantum-trajectory noise.

Each group of interacting qubits is a normalised state vector.  Noise channels
are applied by *trajectory sampling*: Kraus operator ``K_k`` is selected with
probability ``||K_k psi||^2`` and the state renormalised.  Discarding a qubit
that is entangled with others is done by measuring it in the computational
basis and dropping the (unobserved) outcome.

Both procedures are exact **in distribution**: averaged over the backend's
randomness, every observable statistic of the remaining qubits equals the
density-matrix prediction.  A single run is one sample of the unravelled
ensemble, so per-run reduced states shown in the inspector are pure even where
the density-matrix backend would show a mixed state.  This is
checked statistically in tests/test_quantum.py.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

from .base import (BackendInfo, QuantumBackend, QuantumError, ResourceLimit,
                   apply_matrix_to_axes)


class _Group:
    __slots__ = ("qubits", "psi")

    def __init__(self, qubits: List[int], psi: np.ndarray):
        self.qubits = qubits
        self.psi = psi  # vector (2^n,)

    @property
    def n(self):
        return len(self.qubits)


class StateVectorBackend(QuantumBackend):
    info = BackendInfo(
        name="state_vector",
        formalism="pure state vectors; noise by Monte-Carlo trajectories",
        exact_mixed_states=False,
        max_qubits_per_group=24,
        notes=[
            "Noise and discards are sampled (quantum trajectories): statistics are exact in "
            "distribution; per-run states are single trajectories.",
            "Cost per operation grows as 2^n for an n-qubit entangled group.",
        ],
    )

    def __init__(self, rng: np.random.Generator, max_group: int = 24):
        super().__init__(rng, max_group)
        self._group_of: Dict[int, _Group] = {}

    def create(self, ket: np.ndarray) -> int:
        return self.create_entangled(ket, 1)[0]

    def create_entangled(self, ket: np.ndarray, n: int) -> Tuple[int, ...]:
        ket = np.asarray(ket, dtype=complex).reshape(-1).copy()
        if ket.shape[0] != 2 ** n:
            raise QuantumError("state dimension does not match qubit count")
        if abs(np.linalg.norm(ket) - 1) > 1e-9:
            raise QuantumError("state is not normalised")
        if n > self.max_group:
            raise ResourceLimit(f"{n} qubits exceed group limit {self.max_group}")
        qs = [self._new_id() for _ in range(n)]
        g = _Group(qs, ket)
        for q in qs:
            self._group_of[q] = g
        return tuple(qs)

    def exists(self, q: int) -> bool:
        return q in self._group_of

    def _g(self, q: int) -> _Group:
        try:
            return self._group_of[q]
        except KeyError:
            raise QuantumError(f"qubit {q} does not exist") from None

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
            raise ResourceLimit(f"entangled group of {total} qubits exceeds limit {self.max_group}")
        psi = groups[0].psi
        qs = list(groups[0].qubits)
        for g in groups[1:]:
            psi = np.kron(psi, g.psi)
            qs.extend(g.qubits)
        merged = _Group(qs, psi)
        for q in qs:
            self._group_of[q] = merged
        return merged

    def _project_out(self, g: _Group, idx: int, b: np.ndarray, p: float) -> np.ndarray:
        """Return the state of the other qubits after projecting qubit idx onto b."""
        t = g.psi.reshape([2] * g.n)
        t = np.tensordot(b.conj(), t, axes=([0], [idx]))
        return t.reshape(-1) / np.sqrt(p)

    def _measure_idx(self, g: _Group, q: int, basis: np.ndarray) -> int:
        idx = g.qubits.index(q)
        t = g.psi.reshape([2] * g.n)
        amp0 = np.tensordot(basis[:, 0].conj(), t, axes=([0], [idx]))
        p0 = float(np.real(np.vdot(amp0, amp0)))
        p0 = min(1.0, max(0.0, p0))
        outcome = 0 if self.rng.random() < p0 else 1
        p = p0 if outcome == 0 else 1.0 - p0
        if p <= 1e-15:
            raise QuantumError("sampled a zero-probability outcome")
        rest = self._project_out(g, idx, basis[:, outcome], p)
        g.qubits.pop(idx)
        g.psi = rest
        return outcome

    def discard(self, q: int) -> None:
        g = self._g(q)
        if g.n > 1:
            self._measure_idx(g, q, np.eye(2, dtype=complex))
        del self._group_of[q]

    def apply_unitary(self, qubits: Sequence[int], U: np.ndarray) -> None:
        if len(set(qubits)) != len(qubits):
            raise QuantumError("repeated qubit in operation")
        U = np.asarray(U, dtype=complex)
        g = self._merge(qubits)
        axes = [g.qubits.index(q) for q in qubits]
        t = apply_matrix_to_axes(g.psi.reshape([2] * g.n), U, axes)
        g.psi = t.reshape(-1)

    def apply_channel(self, qubits: Sequence[int], kraus: Iterable[np.ndarray]) -> None:
        g = self._merge(qubits)
        axes = [g.qubits.index(q) for q in qubits]
        t = g.psi.reshape([2] * g.n)
        cands = []
        probs = []
        for K in kraus:
            v = apply_matrix_to_axes(t, np.asarray(K, dtype=complex), axes).reshape(-1)
            cands.append(v)
            probs.append(float(np.real(np.vdot(v, v))))
        total = sum(probs)
        if abs(total - 1) > 1e-6:
            raise QuantumError(f"channel is not trace preserving (sum p = {total})")
        r = self.rng.random() * total
        acc = 0.0
        choice = len(cands) - 1
        for i, p in enumerate(probs):
            acc += p
            if r < acc:
                choice = i
                break
        g.psi = cands[choice] / np.sqrt(probs[choice])

    def measure(self, q: int, basis: np.ndarray) -> int:
        g = self._g(q)
        outcome = self._measure_idx(g, q, basis)
        b = basis[:, outcome].astype(complex).copy()
        self._group_of[q] = _Group([q], b)
        return outcome

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
            keep = [i for i, x in enumerate(g.qubits) if x in qubits]
            drop = [i for i, x in enumerate(g.qubits) if x not in qubits]
            t = g.psi.reshape([2] * g.n)
            t = np.transpose(t, keep + drop).reshape(2 ** len(keep), -1)
            rho = t @ t.conj().T
            result = rho if result is None else np.kron(result, rho)
            order.extend(g.qubits[i] for i in keep)
        k = len(order)
        perm = [order.index(q) for q in qubits]
        t = result.reshape([2] * (2 * k))
        t = np.transpose(t, perm + [k + p for p in perm])
        return t.reshape(2 ** k, 2 ** k)

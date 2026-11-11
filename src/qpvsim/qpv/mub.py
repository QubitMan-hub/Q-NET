"""Complete sets of mutually unbiased bases (MUBs) for a qudit of dimension d = 2**k, carried by k qubits.

A d-level system has d + 1 bases that are pairwise *mutually unbiased*: a state of one basis measured in another
gives every outcome with probability 1/d.  For d = 2 they are the Z, X and Y bases (the six-state protocol).

Construction (stabilizer method): basis 0 is the computational basis, the joint eigenbasis of the Z-type Paulis.
Basis a = 1..d is the joint eigenbasis of the commuting Paulis Z^(S_a v) X^v (v != 0) for symmetric binary k x k
matrices S_1 .. S_d whose pairwise differences are invertible; these d + 1 classes split the 4^k - 1 non-identity
Paulis into maximal commuting sets, whose eigenbases are mutually unbiased.  Kets use big-endian qubit order
(the first qubit is the most significant bit of the outcome), as the engine's backends do.
"""

from __future__ import annotations

import itertools
from functools import lru_cache
from typing import List, Sequence, Tuple

import numpy as np

DIMENSIONS = (2, 4, 8)
_I = np.eye(2, dtype=complex)
_X = np.array([[0, 1], [1, 0]], dtype=complex)
_Z = np.array([[1, 0], [0, -1]], dtype=complex)


def qubits_for(d: int) -> int:
    if d not in DIMENSIONS:
        raise ValueError(f"qudit dimension must be one of {', '.join(map(str, DIMENSIONS))}")
    return d.bit_length() - 1


def _kron(ms: Sequence[np.ndarray]) -> np.ndarray:
    out = np.array([[1.0 + 0j]])
    for m in ms:
        out = np.kron(out, m)
    return out


def pauli(u: Sequence[int], v: Sequence[int]) -> np.ndarray:
    """Z^u X^v on k qubits (u, v bit vectors), made Hermitian by the phase i^(u.v)."""
    m = _kron([np.linalg.matrix_power(_Z, ui) @ np.linalg.matrix_power(_X, vi) for ui, vi in zip(u, v)])
    return (1j ** (int(np.dot(u, v)) % 4)) * m


def _gf2_rank(m: np.ndarray) -> int:
    m = m.copy() % 2
    rank, rows, cols = 0, m.shape[0], m.shape[1]
    for c in range(cols):
        piv = next((r for r in range(rank, rows) if m[r, c]), None)
        if piv is None:
            continue
        m[[rank, piv]] = m[[piv, rank]]
        for r in range(rows):
            if r != rank and m[r, c]:
                m[r] ^= m[rank]
        rank += 1
    return rank


@lru_cache(maxsize=None)
def _symmetric_family(k: int) -> Tuple[np.ndarray, ...]:
    """d = 2^k symmetric binary matrices with pairwise invertible differences (found by search; k <= 3)."""
    idx = [(i, j) for i in range(k) for j in range(i, k)]
    mats = []
    for bits in itertools.product((0, 1), repeat=len(idx)):
        m = np.zeros((k, k), dtype=np.uint8)
        for (i, j), b in zip(idx, bits):
            m[i, j] = m[j, i] = b
        mats.append(m)
    d = 2 ** k

    def ok(a, b):
        return _gf2_rank(a ^ b) == k

    def search(chosen, start):
        if len(chosen) == d:
            return chosen
        for i in range(start, len(mats)):
            if all(ok(mats[i], c) for c in chosen):
                found = search(chosen + [mats[i]], i + 1)
                if found:
                    return found
        return None
    family = search([mats[0]], 1)
    if not family:
        raise RuntimeError(f"no MUB family found for k = {k}")
    return tuple(family)


@lru_cache(maxsize=None)
def bases(d: int) -> Tuple[np.ndarray, ...]:
    """The d + 1 bases as unitary matrices whose columns are the basis vectors."""
    k = qubits_for(d)
    vs = [np.array(v, dtype=np.uint8) for v in itertools.product((0, 1), repeat=k) if any(v)]
    out = [np.eye(d, dtype=complex)]
    rng = np.random.default_rng(12345)
    for S in _symmetric_family(k):
        ops = [pauli((S @ v) % 2, v) for v in vs]
        H = sum(rng.normal() * P for P in ops)
        _, vecs = np.linalg.eigh((H + H.conj().T) / 2)
        for c in range(d):  # fix each vector's global phase: first clearly non-zero entry real and positive
            j = int(np.argmax(np.abs(vecs[:, c]) > 1e-9))
            vecs[:, c] *= np.exp(-1j * np.angle(vecs[j, c]))
        out.append(vecs)
    return tuple(out)


def vector(d: int, basis: int, value: int) -> np.ndarray:
    B = bases(d)
    if not 0 <= basis < len(B) or not 0 <= value < d:
        raise ValueError(f"basis must be in 0..{d} and value in 0..{d - 1}")
    return B[basis][:, value]


@lru_cache(maxsize=None)
def _frame_permutation(d: int, basis: int, frame: Tuple[int, ...]) -> Tuple[int, ...]:
    """perm[x] = the outcome a measurement of basis `basis` gives on P |v_x>, P the teleportation frame
    prod_i X^(m1_i) Z^(m0_i) with frame = (m0_0, m1_0, m0_1, m1_1, ...)."""
    k = qubits_for(d)
    P = _kron([np.linalg.matrix_power(_X, frame[2 * i + 1]) @ np.linalg.matrix_power(_Z, frame[2 * i]) for i in range(k)])
    B = bases(d)[basis]
    perm = []
    for x in range(d):
        amps = np.abs(B.conj().T @ (P @ B[:, x])) ** 2
        perm.append(int(np.argmax(amps)))
    return tuple(perm)


def unscramble(d: int, basis: int, outcome: int, frame: Sequence[int]) -> int:
    """The value x that was sent, given the outcome of measuring a teleported qudit in the right basis and the
    teleportation's Bell-measurement results (a Pauli frame only permutes each MUB's vectors)."""
    perm = _frame_permutation(int(d), int(basis), tuple(int(b) for b in frame))
    return perm.index(int(outcome))


def check(d: int) -> float:
    """Largest deviation from mutual unbiasedness (0 for an exact set)."""
    B = bases(d)
    worst = 0.0
    for a in range(len(B)):
        worst = max(worst, float(np.abs(B[a].conj().T @ B[a] - np.eye(d)).max()))
        for b in range(a + 1, len(B)):
            worst = max(worst, float(np.abs(np.abs(B[a].conj().T @ B[b]) ** 2 - 1 / d).max()))
    return worst


def basis_list(d: int) -> List[int]:
    return list(range(d + 1))

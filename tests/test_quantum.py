"""Quantum backend semantics, cross-checked between the two backends."""

import math

import numpy as np
import pytest

from qpvsim.quantum import DensityMatrixBackend, StateVectorBackend, ResourceLimit, QuantumError
from qpvsim.quantum import base as qb

BACKENDS = [DensityMatrixBackend, StateVectorBackend]


def rng(seed=0):
    return np.random.default_rng(seed)


@pytest.mark.parametrize("cls", BACKENDS)
@pytest.mark.parametrize("bit", [0, 1])
@pytest.mark.parametrize("basis", [0, 1])
def test_bb84_same_basis_is_deterministic(cls, bit, basis):
    b = cls(rng())
    for _ in range(20):
        q = b.create(qb.bb84_ket(bit, basis))
        assert b.measure(q, qb.basis_matrix(basis)) == bit
        b.discard(q)


@pytest.mark.parametrize("cls", BACKENDS)
def test_conjugate_basis_is_uniform(cls):
    b = cls(rng(1))
    n = 4000
    ones = sum(b.measure(b.create(qb.bb84_ket(0, 1)), qb.basis_matrix(0)) for _ in range(n))
    assert abs(ones / n - 0.5) < 4 * math.sqrt(0.25 / n)


@pytest.mark.parametrize("cls", BACKENDS)
def test_breidbart_success_probability(cls):
    """Measuring BB84 states in the basis rotated by pi/8 guesses x w.p. cos^2(pi/8)."""
    b = cls(rng(2))
    r = rng(3)
    n = 6000
    wins = 0
    for _ in range(n):
        x, th = int(r.integers(2)), int(r.integers(2))
        q = b.create(qb.bb84_ket(x, th))
        wins += b.measure(q, qb.basis_matrix("angle", math.pi / 8)) == x
    p = math.cos(math.pi / 8) ** 2
    assert abs(wins / n - p) < 4 * math.sqrt(p * (1 - p) / n)


@pytest.mark.parametrize("cls", BACKENDS)
def test_bell_pair_correlations_in_both_bases(cls):
    b = cls(rng(4))
    for basis in (0, 1):
        for _ in range(50):
            q0, q1 = b.create_entangled(qb.BELL["phi+"], 2)
            assert b.group_of(q0) == (q0, q1)
            m0 = b.measure(q0, qb.basis_matrix(basis))
            assert b.group_of(q1) == (q1,)  # measured qubit is split off
            assert b.measure(q1, qb.basis_matrix(basis)) == m0


@pytest.mark.parametrize("cls", BACKENDS)
def test_teleportation_identity(cls):
    """Bell-measure (q, e0); e1 = X^m1 Z^m0 |psi> for any input."""
    b = cls(rng(5))
    psi = np.array([math.cos(0.3), np.exp(0.7j) * math.sin(0.3)])
    for _ in range(30):
        q = b.create(psi)
        e0, e1 = b.create_entangled(qb.BELL["phi+"], 2)
        b.apply_unitary([q, e0], qb.CNOT)
        b.apply_unitary([q], qb.H)
        m0 = b.measure(q, qb.I2)
        m1 = b.measure(e0, qb.I2)
        corr = np.linalg.matrix_power(qb.Z, m0) @ np.linalg.matrix_power(qb.X, m1)
        out = corr.conj().T @ psi  # state at e1 before correction = X^m1 Z^m0 psi
        rho = b.reduced_density([e1])
        fid = np.real(out.conj() @ rho @ out)
        assert fid == pytest.approx(1.0, abs=1e-9)


def test_density_channel_and_partial_trace():
    b = DensityMatrixBackend(rng())
    q0, q1 = b.create_entangled(qb.BELL["phi+"], 2)
    rho = b.reduced_density([q0])
    assert np.allclose(rho, np.eye(2) / 2)
    b.discard(q1)
    assert np.allclose(b.reduced_density([q0]), np.eye(2) / 2)
    q = b.create(qb.KET["+"])
    b.apply_channel([q], qb.depolarizing_kraus(1.0))
    assert np.allclose(b.reduced_density([q]), np.eye(2) / 2)
    q = b.create(qb.KET["+"])
    b.apply_channel([q], qb.dephasing_kraus(0.25))
    assert b.reduced_density([q])[0, 1].real == pytest.approx(0.25)


def test_reduced_density_respects_requested_order():
    b = DensityMatrixBackend(rng())
    q0 = b.create(qb.KET["0"])
    q1 = b.create(qb.KET["1"])
    b.apply_unitary([q0, q1], qb.CNOT)  # merges; |0>|1>
    r01 = b.reduced_density([q0, q1])
    r10 = b.reduced_density([q1, q0])
    assert r01[1, 1] == pytest.approx(1)  # |01>
    assert r10[2, 2] == pytest.approx(1)  # |10>


@pytest.mark.parametrize("p", [0.1, 0.3])
def test_backends_agree_statistically_under_noise(p):
    """Trajectory noise in the state-vector backend matches the exact density matrix."""
    exact = DensityMatrixBackend(rng())
    q = exact.create(qb.KET["+"])
    exact.apply_channel([q], qb.depolarizing_kraus(p))
    exact.apply_channel([q], qb.amplitude_damping_kraus(0.2))
    p_exact = float(np.real(exact.reduced_density([q])[0, 0]))  # P(Z=0)
    sv = StateVectorBackend(rng(9))
    n = 6000
    zeros = 0
    for _ in range(n):
        q = sv.create(qb.KET["+"])
        sv.apply_channel([q], qb.depolarizing_kraus(p))
        sv.apply_channel([q], qb.amplitude_damping_kraus(0.2))
        zeros += sv.measure(q, qb.I2) == 0
        sv.discard(q)
    assert abs(zeros / n - p_exact) < 4 * math.sqrt(p_exact * (1 - p_exact) / n)


def test_memory_noise_composition():
    chans = qb.memory_kraus(100.0, t1_ns=1000.0, t2_ns=500.0)
    b = DensityMatrixBackend(rng())
    q = b.create(qb.KET["+"])
    for k in chans:
        b.apply_channel([q], k)
    coh = abs(b.reduced_density([q])[0, 1]) * 2
    assert coh == pytest.approx(math.exp(-100 / 500), rel=1e-9)
    with pytest.raises(QuantumError):
        qb.memory_kraus(1.0, t1_ns=10.0, t2_ns=30.0)  # T2 > 2 T1 is unphysical


def test_group_limit_enforced():
    b = DensityMatrixBackend(rng(), max_group=3)
    qs = [b.create(qb.KET["0"]) for _ in range(4)]
    b.apply_unitary([qs[0], qs[1]], qb.CNOT)
    b.apply_unitary([qs[1], qs[2]], qb.CNOT)
    with pytest.raises(ResourceLimit):
        b.apply_unitary([qs[2], qs[3]], qb.CNOT)


def test_invalid_operations_raise():
    b = DensityMatrixBackend(rng())
    with pytest.raises(QuantumError):
        b.create(np.array([1, 1]))  # not normalised
    q = b.create(qb.KET["0"])
    with pytest.raises(QuantumError):
        b.apply_unitary([q, q], qb.CNOT)
    b.discard(q)
    with pytest.raises(QuantumError):
        b.measure(q, qb.I2)

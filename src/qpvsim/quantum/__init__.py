"""Pluggable quantum backends behind a stable interface."""

from __future__ import annotations

import numpy as np

from .base import (BackendInfo, QuantumBackend, QuantumError, ResourceLimit,
                   UnsupportedOperation)
from .density import DensityMatrixBackend
from .statevector import StateVectorBackend

BACKENDS = {
    "density_matrix": DensityMatrixBackend,
    "state_vector": StateVectorBackend,
}


def make_backend(name: str, rng: np.random.Generator, **kw) -> QuantumBackend:
    try:
        cls = BACKENDS[name]
    except KeyError:
        raise UnsupportedOperation(
            f"unknown quantum backend {name!r}; available: {sorted(BACKENDS)}") from None
    return cls(rng, **kw)


def backend_catalog():
    return {name: cls.info.as_dict() for name, cls in BACKENDS.items()}


__all__ = [
    "BackendInfo", "QuantumBackend", "QuantumError", "ResourceLimit", "UnsupportedOperation",
    "DensityMatrixBackend", "StateVectorBackend", "BACKENDS", "make_backend", "backend_catalog",
]

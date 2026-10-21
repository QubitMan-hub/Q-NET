"""Time model.

All simulation time is held as a Python ``int`` counting **femtoseconds** (fs).
Python integers are arbitrary precision, so there is no overflow and no
floating-point drift: two timestamps are equal iff their integers are equal,
and deadline comparisons (``arrival <= deadline``) are exact.

Conversions from user-facing quantities (nanoseconds, metres, metres/second)
go through :class:`fractions.Fraction` built from the *decimal string* of the
value, so ``0.1`` ns is exactly 100000 fs rather than the nearest binary
double.  User-supplied times are rounded half-to-even to the nearest
femtosecond, once, at the conversion boundary; propagation delays are rounded
up (see :func:`propagation_fs`).
"""

from __future__ import annotations

from fractions import Fraction
from typing import Union

Number = Union[int, float, str, Fraction]

FS = 1
PS = 1_000
NS = 1_000_000
US = 1_000_000_000
MS = 1_000_000_000_000
S = 1_000_000_000_000_000

UNITS = {"fs": FS, "ps": PS, "ns": NS, "us": US, "ms": MS, "s": S}

SPEED_OF_LIGHT_MPS = 299_792_458  # exact, SI definition


def exact(value: Number) -> Fraction:
    """Return an exact rational for ``value`` (floats via their shortest repr)."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool):
        raise TypeError("boolean is not a time quantity")
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"non-finite quantity: {value!r}")
        return Fraction(repr(value))
    if isinstance(value, str):
        return Fraction(value.strip())
    raise TypeError(f"cannot interpret {value!r} as a number")


def to_fs(value: Number, unit: str = "ns") -> int:
    """Convert a quantity in ``unit`` to integer femtoseconds."""
    if type(value) is int and unit in UNITS:  # fast path, exact
        return value * UNITS[unit]
    try:
        scale = UNITS[unit]
    except KeyError as exc:
        raise ValueError(f"unknown time unit {unit!r}") from exc
    return round(exact(value) * scale)  # ties to even


def ns(value: Number) -> int:
    """Shorthand: nanoseconds -> fs."""
    return to_fs(value, "ns")


def propagation_fs(distance_m: Number, speed_mps: Number) -> int:
    """Propagation delay ``distance / speed`` computed exactly and rounded **up** to fs.

    Rounding up (ceiling) guarantees that discretisation can never make a
    signal arrive earlier than the exact light-cone bound -- a conservative
    choice for position verification, where an early arrival would be an
    unphysical advantage.  The error is below 1 fs per hop.
    """
    d = exact(distance_m)
    v = exact(speed_mps)
    if v <= 0:
        raise ValueError("signal speed must be positive")
    if d < 0:
        raise ValueError("distance must be non-negative")
    q = d / v * S
    return -((-q.numerator) // q.denominator)


def fmt(t: int | None, unit: str = "ns", digits: int = 6) -> str:
    """Human-readable timestamp, e.g. ``'3.335641 ns'``."""
    if t is None:
        return "—"
    return f"{t / UNITS[unit]:.{digits}f} {unit}"

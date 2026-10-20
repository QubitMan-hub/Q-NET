"""Participant-local clocks.

A local clock reading is an affine function of global simulation time::

    local(t) = t + offset + floor(t * drift_ppb / 1e9)

with ``offset`` in fs and ``drift_ppb`` the rate error in parts per billion
(``drift_ppm * 1000``).  Readings are integers (fs) and the map is
monotonically non-decreasing for drift_ppb > -1e9.  Participants never see
global time: guards, timers and recorded observations use the local reading.
Timers specified in local time are converted back to the earliest global
instant whose local reading is >= the target (:meth:`to_global`).
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from ..timeunits import exact, ns

BILLION = 1_000_000_000


@dataclass(frozen=True)
class LocalClock:
    offset_fs: int = 0
    drift_ppb: int = 0  # integer parts-per-billion

    @classmethod
    def from_config(cls, cfg: dict | None) -> "LocalClock":
        cfg = cfg or {}
        offset = ns(cfg.get("offset_ns", 0))
        drift_ppb = round(exact(cfg.get("drift_ppm", 0)) * 1000)
        if drift_ppb <= -BILLION:
            raise ValueError("clock drift must be > -1e6 ppm (clock must advance)")
        return cls(offset, int(drift_ppb))

    @property
    def ideal(self) -> bool:
        return self.offset_fs == 0 and self.drift_ppb == 0

    def local(self, t_global: int) -> int:
        return t_global + self.offset_fs + (t_global * self.drift_ppb) // BILLION

    def to_global(self, t_local: int) -> int:
        """Earliest global time g with local(g) >= t_local."""
        rate = Fraction(BILLION + self.drift_ppb, BILLION)
        g = int((Fraction(t_local - self.offset_fs) / rate).__ceil__())
        # correct for floor() in local(); local is monotone so walk at most a few fs
        while self.local(g) < t_local:
            g += 1
        while g > 0 and self.local(g - 1) >= t_local:
            g -= 1
        return g

    def describe(self) -> str:
        if self.ideal:
            return "ideal (synchronised to global time)"
        return f"offset {self.offset_fs / 1e6:+.6f} ns, drift {self.drift_ppb / 1000:+.3f} ppm"

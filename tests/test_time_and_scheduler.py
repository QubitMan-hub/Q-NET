"""Time model, local clocks and the discrete-event scheduler."""

from fractions import Fraction

import pytest
from hypothesis import given, settings, strategies as st

from qpvsim import timeunits as tu
from qpvsim.kernel import LocalClock, Scheduler, SchedulingError


# ---------------------------------------------------------------- time units
def test_decimal_values_convert_exactly():
    assert tu.ns(0.1) == 100_000
    assert tu.ns("0.1") == 100_000
    assert tu.ns(1) == 1_000_000
    assert tu.to_fs(1, "s") == 10 ** 15
    # 0.1 + 0.2 != 0.3 in binary floating point, but the fs grid is exact
    assert tu.ns(0.1) + tu.ns(0.2) == tu.ns(0.3)


def test_round_half_to_even_at_fs_boundary():
    assert tu.to_fs("0.5", "fs") == 0
    assert tu.to_fs("1.5", "fs") == 2
    assert tu.to_fs("2.5", "fs") == 2


def test_propagation_never_beats_the_light_cone():
    # 3 m at c: 3 / 299792458 s = 10.006922855944561... ns -> rounded up to 10006923 fs
    assert tu.propagation_fs(3.0, tu.SPEED_OF_LIGHT_MPS) == 10_006_923
    exact = Fraction(3) / tu.SPEED_OF_LIGHT_MPS * 10 ** 15
    assert 0 <= tu.propagation_fs(3, tu.SPEED_OF_LIGHT_MPS) - exact < 1
    assert tu.propagation_fs("0.000299792458", tu.SPEED_OF_LIGHT_MPS) == 1000  # exactly 1 ps, no rounding


@settings(max_examples=300, deadline=None)
@given(d=st.floats(0, 1e6, allow_nan=False), v=st.floats(1.0, 3e8))
def test_propagation_rounding_is_ceiling(d, v):
    exact = Fraction(repr(d)) / Fraction(repr(v)) * 10 ** 15
    got = tu.propagation_fs(d, v)
    assert got >= exact and got - exact < 1
    assert tu.propagation_fs(0, 1) == 0
    with pytest.raises(ValueError):
        tu.propagation_fs(1, 0)
    with pytest.raises(ValueError):
        tu.propagation_fs(-1, 1)


def test_non_finite_rejected():
    with pytest.raises(ValueError):
        tu.ns(float("nan"))
    with pytest.raises(TypeError):
        tu.ns(True)


# ---------------------------------------------------------------- local clocks
def test_ideal_clock_is_identity():
    c = LocalClock()
    assert c.local(12345) == 12345 and c.to_global(12345) == 12345


def test_clock_offset_and_drift():
    c = LocalClock.from_config({"offset_ns": 2, "drift_ppm": 100})
    t = tu.ns(1000)  # 1 us
    # 1000 ns * 100e-6 = 0.1 ns of drift
    assert c.local(t) == t + tu.ns(2) + tu.ns("0.1")


@settings(max_examples=300, deadline=None)
@given(offset=st.integers(-10 ** 9, 10 ** 9), drift=st.integers(-500_000, 500_000),
       target=st.integers(0, 10 ** 13))
def test_to_global_is_earliest_preimage(offset, drift, target):
    c = LocalClock(offset, drift)
    g = c.to_global(target)
    if g > 0:
        assert c.local(g) >= target
        assert c.local(g - 1) < target
    else:
        assert c.local(0) >= target or g == 0


# ---------------------------------------------------------------- scheduler
def test_ordering_time_then_priority_then_fifo():
    s = Scheduler()
    a = s.schedule(10, "timer.fire")       # prio 30
    b = s.schedule(10, "msg.deliver")      # prio 10
    c = s.schedule(5, "timer.fire")
    d = s.schedule(10, "msg.deliver")      # same key as b except seq
    order = [s.pop().id for _ in range(4)]
    assert order == [c.id, b.id, d.id, a.id]
    assert s.now == 10


def test_delivery_precedes_timer_at_same_instant_by_default():
    s = Scheduler()
    t = s.schedule(100, "timer.fire")
    m = s.schedule(100, "msg.deliver")
    assert s.pop() is m and s.pop() is t


def test_priorities_are_configurable():
    s = Scheduler({"timer.fire": 1})
    t = s.schedule(100, "timer.fire")
    m = s.schedule(100, "msg.deliver")
    assert s.pop() is t and s.pop() is m


def test_cannot_schedule_in_the_past_or_with_float_time():
    s = Scheduler()
    s.schedule(10, "x")
    s.pop()
    with pytest.raises(SchedulingError):
        s.schedule(5, "x")
    with pytest.raises(SchedulingError):
        s.schedule(10.5, "x")


def test_cancel_and_reschedule():
    s = Scheduler()
    a = s.schedule(10, "x")
    b = s.schedule(20, "x")
    assert s.cancel(a.id) and not s.cancel(a.id)
    nb = s.reschedule(b.id, 5)
    assert nb.rescheduled_from == b.id
    assert [e.id for e in s.pending()] == [nb.id]
    assert s.pop() is nb and s.pop() is None


def test_cause_links_to_current_event():
    s = Scheduler()
    a = s.schedule(1, "x")
    s.pop()
    b = s.schedule(2, "y")
    assert b.cause == a.id and b.scheduled_at == 1


@settings(max_examples=200, deadline=None)
@given(st.lists(st.tuples(st.integers(0, 50), st.sampled_from(["msg.deliver", "timer.fire", "transition.complete"])),
                min_size=1, max_size=60))
def test_pop_order_is_sorted_by_key(items):
    s = Scheduler()
    evs = [s.schedule(t, k) for t, k in items]
    popped = []
    while (e := s.pop()) is not None:
        popped.append(e.key)
    assert popped == sorted(e.key for e in evs)

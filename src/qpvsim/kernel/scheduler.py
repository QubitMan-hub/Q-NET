"""Deterministic discrete-event scheduler.

Ordering key for pending events is the tuple ``(time, priority, seq)``:

* ``time``      integer femtoseconds (exact);
* ``priority``  smaller runs first among events with the same timestamp; the
                default table is :data:`DEFAULT_PRIORITIES` and projects may
                override it per event kind;
* ``seq``       a monotonically increasing insertion counter, so events with
                equal time and priority run in FIFO scheduling order.

The key is a strict total order, so execution order is fully determined by the
scheduling calls -- there is no dependence on hash ordering, wall-clock time,
or heap implementation details.  Cancellation is lazy (a flag), rescheduling is
cancel + schedule of a new event that records ``rescheduled_from``.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

# Lower number = earlier within one timestamp.  Rationale:
# deliveries are processed before timers that expire at the same instant, so a
# response arriving *exactly* at a deadline counts as on time (inclusive
# deadlines); transition completions precede timers for the same reason.
DEFAULT_PRIORITIES: Dict[str, int] = {
    "sim.init": 0,
    "node.start": 5,
    "msg.deliver": 10,
    "msg.loss": 10,
    "transition.complete": 20,
    "timer.fire": 30,
    "sim.stop": 100,
}


class SchedulingError(RuntimeError):
    pass


@dataclass
class Event:
    id: int
    time: int
    priority: int
    seq: int
    kind: str
    node: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    cause: Optional[int] = None  # id of the event during which this was scheduled
    scheduled_at: int = 0  # simulation time when it was scheduled
    cancelled: bool = False
    executed: bool = False
    rescheduled_from: Optional[int] = None
    label: str = ""
    scheduled_exec_count: int = 0  # number of events executed when this was scheduled
    exec_index: Optional[int] = None  # position in the execution order (0-based)

    @property
    def key(self):
        return (self.time, self.priority, self.seq)

    def summary(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "time_fs": self.time,
            "priority": self.priority,
            "seq": self.seq,
            "kind": self.kind,
            "node": self.node,
            "cause": self.cause,
            "scheduled_at_fs": self.scheduled_at,
            "cancelled": self.cancelled,
            "label": self.label,
        }


class Scheduler:
    """Priority-queue scheduler with a global clock that never runs backwards."""

    def __init__(self, priorities: Optional[Dict[str, int]] = None):
        self.priorities = dict(DEFAULT_PRIORITIES)
        if priorities:
            self.priorities.update({k: int(v) for k, v in priorities.items()})
        self.now: int = 0
        self._heap: List[tuple] = []
        self._events: Dict[int, Event] = {}
        self._next_id = 1
        self._next_seq = 0
        self.current: Optional[Event] = None
        self.executed_count = 0

    # -- scheduling -----------------------------------------------------
    def schedule(
        self,
        time: int,
        kind: str,
        node: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        priority: Optional[int] = None,
        label: str = "",
    ) -> Event:
        if not isinstance(time, int) or isinstance(time, bool):
            raise SchedulingError(f"event time must be integer fs, got {time!r}")
        if time < self.now:
            raise SchedulingError(
                f"cannot schedule {kind} at t={time} fs before current time {self.now} fs"
            )
        prio = self.priorities.get(kind, 50) if priority is None else int(priority)
        ev = Event(
            id=self._next_id,
            time=time,
            priority=prio,
            seq=self._next_seq,
            kind=kind,
            node=node,
            payload=dict(payload or {}),
            cause=self.current.id if self.current else None,
            scheduled_at=self.now,
            label=label,
            scheduled_exec_count=self.executed_count,
        )
        self._next_id += 1
        self._next_seq += 1
        self._events[ev.id] = ev
        heapq.heappush(self._heap, (ev.time, ev.priority, ev.seq, ev.id))
        return ev

    def cancel(self, event_id: int) -> bool:
        ev = self._events.get(event_id)
        if ev is None or ev.executed or ev.cancelled:
            return False
        ev.cancelled = True
        return True

    def reschedule(self, event_id: int, new_time: int) -> Event:
        ev = self._events.get(event_id)
        if ev is None or ev.executed or ev.cancelled:
            raise SchedulingError(f"event {event_id} is not pending")
        self.cancel(event_id)
        new = self.schedule(new_time, ev.kind, node=ev.node, payload=ev.payload,
                            priority=ev.priority, label=ev.label)
        new.rescheduled_from = ev.id
        return new

    # -- execution ------------------------------------------------------
    def _drop_cancelled(self) -> None:
        while self._heap and self._events[self._heap[0][3]].cancelled:
            heapq.heappop(self._heap)

    def peek(self) -> Optional[Event]:
        self._drop_cancelled()
        if not self._heap:
            return None
        return self._events[self._heap[0][3]]

    def pop(self) -> Optional[Event]:
        """Remove the next event, advance the clock to it, and return it."""
        self._drop_cancelled()
        if not self._heap:
            return None
        _, _, _, eid = heapq.heappop(self._heap)
        ev = self._events[eid]
        assert ev.time >= self.now, "clock monotonicity violated"
        self.now = ev.time
        ev.executed = True
        ev.exec_index = self.executed_count
        self.current = ev
        self.executed_count += 1
        return ev

    def finish_current(self) -> None:
        self.current = None

    def pending(self) -> List[Event]:
        """Pending (non-cancelled) events in execution order."""
        evs = [self._events[e[3]] for e in self._heap]
        return sorted((e for e in evs if not e.cancelled), key=lambda e: e.key)

    def __len__(self) -> int:
        return sum(1 for e in self._heap if not self._events[e[3]].cancelled)

    def get(self, event_id: int) -> Optional[Event]:
        return self._events.get(event_id)

    def all_events(self) -> Iterator[Event]:
        return iter(self._events.values())

# Simulation semantics

This document defines what the engine does. The tests in `tests/` check these rules, and the invariant checker (`qpvsim/invariants.py`) verifies them on every trace on request.

## 1. Time model

| Quantity | Representation |
|---|---|
| Simulation (global) time | Python `int`, **femtoseconds** (1 ns = 10⁶ fs). Arbitrary precision, so no overflow. |
| User inputs (ns, m, m/s, ppm) | Converted to exact rationals from their **decimal representation** (`0.1` → 1/10, not the nearest binary double). |
| Rounding of user-supplied times | Once, at conversion: round half to even, to the nearest fs. |
| Rounding of propagation delays | `ceil(distance / speed)` in fs. A signal can never arrive before its exact light-cone time; the excess is below 1 fs per hop. |
| Timestamp equality | Integer equality. Two events are simultaneous iff their fs values are equal. |
| Expressions | See time in float **nanoseconds of the participant's local clock** (`now`, `msg.time`), derived from integer fs. `fs_round(x)` snaps a float-ns value onto the fs grid, so float comparisons in guards agree exactly with integer-fs timers. |

The engine distinguishes, and records, the following times:

- **Event scheduling time**: `Event.scheduled_at`, the simulation time when an event was scheduled.
- **Action time**: `Message.send_time`, the transition *begin*, when the `send` action executed.
- **Transmission start**: `Message.depart_time`, the completion of the sending transition.
- **Reception time**: `Message.arrival_time` = departure + propagation + latency (+ jitter).
- **Consumption time**: `Message.consumed_time`, when a transition took the message from the mailbox.
- **Processing interval**: transition begin → completion (`transition.begin` / `transition.complete` records).
- **Local clock readings**: `local_time_fs` on every participant record.
- **Deadline and decision time**: deadline timers (`timer.set` with `fire_fs`) and verdict times (`verdict` records).
- **Wall-clock execution time**: only reported for experiments (`wall_time_s`). It never enters simulation results.

## 2. Event ordering

Pending events are ordered by the key `(time, priority, seq)`:

- `time`: integer fs.
- `priority`: a smaller number runs first among events at the same instant. The defaults are below, and a project can override them in `simulation.priorities`.
- `seq`: a global insertion counter. Equal time and priority means first scheduled, first executed (FIFO).

| Event kind | Default priority | Meaning |
|---|---|---|
| `node.start` | 5 | participant becomes active |
| `msg.deliver`, `msg.loss` | 10 | message arrives (or would have arrived) |
| `transition.complete` | 20 | a transition finishes; outputs depart |
| `timer.fire` | 30 | a named timer expires |

Because the key is a strict total order, execution is fully deterministic given the project and seed.

**Same-timestamp semantics.** Deliveries precede timers at the same instant. A response that arrives *exactly* at a deadline is therefore processed before the deadline timer fires: **deadlines are inclusive**. `tests/test_engine.py::test_deadline_is_inclusive_to_the_femtosecond` checks this, and a response one femtosecond late is rejected.

**Causality.** Events can only be scheduled at or after the current time (`SchedulingError` otherwise), so the clock never runs backwards. An event scheduled while another executes records it as its `cause`. The invariant `event_order` checks that every executed event had the smallest key among the events pending at that moment. Events created during execution at the same instant may legitimately have a smaller key; zero-duration transitions do this.

Cancellation is lazy: the event is flagged and skipped. Rescheduling cancels the event and schedules a copy that records `rescheduled_from`.

## 3. Participant clocks

```
local(t) = t + offset + floor(t · drift_ppb / 10⁹)        (all integers, fs)
```

`offset_ns` and `drift_ppm` are configured per participant. Participants only ever see local time:

- `now` in expressions;
- `msg.time`;
- timers armed with `at_ns` (absolute local time) or `after_ns` (relative to the local time at which the timer is armed).

A local timer target `L` fires at the earliest global time `g` with `local(g) ≥ L`. The clock is monotone because the drift must exceed −10⁶ ppm. Verifiers therefore act on, and judge deadlines with, their own clocks, so clock offsets and drift influence decisions the way they would physically.

## 4. Execution model of a participant

Each participant runs one automaton (see [PROTOCOL_DSL.md](PROTOCOL_DSL.md)) and holds:

- the current state;
- local variables and parameters;
- a **mailbox** of delivered, unconsumed messages;
- a set of **expired timers** not yet consumed;
- named **qubit slots**;
- an optional "busy" record.

1. **Stimuli**: a start event, a delivery or a timer expiry. Each is recorded, then the participant is *evaluated*.
2. **Evaluation**: if the participant is busy or finished, nothing happens; the stimulus waits in the mailbox or expired set. Otherwise the transitions leaving the current state are tried **in declaration order**. A transition is enabled when its trigger is satisfied:
   - `start`: only during the start evaluation;
   - `timer`: the named timer has expired;
   - `receive`: a message for every listed tag is in the mailbox, optionally restricted to one port. The earliest-arrived message per tag is used.
   - `auto`: always.

   An enabled transition must also have a true guard. The first enabled transition fires. If triggers matched but all guards were false, a `guards.rejected` record lists the evaluations, and the inputs stay queued.
3. **Begin** (time `t`):
   - The trigger's inputs are consumed. Their message ids join the participant's causal past.
   - The source state is exited.
   - The actions execute in order, at time `t`: variable assignments, quantum operations and measurements, timers.
   - Outgoing messages and the verdict are **buffered**.
   - Completion is scheduled at `t + d`. `d` is the transition's `duration_ns` expression, or else the participant's `processing_ns`, and never less than the capability minimum.
   - The participant is busy until then.
4. **Complete** (time `t + d`):
   - The target state is entered.
   - Buffered messages depart.
   - A buffered verdict is recorded.
   - If the target state is terminal, the participant finishes and its pending timers are cancelled.
   - Otherwise it is evaluated again, so queued inputs are handled.
5. **Errors**: the participant halts (`outcome = "error"`), the halt is recorded, and the rest of the simulation continues. Errors are:
   - expression errors;
   - a send on a port without a link;
   - an operation on a missing qubit;
   - quantum backend errors;
   - capability violations.

   A halted verifier never accepts.

A safety limit of 10,000 transitions at one instant per participant turns a livelock caused by `auto` cycles into a recorded error.

## 5. Messaging and channels

A link joins `(node, port)` endpoints and has a kind: `classical` or `quantum`. Links are bidirectional unless `directed`. A send uses the participant's link of the right kind on the named port.

```
arrival = departure + ceil(length / speed) + latency (+ jitter)
```

- `length` defaults to the straight-line distance between the endpoints. An explicit length shorter than that is rejected as faster than light.
- `speed` defaults to `physics.signal_speed_mps`, which is exactly c by default. Speeds above c are rejected unless `physics.allow_superluminal` is set.
- `jitter` is drawn uniformly from `[0, jitter_ns]` from the link's own RNG stream. Jitter can reorder messages on a link; FIFO is not guaranteed when it is non-zero.

Loss is decided when the message departs, with survival probability `(1 − loss_prob) · 10^(−attenuation_dB/km · L_km / 10)`. A lost message produces a `msg.loss` record at its would-be arrival time and is never delivered; a lost qubit is discarded from the backend.

Quantum channel noise is applied on delivery, in the order depolarising, dephasing, bit-flip, then amplitude damping. A received qubit is stored in the slot named after the message tag.

## 6. Causality tracking

Every message stores its **causal past**: the ids of all messages its sender had consumed before sending it. The transitive closure (`Simulation.causal_chain`) traces a response back to the challenges it depends on. The console's `chain`, the UI's message inspector and the spacetime highlight all use it.

## 7. Verification decision

Each verifier's automaton records a verdict (`accept`/`reject` plus a reason) on a transition. The project's `verification.rule` (`all`, `any` or `k_of_n`) combines them. A verifier that halted or never decided counts as not accepting.

The decision explanation is reconstructed from the trace: the transition that produced each verdict, the trigger (a message or a timer), the guard results, and the arrival times of the messages consumed. Outcomes are classified for statistics as:

- `accepted`;
- `timeout` (the verdict was triggered by a timer);
- `wrong_answer` (triggered by a message whose guard failed);
- `error`;
- `undecided`.

## 8. Randomness and reproducibility

Every random draw comes from a named PCG64 stream seeded by `SeedSequence([seed, crc32(name)])`:

| Stream | Used for |
|---|---|
| `node:<id>` | expression randomness of that participant, and its measurement-error flips |
| `link:<id>` | loss and jitter on that link |
| `quantum` | Born-rule sampling and trajectory noise in the backend |
| `resources` | pre-shared classical randomness |

The same project and seed give an identical trace. Streams are addressed by name, so adding or removing an unrelated participant does not change other participants' random numbers (`test_random_streams_are_stable_under_unrelated_edits`).

Experiment run `i` of grid point `k` uses seed `SeedSequence([master, k, i])`. That seed is stored with the run, so the run can be reproduced on its own; results are identical with any number of parallel workers.

## 9. Termination

A run stops when the first of these holds:

- all verifiers are in terminal states (`stop_when = "verifiers_decided"`, the default);
- no events remain (`quiescent`);
- the next event lies beyond `max_time_ns`;
- `max_events` have executed.

The stop reason is recorded, and pending events remain inspectable. Messages delivered but never consumed are marked `unconsumed`.

# Architecture

## The contract: the engine is the source of truth

Every number, state and animation the UI shows originates in the Python engine:

- Timestamps are the engine's integer-femtosecond clock.
- A highlighted state is the participant's current FSM state in the engine.
- A message dot on a channel sits where the engine's departure and arrival timestamps put it at the engine's current time.
- The "Play" control does not animate anything by itself. It repeatedly asks the engine to advance its clock by a small interval (`run until=t`) and redraws the returned snapshot.

The UI never computes protocol behaviour, timing or results. The browser end-to-end tests (`frontend/e2e/run.mjs`) check this by comparing what the UI displays with what the engine API reports after each action.

The kernel has no dependency on the UI, the HTTP server or any web framework. Simulations run headlessly from Python, the CLI, the console or the test suite.

## Components

```
            ┌──────────────── frontend (React, React Flow) ───────────────┐
            │ network canvas · automaton editor · spacetime · inspector   │
            │ events · timelines · console · experiments · validation     │
            └──────────────────────────┬──────────────────────────────────┘
                                       │ JSON over HTTP (server/app.py)
┌──────────────────────────────────────┴───────────────────────────────────┐
│ session.py   Session: editable project + current Simulation + results    │
│ console.py   command grammar over Session          cli.py  qpv ...       │
│ experiments.py  sweeps, seeds, Wilson intervals, provenance               │
├───────────────────────────────────────────────────────────────────────────┤
│ engine.py    Simulation: compile project → participants, links, resources │
│              execute events; trace; messages; snapshots; causal chains    │
│ decision.py  verdict combination + explanation                            │
│ invariants.py  trace consistency checks                                   │
├──────────────────────┬──────────────────────┬─────────────────────────────┤
│ kernel/              │ protocol/            │ quantum/                    │
│  scheduler (time,    │  automaton DSL +     │  QuantumBackend interface   │
│  priority, seq)      │  static validation   │  DensityMatrixBackend       │
│  local clocks        │  expression sandbox  │  StateVectorBackend         │
│                      │  capabilities        │  gates, bases, Kraus noise  │
│                      │  project format      │                             │
└──────────────────────┴──────────────────────┴─────────────────────────────┘
library.py + examples/: protocols and scenarios expressed purely as data
```

| # | Component (prompt §14) | Where |
|---|---|---|
| 1 | Discrete-event simulation kernel | `kernel/scheduler.py`, `kernel/clock.py`, `engine.py` |
| 2 | Quantum backend interface | `quantum/base.py` (+ `density.py`, `statevector.py`) |
| 3 | Network and communication models | `engine.py` (`OutLink`, `_transmit`, `_apply_link_noise`), project `links` |
| 4 | Protocol-definition framework | `protocol/automaton.py`, `protocol/expr.py`, `protocol/project.py` |
| 5 | Participant state machines | `protocol/automaton.py` (spec, validation), `engine.py` (`Node`, `_evaluate`, `_begin`, `_on_complete`) |
| 6 | QPV verification logic | verifier automata in `library.py`, `decision.py` |
| 7 | Adversary framework | `protocol/capabilities.py` (capabilities) + strategies as automata in `library.py` |
| 8 | Experiment orchestration | `experiments.py` |
| 9 | Results and trace storage | `TraceRecord`, `Message` in `engine.py`; `Session.export_trace`; experiment raw/derived results |
| 10 | Public scripting API | `qpvsim/__init__.py`, `session.py` |
| 11 | Visual editor and visualisation | `frontend/src/components/*` |
| 12 | Console and developer tools | `console.py`, `cli.py`, UI console panel |
| 13 | Persistence and import/export | `protocol/project.py` (`load_project`, `save_project`, `migrate`), trace/results export |
| 14 | Testing and validation | `tests/`, `invariants.py`, `frontend/e2e/`, `scripts/bench.py` |

## Data flow

1. **Project document**: a versioned JSON file (see [PROJECT_FORMAT.md](PROJECT_FORMAT.md)). The UI edits this document and nothing else. Every edit is one undo step, and it is sent to the server (`PUT /api/project`), which validates it and rebuilds the simulation. Edits that change only editor layout (`ui` fields) keep the running simulation.
2. **Compilation**: `Simulation.__init__` normalises and validates the document, then builds the runtime objects:
   - participants (automaton, capabilities, local clock, RNG stream);
   - outgoing link tables with exact propagation delays;
   - the quantum backend;
   - pre-shared resources.

   It then schedules every participant's start event.
3. **Execution**: `step()` pops exactly one event (`node.start`, `msg.deliver`, `msg.loss`, `transition.complete` or `timer.fire`) and dispatches it. Every effect is appended to the trace as a `TraceRecord` with a human-readable explanation of how its timestamp was obtained.
4. **Observation**: `snapshot(since)` returns the clock, participant states, pending events, messages, link delays, new trace records and the current decision. The UI merges these increments, and the console and experiments read the same structures.

## Design decisions

| Decision | Choice | Why |
|---|---|---|
| Kernel language | Python + NumPy | QPV rounds have few events and qubits, so correctness, auditability and the scientific ecosystem matter more than raw event throughput. Throughput comes from parallel repetitions (≈1,600 runs/s on 4 workers). Integer time has arbitrary precision. See the trade-off table in the REA report §7.2. |
| Time representation | integer femtoseconds | Exact equality and deadline comparisons; no float drift. User-supplied times are converted from their decimal representation and rounded half-to-even. Propagation delays are rounded **up**, so discretisation can never beat the light cone. |
| Ordering | `(time, priority, seq)` | A strict total order. SeQUeNCe orders by `(time, priority)` without a sequence tie-break (REA §2), which leaves equal keys in heap order. |
| Protocols | declarative JSON automata interpreted by the engine | The visual editor and the engine share one representation, and new protocols need no kernel changes. Protocols stay inspectable and serialisable. |
| Guards and arguments | sandboxed expression subset parsed with `ast` | Expressive enough for protocol logic, but it cannot reach Python internals and is deterministic (randomness comes from seeded streams). |
| Adversaries | capability profiles separate from strategies | The same strategy can be compared under different resource assumptions, and vice versa. The engine enforces capabilities on every action. |
| Quantum | `QuantumBackend` interface with group-wise state merging | Exact density matrices for small, mixed-state problems. A state-vector backend with trajectory noise handles larger, purer problems. Other libraries can be added behind the same interface. |
| Randomness | independent name-addressed streams (`SeedSequence([seed, crc32(name)])`) | Adding a participant does not perturb the random numbers drawn by others, and every experiment run records its own seed. |
| UI | browser-served React + React Flow, bundled into the Python package | No native packaging; `pip install` + `qpv serve` is enough. React Flow supplies zoom, pan, minimap and connections. The spacetime view is custom SVG. |
| Validation | hand-written, domain-specific | Messages name protocol concepts (unknown port, unreachable state, superluminal link, entanglement not permitted by profile). |

## Extending the platform

- **A new protocol**: write automata and a project, either in the editor or as JSON (see `library.py` for examples). No engine changes are needed.
- **A new adversary strategy**: write an automaton with the ports `verifier` and `partner` (any names work), then choose it per participant in the inspector or with the console's `strategy` command.
- **A new capability profile**: add an entry to `PROFILES` in `protocol/capabilities.py`.
- **A new quantum backend**: subclass `QuantumBackend` (create, create_entangled, discard, apply_unitary, apply_channel, measure, reduced_density, group_of), register it in `quantum/__init__.py` `BACKENDS`, and add it to the cross-backend tests in `tests/test_quantum.py`.
- **A new action**: add it to `ACTIONS` in `protocol/automaton.py` and implement it in `Simulation._exec_action`, including a capability check if it is privileged.

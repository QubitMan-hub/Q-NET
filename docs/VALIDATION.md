# Validation and test report

Run the suite with `pytest`. The browser tests need Node.js with Playwright and the built UI; they are skipped automatically otherwise.

Status at the time of writing: **112 tests, all passing**, on Python 3.13, NumPy 2.5 and Linux, with Chromium for the end-to-end tests.

## Inventory

| File | Tests | Covers |
|---|---|---|
| `tests/test_time_and_scheduler.py` | 15 | exact decimal→fs conversion; round-half-even; **ceiling** propagation (property-based); clock offset and drift; local→global timer conversion (property-based, 300 cases); ordering by (time, priority, seq); delivery-before-timer at equal times; configurable priorities; no scheduling in the past or at float times; cancel and reschedule; cause links; random schedules pop in key order (property-based) |
| `tests/test_quantum.py` | 23 | both backends: deterministic BB84 in the same basis; uniform outcomes in the conjugate basis; Breidbart success probability; Bell correlations in Z and X with group splitting; teleportation identity for an arbitrary state; partial trace; channels; requested qubit order; trajectory noise vs exact density matrix (statistical); T1/T2 composition and the unphysical-T2 check; group limit; invalid operations raise |
| `tests/test_expr_and_validation.py` | 17 | expression semantics; sandbox rejects imports, dunder access, lambdas, comprehensions, calls, assignments; error messages; automaton validation (unknown states, unreachable, deadlock, unknown names, functions and ops); superluminal and too-short links; entanglement capability; strategy/capability mismatch; duplicate ports; unknown participants |
| `tests/test_engine.py` | 28 | **hand-calculated reference trace** of the honest round (every timestamp to the fs, and the prover's exact event sequence); timestamp explanations; inclusive deadline (on time accepted, **1 fs late rejected**); displaced prover; wrong-answer classification; teleportation attack wins 40/40 seeds; timing defeats it; collinear attack arrives on the light cone; classical PV collusion; clock offset and drift effects; capability violation halts the participant; profile and strategy compatibility; min-processing enforcement; memory capacity; information-flow isolation; loss → timeout; full depolarisation → ½; memory storage limit; reproducibility (same seed → identical trace, different seeds differ, streams stable under unrelated edits); step-by-step ≡ run; run-until; backend agreement; shipped example files equal the library; **property-based**: honest acceptance iff processing ≤ tolerance over random geometries, and invariants hold for random adversary geometries and timing across all examples |
| `tests/test_console_server.py` | 27 | console reports only engine-confirmed results, with grouped help and plain-language errors; error reporting for bad commands and arguments; edit → run changes the outcome; checkpoint and restore replay identically; strategy swap and completion; trace export; project save/load round-trip reproduces the run; newer format rejected; Wilson intervals; per-run seed reproducibility; derived metrics recomputed from raw runs; **Breidbart experiment matches cos²(π/8)** (3,000 runs, fixed seed); parallel workers give identical results; HTTP: step and state come from the engine, loading always restarts while layout-only edits keep the run, validation blocks invalid projects, console, meta, experiment jobs with CSV and raw output, trace export and causal chain, patch paths |
| `tests/test_ui_e2e.py` | 2 | runs `frontend/e2e/run.mjs` and `build.mjs` against a live server (see below) |

## UI-to-engine synchronisation (browser end-to-end)

`frontend/e2e/run.mjs` drives the real UI in headless Chromium. After every action it compares the UI with the engine's API (19 checks):

- clock text = engine `now`;
- 5 UI steps = 5 executed engine events;
- outcome pill = engine decision;
- node badge = engine FSM state;
- event-log rows = trace length;
- one spacetime path per departed message;
- fired-transition markers = engine transition history;
- inspector edits reach the engine project and change the decision;
- undo restores it;
- console-driven runs update the toolbar;
- experiment results render;
- no browser errors.

`frontend/e2e/build.mjs` builds QPV_BB84 **from an empty project using only the editor**:

1. Drag participants from the palette and choose strategies and positions in the inspector.
2. Connect ports for one quantum and two classical channels.
3. Add shared randomness and set the claim.
4. Run: the claim is accepted, with 4 messages exchanged.
5. Add a state and draw a transition in the automaton editor. The engine then fires the new `auto` transition at t = 0 and the claim is rejected by timeout, which is the correct behaviour.
6. Undo the change: the claim is accepted again.
7. Save: the downloaded file equals the engine's project document.

`frontend/e2e/static.mjs` checks the **static GitHub Pages build**, where the engine runs in the browser via Pyodide:

- the engine boots in the page (about 9 s on a first visit here);
- the honest round ends at the hand-calculated 30.206923 ns, identical to the server build;
- the console answers;
- the teleportation attack is accepted;
- a timing sweep runs, with the attack winning when fast and failing when slow;
- no browser errors.

Run it with `scripts/build_pages.sh` and a static file server.

## Reference scenarios

The six bundled examples are deterministic for a fixed seed. Their expected decisions are asserted in `tests/test_engine.py`, and their statistical behaviour is listed with reproduction commands in [QPV_PROTOCOLS.md](QPV_PROTOCOLS.md). The honest QPV_BB84 trace is checked against a hand calculation:

- challenge emission at 9.993077 ns;
- simultaneous arrival at the claim at exactly 20.000000 ns;
- answers departing at 20.2 ns;
- answers arriving at 30.206923 ns;
- deadline at 30.506923 ns.

## Statistical validation

| Quantity | Theory | Simulation (fixed seeds) |
|---|---|---|
| Breidbart guessing probability (backend level, both backends) | cos²(π/8) = 0.85355 | within 4σ (6,000 samples each) |
| Unentangled collusion attack, Breidbart | 0.85355 | 0.8545 [0.8384, 0.8693] |
| Fixed or random basis attack | 0.75 | 0.7435–0.7545, all intervals include 0.75 |
| Honest prover, depolarising p | 1 − p/2 | all 5 sweep points' intervals include it |
| Trajectory noise vs exact channel | exact P(Z = 0) | within 4σ (6,000 trajectories) |

## Invariants

`qpvsim.invariants.check_trace` checks every trace on demand. It is exposed through the `invariants` console command, the Validation panel and `qpv run`, and the tests run it on every reference scenario and property-based case:

- `monotonic_time`
- `event_order`
- `delivery_timing` (arrival = departure + delay; departure = completion of the sending transition)
- `relativistic_bound` (no message faster than c over the straight line, with no slack)
- `causal_consumption`
- `causal_past`
- `fsm_consistency` (a replay of each participant's transitions matches its engine state)
- `single_verdict`
- `terminal_quiet`

## Performance (scripts/bench.py; one machine, 4 cores; numbers are indicative)

| Measurement | Result |
|---|---|
| One QPV_BB84 round (16–22 events) | 3–4 ms |
| Experiment throughput, 1 / 4 workers | ≈590 / ≈1,600 runs/s |
| Relay chain: 4 / 13 / 53 / 103 / 203 participants | 4 / 7 / 19 / 35 / 70 ms per run (linear; 1,016 events and 2,041 records at 203) |
| n-qubit GHZ, density matrix: n = 4 / 8 / 10 / 12 | 0.8 ms / 17 ms / 0.4 s / 7.5 s |
| n-qubit GHZ, state vector: n = 4 / 8 / 10 / 12 | 0.3 / 0.7 / 1.2 / 3.3 ms |

Bottlenecks:
- **Density matrices** beyond about 10 entangled qubits. Use `state_vector` for larger, purer problems.
- **Per-event Python overhead** (≈0.2 ms per event, including tracing). This is irrelevant for QPV-sized rounds, and parallel workers scale experiments.
- **The UI** receives the full snapshot of messages and participants on each step. That is comfortable up to a few thousand trace records; beyond that the snapshot should become incremental (see the roadmap).

## Clean-environment installation check

`scripts/check_clean_install.sh` creates a fresh virtual environment, installs the package from the repository, and then:

1. runs the test suite;
2. runs a headless simulation;
3. starts the server;
4. fetches the UI and the API.

The script was run successfully for this release.

## What the tests do not establish

They establish that the engine follows its documented semantics and reproduces known results for the modelled protocols. They do not establish that:

- the physical model is adequate for a real deployment;
- the shipped adversary strategies are optimal;
- any protocol is secure.

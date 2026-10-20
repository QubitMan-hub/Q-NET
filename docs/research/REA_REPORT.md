# REA Report: Quantum Network Simulators and Quantum Position Verification

*Research phase for the `qpvsim` QPV simulation workbench. Prepared 2026-10-20.*

**How this was done and what was checked.** All material is public and licence-permitted. Each statement is marked by how it was established:

- **[src]**: read directly from the SeQUeNCe 1.3.1 wheel downloaded from PyPI (`sequence-1.3.1-py3-none-any.whl`). It was unpacked into an isolated scratch directory and read as data. It was never imported or executed.
- **[paper]**: read from the full text of an arXiv PDF or abstract retrieved during this research.
- **[meta]**: from arXiv API or PyPI JSON metadata (titles, authors, journal references, licence fields).
- **[prior]**: from prior knowledge and **not re-verified** in this session.

Things that could not be checked:

- NetSquid's online documentation (`docs.netsquid.org`) was not reachable. The direct fetch failed DNS resolution, and a proxied request returned HTTP 401. That is consistent with the NetSquid paper's note that "access to documentation requires registration". No attempt was made to get around this.
- The SeQUeNCe GitHub repository, including its `tests/` directory, could not be reached from this session.

---

## 1. Executive summary

- **No existing simulator covers a QPV workflow end to end.** The two leading quantum-network discrete-event simulators are SeQUeNCe (Argonne, BSD-3-style licence) and NetSquid (QuTech, proprietary and registration-gated). Both are mature, and their kernels and quantum-state engines are well suited to repeater and entanglement-distribution studies. Neither treats the following as first-class: spacetime geometry, a claimed prover position, verifier deadlines, adversary capability limits, or causality checks on traces. QPV security arguments depend on exactly these.
- **SeQUeNCe kernel** [src]:
  - Integer **picosecond** time.
  - A `heapq` min-heap of `Event` objects ordered by `(time, priority)`.
  - Lazy deletion through an invalid flag.
  - A `QuantumManager` registry with ket, density-matrix, Fock-truncated density-matrix, Bell-diagonal and Stim-backed stabilizer formalisms. Quantum states are merged with `np.kron` when a circuit spans separate states, and split when qubits are measured.
  - **Same-time, same-priority events are not ordered FIFO by an insertion counter.** `Process.number` is assigned but is not used in comparisons. Tie order is therefore an artefact of the heap: reproducible, but not specified. We should add an explicit sequence number.
- **NetSquid** [paper]:
  - A C++ engine (PyDynAA) with Cython bindings.
  - Shared `QState` objects that grow and shrink, in KET, DM, STAB and GSLC formalisms.
  - Memoised operators.
  - Composable components with models for delay, noise and loss.
  - Generator-based protocols that `yield` composable *event expressions* (`await_port_input`, `await_timer`, `await_signal`).
  - Its licence rules out redistribution or bundling with an open-source project.
- **QPV theory sets the requirements.**
  - Classical position verification is impossible against colluding adversaries (Chandran et al. 2009).
  - Quantum PV is impossible against adversaries with unbounded entanglement (Buhrman et al. 2014; Kent–Munro–Spiller 2011; Lau–Lo 2011).
  - QPV_BB84 is broken by a single shared EPR pair through teleportation.
  - QPV_BB84 is secure against *unentangled* attackers with success probability at most cos²(π/8) ≈ 0.854 (Tomamichel–Fehr–Kaniewski–Wehner 2013).
  - QPV_BB84 becomes trivially insecure if attackers may declare loss on 50% of rounds.
  - Newer work (QPV_f, QPV_SWAP, the commitment-based loss fix) adds requirements: slow-quantum / fast-classical timing, loss accounting, and bounds that depend on entanglement.
  - The workbench therefore has to enforce **who can do what, where, and by when**. This is the main gap in existing tools.
- **Recommendation**, matching the decided design: build a small, deterministic, auditable Python kernel (`qpvsim`) with integer femtosecond time and `(time, priority, seq)` ordering, a pluggable `QuantumBackend`, a declarative automaton DSL, capability-checked adversaries and statistical experiment runners. Expose it through FastAPI to a React/@xyflow UI. Borrow patterns from SeQUeNCe and NetSquid, not code. QuTiP, Qiskit Aer and Stim can be integrated later as optional backends.

## 2. Comparative analysis

### 2.1 Table

| Dimension | SeQUeNCe 1.3.1 | NetSquid (≈1.x) | QuNetSim | SimulaQron / NetQASM (+SquidASM) | QuISP |
|---|---|---|---|---|---|
| Architecture | Pure Python; `Timeline` + `Entity` + `Process`/`Event`; five-layer stack (hardware, entanglement mgmt, resource mgmt, network mgmt, app) [src][paper] | Python + Cython over the C++ PyDynAA engine; Entity/EventHandler/EventExpression; Components composed of Models and connected by Ports [paper] | Python, thread-per-host, message queues; not a discrete-event simulator in the strict sense [prior] | SimulaQron: distributed real-time simulation of quantum processors for app development. NetQASM: ISA + SDK. SquidASM runs NetQASM on NetSquid [paper][prior] | C++ on OMNeT++ DES; RuleSet-driven protocol architecture [meta][prior] |
| Time model and precision | Integer ps (`Timeline.time: int`); constants `NANOSECOND = 10**3` … `SECOND = 10**12`; gmpy2 80-bit `mpfr` for time-bin conversions [src] | Float simulation time in ns [prior, not re-verified] | Wall-clock / thread scheduling; no global simulated time [prior] | Wall-clock (SimulaQron); NetSquid time under SquidASM [prior] | OMNeT++ `simtime_t` (fixed-point int64 with a configurable exponent) [prior] |
| Event ordering | Min-heap by `(time, priority)`, with `priority=inf` default and lower values first. No sequence tie-breaker in `Event.__lt__`. Lazy removal; `update_event_time` is an O(n) scan [src] | Sequential stepping; handlers matched by hash lookup on type, source and id [paper]; tie semantics not documented in the paper | n/a | n/a | OMNeT++ ordering: time, then scheduling priority, then insertion order [prior] |
| Quantum formalisms | Ket, density matrix, Fock density (truncation), Bell-diagonal (analytic), stabilizer (Stim `TableauSimulator`), chosen globally through a class-level registry [src] | KET, DM (dense/sparse), STAB, GSLC; formalism-agnostic `qubitapi`; automatic conversion between formalisms; memoised sparse operators [paper] | Pluggable backends (EQSN, ProjectQ, QuTiP) [prior] | Backends include projectQ, QuTiP and stabilizer [prior] | Mainly error-basis / Pauli-frame-style tracking and stabilizer-like approaches for scale [paper: NetSquid comparison][prior] |
| State merging | `np.kron` of distinct `KetState`s touched by `run_circuit`; keys of one joint state share an object; measurement collapses measured keys to product basis states [src] | QStates "grow and shrink" as qubits interact or are measured [paper] | Backend-dependent | Backend-dependent | n/a (error tracking) |
| Channels and noise | `QuantumChannel`: `delay = round(distance/light_speed)` with default `2e-4` m/ps (≈ c/1.5); `loss = 1 − 10^(−αL/10)`; polarization fidelity; send-frequency time bins. `ClassicalChannel`: lossless, fixed delay, carries a message priority [src] | Delay, loss and quantum-noise models attached to channels; FibreDelay/FibreLoss-type models [paper][prior] | Simple loss/noise per link [prior] | Idealised (SimulaQron); NetSquid models (SquidASM) [prior] | Detailed link-level models (fibre loss, gate errors, memory errors) [prior] |
| Components | Memory/MemoryArray (fidelity, coherence time, expiry events, analytic BDS Pauli decoherence applied on access), Detector (efficiency, Poisson dark counts, dead time from `count_rate`, `time_resolution` binning), BSM, SPDC, beam splitter, transducer, etc. [src] | QuantumMemory, QuantumProcessor (programs, physical instructions with duration/noise), sources, detectors; T1/T2 noise applied when an idle qubit is next acted upon [paper] | Hosts, routers | Nodes with quantum processors | QNIC, BSA, EPPS models |
| Protocol abstraction | `Protocol`/`StackProtocol` (`push`/`pop`); entanglement generation (Barrett–Kok, single-heralded), swapping, purification (BBPSSW, DEJMPS-BDS) behind registries; `RuleManager` with `Rule(priority, action, condition)` [src] | `Protocol`, `NodeProtocol`, `LocalProtocol`, `ServiceProtocol`; `Signals`; `run()` generator yielding event expressions [paper] | Host-level Python functions; send/receive helpers | NetQASM programs (application layer) | RuleSets (condition → action) |
| Reproducibility | Per-node `np.random.default_rng(seed)`; `Timeline.seed` seeds legacy global NumPy RNG; `Entity.get_generator()` falls back to **unseeded** `default_rng()` if an entity has no owning node [src] | `simtools.set_random_state` / global seed [prior] | Thread interleavings limit determinism [prior] | Real-time ⇒ limited | OMNeT++ RNG streams per module, seedable [prior] |
| Extensibility | Decorator registries for formalisms and protocol variants; subclassing [src] | Subclass Components/Models/Protocols [paper] | Subclassing / functions | ISA/SDK | C++ modules + NED files |
| Testing | No tests shipped in the wheel or sdist; a pytest suite is believed to exist in the repo [prior; repo not reachable] | Not public | pytest [prior] | pytest [prior] | Google Test [prior] |
| Performance | Pure Python. A separate parallel SeQUeNCe exists (scalability study by Welch & Kiran 2025). In 1.3.1 `QuantumChannel.transmit` calls `quantum_manager.move_manage_to_server`, which is **not defined** anywhere in the wheel: a leftover hook for the parallel/server manager [src][meta] | C++ engine + Cython; memoisation; the paper reports repeater chains with many nodes and runs that parallelise trivially across independent seeds [paper] | Low (threads) | Low | High (C++) |
| Licence | BSD-3-Clause-style "Open Source License", © UChicago Argonne, LLC [src] | Proprietary; free for registered (academic) users; not on public PyPI (confirmed: PyPI JSON lookup fails) [meta][prior] | MIT [meta] | SimulaQron BSD-3 [prior]; NetQASM MIT; SquidASM MIT but needs NetSquid [meta] | BSD-3 [prior] |

### 2.2 Prose

**SeQUeNCe kernel** [src]. `sequence/kernel/timeline.py` defines `Timeline` with `time: int` in picoseconds and `stop_time` defaulting to `10**23` ps (≈ 3,000 years). `schedule()` stamps `event.process.number = schedule_counter` and pushes onto `EventList` (`eventlist.py`, a `heapq` wrapper). `run()` pops events, skips those marked invalid, asserts monotone time, and calls `Process.run()`, which is `getattr(owner, activation)(*args, **kwargs)`. Late binding by method name keeps scheduling cheap and serialisable, but it weakens static checking.

`Event` (`event.py`) compares only `time` and `priority`, and the default priority is `math.inf`. Python's `heapq` is not stable, so two events at the same `(time, priority)` run in whatever order the heap leaves them. That order is reproducible for an identical schedule sequence, but it is not FIFO and not documented. For QPV, where a reply "arriving exactly at the deadline" is a meaningful boundary case, this is a correctness hazard.

**SeQUeNCe quantum managers** [src]. `kernel/quantum_manager/base.py` defines an abstract `QuantumManager`. Its `_registry` is populated by the `@QuantumManager.register(name)` decorator. A process-global `_global_formalism`, guarded by a `threading.Lock`, selects which manager `Timeline` creates.

- `ket_vector.py` (`QuantumManagerKet`) merges every distinct `KetState` referenced by a circuit with `np.kron` and applies gates by tensor contraction on a `(2,)*k` reshaped array. The docstring gives the cost as O(2^k) per gate. Measurement uses Born probabilities from axis-grouped amplitudes, with a caller-supplied uniform sample `meas_samp`. That sample is the hook for reproducible sampling. Measured keys are reset to single-qubit basis states, and the remainder is renormalised into a new shared `KetState`.
- `density_matrix.py` builds the full circuit unitary by `np.kron` with identity padding, which is simpler but costs O(8^k).
- `stabilizer.py` wraps `stim.TableauSimulator`, includes gate, idle and measurement Pauli noise, and has fixed gate durations (for example `TWO_QUBIT_GATE_TIME_PS = 250_000`).
- `bell_diagonal.py` tracks only the four Bell-diagonal coefficients, analytically.
- `fock_density_matrix.py` handles photonic modes with a `truncation` parameter and generalized amplitude damping.

**SeQUeNCe channels and components** [src].

- `components/optical_channel.py`: `QuantumChannel.init()` sets `delay = round(distance / light_speed)` and `loss = 1 - 10**(-distance*attenuation/10)`. In `transmit`, loss is sampled from the *sender node's* generator and polarization noise is applied. Transmissions are quantised to `frequency` time bins using gmpy2 high-precision arithmetic. `ClassicalChannel` is explicitly lossless and passes a `priority` into the receive event.
- `components/memory.py`: `Memory` schedules an `expire` event at `cutoff_ratio * coherence_time`. Under the Bell-diagonal formalism it applies a time-dependent Pauli channel *lazily*: `bds_decohere()` computes Δt from `last_update_time` when the state is next used. This is the same lazy pattern NetSquid describes for T1/T2 noise.
- `components/detector.py`: `Detector` models efficiency, Poisson dark counts (exponential inter-arrival scheduling), dead time `1/count_rate`, and arrival-time binning to `time_resolution`.

**SeQUeNCe protocols** [src].

- `protocol.py` defines `Protocol` (owner node, `received_message`) and `StackProtocol` (`push`/`pop` between layers).
- Entanglement generation (`generation_base.py`: `EntanglementGenerationA/B`, registry with `BARRET_KOK` default and `SINGLE_HERALDED`), swapping (`swapping_base.py`, `_circuit`, `_bds`) and purification (`bbpssw_*`, `dejmps_bds`) are classes with hand-written state, such as `ent_round` and `bsm_res`.
- Orchestration goes through `resource_management/rule_manager.py`. A `Rule` has a priority, a condition function over `MemoryInfo`, and an action that instantiates protocols.
- Protocol state machines are implicit in methods and fields. They are not inspectable data.

**NetSquid** [paper; Coopmans et al. 2021].

- PyDynAA is "a C++ port of the core engine layer from the DynAA simulation framework", with Python/Cython bindings. Entities schedule events and register `EventHandler`s keyed by event type, source and id. An `EventExpression` composes waits with AND/OR to any depth. DEJMPS is the paper's example: wait for local operations AND the remote outcome.
- `Qubit` objects share `QState`s that grow and shrink. `qubitapi` is formalism-agnostic, and states can be converted between formalisms.
- KET/DM operators are memoised as sparse 2ⁿ×2ⁿ matrices keyed by indices and size. Continuous parameters are discretised so that memoisation applies.
- Components are composed of models (delay, loss, noise) and communicate through ports. `QuantumProcessor` executes `QuantumProgram`s mapped to timed, noisy physical instructions.
- `Protocol.run()` is a generator that `yield`s event expressions, with helpers `await_port_input()`, `await_timer()`, `await_signal()` and `await_program()`. Protocols can be nested, and `Signals` (SUCCESS, FAIL, FINISHED, …) carry state changes.
- The NV-repeater case applies amplitude damping with `p = 1 − e^{−Δt/T1}`, then dephasing, "if a spin is acted upon after having been idle for time Δt". This is lazy decoherence on access.
- Benchmarks used NetSquid 0.10.0 / PyDynAA 0.3.5.

**Other tools.**

- **QuNetSim** (DiAdamo et al., IEEE TQE 2021) [meta][prior]: a high-level, MIT-licensed Python framework where each host runs in a thread, with pluggable backends (EQSN, ProjectQ, QuTiP). It is good for teaching protocols. It has no rigorous simulated time, which rules it out for deadline-based QPV.
- **SimulaQron** (Dahlberg & Wehner, QST 2019) [meta]: simulates distributed quantum processors in real time for application development. **NetQASM** (Dahlberg et al. 2021, arXiv:2111.09823) is a low-level ISA plus Python SDK for quantum-internet applications. SquidASM executes NetQASM on NetSquid. The application-layer program model is a useful reference for how a "prover program" might be expressed, but timing comes from the underlying simulator.
- **QuISP** (Satoh et al., IEEE QCE 2022) [meta]: a C++/OMNeT++ event-driven simulator aimed at thousands of qubits across dozens of nodes, with RuleSet-based protocol control. It scales well but needs a heavyweight toolchain and an OMNeT++ GUI, and has no QPV notions.

**General-purpose backends** [meta][prior].

- **QuTiP 5** (BSD-3; Lambert et al., Physics Reports 1153, 2026) has `Qobj`, master-equation solvers and a pluggable data layer (JAX/CuPy). It suits continuous-time noise models, but its dependencies are heavy.
- **Qiskit Aer** (Apache-2.0) provides fast C++ state-vector, density-matrix, MPS and stabilizer simulators with noise models. It is circuit- and shot-oriented, which is awkward for interleaving with event-driven measurement, but usable per-operation.
- **Stim** (Apache-2.0; Gidney, Quantum 5, 497, 2021) is an extremely fast stabilizer tableau simulator. It is ideal for Clifford-only QPV_BB84 attacks at scale, and SeQUeNCe already uses it.
- **Cirq** (Apache-2.0) offers state-vector and density-matrix simulators with clean `Simulator.simulate` stepping and noise channels.

## 3. Architectural patterns worth adopting

1. **Integer time with explicit `(time, priority, seq)` ordering.**
   - Integer time eliminates floating-point drift and rounding-dependent orderings. SeQUeNCe's ps integers show the idea works, and its gmpy2 workaround for frequency bins shows what happens when floats creep in.
   - Adding a monotone `seq` from a schedule counter makes simultaneous events FIFO and fully specified. SeQUeNCe stamps `Process.number` but does not compare on it.
   - Femtoseconds give about 0.3 µm of light travel per tick in vacuum. That is well below any positional claim of interest, and Python's arbitrary-precision `int` avoids overflow. An int64 would overflow at about 2.56 h of simulated time in fs, which matters for any future Rust port.
2. **Lazy decoherence applied on access.** Both tools apply idle noise from Δt when a stored qubit is next touched (SeQUeNCe `Memory.bds_decohere`, NetSquid T1/T2 models). This avoids periodic tick events, keeps time exact, and makes noise a pure function of Δt. That function can be unit-tested against closed forms.
3. **State merging on entangling operations and splitting on measurement.** Keep each independent subsystem as small as possible (SeQUeNCe `KetState` shared-object keys; NetSquid QState grow/shrink). For QPV most rounds involve one to three qubits, so merging keeps density-matrix cost tiny even with many rounds in flight.
4. **Caller-supplied randomness for measurement** (`meas_samp`). The backend never owns an RNG. The engine passes in a draw from a named, seeded stream. This lets runs be replayed exactly and lets backends be swapped without changing outcomes for deterministic cases.
5. **Per-entity RNG streams with no unseeded fallback.** Adopt SeQUeNCe's per-node `default_rng(seed)`. Fix its pitfall, where `Entity.get_generator()` falls back to an unseeded `default_rng()`, by deriving every stream from one root `SeedSequence.spawn()`.
6. **Separate physical entities from protocol logic.** SeQUeNCe separates nodes/components from protocols/rules. NetSquid separates components/models from protocols. QPV needs the same split so that the *same* channel geometry can host honest provers and different adversary strategies.
7. **Signal/await protocol style.** NetSquid's `yield await_port_input() | await_timer(t)` expresses "reply or time out" naturally. We adopt the *semantics* (composable AND/OR waits, timers, signals) in a declarative automaton DSL instead of Python generators, so participant behaviour stays inspectable and editable in a UI.
8. **Registries for pluggable formalisms and protocol variants.** This is the decorator-registry pattern in SeQUeNCe. We avoid its process-global formalism setting by making the backend a per-simulation constructor argument.
9. **Models as composable, parameterised objects.** NetSquid's delay, loss and noise models attached to channels map directly onto JSON channel specs.

## 4. Capabilities missing for a QPV workflow

None of the surveyed tools provide the following as first-class features. Some can be approximated with custom code.

1. **Explicit spacetime geometry.** Verifier, prover and adversary positions as coordinates, a claimed position, and channel delays *derived* from distances and propagation speed with the constraint delay ≥ distance/c. SeQUeNCe derives delay from fibre length, but nothing ties that length to physical placement or forbids super-luminal links.
2. **Verifier deadlines as first-class objects.** Each verifier's acceptance window is computed from the claimed position, and late or early replies are rejected with a reason.
3. **Adversary capability enforcement.** Capabilities to check:
   - pre-shared entanglement budget (number of ebits);
   - quantum memory size and coherence;
   - whether quantum communication between attackers is allowed (Allerstorfer et al. 2022 show it matters);
   - the ability to declare loss;
   - placement constraints, i.e. attackers not at the claimed position.

   Violations must be impossible by construction, not by convention.
4. **Local clocks with offset and drift.** Participants act on local time `t_local = (1+δ)·t + θ`. Verifier synchronisation error directly widens the attack window.
5. **Inspectable participant FSMs.** States, transitions and guards must be data, so that the UI can render them and traces can name the transition that fired. Today they are implicit in Python methods.
6. **Visual protocol design.** Node-editor composition of participants, channels and automata. A SeQUeNCe GUI exists (Kiefer 2025, arXiv:2501.09100 [meta]) but targets network topologies, not adversarial timing games.
7. **Trace-level causality validation.** An independent post-hoc checker should verify that every message's receive event lies in or on the future light cone of its send event, and that no information-dependent action precedes its causal inputs.
8. **Decision explanations.** For each round: accept or reject, plus *why*. Reasons include wrong bit, late by Δ fs, missing answer, loss declared, or inconsistent answers. For each experiment: acceptance rate with a confidence interval, compared against theoretical bounds such as cos²(π/8).
9. **Statistical experiment management.** Seed spawning, many independent repetitions, and Wilson intervals. NetSquid/SeQUeNCe users write this by hand.

## 5. Components integrable through supported interfaces

| Component | Use in `qpvsim` | Interface / licence note |
|---|---|---|
| **NumPy** (BSD-3) | Core of built-in density-matrix and state-vector backends | Direct dependency |
| **QuTiP 5** (BSD-3) | Optional `QuantumBackend` adapter (`Qobj` density matrices, Kraus channels); cross-validation of built-in backends in tests | Optional extra; heavy deps |
| **Qiskit Aer** (Apache-2.0) | Optional adapter for larger state-vector/MPS experiments | Circuit/shot model; adapter must apply ops incrementally and supply measurement randomness or reseed per op |
| **Stim** (Apache-2.0) | Optional stabilizer backend for Clifford-only protocols (QPV_BB84 and its standard attacks) at large scale | `TableauSimulator` supports incremental ops; its RNG must be seeded from our stream |
| **Cirq** (Apache-2.0) | Optional adapter / reference simulator | Same considerations as Aer |
| **SeQUeNCe** (BSD-3-style) | Licence would permit reuse with attribution. We reuse *ideas only*, as reference for detector and fibre models and for validation comparisons | Must keep the copyright notice if any code is copied (none planned). Heavy dependency set (jupyterlab, qutip, stim, gmpy2, …; Python ≥ 3.12) argues against depending on it |
| **NetSquid** | Not integrable. Proprietary, registration-gated, no redistribution. Could only ever be an *external, user-installed* optional adapter, and even that would need its licence terms checked | Do not vendor, bundle, or depend on it; do not copy documentation text |
| **FastAPI / Pydantic / Uvicorn** (MIT / MIT / BSD-3) | HTTP bridge and schema validation | Standard |
| **React, Vite, @xyflow/react** (MIT) | UI and node editor | Standard; React Flow core is MIT (Pro features separate) [prior] |

## 6. Components to implement independently

- **Discrete-event kernel**: integer fs time, `(time, priority, seq)` heap, lazy cancellation, a stop condition and an event trace recorder. This takes a few hundred lines and is fully testable.
- **Spacetime and geometry layer**: positions in 1D/2D/3D, straight-line propagation at c/n, channel delay derivation, and light-cone checks.
- **Clock model**: per-participant offset and drift, and conversion between global and local time.
- **QuantumBackend interface plus two NumPy backends**:
  - density matrix with Kraus channels (exact, ≲10–12 qubits);
  - state vector with Monte-Carlo trajectories for noise (more qubits, sampled).

  Both include merge-on-entangle, split-on-measure, lazy idle noise, and a caller-supplied measurement sample.
- **Protocol/automaton DSL**: a JSON schema of states, transitions, guards, actions, timers and composable waits, plus a **sandboxed expression language**. Use a whitelisted AST evaluator. No `eval`, and no attribute access to arbitrary objects.
- **Adversary capability model**: declarative capabilities checked at action time (entanglement budget, memory, comms type, loss declaration, placement).
- **Verifier decision engine** with explanations, and theoretical reference bounds for known protocols.
- **Experiment runner**: `SeedSequence.spawn`, parallel independent repetitions (process pool), Wilson score intervals, and result persistence.
- **Trace causality validator**: independent of the engine, so it can catch engine bugs.
- **QPV protocol library** (as DSL documents): QPV_BB84, QPV_BB84^f, honest prover, unentangled Breidbart attack, one-EPR teleportation attack, and loss-declaration attack.

## 7. Proposed architecture and technology stack

### 7.1 Decided design

> **Implementation note (added after the build).** This subsection records the design as
> proposed before implementation. What was built is described in
> [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md). Deviations:
> - The modules are `kernel`, `quantum`, `protocol` (DSL, expressions, capabilities, project
>   format), `engine`, `decision`, `invariants`, `experiments`, `session`, `console` and `server`.
>   There are no separate `geometry`, `dsl`, `adversary` or `trace` packages.
> - Validation is hand-written (`protocol/project.py`, `protocol/automaton.py`) rather than
>   Pydantic-based, so that error messages can name domain concepts (unknown port, unreachable
>   state, superluminal link).
> - Composite waits are `all`-of-tags receive triggers. `any`-waits are expressed as several
>   transitions leaving the same state.
> - The rounding rule proposed here (ceiling for propagation delays) **was adopted**. User-given
>   times are rounded half-to-even.
> - The measurement random number is drawn inside the backend from its own seeded stream,
>   rather than passed in by the caller.

**Python ≥ 3.11 package `qpvsim`:**

- `qpvsim.kernel`: `Simulator` with `now_fs: int`. It has a `heapq` of `(time_fs, priority, seq, event)` tuples, where `seq` is a global monotone counter and `priority` is a small int. Equal keys are impossible, so ordering is total and deterministic. Cancellation uses tombstones. All times are integers in femtoseconds, and conversions are exact (`1 ns = 10**6 fs`). Floats are allowed only for physical parameters, and are converted to integers with an explicit, documented rounding rule (ceil for propagation delays, so that rounding never makes a signal faster than light).
- `qpvsim.geometry`: positions, `delay_fs(a, b, n)` = ⌈|a−b|·n / c⌉, and light-cone predicates.
- `qpvsim.quantum`: a `QuantumBackend` protocol with `new_qubits`, `apply(op, qubits)`, `apply_channel(kraus, qubits)`, `measure(qubits, basis, u: float)`, `discard`, `reduced_state`, `fidelity` and `idle(qubits, dt_fs, model)`. It ships `DensityMatrixBackend` and `StateVectorBackend`, the latter with a trajectory option. Subsystems are merged on demand and split on measurement.
- `qpvsim.dsl`: a JSON protocol and automaton schema validated by Pydantic. Participants are FSMs whose transitions are triggered by message arrival, timers, or composite waits (`all`/`any`). Actions include send, measure, apply-gate and decide. The expression language is sandboxed, with arithmetic, boolean logic, bit operations, comparisons and whitelisted functions only.
- `qpvsim.adversary`: a capability set attached to non-honest participants. The engine checks it on every privileged action and rejects with a typed error.
- `qpvsim.experiment`: a runner that spawns `numpy.random.SeedSequence` children per repetition and per entity stream. It aggregates accept rates with **Wilson score intervals**, (p̂ + z²/2n ± z√(p̂(1−p̂)/n + z²/4n²)) / (1 + z²/n), and records full traces for sampled runs.
- `qpvsim.trace`: an append-only event trace, a causality validator, and explanation records.

**FastAPI bridge**: REST endpoints to validate a DSL document, run a single trace, launch experiments, and fetch results. Pydantic models are shared with the DSL. A single process is enough for the MVP, with background tasks for experiments.

**UI**: React + TypeScript + Vite + `@xyflow/react`. Participants and channels are nodes and edges on a spatial canvas. Each participant has an automaton editor. Traces are shown in a spacetime (x–t) diagram with light cones and deadlines, alongside an experiment dashboard.

### 7.2 Stack trade-offs

| Decision | Option | Pros | Cons | Verdict |
|---|---|---|---|---|
| Kernel language | **Python** | Fastest to build and audit; NumPy/QuTiP/Stim ecosystem; matches SeQUeNCe/NetSquid user base; arbitrary-precision int time | Slower per event (≈µs-scale overhead) | **Chosen.** QPV rounds involve few events and qubits; throughput comes from parallel repetitions |
|  | Rust / C++ | 10–100× event throughput; strong typing | Slower iteration; bindings for quantum libs; int64 fs overflows at ≈2.56 h (needs i128) | Possible later for the kernel hot loop only |
|  | TypeScript-only (in browser) | Zero install; live interactivity | Weak numerics (no mature complex linear algebra); `number` loses integer precision above 2⁵³ fs ≈ 9 s of simulated time (BigInt is slow); duplicates science code | Rejected for the engine; fine for UI-side previews |
| UI shell | **Browser-served (FastAPI + Vite build)** | No native packaging; works locally or remote; simple CI | Requires a running Python server | **Chosen** |
|  | Electron | Single desktop app | Large bundles; still needs a bundled Python | Rejected for MVP |
|  | Tauri | Small binaries | Rust toolchain + Python sidecar complexity | Rejected for MVP |
| Node editor | **@xyflow/react (React Flow)** | Mature, MIT, custom nodes and edges, good docs | Generic graph semantics, so the spatial and time axes need custom layers | **Chosen** |
|  | Custom canvas (SVG/Canvas/WebGL) | Full control of spacetime rendering | Large effort for selection, zoom, edge routing and accessibility | Use only for the spacetime diagram view |

## 8. Known constraints

**Scientific**

- **No relativistic dynamics beyond the light-speed bound.** The model is flat Minkowski spacetime in a single inertial frame, with straight-line propagation at c/n. There is no GR, no gravitational time dilation, no moving participants (velocity-dependent effects), no Sagnac effect, and no atmospheric refraction or curvature. Real deployments would need these corrections at ns precision.
- **Idealised propagation.** Fibre routes are not straight lines. The model has no dispersion and no timing jitter unless modelled explicitly, and detector jitter or time resolution must be added by hand.
- **Security is not proved by simulation.** A simulation evaluates *specified* strategies. It cannot show that no better attack exists. Theoretical bounds (for example cos²(π/8) for unentangled QPV_BB84 attackers) should be shown as reference lines, not as derived results. The general Buhrman et al. attack and port-based or garden-hose attacks need entanglement that grows exponentially or linearly, so only small instances can be simulated.
- **Physical-model fidelity.** Loss, noise and detector models are phenomenological (Kraus channels, Bernoulli loss, Poisson dark counts). Multi-photon emissions, decoy states and continuous-variable QPV need Fock-space modelling. That is out of scope at first, and SeQUeNCe's `fock_density` manager shows the cost.

**Computational**

- **Exponential state size.** A density matrix on n qubits takes 16·4ⁿ bytes in complex128: 268 MB at n=12 and 1.07 GB at n=13. Gate application with full unitaries scales up to O(8ⁿ). The practical limit is about 10–12 qubits per merged subsystem. State vectors reach about 25–28 qubits (512 MB at n=25), with trajectories needed for noise. Stabilizer simulation scales polynomially but only for Clifford circuits with Pauli noise.
- **Python event overhead.** Throughput is roughly 10⁵–10⁶ events/s per core [prior estimate]. This is mitigated by embarrassingly parallel repetitions.
- **Statistics.** Distinguishing acceptance rates near 0.854 from 1.0 is easy. Resolving 0.854 against 0.85 at 95% confidence needs about 10⁴–10⁵ rounds, so the runner must be efficient and report intervals.

**Licensing**

- NetSquid cannot be bundled or required. Even mirroring its API names in a way that reproduces its documentation is undesirable.
- SeQUeNCe's BSD-3-style licence permits reuse with notice retention. We copy no code.
- QuTiP is BSD-3. Stim, Qiskit Aer and Cirq are Apache-2.0, whose NOTICE obligations apply only if we redistribute them. All optional backends stay optional extras.

**Performance and engineering**

- Determinism requires a single-threaded kernel per run, ordered dict and set iteration (no iteration over `set` of objects), and RNG draws ordered by event order.
- Parallelism is across runs only.
- The sandboxed DSL must bound computation (expression depth, loop-free design) to prevent denial of service through the HTTP bridge.

## 9. QPV literature summary (supporting Sections 4 and 8)

- **Classical impossibility.** Chandran, Goyal, Moriarty and Ostrovsky (CRYPTO 2009) show that colluding adversaries placed between the verifiers can copy classical messages and jointly simulate an honest prover. Classical PV is therefore impossible without extra assumptions such as bounded retrieval [prior].
- **Early quantum schemes.** Malaney (PRA 81, 042319, 2010) proposed entanglement-based location verification [meta]. Kent, Munro and Spiller ("quantum tagging", PRA 84, 012326, 2011) described several schemes, showed teleportation attacks on them, and noted a 2006 patent [meta][paper-abstract]. Chandran et al. (arXiv:1005.1750) was superseded by Buhrman et al. [meta].
- **Entanglement attacks.** Lau and Lo (PRA 83, 012322, 2011 [journal ref prior]; arXiv:1009.2256) broke the existing protocols with teleportation and secret-sharing attacks [meta]. Buhrman, Chandran, Fehr, Gelles, Goyal, Ostrovsky and Schaffner (SIAM J. Comput. 43(1):150–178, 2014 [journal ref prior]; arXiv:1009.2490) gave a **general attack**. Attackers sharing enough entanglement can perform any unitary using local operations and one round of classical communication (via Vaidman-style instantaneous non-local computation, with exponential entanglement), so no QPV scheme of a general form is secure against them. The paper also proves security against unentangled attackers [paper-abstract].
- **QPV_BB84** [prior; standard formulation].
  - Protocol, in 1D: V₀ sends H^θ|x⟩ and V₁ sends θ, timed to arrive together at the claimed position P. The prover measures in basis θ and sends x to both verifiers, who check correctness and timing.
  - **One-EPR teleportation attack** (Kent–Munro–Spiller; Lau–Lo; Buhrman et al.): attacker A, near V₀, teleports the qubit to B using one shared EPR pair and broadcasts the Pauli correction bits (a, b). B, near V₁, measures his EPR half in basis θ and broadcasts θ and the outcome. Each attacker can then correct the outcome (flip by a if θ=0, by b if θ=1) and answers in time with success probability 1.
  - **Unentangled attackers**: Tomamichel, Fehr, Kaniewski and Wehner (NJP 15, 103002, 2013; arXiv:1210.4359) bound the monogamy-of-entanglement game. The optimal success probability is cos²(π/8) = ½ + 1/(2√2) ≈ 0.8536, it is achieved without entanglement (measuring in the Breidbart basis, midway between Z and X), and it is tight under parallel repetition [paper-abstract; the numerical value and Breidbart strategy are prior].
- **Loss.** QPV_BB84 is insecure if provers may declare loss. Attacker A guesses θ', measures, and forwards (θ', outcome). B forwards the true θ. Both answer only when θ' = θ and otherwise claim "loss". All answered rounds are correct at a 50% response rate, so any protocol that tolerates ≥50% loss is broken [prior; discussed in Qi & Siopsis, PRA 91, 042337, 2015, arXiv:1502.02020, and motivated in Allerstorfer et al. 2021].
- **Newer protocols.**
  - Bluhm, Christandl and Speelman (Nat. Phys. 18, 623–626, 2022; arXiv:2104.06301) send a single qubit plus n classical bits, with a basis given by f(x, y). The entanglement needed to attack grows with n, so the protocol is noise-robust. In QPV_f the quantum state may travel slowly while only the classical inputs need light-speed timing ("slow quantum, fast classical") [meta; slow/fast framing prior].
  - Allerstorfer, Buhrman, Speelman and Verduyn Lunel (arXiv:2106.12911, 2021) propose the fully loss-tolerant QPV_SWAP [meta]. A 2022 paper by the same authors (arXiv:2208.04341) studies quantum communication and loss in attacks [meta].
  - Allerstorfer, Bluhm, Buhrman, Christandl, Escolà-Farràs, Speelman and Verduyn Lunel (PRL 135, 260801, 2025; arXiv:2312.12614) make QPV_BB84^f secure against arbitrary *transmission* loss through photon presence detection, a small prover delay and a commitment step [meta].

## 10. References

Verification status: [meta] means checked against arXiv API or PyPI metadata in this session; [prior] means not re-verified.

1. X. Wu, A. Kolar, J. Chung, D. Jin, T. Zhong, R. Kettimuthu, M. Suchara. "SeQUeNCe: A Customizable Discrete-Event Simulator of Quantum Networks." *Quantum Sci. Technol.* 6(4), 045027 (2021). arXiv:2009.12000. [meta; article number prior]
2. SeQUeNCe 1.3.1 source, PyPI package `sequence`, © UChicago Argonne, LLC, BSD-3-style licence. https://github.com/sequence-toolbox/SeQUeNCe [src]
3. A. Welch, M. Kiran. "A Short Scalability Study on the SeQUeNCe Parallel Quantum Network Simulator." arXiv:2503.09776 (2025). [meta]
4. A. Kiefer. "SeQUeNCe GUI: An Extensible User Interface for Discrete Event Quantum Network Simulations." arXiv:2501.09100 (2025). [meta]
5. T. Coopmans, R. Knegjens, A. Dahlberg, D. Maier, L. Nijsten, J. de Oliveira Filho, M. Papendrecht, J. Rabbie, F. Rozpędek, M. Skrzypczyk, L. Wubben, W. de Jong, D. Podareanu, A. Torres-Knoop, D. Elkouss, S. Wehner. "NetSquid, a NETwork Simulator for QUantum Information using Discrete events." *Commun. Phys.* 4, 164 (2021). arXiv:2010.12535. [meta, paper read]
6. S. DiAdamo, J. Nötzel, B. Zanger, M. M. Beşe. "QuNetSim: A Software Framework for Quantum Networks." *IEEE Trans. Quantum Eng.* (2021). arXiv:2003.06397. [meta]
7. A. Dahlberg, S. Wehner. "SimulaQron — a simulator for developing quantum internet software." *Quantum Sci. Technol.* 4, 015001 (2019). arXiv:1712.08032. [meta]
8. A. Dahlberg, B. van der Vecht, C. Delle Donne, M. Skrzypczyk, I. te Raa, W. Kozlowski, S. Wehner. "NetQASM — A low-level instruction set architecture for hybrid quantum-classical programs in a quantum internet." arXiv:2111.09823. [meta]
9. R. Satoh, M. Hajdušek, N. Benchasattabuse, S. Nagayama, K. Teramoto, T. Matsuo, S. A. Metwalli, T. Satoh, S. Suzuki, R. Van Meter. "QuISP: a Quantum Internet Simulation Package." *2022 IEEE QCE*, pp. 353–364. arXiv:2112.07093. [meta]
10. C. Gidney. "Stim: a fast stabilizer circuit simulator." *Quantum* 5, 497 (2021). arXiv:2103.02202. [meta]
11. N. Lambert et al. "QuTiP 5: The Quantum Toolbox in Python." *Physics Reports* 1153, 1–62 (2026). arXiv:2412.04705. [meta]
12. Qiskit Aer (Apache-2.0) and Cirq (Apache-2.0), PyPI `qiskit-aer` 0.18.0 and `cirq-core` 1.7.0. [meta]
13. N. Chandran, V. Goyal, R. Moriarty, R. Ostrovsky. "Position Based Cryptography." *CRYPTO 2009*, LNCS 5677, pp. 391–407. [prior]
14. R. A. Malaney. "Location-dependent communications using quantum entanglement." *Phys. Rev. A* 81, 042319 (2010). arXiv:1003.0949. [meta] See also R. A. Malaney, "Quantum location verification in noisy channels," arXiv:1004.4689 (2010). [meta]
15. A. Kent, W. J. Munro, T. P. Spiller. "Quantum tagging: Authenticating location via quantum information and relativistic signaling constraints." *Phys. Rev. A* 84, 012326 (2011). arXiv:1008.2147. [meta]
16. H.-K. Lau, H.-K. Lo. "Insecurity of position-based quantum-cryptography protocols against entanglement attacks." *Phys. Rev. A* 83, 012322 (2011). arXiv:1009.2256. [title and arXiv meta; journal ref prior]
17. H. Buhrman, N. Chandran, S. Fehr, R. Gelles, V. Goyal, R. Ostrovsky, C. Schaffner. "Position-Based Quantum Cryptography: Impossibility and Constructions." *SIAM J. Comput.* 43(1), 150–178 (2014); *CRYPTO 2011*. arXiv:1009.2490. [title and arXiv meta; venues prior]
18. M. Tomamichel, S. Fehr, J. Kaniewski, S. Wehner. "A monogamy-of-entanglement game with applications to device-independent quantum cryptography." *New J. Phys.* 15, 103002 (2013). arXiv:1210.4359. [meta]
19. F. Speelman. "Position-Based Quantum Cryptography and the Garden-Hose Game." arXiv:1210.4353 (2012). [meta]
20. B. Qi, G. Siopsis. "Loss-tolerant position-based quantum cryptography." *Phys. Rev. A* 91, 042337 (2015). arXiv:1502.02020. [meta]
21. A. Bluhm, M. Christandl, F. Speelman. "A single-qubit position verification protocol that is secure against multi-qubit attacks." *Nat. Phys.* 18, 623–626 (2022). arXiv:2104.06301. [meta]
22. R. Allerstorfer, H. Buhrman, F. Speelman, P. Verduyn Lunel. "Towards practical and error-robust quantum position verification." arXiv:2106.12911 (2021). [meta]
23. R. Allerstorfer, H. Buhrman, F. Speelman, P. Verduyn Lunel. "On the Role of Quantum Communication and Loss in Attacks on Quantum Position Verification." arXiv:2208.04341 (2022). [meta]
24. R. Allerstorfer, A. Bluhm, H. Buhrman, M. Christandl, L. Escolà-Farràs, F. Speelman, P. Verduyn Lunel. "Making Existing Quantum Position Verification Protocols Secure Against Arbitrary Transmission Loss." *Phys. Rev. Lett.* 135, 260801 (2025). arXiv:2312.12614. [meta]
25. E. B. Wilson. "Probable inference, the law of succession, and statistical inference." *J. Amer. Statist. Assoc.* 22(158), 209–212 (1927). [prior]

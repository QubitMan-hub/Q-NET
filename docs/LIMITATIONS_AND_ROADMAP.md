# What the platform can and cannot establish

## Three kinds of statement

1. **Deterministic observations.** For a given project and seed, the engine reports exactly what happened in that run: which transitions fired, when, why, and what the verifiers decided. These are facts about the model, and they are reproducible bit for bit.
2. **Statistical estimates.** Experiments estimate probabilities, such as acceptance rates, from repeated independent runs. They are reported with sample sizes and 95% Wilson intervals. They are estimates for the modelled protocol, strategy and parameters.
3. **Analytical or formal guarantees.** These come from the literature or from independent proofs. The workbench cites them; for example, the cos²(π/8) bound for unentangled attacks on QPV_BB84 is from Tomamichel et al. 2013. It does not derive them. **No simulation result in this workbench is a security proof.** Passing the test suite shows that the engine is consistent with its own semantics, not that a protocol is secure.

## Known limitations

**Physics**
- Signals travel on straight lines at a fixed speed, c by default, or slower per link with optional fixed latency and jitter. There is no relativity beyond the finite signal speed, no media dispersion, and no routing geometry beyond an explicit length.
- Positions are fixed for the whole run; participants do not move.
- Quantum noise is limited to the channels listed in [QUANTUM_MODEL.md](QUANTUM_MODEL.md). There are no detector models (efficiency, dark counts, dead time), no multi-photon or Fock-space states, and gate durations are not modelled per gate.
- Clock offsets and drift are fixed parameters. No synchronisation protocol, and no clock noise, is simulated.

**Protocol and adversary model**
- One run is one protocol round. Multi-round protocols can be written as automata with loops, but the bundled verifiers decide after one round.
- Loss handling: a missing answer counts as a rejection. QPV_BB84 is attackable by provers allowed to claim loss, and loss-tolerant variants are not bundled.
- Adversary strategies are the automata provided. The simulator does not optimise or search over strategies, so observed attack success rates are **lower bounds** on what adversaries can achieve.
- Capability enforcement covers the listed operations and resources. It cannot restrict computational power beyond `min_processing_ns`. "Unrestricted" means unrestricted within this action set.
- Messages are addressed to ports, and a participant cannot learn another participant's state except through delivered messages. The engine itself (and the inspector) can see everything; this is a simulation, not a cryptographic implementation.

**Computation**
- Density matrices are exponential: practical up to about 10 entangled qubits per group. State vectors reach about 20 qubits, with noise sampled.
- The Python kernel costs about 0.2 ms per event. This is fine for QPV rounds; experiments scale with parallel workers.
- The server is single-user and has no authentication. It binds to localhost by default.

**In-browser build (GitHub Pages)**
- The engine runs in WebAssembly (Pyodide), roughly 2–5× slower than native Python, and experiments use a single process. Large sweeps are better run locally (`qpv experiment … --workers N`).
- The first visit downloads the Python runtime and NumPy from the jsDelivr CDN (about 15 MB). An offline copy needs the local install.
- Each browser tab has its own engine; nothing is stored on a server, so save projects with **Save**.

**UI**
- Snapshots are sent whole on each step. This is comfortable for traces of a few thousand records.
- The spacetime diagram projects positions onto the x axis. Two- and three-dimensional geometry is simulated correctly (distances are Euclidean), but it is drawn only along x.

## Roadmap

1. **Backends**: a stabiliser backend (Stim) for large Clifford circuits; an optional QuTiP or Qiskit Aer adapter behind `QuantumBackend`; Fock or photonic models for loss-tolerant QPV.
2. **Protocols**:
   - QPV_f and routing-based protocols (Bluhm, Christandl & Speelman);
   - loss-tolerant BB84 variants (Allerstorfer et al.);
   - multi-round protocols with sequential deadlines;
   - 2-D and 3-D verifier configurations with a 2-D spacetime view.
3. **Adversaries**: a library of strategies with parameterised entanglement budgets; strategy search (for example, SDP-optimal attacks for small instances) to report bounds alongside simulations.
4. **Experiments**: persistent result store, comparison dashboards across protocols, convergence diagnostics, and sensitivity analysis over clock drift and noise.
5. **Engine**: incremental snapshots and streaming (WebSocket) for very large traces; optional compiled hot loop.
6. **Packaging**: optional desktop wrapper (Tauri or Electron) around `qpv serve`; signed wheels with the prebuilt UI.
7. **Formal methods**: export of automata to a model checker (for example UPPAAL timed automata) to check timing properties exhaustively for small configurations.

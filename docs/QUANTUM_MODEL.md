# Quantum model

## What is simulated

The engine manipulates a **classical description of a simulated quantum state** held by a backend. Participants can only interact with qubits through actions: prepare, gate, measure, Bell-measure, send and discard. They cannot read amplitudes. The inspector shows reduced density matrices and Bloch vectors for inspection only, and it labels them as a simulation-only view. Nothing here models or controls a physical quantum device.

## Backend interface (`qpvsim/quantum/base.py`)

```python
class QuantumBackend:
    create(ket) -> qubit                       # fresh single-qubit pure state
    create_entangled(ket, n) -> (q1..qn)       # joint pure state (e.g. Bell pairs for resources)
    discard(q)                                 # remove (partial trace)
    apply_unitary(qubits, U)                   # first listed qubit = most significant factor
    apply_channel(qubits, kraus_ops)           # CPTP map
    measure(q, basis) -> 0|1                   # projective; basis columns are the basis vectors
    reduced_density(qubits) -> ndarray         # inspection only
    group_of(q) -> qubits sharing a joint state
```

Every backend publishes `BackendInfo`: its formalism, whether mixed states are exact, its group limit and notes. A backend must raise `UnsupportedOperation` rather than silently approximate. Randomness comes only from the backend's seeded `quantum` stream.

## Backends

| | `density_matrix` (default) | `state_vector` |
|---|---|---|
| State | joint density matrix per group of interacting qubits | joint state vector per group |
| Measurement | exact Born rule; post-measurement state; the measured qubit is split off | same |
| Noise channels | exact Kraus sum (mixed states) | **quantum trajectories**: Kraus operator *k* is chosen with probability ‖Kₖψ‖², then the state is renormalised |
| Discard of an entangled qubit | exact partial trace | measure in Z and drop the unobserved outcome |
| Cost per operation, n-qubit group | O(4ⁿ) memory and time; practical up to ~10 entangled qubits (default limit 12) | O(2ⁿ); default limit 24 |
| Exactness | exact for every supported operation | exact **in distribution**: averaged over runs, all statistics equal the density-matrix prediction. A single run is one trajectory, so its displayed states are pure. |

Groups merge when a multi-qubit operation touches separate groups, using a Kronecker product. They shrink when a qubit is measured or discarded. This is the strategy reported for NetSquid's shared quantum states and SeQUeNCe's quantum manager (REA §3). `tests/test_quantum.py` cross-checks the two backends: deterministic BB84 outcomes, Bell correlations, the teleportation identity, the Breidbart probability and agreement under noise.

## States, gates and bases

- **States**: `|0⟩ |1⟩ |+⟩ |−⟩ |+i⟩ |−i⟩`; BB84 states H^θ|x⟩; Bell states φ±, ψ±.
- **Gates**: I, X, Y, Z, H, S, S†, T, CNOT/CX, CZ, SWAP, RX(θ), RY(θ), RZ(θ).
- **Bases**:
  - Z (computational);
  - X (Hadamard);
  - Y;
  - `angle`(a), the real basis {cos a|0⟩ + sin a|1⟩, −sin a|0⟩ + cos a|1⟩}. The Breidbart basis is a = π/8.

## Noise models

| Where | Parameter | Channel |
|---|---|---|
| Quantum link | `noise.depolarizing` p | ρ → (1−p)ρ + p·I/2 |
| | `noise.dephasing` p | ρ → (1−p)ρ + pZρZ |
| | `noise.bitflip` p | ρ → (1−p)ρ + pXρX |
| | `noise.amplitude_damping` γ | standard amplitude damping |
| | `loss_prob`, `attenuation_db_per_km` | the photon is lost (no delivery) |
| Participant | `noise.gate_depolarizing` p | depolarising on each qubit after every gate (and the Bell-measurement circuit) |
| | `noise.measurement_flip` p | classical outcome flipped with probability p |
| | `noise.memory_t1_ns`, `memory_t2_ns` | applied lazily when a stored qubit is next used: amplitude damping γ = 1 − e^(−Δt/T1), then dephasing so that coherences decay as e^(−Δt/T2) overall (requires T2 ≤ 2T1) |
| Capability | `memory_ns` | a qubit held longer than this is fully depolarised (a resource limit, not physics) |
| Resource | `werner_p` on an EPR pair | one half is depolarised with p, producing a Werner state |

Lazy memory noise follows the "apply decoherence on next access" pattern used by NetSquid and SeQUeNCe. It is exact for the stated channel because nothing else acts on the qubit while it is stored, and channels on different qubits commute.

## Limitations

- These are the only noise processes, and they are idealised channels. There are no detector models (dark counts, efficiency, dead time), no multi-photon or Fock-space effects, and no time-dependent drifts except through the T1/T2 model.
- Exponential cost: density matrices are practical up to about 10 entangled qubits per group; state vectors go further, but noise is sampled.
- There is no stabiliser or Fock backend yet. The interface allows one: Stim or QuTiP could be wrapped behind `QuantumBackend` (see the roadmap).
- Gate durations are not modelled per gate. Processing time is a property of the transition (`duration_ns`) or the participant (`processing_ns`).

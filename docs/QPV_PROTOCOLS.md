# Reference protocols, attacks and results

All protocols and attacks below are **data**: automata and projects in `src/qpvsim/library.py`, exported to `src/qpvsim/examples/*.json`. The engine has no protocol-specific code. Literature facts are cited. The simulated numbers are Monte-Carlo observations of the *model* and do not independently establish any security claim.

## QPV_BB84 (one dimension, two verifiers)

**Sources.**
- Kent, Munro & Spiller, *Phys. Rev. A* 84, 012326 (2011), arXiv:1008.2147.
- Lau & Lo, *Phys. Rev. A* 83, 012322 (2011), arXiv:1009.2256.
- Buhrman, Chandran, Fehr, Gelles, Goyal, Ostrovsky & Schaffner, *SIAM J. Comput.* 43(1) (2014), arXiv:1009.2490.
- Tomamichel, Fehr, Kaniewski & Wehner, *New J. Phys.* 15, 103002 (2013), arXiv:1210.4359.

See also [REA_REPORT.md](REA_REPORT.md) §9.

**Model.**
- **Positions**: V0 at x = −3 m, V1 at x = +3 m, claimed position x = 0. Signals travel at c on straight lines.
- **Shared randomness**: the verifiers share random bits x and θ before the round (a `shared_random` resource).
- **Challenges**:
  - The emission time is computed from the geometry: local time `t_ref − d(V, claim)/c`, with `t_ref` = 20 ns.
  - V0 sends the qubit H^θ|x⟩ over a quantum link; V1 sends θ over a classical link.
  - Both arrive at the claim at exactly t = 20 ns (checked to the femtosecond in `test_honest_reference_trace_hand_calculated`).
- **Honest prover**: waits for both the qubit and θ (a two-tag receive trigger), measures in basis θ, and sends the outcome to both verifiers. Processing defaults to 0.2 ns.
- **Verifiers**: each arms a deadline timer at `t_ref + d(V, claim)/c + tolerance` (tolerance 0.5 ns), using its own clock. A verifier accepts iff an answer equal to x arrives by the deadline (inclusive). A wrong answer, or no answer by the deadline, is a rejection.
- **Decision**: all verifiers must accept.

### Scenarios and results

The measurements below were produced with the commands shown (engine 0.1.0). The CSVs are in [results/](results/).

| Scenario | Command | Acceptance (95% Wilson CI) | Reference value |
|---|---|---|---|
| Honest, ideal channel | `qpv experiment src/qpvsim/examples/qpv_bb84_honest.json --id noise_sweep` (p = 0) | 1.000 [0.990, 1.000], n = 400 | 1 |
| Honest, depolarising p = 0.05 / 0.1 / 0.2 / 0.4 | same sweep | 0.968 / 0.960 / 0.883 / 0.773 | 1 − p/2 = 0.975 / 0.95 / 0.90 / 0.80 (all inside the intervals) |
| Honest, prover processing 0 / 0.25 / 0.5 / 0.75 / 1.0 ns | `… --id processing_sweep` | 1, 1, 1, 0, 0 (n = 50 each) | accept iff processing ≤ tolerance (0.5 ns; inclusive deadline) |
| Dishonest prover at x = −1 m running the honest procedure | `qpv experiment src/qpvsim/examples/qpv_bb84_displaced_prover.json --runs 500 --seed 5` | 0.000 [0, 0.008]; V0 accepts every round, V1 times out | geometry: the answer reaches V1 6.67 ns late |
| Colluding adversaries without entanglement, Breidbart basis | `qpv experiment src/qpvsim/examples/qpv_bb84_collusion_unentangled.json --id strategies` | 0.8545 [0.8384, 0.8693], n = 2000 | cos²(π/8) ≈ 0.8536, optimal for unentangled attackers (Tomamichel et al. 2013) |
| … measuring in Z / X / a random basis | same sweep | 0.7545 / 0.7435 / 0.7495 | 3/4 |
| Colluding adversaries with one EPR pair (teleportation attack), processing 0 / 0.2 / 0.4 ns | `qpv experiment src/qpvsim/examples/qpv_bb84_teleportation_attack.json --id timing` | 1.000 [0.981, 1.000] each | 1 (Lau–Lo 2011; Buhrman et al. 2014) |
| … processing 0.6 / 0.8 ns per adversary | same sweep | 0.000 (every verifier times out) | the attack path accumulates the adversary's processing beyond the 0.5 ns tolerance |

**How the attacks work in the model.**

- **Geometry**: E0 sits at −1.5 m, between V0 and the claim, and E1 at +1.5 m. They have a classical link of their own. On a line, the path V1 → E1 → E0 → V0 has exactly the length of the honest path V1 → claim → V0. Collinear adversaries with zero processing therefore answer precisely at the honest light-cone time, give or take a few fs of per-hop ceiling rounding (`test_attack_arrival_equals_honest_light_cone_on_a_line`). This is why QPV tolerances must be small.
- **Unentangled (`no_entanglement` profile)**: E0 measures the qubit immediately, without knowing θ, and broadcasts the outcome; E1 forwards θ. Both answer with E0's outcome. Measuring in the Breidbart basis (π/8) is correct with probability cos²(π/8) for every BB84 state.
- **Teleportation (`bounded_entanglement` profile with an EPR resource)**:
  - E0 Bell-measures the intercepted qubit together with its EPR half and sends both outcomes (b0, b1).
  - E1, on receiving θ, measures its EPR half in basis θ and sends (θ, m).
  - Both then compute x = m ⊕ (b1 if θ = 0 else b0), which is correct with certainty.
  - Giving these strategies a weaker profile makes the engine stop them. `classical_only` halts E0 with a capability violation on its first measurement. Holding the EPR pair under `no_entanglement` is rejected by validation (see `tests/test_engine.py`).

**What these numbers mean.**
- They reproduce known facts about the *modelled* protocol, which is a self-consistency check of the engine.
- They do not prove that QPV_BB84 is secure or insecure in any physical deployment.
- The unentangled strategies shipped here are not all possible strategies. The 0.854 value is a literature bound, and the simulation only shows that one strategy reaches it.

## Classical position verification (baseline)

**Source**: Chandran, Goyal, Moriarty & Ostrovsky, *Position Based Cryptography*, CRYPTO 2009.

The verifiers send random bits x0 and x1, timed to meet at the claim, and the prover answers x0 ⊕ x1. With two colluding adversaries that copy and forward (`classical_only` profile), the claim is accepted in every round (500/500, `docs/results/cpv_collusion.csv`): classical PV is insecure against colluding adversaries. The honest prover is also accepted 500/500.

## Writing your own

Start from an example (Examples menu, or `load example …` in the console), or click **New**. Then:

1. Drag in participants.
2. Pick strategies from the automaton library, or draw your own states and transitions.
3. Wire ports with quantum or classical channels.
4. Add pre-shared resources.
5. Set the claim and the decision rule.

The validator lists everything that is inconsistent. Document the protocol's trust assumptions and limitations in the project's `meta.assumptions` and `meta.limitations`. They are shown in the UI and copied into every experiment's provenance.

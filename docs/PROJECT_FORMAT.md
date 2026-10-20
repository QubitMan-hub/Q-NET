# Project file format (version 1)

A project (`*.qpv.json`) fully determines a simulation. A project with the same seed reproduces the same trace. `normalize()` fills the defaults shown below, so saved files are explicit.

```jsonc
{
  "format": "qpvsim-project",
  "version": 1,
  "meta": {
    "name": "QPV_BB84 — honest prover",
    "description": "…",
    "protocol": {"name": "QPV_BB84", "version": "1.0", "references": ["Kent, Munro, Spiller, PRA 84 012326 (2011)", "…"]},
    "assumptions": ["…"],                  // shown in the UI and recorded in experiment provenance
    "limitations": ["…"]
  },
  "physics":    {"signal_speed_mps": 299792458, "allow_superluminal": false},
  "simulation": {"seed": 7, "backend": "density_matrix", "max_time_ns": 1000, "max_events": 100000,
                 "stop_when": "verifiers_decided", "priorities": {}},
  "claim": {"prover": "P", "position": [0.0, 0.0]},        // prover may be null (pure attack scenario)
  "participants": [{
    "id": "V0", "role": "verifier", "label": "Verifier V0",
    "position": [-3.0, 0.0],                 // metres (1–3 coordinates)
    "automaton": "qpv_bb84_verifier_quantum", "params": {"t_ref_ns": 20.0, "tolerance_ns": 0.5},
    "processing_ns": 0, "start_ns": 0,
    "clock": {"offset_ns": 0, "drift_ppm": 0},
    "capabilities": "verifier",             // profile name or {"profile": …, overrides}
    "noise": {"measurement_flip": 0.0, "gate_depolarizing": 0.0, "memory_t1_ns": null, "memory_t2_ns": null},
    "group": null,                          // coalition label (informational)
    "ui": {"x": 40, "y": 220}               // editor layout only; never affects execution
  }],
  "links": [{
    "id": "q0", "kind": "quantum",
    "a": {"node": "V0", "port": "prover"}, "b": {"node": "P", "port": "left"},
    "directed": false, "length_m": null, "speed_mps": null, "latency_ns": 0, "jitter_ns": 0,
    "loss_prob": 0, "attenuation_db_per_km": 0,
    "noise": {"depolarizing": 0.0, "dephasing": 0.0, "bitflip": 0.0, "amplitude_damping": 0.0}
  }],
  "resources": [ /* shared_random | epr, see PROTOCOL_DSL.md */ ],
  "automata": { "qpv_bb84_verifier_quantum": { /* see PROTOCOL_DSL.md */ } },
  "verification": {"rule": "all", "verifiers": ["V0", "V1"]},   // all | any | k_of_n (+ "k")
  "experiments": [{
    "id": "noise_sweep", "name": "…", "runs": 400, "seed": 11, "workers": 1,
    "sweep": [{"path": "links.q0.noise.depolarizing", "values": [0.0, 0.1, 0.2]}],
    "patch": {"simulation.backend": "state_vector"}
  }]
}
```

Notes:

- **Automata are embedded**, so a project is self-contained. Choosing a library strategy in the editor copies it into the project.
- **Versioning**: `version` is checked on load. Newer versions are rejected with a clear error, and `protocol/project.py::migrate` is the hook for upgrading older ones.
- **Paths** (used by experiment sweeps and patches, the console's `set`/`get`, and `qpvsim.set_path`) are dot-separated. List items can be addressed by their `id` or by index: `participants.E0.params.policy`, `links[q0].noise.depolarizing`, `participants.0.position`.
- **Traces** are exported separately, by `export trace <file>`, `qpv run --trace` or `GET /api/sim/export`. They use the format `qpvsim-trace` v1 and contain the project, provenance, every trace record, messages, scheduler events, final participant states, the decision and the invariant results.
- **Experiment results** contain raw per-run records (seed, outcome, per-verifier verdicts and observations, counters) kept separately from the derived per-point statistics. The statistics can be recomputed from the raw records with `experiments.summarize_point`.

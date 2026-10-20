# QPV Workbench

An event-driven, quantum-capable, adversary-aware simulation workbench for **Quantum Position Verification**. You design protocols visually, run them in a deterministic engine with exact femtosecond timing, inspect every transition and timestamp, attack them with capability-limited colluding adversaries, and run reproducible experiments.

```bash
pip install -e ".[server,test]"
qpv serve            # open http://127.0.0.1:8765
```

**All documentation is in [`docs/`](docs/README.md)**: the start guide, architecture, semantics, protocol language, quantum model, reference protocols with results, API and console reference, the validation report, limitations and roadmap, and the research report.

Simulation results describe the modelled protocol only; they are not security proofs.

Licence: Apache-2.0.

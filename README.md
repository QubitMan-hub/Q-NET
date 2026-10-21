# QPV Workbench

An event-driven, quantum-capable simulation workbench for Quantum Position Verification: design protocols as state machines, run them with exact femtosecond timing, attack them with capability-limited adversaries, and run repeatable experiments. Simulation results describe the modelled protocol only; they are not security proofs.

Use it in the browser: <https://qubitman-hub.github.io/Q-NET/>

Install and run locally:

```bash
pip install -e ".[server,test]"
qpv serve              # open http://127.0.0.1:8765
qpv run qpv_bb84_honest   # headless run of a bundled example
```

Test:

```bash
python -m pytest
```

Licence: Apache-2.0.

# QPV Workbench

An event-driven, quantum-capable simulation workbench for Quantum Position Verification: design protocols as state machines, run them with exact femtosecond timing, attack them with capability-limited adversaries, and run repeatable experiments. Simulation results describe the modelled protocol only; they are not security proofs.

Use it in the browser, nothing to install: <https://qubitman-hub.github.io/Q-NET/>

## Run it on your computer

```bash
./run.sh                       # installs, builds the interface once, opens the workbench in your browser
./run.sh e5_two_at_claim       # ...or go straight to one scenario
```

`run.sh` needs Python 3.10+ and, for the one-time interface build, Node.js 18+. The same by hand:

```bash
pip install -e ".[server]"
cd frontend && npm install && npm run build && cd ..
qpv serve --open
```

## Scenarios

The workbench ships a gallery of 35 ready-made scenarios: honest provers, cheaters with and without entanglement,
noise, lost photons, clock errors, fibre, someone in the middle, leaked secrets. In the workbench click
**Scenarios**; from the command line:

```bash
qpv scenarios                          # list them
qpv scenario c2_breidbart --rounds 500 # run one many times and print the pass rate
qpv serve --open --scenario d1_teleport
```

A link like `https://qubitman-hub.github.io/Q-NET/#scenario=d1_teleport` opens a scenario directly.
Every scenario is a *recipe*: a standard setup plus a list of twists. Click **Edit** on any scenario to change it in
the builder, or write your own recipe file and run it with `qpv scenario my-recipe.json`.

Other commands: `qpv run qpv_bb84_honest` (one headless run of a bundled example), `qpv console`, `qpv --help`.

Test:

```bash
python -m pytest
```

Licence: Apache-2.0.

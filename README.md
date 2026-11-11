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

The workbench ships a gallery of 62 ready-made scenarios: honest provers, cheaters with and without entanglement,
noise, lost photons, weak lasers, false clicks, a walking prover, clock errors, fibre, someone in the middle, keyed answers,
leaked secrets, and a four-basis protocol that stands up to selective 'no photon' answers. In the workbench click
**Scenarios**; from the command line:

```bash
qpv scenarios                          # list them
qpv scenario c2_breidbart --rounds 500 # run one many times and print the pass rate
qpv serve --open --scenario d1_teleport
```

A link like `https://qubitman-hub.github.io/Q-NET/#scenario=d1_teleport` opens a scenario directly.
Every scenario is a *recipe*: a standard setup plus a list of twists. Click **Edit** on any scenario to change it in
the builder, or write your own recipe file and run it with `qpv scenario my-recipe.json`.

Any scenario, including one you built yourself, has a shareable link: **Copy link** puts the whole recipe in the
address (`#recipe=...`).

### Showing and checking results

- **Present**: in the Scenarios dialog, pick all scenarios or one section and press *Present*. Each scenario fills the
  screen, runs one round, plays 100 rounds and shows the measured pass rate against the expected one. Arrow keys move
  between scenarios and Esc leaves. A link like `#present=all` or `#present=b8_88_rounds,f2_four_bases_cheaters` opens a
  presentation directly.
- **Report**: *Report...* in the Scenarios dialog runs every scenario and saves the table as Markdown, CSV or a printable
  page (print it to PDF). From the command line: `qpv report --rounds 500 --out report.html`.
- **Chart**: *Chart...* on a scenario's card draws its pass rate as one setting changes (noise, loss, photons per pulse,
  false clicks, distance, entanglement noise and more), with the theory curve where a simple formula exists.

### Judging over many rounds

One simulation run is one protocol round. A *Judge over many rounds* twist sets the real verdict: n rounds, the fraction
that must be answered and the fraction of answers that must be right. The workbench gives the exact chance of passing
from the measured per-round rates. `qpv rounds --honest 0.98 --cheat 0.854` finds the fewest rounds that separate an
honest prover from a cheater.

### More protocols, real sites, faulty verifiers

- **Protocols** (pick one in the builder): BB84; a *qudit* of 2, 4 or 8 levels in d + 1 mutually unbiased bases
  (d = 2 is the six-state protocol); *QPV_BB84^f*, where the basis is f(x, y) of two n-bit strings, with a budget
  attack that needs one EPR pair per possible x; and *classical* position verification as a baseline that colluders
  always beat. **Compare protocols...** in the Scenarios dialog (or `qpv protocols`) runs every protocol against
  guessing, unentangled and entangled cheaters side by side.
- **Real sites**: verifiers at real coordinates (an optical table, a campus with free-space links, a city over street
  fibre) with detector efficiency, false clicks and jitter. The scenario card shows the location precision and the
  photon loss; over city fibre an impostor kilometres away still passes.
- **Faulty verifiers**: a verifier can be offline, accept everything or reject everything, and the rule can require
  k of n verifiers. Gallery section G shows the trade-off.

### New twists

- *Answers must carry a secret key*: the genuine prover shares a fresh key with the verifiers; an impostor at the right
  spot must guess it.
- *Weak laser source*: a random (Poisson) number of photons per pulse. Photon-splitting cheaters wait for two-photon pulses.
- *Detector false clicks*: a spurious click beside the real one turns the answer into a random bit.
- *The prover moves between rounds*: it walks at a set speed; the verifiers follow its path fully, partly or not at all.
- *Measurement bases* (setup): more than two bases make selective 'no photon' answers far less useful to cheaters.

Other commands: `qpv run qpv_bb84_honest` (one headless run of a bundled example), `qpv console`, `qpv --help`.

Test:

```bash
python -m pytest
```

Licence: Apache-2.0.

# qpv

Quantum position verification on top of the generic engine.

| File | What it does |
|---|---|
| `scenario.py` | Builds ready-to-run QPV setups in 1D, 2D or 3D: verifiers, an honest or displaced prover, or attackers, with links. Also switches the attack and auto-wires. |
| `automata.py` | The QPV_BB84^f protocol and its attacks (unentangled, teleportation chain, guessing, photon splitting, selective "no photon") as state machines, plus a multi-photon source. |
| `recipe.py` | Scenario recipes: a base setup plus generic twists (move a party, change links, clock offsets, someone in the middle, a second party at the claim, multi-photon pulses, leaks, …) and reusable single-party strategies. `schema()` describes them all for the interface; `compose()` builds the project. |
| `demos.json` | The scenario gallery as data: each case from the "QPV-BB84 under stress" write-up as a recipe, with what to watch and the expected pass rate (checked by the tests). |
| `timing.py` | When each verifier really sends and judges, and the slack an honest prover has. |
| `lightcone.py` | Where could a lone attacker stand and still answer every verifier in time? |
| `geometry.py` | Dimension of a setup and whether the claim lies inside the verifiers' hull. |
| `presets.py` | One-click sweeps (distance, noise, attack, …) and theoretical acceptance rates. |
| `cache.py` | Small cache for analyses that depend only on the setup. |

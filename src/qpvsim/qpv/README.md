# qpv

Quantum position verification on top of the generic engine.

| File | What it does |
|---|---|
| `scenario.py` | Builds ready-to-run QPV setups in 1D, 2D or 3D: verifiers, an honest or displaced prover, or attackers, with links. Also switches the attack and auto-wires. |
| `automata.py` | The QPV_BB84^f protocol and its attacks (unentangled, teleportation chain, guessing) as state machines. |
| `timing.py` | When each verifier really sends and judges, and the slack an honest prover has. |
| `lightcone.py` | Where could a lone attacker stand and still answer every verifier in time? |
| `geometry.py` | Dimension of a setup and whether the claim lies inside the verifiers' hull. |
| `presets.py` | One-click sweeps (distance, noise, attack, …) and theoretical acceptance rates. |
| `cache.py` | Small cache for analyses that depend only on the setup. |

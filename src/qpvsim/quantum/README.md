# quantum

Two interchangeable quantum backends behind one interface; tests cross-check them.

| File | What it does |
|---|---|
| `base.py` | The backend interface: allocate qubits, apply gates and noise, measure. |
| `density.py` | Exact density-matrix simulation. |
| `statevector.py` | State-vector simulation with sampled noise; faster for larger groups. |

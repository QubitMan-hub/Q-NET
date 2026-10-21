# kernel

| File | What it does |
|---|---|
| `scheduler.py` | Deterministic discrete-event queue: events run in time order, ties broken by priority and insertion order. |
| `clock.py` | Each participant's local clock, with offset and drift from global time. |

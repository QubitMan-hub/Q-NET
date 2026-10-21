# protocol

How a protocol is written down.

| File | What it does |
|---|---|
| `project.py` | The versioned project JSON: defaults, validation, path editing. |
| `automaton.py` | State machines for participants: states, transitions, triggers (start, receive, timer) and actions. |
| `expr.py` | The small, sandboxed expression language used in guards and action arguments. |
| `capabilities.py` | What each participant may do (prepare, measure, hold entanglement), checked on every action. |

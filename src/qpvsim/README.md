# qpvsim: the engine

An event-driven, quantum-capable simulator of position-verification protocols. The engine is the single source
of truth; the UI, console and CLI only read and edit it.

| Module | What it does |
|---|---|
| `engine.py` | Runs a project: schedules events, moves messages at light speed, executes automata and quantum operations. |
| `session.py` | One editable project plus its current simulation, with undoable edits. |
| `decision.py` | Combines verifier verdicts into accept or reject and explains each one in a sentence. |
| `experiments.py` | Repeated runs, parameter sweeps and confidence intervals. |
| `invariants.py` | Consistency checks that a finished trace obeys the documented engine semantics. |
| `console.py` | The text command language used by the console and `qpv console`. |
| `webapi.py` | The API dispatcher shared by the HTTP server and the in-browser build. |
| `library.py` | Bundled example projects and the automaton library. |
| `timeunits.py` | The time model: integer femtoseconds and round-up light delays. |
| `cli.py` | The `qpv` command: `serve`, `run`, `console`, `experiment`, `validate`, `examples`. |

| Folder | What it holds |
|---|---|
| `kernel/` | Discrete-event scheduler and local clocks. |
| `protocol/` | Project format, state-machine DSL, expressions and capabilities. |
| `quantum/` | Quantum backends (density matrix, state vector). |
| `qpv/` | QPV-specific scenarios, attacks, timing and light-cone analysis. |
| `server/` | FastAPI server and the built UI. |
| `examples/` | Example projects as JSON. |

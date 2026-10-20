# Programmatic API, console and HTTP endpoints

## Python

```python
import qpvsim
from qpvsim import Simulation, example, load_project, save_project, validate_project, set_path, check_trace
from qpvsim.session import Session
from qpvsim.experiments import run_experiment, run_once, results_to_csv
from qpvsim import timeunits as tu
```

| Call | Purpose |
|---|---|
| `Simulation(project, seed=None)` | compile and validate (raises `ProjectError` listing the errors) |
| `sim.step()` | execute exactly one event; returns it, or `None` when stopped |
| `sim.run(until_fs=None, max_steps=None)` | run to the end, to a time (the clock advances to `until_fs`) or for n events |
| `sim.advance(dt_fs)` | run for an interval |
| `sim.now`, `sim.stopped`, `sim.stop_reason` | the engine clock and status |
| `sim.trace` | list of `TraceRecord(seq, time, kind, node, event, data, explain)` |
| `sim.messages` | dict id → `Message` (all timestamps, link, status, causal past) |
| `sim.nodes[id]` | runtime participant: `state`, `vars`, `history`, `verdict`, `observations`, `local(t)` … |
| `sim.scheduler.pending()` | pending events in execution order |
| `sim.snapshot(since=0)` | JSON-able state for UIs (nodes, pending, messages, trace slice, decision, links) |
| `sim.causal_chain(msg_id)` | the message's causal past, ordered by departure |
| `qpvsim.decide(sim)` | decision and explanation |
| `check_trace(sim)` | invariant results `{ok, checked, violations}` |
| `run_experiment(project, exp, progress=None, cancel=None)` | batches and sweeps → `{points: [{assignment, runs, summary}], provenance, …}` |
| `Session` | editable project + simulation + checkpoints (what the console and server use) |

Times are integer femtoseconds. Use `tu.ns(x)` to convert from ns and `tu.fmt(fs)` to format.

## Console

`qpv console [project]` opens the console in a terminal, with tab completion and history. The same console is the Console tab of the UI (Tab completes, ↑/↓ recall history), and `qpv console --script file` runs a script and exits non-zero on the first failing command.

Grammar: `command {argument}`. An argument is a word, a `"quoted string"` or a `key=value` pair. Values are parsed as JSON when possible (`0.6`, `true`, `[1,2]`, `{"a":1}`), and otherwise kept as strings. Times are in ns of global time.

In the UI, the console opens with one-click starting actions and a **command guide** that groups commands by task. Typing shows the matching command's usage underneath, results appear as "command → result" pairs that you can click to re-run, long output collapses, and `help` and `decision` render as readable lists. `why` is an alias of `decision`.

A command reports success only after the session or engine call has returned without error. Errors are reported with their cause, and invalid commands get a usage line or a suggestion.

| Command | Effect |
|---|---|
| `help [cmd]` | list commands or show usage |
| `examples` · `load example <name>` · `load <path>` · `save [path]` | projects |
| `info` · `validate` | summary with assumptions and limitations; static validation |
| `participants` · `node <id>` · `fsm <id>` · `links` · `queue [n]` · `time` | inspection (states, variables, timers, qubits, automaton and history, link delays, pending events, local clocks) |
| `reset [seed]` · `step [n]` · `run [until=<ns>] [steps=<n>]` · `advance <dt_ns>` | execution |
| `events [node=] [kind=] [grep=] [last=]` · `event <seq>` · `messages [node]` · `chain <msg>` | the trace, messages, causal paths |
| `decision` · `invariants` | verdicts with reasons; trace consistency |
| `set <path> <value>` · `get <path>` · `strategy <participant> <automaton>` · `caps <participant> [profile]` | edit the project (each edit resets the simulation) |
| `batch <runs> [seed=] [sweep=<path>:v1,v2] [workers=]` · `experiment <id>` | experiments |
| `export trace\|results\|project <path>` | export JSON |
| `checkpoint <name>` · `restore <name>` | snapshot and restore engine state (deterministic replay) |
| `assert decision.outcome <v>` · `assert node.<id>.<field> <v>` | scripted checks (fail with a non-zero exit in `--script` mode) |

Example session:

```
qpv> load example qpv_bb84_teleportation_attack
qpv> run until=20
qpv> queue
qpv> run
qpv> decision
qpv> chain 6
qpv> set participants.E0.processing_ns 0.6
qpv> run
qpv> assert decision.outcome reject
qpv> batch 500 sweep=participants.E0.processing_ns:0,0.2,0.4,0.6
```

## HTTP (used by the UI; single-user, local)

| Method and path | Body / query | Returns |
|---|---|---|
| `GET /api/meta` | none | version, backends, capability profiles, action and function catalogue, examples, automaton library |
| `GET /api/project` · `PUT /api/project` | project | `{project, issues, revision, sim_error}`; PUT rebuilds the simulation (unless only `ui` fields changed) |
| `POST /api/project/validate` | project | `{issues}` |
| `POST /api/project/example/{name}` | none | load a bundled example |
| `GET /api/project/export` | none | project file download |
| `POST /api/sim/reset` | `{seed?}` | snapshot |
| `POST /api/sim/step` | `{n, since}` | snapshot containing trace records from `since` |
| `POST /api/sim/run` | `{since, until_ns?, max_steps?}` | snapshot |
| `GET /api/sim/state?since=` | none | snapshot |
| `GET /api/sim/chain/{msg}` · `GET /api/sim/invariants` · `GET /api/sim/export` | none | causal chain · invariant check · full trace export |
| `POST /api/console` | `{line, since}` | `{result: {ok, output, data}, state}` |
| `GET /api/console/complete?prefix=` | none | completions |
| `POST /api/experiments` | experiment | `{id}` (runs in a background thread) |
| `GET /api/experiments/{id}` | none | progress and derived results |
| `GET /api/experiments/{id}/raw` · `/csv` · `POST /api/experiments/{id}/cancel` | none | raw runs · CSV · cancel |

The server binds to 127.0.0.1 by default and has no authentication. Do not expose it on untrusted networks.

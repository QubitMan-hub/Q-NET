# Protocol definition language

A protocol is a set of **participants**. Each runs an **automaton**, which is a finite-state machine whose transitions consume messages or timer expiries, evaluate guards, and execute actions. Automata are plain JSON in the project's `automata` map. The graphical editor and the engine use exactly this representation.

## Automaton

```jsonc
{
  "name": "qpv_bb84_verifier_quantum",
  "role": "verifier",                 // informational
  "description": "…",
  "ports": ["prover"],                // port names used by sends/receives (links bind them)
  "params":    { "t_ref_ns": {"default": 20.0, "description": "…"} },   // per-participant overridable, read-only
  "variables": { "x": 0, "theta": 0 },                                   // mutable local state
  "initial": "idle",
  "states": [
    {"id": "idle", "kind": "initial"},
    {"id": "waiting", "kind": "normal", "label": "Awaiting answer"},
    {"id": "accepted", "kind": "terminal", "outcome": "accept"},
    {"id": "rejected", "kind": "terminal", "outcome": "reject"}
  ],
  "transitions": [
    {"id": "accept", "from": "waiting", "to": "accepted",
     "trigger": {"type": "receive", "tags": ["answer"], "port": "prover"},
     "guard": "msg.value == x and msg.time <= deadline",
     "duration_ns": 0,
     "actions": [{"op": "verdict", "outcome": "accept", "reason": "'correct and on time'"}]}
  ]
}
```

**States.**
- `kind` is `initial`, `normal` or `terminal`.
- A terminal state may carry an `outcome`: `accept`, `reject`, `abort` or `done`. Reaching a terminal state finishes the participant.

**Transitions.** The transitions leaving a state are tried in list order (this is their priority), and the first one that is enabled and whose guard is true fires. The fields are:

- `duration_ns`: an expression giving the processing time in ns. If it is null, the participant's `processing_ns` is used. A capability minimum applies.
- `guard`: an expression. It defaults to `true`.

### Triggers

| Trigger | Enabled when | Expression bindings |
|---|---|---|
| `{"type": "start"}` | the participant's start event is being processed (initial state) | none |
| `{"type": "receive", "tags": [..], "port": p?}` | for every listed tag, a message with that tag is in the mailbox (optionally only from port `p`). Repeat a tag to wait for several messages with it. | `msg` (first consumed message), `msgs.<tag>` |
| `{"type": "timer", "name": n}` | timer `n` has expired and has not yet been consumed | none |
| `{"type": "auto"}` | always, whenever the participant is evaluated | none |

A message record has the fields `tag`, `value`, `port`, `kind` (`classical` or `quantum`), `time` (local arrival time, ns) and `id`. For a quantum message, `value` is the name of the qubit slot it was stored in, which is the message tag.

To wait for "either A or B", use two transitions leaving the same state.

## Expression language

Guards and many action fields are **expressions**. These are a safe subset of Python expression syntax, parsed with `ast` and interpreted by a whitelist; `eval` is never used.

- Literals (numbers, strings, `true`/`false`/`null`, lists, tuples, dicts); names; `msg.field` on message records only; subscripts and slices.
- Arithmetic `+ - * / // % **`; bitwise `^ & | ~`; comparisons, including chained ones; `and`, `or`, `not`; `a if c else b`.
- **Not allowed**: attribute access on anything but records, private names, lambdas, comprehensions, assignments, keyword arguments, and calls to anything that is not whitelisted.

Names resolve to:

- the automaton's parameters, then its variables;
- the built-ins `now` (local time, ns), `msg`, `msgs`, `pos` (own position, m), `claim_pos`, `claim_travel_ns` (light travel time from own position to the claimed position), `node_id`, `role` and `speed_m_per_ns`;
- the constants `pi`, `true` and `false`.

Functions:

| Function | Meaning |
|---|---|
| `abs min max int float bool round len sum str sqrt cos sin exp log floor ceil` | as in Python / math |
| `xor(a, b, …)` | XOR of bits |
| `distance(p, q)` | Euclidean distance |
| `rand_bit()`, `rand_int(lo, hi)`, `rand_uniform()`, `rand_choice(list)` | draws from the participant's **own** seeded stream |
| `travel_ns(d_m)` | light-cone delay for a distance at the project signal speed |
| `fs_round(x_ns)` | snap a time onto the engine's fs grid (use it for deadlines compared with `now`/`msg.time`) |

Participants cannot read each other's variables. Expressions see only local state and the messages actually delivered to the participant. This enforces information flow structurally, and the validator flags any unknown name.

## Actions

| `op` | Fields (expr = expression) | Effect |
|---|---|---|
| `set` | `var`, `expr` | assign a local variable |
| `send` | `port`, `tag`, `value` (expr) | classical message on the port's classical link |
| `send_qubit` | `port`, `tag`, `qubit` (slot) | send the qubit in a slot through the port's quantum link; the slot is emptied |
| `prepare` | `qubit` (slot), `state` (`0 1 + - +i -i`) | create a fresh qubit |
| `prepare_bb84` | `qubit`, `bit` (expr), `basis` (expr: 0 = Z, 1 = X) | create H^basis \|bit⟩ |
| `gate` | `gate` (`I X Y Z H S SDG T CNOT CX CZ SWAP RX RY RZ`), `qubits` (slots), `angle` (expr, radians) | unitary on one or two slots |
| `measure` | `qubit`, `basis` (expr: `Z`/`X`/`Y`/`angle` or 0/1), `angle` (expr), `result` (var), `discard` (default true) | projective measurement; outcome 0/1 stored in `result` |
| `bell_measure` | `qubits` [a, b], `results` [r0, r1] | CNOT(a→b), H(a), measure both in Z; both qubits consumed |
| `discard` | `qubit` | partial trace |
| `timer` | `name`, exactly one of `after_ns` / `at_ns` (expr; local clock) | (re)arm a named timer |
| `cancel_timer` | `name` | cancel a pending timer |
| `verdict` | `outcome` (`accept`/`reject`), `reason` (expr) | record this participant's decision at transition completion |
| `record` | `key`, `value` (expr) | named observation exported to experiment statistics (e.g. `rtt_ns`) |
| `log` | `text` (expr) | add a message to the trace |

Actions execute in order at the transition's begin time. Variable updates are visible to later actions in the same transition. Messages depart, and the verdict is recorded, at completion.

## Capabilities (adversary model)

A participant's `capabilities` is either a profile name or `{"profile": name, …overrides}`. The fields are:

| Field | Meaning |
|---|---|
| `prepare` | may create or prepare qubits |
| `gates` | allowed gate names (`null` = all) |
| `measure_bases` | allowed bases among `Z X Y angle` (`null` = all) |
| `bell_measure` | may perform Bell measurements |
| `quantum_send`, `quantum_receive`, `classical_send` | channel access |
| `entanglement` | may hold pre-shared entangled resources |
| `max_qubits` | simultaneous qubits in memory; an incoming qubit beyond this is lost (`msg.refused`) |
| `memory_ns` | storage time after which a held qubit is fully depolarised |
| `min_processing_ns` | lower bound on every transition duration |

| Profile | Summary |
|---|---|
| `unrestricted` | no restrictions |
| `verifier` | trusted verifier (no restrictions) |
| `honest_prover` | no pre-shared entanglement |
| `no_entanglement` | arbitrary local quantum operations and classical communication, no pre-shared entanglement: the setting of the cos²(π/8) bound for QPV_BB84 |
| `bounded_entanglement` | entanglement allowed, at most 2 qubits in memory |
| `measure_only` | measurements only; no gates, preparation or entanglement |
| `classical_only` | may relay classical data and forward qubits unchanged, but may not prepare, transform or measure them |

Enforcement:

- **At validation**: the operations an automaton uses are compared with the profile and reported as warnings, for example "strategy performs Bell measurements not permitted by profile 'classical_only'". Holding an EPR resource without `entanglement` is an error.
- **At run time**: every privileged action is checked. A violation halts the participant and records a `capability.violation` that names the denied capability.

Capabilities describe resources and strategies describe behaviour, so different strategies can be compared under identical assumptions.

## Pre-shared resources

These are set up before t = 0 and represent explicit trust assumptions:

```jsonc
{"id": "vshared", "type": "shared_random", "holders": ["V0", "V1"],
 "vars": {"x": "rand_bit()", "theta": "rand_bit()"}}          // copied into each holder's variables

{"id": "epr", "type": "epr", "state": "phi+", "werner_p": 0,
 "holders": [{"node": "E0", "slot": "e"}, {"node": "E1", "slot": "e"}]}   // Bell pair; werner_p depolarises one half
```

## Validation

`qpv validate` and the Validation panel run these static checks:

- unique ids;
- defined initial and target states, and reachability from the initial state;
- deadlock states (non-terminal states with no outgoing transitions);
- transitions that leave terminal states;
- trigger shapes, and timers used but never armed;
- action fields;
- expression syntax, and unknown names and functions;
- reserved names, and parameter/variable collisions;
- ports declared versus linked, and duplicate port bindings;
- links that are self-loops, superluminal or shorter than the straight-line distance;
- probabilities in [0, 1];
- capability versus strategy mismatches;
- EPR holders without entanglement capability;
- the verification rule.

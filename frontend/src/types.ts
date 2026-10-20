// Types mirror the JSON produced by the Python engine (qpvsim). The UI never
// derives simulation results itself; these are read-only views of engine data.

export type Role = "verifier" | "prover" | "adversary" | "other";
export type LinkKind = "classical" | "quantum";

export interface Action { op: string; [k: string]: any }
export interface Trigger { type: "start" | "timer" | "receive" | "auto"; name?: string; tags?: string[]; port?: string | null }
export interface TransitionSpec {
  id: string; from: string; to: string; label?: string; trigger: Trigger;
  guard?: string | boolean; duration_ns?: string | number | null; actions: Action[];
  ui?: { dx?: number; dy?: number };
}
export interface StateSpec {
  id: string; kind?: "initial" | "normal" | "terminal"; outcome?: string | null;
  label?: string; description?: string; ui?: { x: number; y: number };
}
export interface AutomatonSpec {
  name: string; role?: Role; description?: string; ports?: string[];
  params?: Record<string, { default?: any; description?: string; type?: string }>;
  variables?: Record<string, any>; initial: string; states: StateSpec[]; transitions: TransitionSpec[];
}
export interface ParticipantSpec {
  id: string; role: Role; label: string; position: number[]; automaton: string;
  params: Record<string, any>; processing_ns: number; start_ns: number;
  clock: { offset_ns: number; drift_ppm: number }; capabilities: string | Record<string, any>;
  noise: Record<string, number>; group: string | null; ui: { x?: number; y?: number };
}
export interface LinkSpec {
  id: string; kind: LinkKind; a: { node: string; port: string }; b: { node: string; port: string };
  directed: boolean; length_m: number | null; speed_mps: number | null; latency_ns: number;
  jitter_ns: number; loss_prob: number; attenuation_db_per_km: number; noise: Record<string, number>;
}
export interface ExperimentSpec {
  id: string; name?: string; runs: number; seed: number;
  sweep?: { path: string; values: any[] }[]; patch?: Record<string, any>; workers?: number;
}
export interface Project {
  format: string; version: number;
  meta: { name: string; description: string; protocol: { name: string; version: string; references: string[] };
    assumptions: string[]; limitations: string[] };
  physics: { signal_speed_mps: number; allow_superluminal: boolean };
  simulation: { seed: number; backend: string; max_time_ns: number; max_events: number; stop_when: string; priorities: Record<string, number> };
  claim: { prover: string | null; position: number[] };
  participants: ParticipantSpec[]; links: LinkSpec[]; resources: any[];
  automata: Record<string, AutomatonSpec>;
  verification: { rule: string; verifiers: string[] | null; k?: number };
  experiments: ExperimentSpec[];
}
export interface Issue { level: "error" | "warning"; path: string; message: string }

export interface TraceRecord {
  seq: number; time_fs: number; time_ns: number; kind: string; node: string | null;
  event: number | null; data: Record<string, any>; explain: string;
}
export interface Message {
  id: number; kind: LinkKind; tag: string; value: any; src: string; src_port: string; dst: string; dst_port: string;
  link: string; sent_by_transition: string; send_time_fs: number; depart_time_fs: number | null;
  arrival_time_fs: number | null; delay_fs: number | null; distance_m: number; speed_mps: number;
  latency_fs: number; jitter_fs: number; status: string; consumed_time_fs: number | null; consumed_by: string | null;
  causal_past: number[]; send_event: number | null; deliver_event: number | null;
}
export interface NodeState {
  id: string; role: Role; automaton: string; state: string; state_entered_fs: number;
  busy: null | { transition: string; begin_fs: number; complete_fs: number };
  started: boolean; finished: boolean; outcome: string | null; error: string | null;
  vars: Record<string, any>; params: Record<string, any>; mailbox: number[]; expired_timers: string[];
  timers: Record<string, any>; qubits: Record<string, any>; verdict: any; observations: Record<string, any>;
  local_time_fs: number; clock: string; capabilities: Record<string, any>;
  history: { transition: string; from: string; to: string; begin_fs: number; complete_fs: number; begin_record: number }[];
  state_log: { state: string; entered_fs: number; exited_fs: number | null }[]; position: number[];
}
export interface PendingEvent { id: number; time_fs: number; priority: number; seq: number; kind: string; node: string | null; label: string; cause: number | null; scheduled_at_fs: number }
export interface Decision {
  outcome: "accept" | "reject" | "pending"; rule: string; rule_text: string; accepts: number;
  verifiers: any[]; complete: boolean; summary: string; explanation: string[];
}
export interface SimState {
  now_fs: number; stopped: boolean; stop_reason: string | null; seed: number; events_executed: number;
  nodes: Record<string, NodeState>; pending: PendingEvent[]; messages: Message[]; trace: TraceRecord[];
  trace_length: number; counters: Record<string, number>; decision: Decision; revision: number; error?: string;
  links: { id: string; kind: LinkKind; distance_m: number; speed_mps: number; propagation_fs: number; latency_fs: number; delay_fs: number }[];
}

export type Selection =
  | { kind: "project" }
  | { kind: "participant"; id: string }
  | { kind: "link"; id: string }
  | { kind: "state"; automaton: string; id: string }
  | { kind: "transition"; automaton: string; id: string }
  | { kind: "message"; id: number }
  | { kind: "event"; seq: number }
  | { kind: "resource"; index: number };

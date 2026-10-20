import { memo, useCallback, useEffect, useMemo, useState } from "react";
import {
  Background, BackgroundVariant, BaseEdge, Controls, EdgeLabelRenderer, Handle, MarkerType, Position, ReactFlow,
  ReactFlowProvider, applyNodeChanges, useInternalNode, useReactFlow,
  type Edge, type EdgeProps, type Node, type NodeChange, type NodeProps,
} from "@xyflow/react";
import { useStore } from "../store";
import type { StateSpec, TransitionSpec } from "../types";
import { addState, addTransition, layoutAutomaton } from "../editing";
import { Icon, Select } from "./ui";
import { nsLabel } from "../format";

type SData = { st: StateSpec; automaton: string; initial: boolean; current: boolean; visited: boolean; enteredFs?: number };

const StateNode = memo(function StateNode({ data, selected }: NodeProps<Node<SData>>) {
  const { st, initial, current, visited } = data;
  const cls = ["s-node", initial ? "initial" : "", st.kind === "terminal" ? `terminal ${st.outcome ?? ""}` : "",
    current ? "current" : visited ? "visited" : "", selected ? "selected" : ""].join(" ");
  return (
    <div className={cls} data-testid={`state-${st.id}`}>
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <div className="sid">{st.id}</div>
      {st.label && st.label !== st.id && <div className="slabel">{st.label}</div>}
      {st.kind === "terminal" && st.outcome && <div className="slabel">→ {st.outcome}</div>}
      {current && data.enteredFs !== undefined && <div className="slabel mono">since {nsLabel(data.enteredFs, 3)}</div>}
      <Handle type="source" position={Position.Bottom} style={{ width: 10, height: 10, background: "var(--panel)", border: "1.5px solid var(--ink-2)" }} />
    </div>
  );
});

function rectBorder(node: any, toward: { x: number; y: number }) {
  const w = node.measured?.width ?? 120, h = node.measured?.height ?? 40;
  const c = { x: node.internals.positionAbsolute.x + w / 2, y: node.internals.positionAbsolute.y + h / 2 };
  const dx = toward.x - c.x, dy = toward.y - c.y;
  if (dx === 0 && dy === 0) return c;
  const s = Math.min(Math.abs((w / 2 + 4) / (dx || 1e-9)), Math.abs((h / 2 + 4) / (dy || 1e-9)));
  return { x: c.x + dx * s, y: c.y + dy * s, c };
}

const OP_CLASS: Record<string, string> = {
  prepare: "q", prepare_bb84: "q", gate: "q", measure: "q", bell_measure: "q", send_qubit: "q", discard: "q",
  send: "c", verdict: "v", record: "", set: "", timer: "", cancel_timer: "", log: "",
};

type TData = { t: TransitionSpec; automaton: string; index: number; count: number; fired: number; last: boolean; selectedT: boolean };

const TransitionEdge = memo(function TransitionEdge({ id, source, target, data, markerEnd }: EdgeProps<Edge<TData>>) {
  const sn = useInternalNode(source);
  const tn = useInternalNode(target);
  const select = useStore((s) => s.select);
  if (!sn || !tn || !data) return null;
  const { t } = data;
  let path: string, lx: number, ly: number;
  if (source === target) {
    const w = sn.measured?.width ?? 120;
    const p = sn.internals.positionAbsolute;
    const x = p.x + w, y = p.y + 12;
    const r = 34 + data.index * 18;
    path = `M ${x} ${y} C ${x + r * 1.6} ${y - r}, ${x + r * 1.6} ${y + r + 16}, ${x} ${y + 20}`;
    lx = x + r * 1.3 + 12; ly = y + 10;
  } else {
    const sc = { x: sn.internals.positionAbsolute.x + (sn.measured?.width ?? 0) / 2, y: sn.internals.positionAbsolute.y + (sn.measured?.height ?? 0) / 2 };
    const tc = { x: tn.internals.positionAbsolute.x + (tn.measured?.width ?? 0) / 2, y: tn.internals.positionAbsolute.y + (tn.measured?.height ?? 0) / 2 };
    const dx = tc.x - sc.x, dy = tc.y - sc.y;
    const len = Math.hypot(dx, dy) || 1;
    const nx = -dy / len, ny = dx / len;
    const bend = (data.index - (data.count - 1) / 2) * 140;
    const ctrl = { x: (sc.x + tc.x) / 2 + nx * bend, y: (sc.y + tc.y) / 2 + ny * bend };
    const a = rectBorder(sn, ctrl), b = rectBorder(tn, ctrl);
    path = `M ${a.x} ${a.y} Q ${ctrl.x} ${ctrl.y} ${b.x} ${b.y}`;
    lx = 0.25 * a.x + 0.5 * ctrl.x + 0.25 * b.x;
    ly = 0.25 * a.y + 0.5 * ctrl.y + 0.25 * b.y;
  }
  const trig = t.trigger.type === "receive" ? `recv ${(t.trigger.tags ?? []).join(", ")}${t.trigger.port ? ` @${t.trigger.port}` : ""}`
    : t.trigger.type === "timer" ? `timer ${t.trigger.name}` : t.trigger.type;
  const stroke = data.last ? "var(--ink)" : data.fired ? "var(--ink-2)" : "var(--rule-strong)";
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={{ stroke, strokeWidth: data.last ? 2.4 : data.selectedT ? 2.2 : 1.4 }} />
      <EdgeLabelRenderer>
        <div className={`t-label${data.selectedT ? " selected" : ""}${data.fired ? " fired" : ""}${data.last ? " last" : ""}`}
          style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}
          onClick={() => select({ kind: "transition", automaton: data.automaton, id: t.id })}
          data-testid={`transition-${t.id}`}>
          {data.fired > 0 && <span className="count" title="times fired in this run">×{data.fired}</span>}
          <span className="tid">{t.id}</span> <span className="trig">{trig}</span>
          {typeof t.guard === "string" && t.guard.trim() !== "" && t.guard !== "true" && <div className="guard" title={t.guard}>[{t.guard}]</div>}
          {t.actions.length > 0 && (
            <div className="ops">{t.actions.map((a, i) => <span key={i} className={OP_CLASS[a.op] ?? ""}>{a.op}</span>)}</div>
          )}
        </div>
      </EdgeLabelRenderer>
    </>
  );
});

const nodeTypes = { state: StateNode };
const edgeTypes = { transition: TransitionEdge };

function AutomatonInner() {
  const project = useStore((s) => s.project)!;
  const focus = useStore((s) => s.focus);
  const setFocus = useStore((s) => s.setFocus);
  const selection = useStore((s) => s.selection);
  const select = useStore((s) => s.select);
  const edit = useStore((s) => s.edit);
  const live = useStore((s) => (focus ? s.sim?.nodes[focus] : undefined));
  const rf = useReactFlow();

  const participant = project.participants.find((p) => p.id === focus) ?? project.participants[0];
  const aname = participant?.automaton;
  const a = aname ? project.automata[aname] : undefined;
  const users = project.participants.filter((p) => p.automaton === aname).map((p) => p.id);

  const visited = useMemo(() => new Set(live?.state_log.map((s) => s.state) ?? []), [live]);
  const firedCount = useMemo(() => {
    const m = new Map<string, number>();
    for (const h of live?.history ?? []) m.set(h.transition, (m.get(h.transition) ?? 0) + 1);
    return m;
  }, [live]);
  const lastT = live?.busy?.transition ?? live?.history[live.history.length - 1]?.transition;

  const derived: Node<SData>[] = useMemo(() => (a?.states ?? []).map((st, i) => ({
    id: st.id, type: "state", position: { x: st.ui?.x ?? i * 200, y: st.ui?.y ?? 0 },
    data: { st, automaton: a!.name, initial: st.id === a!.initial, current: live?.state === st.id && !live?.busy,
      visited: visited.has(st.id), enteredFs: live?.state === st.id ? live?.state_entered_fs : undefined },
    selected: selection.kind === "state" && selection.automaton === a!.name && selection.id === st.id,
  })), [a, live, visited, selection]);

  // React Flow keeps measured sizes and in-progress drags in node state; the
  // project document stays the source of truth and is re-applied on change.
  const [nodes, setNodes] = useState<Node<SData>[]>(derived);
  useEffect(() => setNodes((cur) => derived.map((n) => {
    const old = cur.find((c) => c.id === n.id);
    return old ? { ...old, ...n, measured: old.measured, dragging: old.dragging } : n;
  })), [derived]);
  const onNodesChange = useCallback((ch: NodeChange<Node<SData>>[]) =>
    setNodes((nds) => applyNodeChanges(ch.filter((c) => c.type !== "remove" && c.type !== "select"), nds)), []);

  const edges: Edge<TData>[] = useMemo(() => {
    if (!a) return [];
    const pairCount = new Map<string, number>();
    const pairIndex = new Map<string, number>();
    for (const t of a.transitions) {
      const k = [t.from, t.to].sort().join("|");
      pairCount.set(k, (pairCount.get(k) ?? 0) + 1);
    }
    return a.transitions.map((t) => {
      const k = [t.from, t.to].sort().join("|");
      const idx = pairIndex.get(k) ?? 0;
      pairIndex.set(k, idx + 1);
      const sel = selection.kind === "transition" && selection.automaton === a.name && selection.id === t.id;
      return {
        id: `${t.id}`, source: t.from, target: t.to, type: "transition",
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: lastT === t.id ? "var(--ink)" : "var(--ink-2)" },
        data: { t, automaton: a.name, index: idx, count: pairCount.get(k)!, fired: firedCount.get(t.id) ?? 0, last: lastT === t.id, selectedT: sel },
      };
    });
  }, [a, selection, firedCount, lastT]);

  if (!participant || !a) {
    return <div className="empty">No participant selected. Add a participant on the <b>Network</b> canvas, then open its automaton here.</div>;
  }

  return (
    <div className="canvas-wrap">
      <div className="canvas-tools">
        <span className="small muted" style={{ padding: "0 4px" }}>Participant</span>
        <div style={{ width: 120 }}>
          <Select value={participant.id} ariaLabel="Participant" options={project.participants.map((p) => ({ value: p.id, label: `${p.id} (${p.role})` }))}
            onChange={(v) => setFocus(v)} />
        </div>
        <span className="small mono" title={`Shared by: ${users.join(", ")}`} style={{ padding: "0 6px" }}>{a.name}</span>
        {users.length > 1 && <span className="xs muted">shared by {users.join(", ")}</span>}
        <span className="tool-sep" />
        <button className="btn ghost" onClick={() => addState(a.name, "normal", null)}><Icon.plus />State</button>
        <button className="btn ghost" onClick={() => addState(a.name, "terminal", "accept")}>Accept</button>
        <button className="btn ghost" onClick={() => addState(a.name, "terminal", "reject")}>Reject</button>
        <button className="btn ghost" title="Layered layout from the initial state" onClick={() => layoutAutomaton(a.name)}><Icon.layout />Layout</button>
        <button className="btn ghost" title="Fit view" onClick={() => rf.fitView({ duration: 250, padding: 0.2 })}><Icon.fit /></button>
      </div>
      <ReactFlow
        key={a.name}
        nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} onNodesChange={onNodesChange}
        onConnect={(c) => c.source && c.target && addTransition(a.name, c.source, c.target)}
        onNodeClick={(_, n) => select({ kind: "state", automaton: a.name, id: n.id })}
        onPaneClick={() => select({ kind: "participant", id: participant.id })}
        onNodeDragStop={(_, n) => edit((p) => {
          const st = p.automata[a.name].states.find((x) => x.id === n.id);
          if (st) st.ui = { x: Math.round(n.position.x), y: Math.round(n.position.y) };
        })}
        deleteKeyCode={null}
        fitView fitViewOptions={{ padding: 0.3 }} minZoom={0.2} maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} color="var(--rule-strong)" />
        <Controls showInteractive={false} />
      </ReactFlow>
      <div className="canvas-note">
        {live ? <>
          {participant.id}: <b>{live.busy ? `executing ${live.busy.transition}` : live.state}</b>
          {live.mailbox.length > 0 && <> · mailbox {live.mailbox.map((m) => `m${m}`).join(", ")}</>}
          {Object.keys(live.timers).length > 0 && <> · timers {Object.keys(live.timers).join(", ")}</>}
          {live.error && <span style={{ color: "var(--reject)" }}> · halted: {live.error}</span>}
        </> : <span className="muted">Simulation not available — fix validation errors to run.</span>}
        <span className="muted"> · drag from a state’s lower handle to add a transition</span>
      </div>
    </div>
  );
}

export function AutomatonCanvas() {
  return <ReactFlowProvider><AutomatonInner /></ReactFlowProvider>;
}

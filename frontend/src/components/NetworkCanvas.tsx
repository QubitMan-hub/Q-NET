import { memo, useCallback, useEffect, useMemo, useState } from "react";
import {
  Background, BackgroundVariant, BaseEdge, Controls, EdgeLabelRenderer, Handle, MiniMap, Position, ReactFlow,
  ReactFlowProvider, applyNodeChanges, useInternalNode, useReactFlow,
  type Connection, type Edge, type NodeChange, type EdgeProps, type Node, type NodeProps,
} from "@xyflow/react";
import { useStore } from "../store";
import { nsLabel, uniqueId } from "../format";
import type { Issue, LinkKind, LinkSpec, ParticipantSpec, Project, Role, VerifierType } from "../types";
import { GLOSSARY } from "../glossary";
import { Icon } from "./ui";
import { addParticipant, deleteSelection, duplicateParticipant } from "../editing";

type Port = { name: string; side: "left" | "right"; kinds: LinkKind[]; missing?: string };
type PData = { p: ParticipantSpec; ports: Port[]; vtype?: VerifierType };
const BOTH: LinkKind[] = ["classical", "quantum"];

/** Ports of a participant with the link kinds they carry, each on the side facing the peers it is linked to. */
function participantPorts(project: Project, p: ParticipantSpec, kinds: Record<string, LinkKind[]>, issues: Issue[]): Port[] {
  const declared = project.automata[p.automaton]?.ports ?? [];
  const used = project.links.flatMap((l) => [l.a, l.b]).filter((e) => e.node === p.id).map((e) => e.port);
  const names = Array.from(new Set([...declared, ...Object.keys(kinds), ...used]));
  const missing = new Map(issues.filter((i) => i.path === `participants[${p.id}]`)
    .map((i) => [/^port '([^']+)' is not connected/.exec(i.message)?.[1], i.message] as const));
  const myX = p.ui?.x ?? 0;
  return names.map((name, i) => {
    const peers = project.links.flatMap((l) =>
      l.a.node === p.id && l.a.port === name ? [l.b.node] : l.b.node === p.id && l.b.port === name ? [l.a.node] : []);
    const xs = peers.map((id) => project.participants.find((q) => q.id === id)?.ui?.x ?? myX);
    const side = xs.length ? (xs.reduce((a, b) => a + b, 0) / xs.length >= myX ? "right" : "left") : (i % 2 ? "right" : "left");
    return { name, side, kinds: kinds[name] ?? BOTH, missing: missing.get(name) };
  });
}

const kindClass = (k: LinkKind[]) => (k.length === 1 ? `k-${k[0]}` : "k-both");
const kindHint = (k: LinkKind[]) => (k.length === 1 ? GLOSSARY[`port_${k[0]}`] : "This port carries qubits and classical messages.");

const ROLE_HEX: Record<string, string> = { verifier: "#0e6e6e", prover: "#2f6f3a", adversary: "#b0283f", other: "#56606b" };

const ParticipantNode = memo(function ParticipantNode({ data, selected }: NodeProps<Node<PData>>) {
  const { p, ports, vtype } = data;
  const live = useStore((s) => s.sim?.nodes[p.id]);
  const caps = typeof p.capabilities === "string" ? p.capabilities : p.capabilities?.profile ?? "custom";
  const stateClass = live?.error ? "error" : live?.outcome === "accept" ? "accept" : live?.outcome === "reject" ? "reject" : live?.busy ? "busy" : "";
  const left = ports.filter((q) => q.side === "left");
  const right = ports.filter((q) => q.side === "right");
  return (
    <div className={`p-node ${p.role}${vtype ? ` v-${vtype}` : ""}${selected ? " selected" : ""}`} data-testid={`node-${p.id}`}
      title={vtype ? GLOSSARY[`${vtype}_verifier`] : GLOSSARY[p.role]}>
      <div className="stripe" />
      <div className="head">
        {vtype && <span className="vtype" aria-label={`${vtype} verifier`}>{vtype === "quantum" ? <Icon.qubit /> : <Icon.bit />}</span>}
        <span className="id">{p.id}</span>
        <span className="muted grow" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.label !== p.id ? p.label : p.role}</span>
      </div>
      <div className="body">
        <div className="kv"><span>state</span>
          <span className={`state-badge ${stateClass}`} title={live?.error ?? undefined}>
            {live ? (live.busy ? `${live.busy.transition}…` : live.state) : "—"}
          </span>
        </div>
        <div className="kv"><span>x</span><b className="mono">{p.position.map((v) => v.toFixed(2)).join(", ")} m</b></div>
        <div className="kv"><span>processing</span><b className="mono">{p.processing_ns} ns</b></div>
        <div className="kv"><span>caps</span><b>{caps}</b></div>
        {live?.verdict && <div className="kv"><span>verdict</span><b style={{ color: live.verdict.outcome === "accept" ? "var(--accept)" : "var(--reject)" }}>{live.verdict.outcome}</b></div>}
      </div>
      {([["left", left], ["right", right]] as const).map(([side, list]) => list.map((q, i) => {
        const top = ((i + 1) / (list.length + 1)) * 100;
        return (<div key={q.name}>
          <Handle type="source" id={q.name} position={side === "left" ? Position.Left : Position.Right}
            className={`port ${kindClass(q.kinds)}`} style={{ top: `${top}%` }} title={`${q.name}: ${kindHint(q.kinds)}`} />
          <span className={`port-label${q.missing ? " missing" : ""}`} title={q.missing}
            style={{ [side === "left" ? "right" : "left"]: "calc(100% + 8px)", top: `calc(${top}% - 7px)` }}>{q.name}</span>
        </div>);
      }))}
    </div>
  );
});

function handlePoint(node: any, handleId: string | null | undefined) {
  const hb = node?.internals?.handleBounds;
  const all = [...(hb?.source ?? []), ...(hb?.target ?? [])];
  const h = all.find((x: any) => x.id === handleId) ?? all[0];
  const pos = node.internals.positionAbsolute;
  if (!h) return { x: pos.x + (node.measured?.width ?? 0) / 2, y: pos.y + (node.measured?.height ?? 0) / 2 };
  return { x: pos.x + h.x + h.width / 2, y: pos.y + h.y + h.height / 2 };
}

type LData = { link: LinkSpec; offset: number };

const LinkEdge = memo(function LinkEdge({ id, source, target, sourceHandleId, targetHandleId, data, selected }: EdgeProps<Edge<LData>>) {
  const sn = useInternalNode(source);
  const tn = useInternalNode(target);
  const sim = useStore((s) => s.sim);
  const select = useStore((s) => s.select);
  const chain = useStore((s) => s.highlightChain);
  const [hover, setHover] = useState(false);
  if (!sn || !tn || !data) return null;
  const a = handlePoint(sn, sourceHandleId);
  const b = handlePoint(tn, targetHandleId);
  const dx = b.x - a.x, dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len, ny = dx / len;
  const off = data.offset;
  const ax = a.x + nx * off, ay = a.y + ny * off, bx = b.x + nx * off, by = b.y + ny * off;
  const path = `M ${ax} ${ay} L ${bx} ${by}`;
  // Parallel channels share a corridor: stagger their labels along the edge and
  // put each on its own side so they never cover one another.
  const quantumLink = data.link.kind === "quantum";
  const side = quantumLink ? -1 : 1;
  const labelAt = quantumLink ? 0.36 : 0.64;
  const quantum = data.link.kind === "quantum";
  const color = quantum ? "var(--quantum)" : "var(--classical)";
  const summary = sim?.links?.find((l) => l.id === data.link.id);
  const now = sim?.now_fs ?? 0;
  // Messages are drawn where the engine's departure/arrival timestamps put them at the engine's current time.
  const inflight = (sim?.messages ?? []).filter((m) => m.link === data.link.id && m.depart_time_fs !== null &&
    m.depart_time_fs <= now && (m.status === "in_flight" || (m.arrival_time_fs !== null && m.arrival_time_fs > now)));
  const lit = (sim?.messages ?? []).some((m) => m.link === data.link.id && chain.includes(m.id));
  return (
    <>
      <g onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)} data-testid={`link-hit-${data.link.id}`}>
        {quantum ? (
          <>
            <BaseEdge id={id} path={path} style={{ stroke: color, strokeWidth: selected || lit ? 5.5 : 4.5 }} />
            <path d={path} stroke="var(--paper)" strokeWidth={selected || lit ? 2.5 : 1.6} fill="none" />
          </>
        ) : (
          <BaseEdge id={id} path={path} style={{ stroke: color, strokeWidth: selected || lit ? 2.6 : 1.6, strokeDasharray: "6 4" }} />
        )}
      </g>
      {inflight.map((m) => {
        const toB = m.src === data.link.a.node && m.src_port === data.link.a.port;
        const end = m.arrival_time_fs ?? (m.depart_time_fs! + (m.delay_fs ?? 1));
        const f = Math.min(1, Math.max(0, (now - m.depart_time_fs!) / Math.max(1, end - m.depart_time_fs!)));
        const t = toB ? f : 1 - f;
        const x = ax + (bx - ax) * t, y = ay + (by - ay) * t;
        return (
          <g key={m.id} style={{ cursor: "pointer" }} onClick={(e) => { e.stopPropagation(); select({ kind: "message", id: m.id }); }}>
            <circle cx={x} cy={y} r={6} fill={color} stroke="var(--panel)" strokeWidth={2} />
            <text x={x + 9} y={y - 7} fontSize={10} fill="var(--ink)" fontFamily="var(--font-code)">{m.tag}{m.kind === "classical" ? `=${JSON.stringify(m.value)}` : ""}</text>
          </g>
        );
      })}
      <EdgeLabelRenderer>
        <div className={`edge-label${selected ? " selected" : ""}`}
          style={{ transform: `translate(-50%, -50%) translate(${ax + (bx - ax) * labelAt + nx * 14 * side}px, ${ay + (by - ay) * labelAt + ny * 14 * side}px)`, color }}
          onClick={() => select({ kind: "link", id: data.link.id })} data-testid={`link-${data.link.id}`}>
          {data.link.id} · {summary ? nsLabel(summary.delay_fs, 3) : `${data.link.kind}`}
        </div>
        {hover && (
          <div className="link-tip" role="tooltip" data-testid="link-tip"
            style={{ transform: `translate(-50%, 12px) translate(${(ax + bx) / 2}px, ${(ay + by) / 2}px)` }}>
            <b>{data.link.id}</b>: {data.link.kind} link, {data.link.a.node}.{data.link.a.port} ↔ {data.link.b.node}.{data.link.b.port}
            {summary ? <>
              <div>length {summary.distance_m.toFixed(3)} m{data.link.length_m === null ? " (straight line)" : ""}</div>
              <div>propagation {nsLabel(summary.propagation_fs)}{summary.latency_fs ? ` + latency ${nsLabel(summary.latency_fs)}` : ""}</div>
              <div>delay {nsLabel(summary.delay_fs)}</div>
            </> : <div>Fix the validation errors to see the engine's delay.</div>}
          </div>
        )}
      </EdgeLabelRenderer>
    </>
  );
});

const nodeTypes = { participant: ParticipantNode };
const edgeTypes = { link: LinkEdge };

function NetworkInner() {
  const project = useStore((s) => s.project)!;
  const selection = useStore((s) => s.selection);
  const select = useStore((s) => s.select);
  const edit = useStore((s) => s.edit);
  const linkKind = useStore((s) => s.linkKind);
  const portKinds = useStore((s) => s.ports);
  const issues = useStore((s) => s.issues);
  const vtypes = useStore((s) => s.verifierTypes);
  const autowire = useStore((s) => s.autowire);
  const qpv = useStore((s) => s.analysis?.qpv ?? false);
  const setView = useStore((s) => s.setView);
  const setFocus = useStore((s) => s.setFocus);
  const rf = useReactFlow();
  const [search, setSearch] = useState("");
  const [menu, setMenu] = useState<{ x: number; y: number; id: string } | null>(null);

  const derived: Node<PData>[] = useMemo(() => project.participants.map((p, i) => ({
    id: p.id, type: "participant", position: { x: p.ui?.x ?? 120 + i * 220, y: p.ui?.y ?? 200 },
    data: { p, ports: participantPorts(project, p, portKinds[p.id] ?? {}, issues), vtype: p.verifier_type ?? vtypes[p.id] },
    selected: selection.kind === "participant" && selection.id === p.id,
  })), [project, selection, portKinds, issues, vtypes]);

  // React Flow keeps measured sizes and in-progress drags in node state; the
  // project document stays the source of truth and is re-applied on change.
  const [nodes, setNodes] = useState<Node<PData>[]>(derived);
  useEffect(() => setNodes((cur) => derived.map((n) => {
    const old = cur.find((c) => c.id === n.id);
    return old ? { ...old, ...n, measured: old.measured, dragging: old.dragging } : n;
  })), [derived]);
  const onNodesChange = useCallback((ch: NodeChange<Node<PData>>[]) =>
    setNodes((nds) => applyNodeChanges(ch.filter((c) => c.type !== "remove" && c.type !== "select"), nds)), []);

  const edges: Edge<LData>[] = useMemo(() => {
    const groups = new Map<string, number>();
    return project.links.map((l) => {
      const key = [l.a.node + l.a.port, l.b.node + l.b.port].sort().join("|");
      const k = groups.get(key) ?? 0;
      groups.set(key, k + 1);
      return {
        id: l.id, source: l.a.node, sourceHandle: l.a.port, target: l.b.node, targetHandle: l.b.port, type: "link",
        data: { link: l, offset: (k % 2 === 0 ? 1 : -1) * Math.ceil(k / 2) * 9 + (l.kind === "quantum" ? -4 : 4) },
        selected: selection.kind === "link" && selection.id === l.id,
      };
    });
  }, [project, selection]);

  // Validate as the user connects: the link kind must be one both ports carry.
  const onConnect = useCallback((c: Connection) => {
    if (!c.source || !c.target || c.source === c.target) return;
    const [ap, bp] = [c.sourceHandle ?? "port", c.targetHandle ?? "port"];
    const ka = portKinds[c.source]?.[ap] ?? BOTH, kb = portKinds[c.target]?.[bp] ?? BOTH;
    const common = ka.filter((k) => kb.includes(k));
    const toast = useStore.getState().setToast;
    if (!common.length) {
      return toast(`${c.source}.${ap} carries only ${ka.join(" and ")} signals and ${c.target}.${bp} only ${kb.join(" and ")}, `
        + "so no channel can join them.", true);
    }
    const kind = common.length === 1 ? common[0] : linkKind;
    if (project.links.some((l) => l.kind === kind && [l.a, l.b].some((e) => e.node === c.source && e.port === ap)
      && [l.a, l.b].some((e) => e.node === c.target && e.port === bp))) {
      return toast(`${c.source}.${ap} and ${c.target}.${bp} already have a ${kind} link.`, true);
    }
    const id = uniqueId(kind[0], project.links.map((l) => l.id));
    edit((p) => {
      p.links.push({
        id, kind, a: { node: c.source!, port: ap }, b: { node: c.target!, port: bp },
        directed: false, length_m: null, speed_mps: null, latency_ns: 0, jitter_ns: 0, loss_prob: 0, attenuation_db_per_km: 0, noise: {},
      });
    }, { select: { kind: "link", id } });
  }, [edit, linkKind, project.links, portKinds]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const [role, vtype] = e.dataTransfer.getData("application/qpv-role").split(":") as [Role, VerifierType?];
    if (!role) return;
    addParticipant(role, rf.screenToFlowPosition({ x: e.clientX, y: e.clientY }), vtype);
  }, [rf]);

  const find = () => {
    const q = search.trim().toLowerCase();
    if (!q) return;
    const hit = project.participants.find((p) => p.id.toLowerCase().includes(q) || p.label.toLowerCase().includes(q));
    if (hit) {
      select({ kind: "participant", id: hit.id });
      rf.fitView({ nodes: [{ id: hit.id }], duration: 250, maxZoom: 1.4 });
    } else useStore.getState().setToast(`No participant matches “${search}”`, true);
  };

  const arrangeByPosition = () => edit((p) => {
    const xs = p.participants.map((q) => q.position[0]);
    const min = Math.min(...xs), max = Math.max(...xs);
    const span = max - min || 1;
    p.participants.forEach((q, i) => {
      q.ui = { x: 60 + ((q.position[0] - min) / span) * 900, y: 160 + (q.role === "adversary" ? 190 : 0) + (i % 2) * 0 + ((q.position[1] ?? 0) * 40) };
    });
  });

  return (
    <div className="canvas-wrap" onDrop={onDrop} onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; }}>
      <div className="canvas-tools">
        <input placeholder="Find participant…" value={search} onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && find()} aria-label="Find participant" />
        <button className="btn ghost" title={qpv ? GLOSSARY.autowire : "Auto-wire needs a QPV setup: a quantum verifier and classical verifiers from the QPV library."}
          onClick={autowire} disabled={!qpv} data-testid="btn-autowire"><Icon.wire />Auto-wire</button>
        <button className="btn ghost" title="Lay out by physical x position" onClick={arrangeByPosition}><Icon.layout />Arrange by position</button>
        <button className="btn ghost" title="Fit view" onClick={() => rf.fitView({ duration: 250, padding: 0.2 })}><Icon.fit /></button>
      </div>
      <ReactFlow
        nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} onNodesChange={onNodesChange}
        onConnect={onConnect} connectionMode={"loose" as any} connectionRadius={36}
        onNodeClick={(_, n) => select({ kind: "participant", id: n.id })}
        onNodeDoubleClick={(_, n) => { setFocus(n.id); setView("automaton"); }}
        onEdgeClick={(_, e) => select({ kind: "link", id: e.id })}
        onPaneClick={() => { select({ kind: "project" }); setMenu(null); }}
        onNodeContextMenu={(e, n) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, id: n.id }); }}
        onNodeDragStop={(_, n) => edit((p) => {
          const q = p.participants.find((x) => x.id === n.id);
          if (q) q.ui = { x: Math.round(n.position.x), y: Math.round(n.position.y) };
        })}
        onNodesDelete={() => deleteSelection()}
        deleteKeyCode={null}
        fitView fitViewOptions={{ padding: 0.25, maxZoom: 1.2 }} minZoom={0.2} maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Lines} gap={40} color="var(--grid)" />
        <MiniMap pannable zoomable nodeColor={(n) => ROLE_HEX[(n.data as PData).p.role] ?? "#56606b"} maskColor="rgba(120,130,140,0.15)"
          style={{ width: 160, height: 100 }} />
        <Controls showInteractive={false} />
      </ReactFlow>
      {menu && (
        <div className="ctx-menu" style={{ left: menu.x, top: menu.y }} onMouseLeave={() => setMenu(null)}>
          <button onClick={() => { setFocus(menu.id); setView("automaton"); setMenu(null); }}>Open automaton</button>
          <button onClick={() => { duplicateParticipant(menu.id); setMenu(null); }}>Duplicate <span className="kbd">Ctrl D</span></button>
          <hr />
          <button className="danger" onClick={() => { select({ kind: "participant", id: menu.id }); deleteSelection(); setMenu(null); }}>Delete <span className="kbd">Del</span></button>
        </div>
      )}
      {project.participants.length === 0 && (
        <div className="canvas-note">Drag a verifier, prover or adversary from the palette to start a protocol.</div>
      )}
    </div>
  );
}

export function NetworkCanvas() {
  return <ReactFlowProvider><NetworkInner /></ReactFlowProvider>;
}

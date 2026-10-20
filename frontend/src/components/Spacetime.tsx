import { useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../store";
import { nsLabel } from "../format";
import { Check } from "./ui";

const C = 299_792_458;
const NS_PER_M = 1e9 / C;

function useSize(ref: React.RefObject<HTMLDivElement>) {
  const [size, setSize] = useState({ w: 800, h: 500 });
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, [ref]);
  return size;
}

function niceStep(range: number, target: number) {
  const raw = range / target;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
}

/** Spacetime (Minkowski) diagram of the run: x = position along the verifier axis, time upward. */
export function Spacetime() {
  const ref = useRef<HTMLDivElement>(null);
  const { w, h } = useSize(ref);
  const project = useStore((s) => s.project)!;
  const sim = useStore((s) => s.sim);
  const select = useStore((s) => s.select);
  const selection = useStore((s) => s.selection);
  const chain = useStore((s) => s.highlightChain);
  const [lightScale, setLightScale] = useState(true);
  const [cones, setCones] = useState(true);

  const model = useMemo(() => {
    if (!sim) return null;
    const xs = project.participants.map((p) => p.position[0]).concat([project.claim.position[0] ?? 0]);
    let xmin = Math.min(...xs), xmax = Math.max(...xs);
    const pad = Math.max(0.5, (xmax - xmin) * 0.08);
    xmin -= pad; xmax += pad;
    const deadlines = sim.trace.filter((r) => r.kind === "timer.set" && /deadline/i.test(r.data.name))
      .map((r) => ({ node: r.node!, t: r.data.fire_fs as number }));
    const times = [sim.now_fs, ...sim.messages.map((m) => m.arrival_time_fs ?? m.depart_time_fs ?? 0), ...deadlines.map((d) => d.t)];
    const tmax = Math.max(1, ...times) * 1.06;
    return { xmin, xmax, tmax, deadlines };
  }, [sim, project]);

  if (!sim || !model) {
    return <div className="empty">The spacetime diagram plots the engine’s trace. Fix the validation errors listed in the <b>Validation</b> tab so the project can run.</div>;
  }

  const m = { l: 64, r: 24, t: 84, b: 34 };
  const W = Math.max(200, w - m.l - m.r), H = Math.max(150, h - m.t - m.b);
  const tNs = model.tmax / 1e6;
  let pxPerNs = H / tNs;
  let pxPerM = W / (model.xmax - model.xmin);
  if (lightScale) {
    // equal scaling: a light ray is a 45° line
    const k = Math.min(H / tNs, W / ((model.xmax - model.xmin) * NS_PER_M));
    pxPerNs = k;
    pxPerM = k * NS_PER_M;
  }
  const plotW = (model.xmax - model.xmin) * pxPerM, plotH = tNs * pxPerNs;
  const ox = m.l + (W - plotW) / 2, oy = m.t + (H - plotH);
  // On small plots, drop secondary text so labels do not collide.
  const minGap = Math.min(...project.participants.map((a, i) => Math.min(...project.participants
    .filter((_, j) => j !== i).map((b) => Math.abs(a.position[0] - b.position[0]) * pxPerM), Infinity)));
  const compact = plotW < 420 || minGap < 70;
  const X = (xm: number) => ox + (xm - model.xmin) * pxPerM;
  const T = (fs: number) => oy + plotH - (fs / 1e6) * pxPerNs;
  const posOf = (id: string) => project.participants.find((p) => p.id === id)?.position[0] ?? 0;
  const roleOf = (id: string) => project.participants.find((p) => p.id === id)?.role ?? "other";
  const tStep = niceStep(tNs, 8);
  const xStep = niceStep(model.xmax - model.xmin, 8);
  const now = sim.now_fs;
  const selMsg = selection.kind === "message" ? selection.id : null;
  const dim = chain.length > 0;

  const challenges = sim.messages.filter((mm) => roleOf(mm.src) === "verifier" && mm.depart_time_fs !== null)
    .filter((mm, i, arr) => arr.findIndex((o) => o.src === mm.src) === i);

  return (
    <div className="canvas-wrap" ref={ref}>
      <div className="canvas-tools">
        <Check checked={lightScale} onChange={setLightScale} label="Light rays at 45°" />
        <Check checked={cones} onChange={setCones} label="Challenge light cones" />
        {dim && <button className="btn ghost" onClick={() => useStore.getState().setHighlightChain([])}>Clear causal path</button>}
      </div>
      <div className="st-legend">
        <div className="row"><span className="chan quantum" />quantum message</div>
        <div className="row"><span className="chan classical" />classical message</div>
        <div className="row"><svg width="22" height="8"><path d="M0 4h22" stroke="var(--ink-3)" strokeDasharray="2 3" /></svg>light cone of a challenge</div>
        <div className="row"><svg width="22" height="8"><path d="M4 4h14" stroke="var(--reject)" strokeWidth="2" /></svg>verifier deadline</div>
        <div className="row"><svg width="22" height="8"><path d="M0 4h22" stroke="var(--now)" /></svg>engine time {nsLabel(sim.now_fs, 3)}</div>
      </div>
      <svg width={w} height={h} role="img" aria-label="Spacetime diagram of the simulation run"
        style={{ position: "absolute", inset: 0 }}>
        <defs>
          <marker id="arr-q" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10z" fill="var(--quantum)" /></marker>
          <marker id="arr-c" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10z" fill="var(--classical)" /></marker>
          <clipPath id="plot"><rect x={ox} y={oy} width={plotW} height={plotH} /></clipPath>
        </defs>
        {/* grid & axes */}
        {Array.from({ length: Math.floor(tNs / tStep) + 1 }, (_, i) => i * tStep).map((t) => (
          <g key={`t${t}`}>
            <line x1={ox} x2={ox + plotW} y1={T(t * 1e6)} y2={T(t * 1e6)} stroke="var(--grid)" />
            <text className="tick" x={ox - 6} y={T(t * 1e6) + 3} textAnchor="end">{+t.toFixed(6)}</text>
          </g>
        ))}
        {Array.from({ length: Math.floor((model.xmax - model.xmin) / xStep) + 2 }, (_, i) => Math.ceil(model.xmin / xStep) * xStep + i * xStep)
          .filter((x) => x <= model.xmax).map((x) => (
            <g key={`x${x}`}>
              <line x1={X(x)} x2={X(x)} y1={oy} y2={oy + plotH} stroke="var(--grid)" />
              <text className="tick" x={X(x)} y={oy + plotH + 14} textAnchor="middle">{+x.toFixed(4)}</text>
            </g>
          ))}
        <text x={ox + plotW / 2} y={h - 6} textAnchor="middle" fontSize={11} fill="var(--ink-3)">position x (m)</text>
        <text transform={`translate(14 ${oy + plotH / 2}) rotate(-90)`} textAnchor="middle" fontSize={11} fill="var(--ink-3)">time (ns)</text>
        <rect x={ox} y={oy} width={plotW} height={plotH} fill="none" stroke="var(--rule-strong)" />

        <g clipPath="url(#plot)">
          {/* claimed position */}
          <line x1={X(project.claim.position[0] ?? 0)} x2={X(project.claim.position[0] ?? 0)} y1={oy} y2={oy + plotH}
            stroke="var(--prover)" strokeDasharray="1 4" strokeWidth={1.5} />
          {/* light cones of the challenges */}
          {cones && challenges.map((c) => {
            const x0 = posOf(c.src), t0 = c.depart_time_fs!;
            const dt = (model.tmax - t0) / 1e6;
            const dx = dt / NS_PER_M;
            return (
              <g key={`cone${c.id}`} stroke="var(--ink-3)" strokeDasharray="2 4" strokeWidth={1}>
                <line x1={X(x0)} y1={T(t0)} x2={X(x0 + dx)} y2={T(model.tmax)} />
                <line x1={X(x0)} y1={T(t0)} x2={X(x0 - dx)} y2={T(model.tmax)} />
              </g>
            );
          })}
          {/* worldlines with busy intervals */}
          {project.participants.map((p) => {
            const live = sim.nodes[p.id];
            const x = X(p.position[0]);
            const end = live?.finished ? (live.state_log[live.state_log.length - 1]?.entered_fs ?? now) : now;
            return (
              <g key={p.id}>
                <line x1={x} x2={x} y1={T(0)} y2={T(end)} stroke={`var(--${p.role})`} strokeWidth={1.5} />
                {live?.finished && <line x1={x} x2={x} y1={T(end)} y2={oy} stroke={`var(--${p.role})`} strokeWidth={1} strokeDasharray="1 3" opacity={0.5} />}
                {(live?.history ?? []).filter((hh) => hh.complete_fs > hh.begin_fs).map((hh, i) => (
                  <rect key={i} x={x - 3} width={6} y={T(hh.complete_fs)} height={Math.max(1, T(hh.begin_fs) - T(hh.complete_fs))}
                    fill={`var(--${p.role})`} opacity={0.75}><title>{`${p.id} ${hh.transition}: ${nsLabel(hh.begin_fs)} → ${nsLabel(hh.complete_fs)}`}</title></rect>
                ))}
                {(live?.history ?? []).map((hh, i) => (
                  <circle key={`b${i}`} cx={x} cy={T(hh.begin_fs)} r={2.5} fill="var(--panel)" stroke={`var(--${p.role})`} strokeWidth={1.2}>
                    <title>{`${p.id}: ${hh.from} → ${hh.to} via ${hh.transition} at ${nsLabel(hh.begin_fs)}`}</title>
                  </circle>
                ))}
              </g>
            );
          })}
          {/* deadlines */}
          {model.deadlines.map((d, i) => {
            const xd = posOf(d.node);
            const inward = xd <= (project.claim.position[0] ?? 0);
            return (
              <g key={`d${i}`}>
                <line x1={X(xd) - 12} x2={X(xd) + 12} y1={T(d.t)} y2={T(d.t)} stroke="var(--reject)" strokeWidth={2} />
                <text x={X(xd) + (inward ? 8 : -8)} y={T(d.t) + 13} fontSize={10} fill="var(--reject)" textAnchor={inward ? "start" : "end"}>
                  {compact ? (d.t / 1e6).toFixed(3) : `${d.node} deadline ${nsLabel(d.t, 3)}`}
                </text>
              </g>
            );
          })}
          {/* messages */}
          {sim.messages.filter((mm) => mm.depart_time_fs !== null).map((mm) => {
            const q = mm.kind === "quantum";
            const color = q ? "var(--quantum)" : "var(--classical)";
            const t0 = mm.depart_time_fs!;
            const lost = mm.status === "lost";
            const tArr = mm.arrival_time_fs ?? (t0 + (mm.delay_fs ?? 0));
            const t1 = Math.min(tArr, now);
            const x0 = posOf(mm.src), xd = posOf(mm.dst);
            const f = tArr === t0 ? 1 : (t1 - t0) / (tArr - t0);
            const x1 = x0 + (xd - x0) * f;
            const hl = chain.includes(mm.id) || selMsg === mm.id;
            const op = dim && !hl ? 0.18 : 1;
            const d = `M ${X(x0)} ${T(t0)} L ${X(x1)} ${T(t1)}`;
            return (
              <g key={mm.id} opacity={op} style={{ cursor: "pointer" }} onClick={() => select({ kind: "message", id: mm.id })} data-testid={`st-msg-${mm.id}`}>
                <path d={d} stroke="transparent" strokeWidth={10} fill="none" />
                {q ? (<>
                  <path d={d} stroke={color} strokeWidth={hl ? 5 : 4} fill="none" markerEnd={f >= 1 && !lost ? "url(#arr-q)" : undefined} />
                  <path d={d} stroke="var(--paper)" strokeWidth={hl ? 2 : 1.4} fill="none" />
                </>) : (
                  <path d={d} stroke={color} strokeWidth={hl ? 2.6 : 1.6} fill="none" strokeDasharray={lost ? "3 3" : undefined}
                    markerEnd={f >= 1 && !lost ? "url(#arr-c)" : undefined} />
                )}
                {lost && f >= 1 && <path d={`M ${X(xd) - 5} ${T(tArr) - 5} l 10 10 m 0 -10 l -10 10`} stroke="var(--reject)" strokeWidth={2} />}
                <text x={X(x0) + (X(x1) - X(x0)) * 0.3 + (xd >= x0 ? 6 : -6)} y={T(t0) + (T(t1) - T(t0)) * 0.3 - 4}
                  textAnchor={xd >= x0 ? "start" : "end"} fontSize={10} fill={color} fontFamily="var(--font-code)"
                  paintOrder="stroke" stroke="var(--paper)" strokeWidth={3}>
                  {mm.tag}{mm.kind === "classical" ? `=${JSON.stringify(mm.value)}` : ""}
                </text>
                <title>{`m${mm.id} ${mm.kind} '${mm.tag}' ${mm.src} → ${mm.dst}\ndepart ${nsLabel(t0)}\narrive ${nsLabel(mm.arrival_time_fs)}${lost ? " (lost)" : ""}\n${mm.distance_m.toFixed(6)} m at ${mm.speed_mps} m/s`}</title>
              </g>
            );
          })}
          {/* verdicts */}
          {Object.values(sim.nodes).filter((n) => n.verdict).map((n) => (
            <g key={`v${n.id}`}>
              <circle cx={X(n.position[0])} cy={T(n.verdict.time_fs)} r={6} fill={n.verdict.outcome === "accept" ? "var(--accept)" : "var(--reject)"} stroke="var(--panel)" strokeWidth={1.5}>
                <title>{`${n.id} ${n.verdict.outcome} at ${nsLabel(n.verdict.time_fs)}: ${n.verdict.reason}`}</title>
              </circle>
            </g>
          ))}
        </g>
        {/* participant headers */}
        {project.participants.map((p) => (
          <g key={`h${p.id}`} style={{ cursor: "pointer" }} onClick={() => select({ kind: "participant", id: p.id })}>
            <text x={X(p.position[0])} y={oy - 16} textAnchor="middle" fontSize={12} fontWeight={700} fill={`var(--${p.role})`}>{p.id}</text>
            <text x={X(p.position[0])} y={oy - 4} textAnchor="middle" fontSize={9.5} fill="var(--ink-3)" fontFamily="var(--font-code)">
              {compact ? "" : sim.nodes[p.id]?.state}
            </text>
          </g>
        ))}
        <text x={X(project.claim.position[0] ?? 0)} y={oy + plotH - 6} textAnchor="middle" fontSize={10} fill="var(--prover)">claimed position</text>
        {/* engine time */}
        <line x1={ox} x2={ox + plotW} y1={T(now)} y2={T(now)} stroke="var(--now)" strokeWidth={1} />

      </svg>
    </div>
  );
}

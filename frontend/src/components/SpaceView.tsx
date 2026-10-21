import { useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../store";
import { api } from "../api";
import { C_MPS, niceStep, nsLabel } from "../format";
import { GLOSSARY } from "../glossary";
import type { LightGrid, LightPoint } from "../types";
import { Check, useSize } from "./ui";
import { Spacetime } from "./Spacetime";

type V3 = [number, number, number];
const v3 = (p: number[]): V3 => [p[0] ?? 0, p[1] ?? 0, p[2] ?? 0];
const DEG = Math.PI / 180;
// [yaw, pitch] in degrees for an orthographic camera; pitch 90 looks straight down the z axis
const PRESETS: Record<string, [number, number]> = { top: [0, 90], front: [0, 0], side: [-90, 0], orbit: [-32, 32] };

type GeoMode = "spacetime" | "map" | "3d";
const MODES: [GeoMode, string, string][] = [
  ["spacetime", "Spacetime (x–t)", "Position along x against time: challenges, answers and light cones"],
  ["map", "Map", "Top-down view with the light-cone check"],
  ["3d", "3D", "Orthographic view you can rotate"],
];

/** The geometry canvas: the x-t diagram for 1-D setups, a map for 2-D and a 3-D view for 3-D (switchable). */
export function Geometry() {
  const dim = useStore((s) => s.analysis?.dimension ?? 1);
  const [mode, setMode] = useState<GeoMode | null>(null);
  useEffect(() => setMode(null), [dim]);
  const m = mode ?? (dim >= 3 ? "3d" : dim === 2 ? "map" : "spacetime");
  return (
    <div className="geo">
      <div className="geo-modes" role="tablist" aria-label="Geometry view">
        {MODES.map(([k, label, hint]) => (
          <button key={k} role="tab" aria-selected={m === k} className={`btn ghost${m === k ? " active" : ""}`} title={hint}
            onClick={() => setMode(k)} data-testid={`geo-${k}`}>{label}</button>
        ))}
        <span className="xs muted">{dim}D setup</span>
      </div>
      <div className="geo-body">{m === "spacetime" ? <Spacetime /> : <SpaceView mode={m} key={m} />}</div>
    </div>
  );
}

/** Convex hull of 2-D points (monotone chain), counter-clockwise. */
function hull(pts: [number, number][]): [number, number][] {
  const p = [...pts].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (p.length < 3) return p;
  const cross = (o: number[], a: number[], b: number[]) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const half = (list: [number, number][]) => list.reduce<[number, number][]>((h, q) => {
    while (h.length >= 2 && cross(h[h.length - 2], h[h.length - 1], q) <= 0) h.pop();
    return [...h, q];
  }, []);
  const lower = half(p), upper = half([...p].reverse());
  return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}

/** Shading image of the light-cone grid: red where a lone adversary meets every deadline, green elsewhere. */
function shade(g: LightGrid, theme: string): string {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = g.n;
  const ctx = canvas.getContext("2d")!;
  const css = getComputedStyle(document.documentElement);
  const color = (v: string, a: number) => { ctx.fillStyle = css.getPropertyValue(v).trim() || "#888"; ctx.globalAlpha = a; };
  g.slack_ns.forEach((row, i) => row.forEach((s, j) => {
    color(s >= 0 ? "--reject" : "--accept", s >= 0 ? 0.3 : theme === "dark" ? 0.2 : 0.15);
    ctx.fillRect(j, g.n - 1 - i, 1, 1);  // grid row 0 is the lowest y
  }));
  return canvas.toDataURL();
}

/** Top-down map (x-y) or orthographic 3-D view of the setup, with challenge wavefronts and the light-cone checker. */
export function SpaceView({ mode }: { mode: "map" | "3d" }) {
  const ref = useRef<HTMLDivElement>(null);
  const { w, h } = useSize(ref);
  const project = useStore((s) => s.project)!;
  const sim = useStore((s) => s.sim);
  const analysis = useStore((s) => s.analysis);
  const revision = useStore((s) => s.revision);
  const theme = useStore((s) => s.theme);
  const edit = useStore((s) => s.edit);
  const select = useStore((s) => s.select);
  const vtypes = useStore((s) => s.verifierTypes);
  const [cam, setCam] = useState<[number, number]>(mode === "map" ? PRESETS.top : PRESETS.orbit);
  const [cones, setCones] = useState(true);
  const [shading, setShading] = useState(true);
  const [tau, setTau] = useState<number | null>(null);
  const [z, setZ] = useState<number | null>(null);
  const [grid, setGrid] = useState<LightGrid | null>(null);
  const [probe, setProbe] = useState<LightPoint | null>(null);
  const [atClaim, setAtClaim] = useState<number | null>(null);
  const [drag, setDrag] = useState<{ id: string; pos: V3 } | null>(null);
  const orbit = useRef<{ x: number; y: number; cam: [number, number] } | null>(null);
  useEffect(() => setCam(mode === "map" ? PRESETS.top : PRESETS.orbit), [mode]);

  const claim = v3(project.claim.position);
  const zNow = z ?? claim[2];
  const tauNs = tau ?? analysis?.default_tau_ns ?? 0;
  const tolerance = Math.max(0.5, ...project.participants.map((p) => Number(p.params?.tolerance_ns ?? 0)));
  const map = mode === "map";

  useEffect(() => setProbe(null), [revision, tauNs, zNow]);
  const image = useMemo(() => (grid && !grid.reason ? shade(grid, theme) : null), [grid, theme]);

  const positions = useMemo(() => Object.fromEntries(project.participants.map((p) =>
    [p.id, drag?.id === p.id ? drag.pos : v3(p.position)])), [project, drag]);

  // orthographic camera: yaw about z, then pitch; screen y points up
  const [yaw, pitch] = [cam[0] * DEG, cam[1] * DEG];
  const rot = (p: V3) => {
    const x1 = p[0] * Math.cos(yaw) - p[1] * Math.sin(yaw), y1 = p[0] * Math.sin(yaw) + p[1] * Math.cos(yaw);
    return [x1, y1 * Math.sin(pitch) + p[2] * Math.cos(pitch), y1 * Math.cos(pitch) - p[2] * Math.sin(pitch)] as V3;
  };
  const proj = [...Object.values(positions), claim].map(rot);
  const [minX, maxX] = [Math.min(...proj.map((p) => p[0])), Math.max(...proj.map((p) => p[0]))];
  const [minY, maxY] = [Math.min(...proj.map((p) => p[1])), Math.max(...proj.map((p) => p[1]))];
  const span = Math.max(maxX - minX, maxY - minY, 1e-6);
  const fitW = w - (map && shading ? 310 : 0);  // keep the setup clear of the light-cone panel
  const k = Math.min((fitW - 80) / Math.max(maxX - minX, span * 0.25), (h - 90) / Math.max(maxY - minY, span * 0.25));
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const S = (p: V3) => { const r = rot(p); return [fitW / 2 + (r[0] - cx) * k, h / 2 + 18 - (r[1] - cy) * k] as const; };
  const unS = (sx: number, sy: number): V3 => [cx + (sx - fitW / 2) / k, cy - (sy - h / 2 - 18) / k, zNow];  // top view only
  const round = (x: number) => Math.round(x * 1000) / 1000;
  const visible = map ? [[round(unS(0, 0)[0]), round(unS(w, 0)[0])], [round(unS(0, h)[1]), round(unS(0, 0)[1])]] : null;
  const visibleKey = JSON.stringify(visible);
  useEffect(() => {
    if (!visible || !shading) return;
    let alive = true;
    const t = window.setTimeout(() => {
      api.lightGrid({ n: 96, tau_ns: tauNs, z: zNow, bounds: visible }).then((g) => { if (alive) setGrid(g); }).catch(() => setGrid(null));
      api.lightPoint(claim.slice(0, Math.max(2, project.claim.position.length)), tauNs)
        .then((p) => { if (alive) setAtClaim(p.reason ? null : p.slack_fs); }).catch(() => setAtClaim(null));
    }, 150);
    return () => { alive = false; window.clearTimeout(t); };
  }, [visibleKey, shading, tauNs, zNow, revision]); // eslint-disable-line react-hooks/exhaustive-deps
  // Near the claim the lone-adversary region is about c * slack / 2 across each verifier direction.
  const regionM = atClaim !== null && atClaim >= 0 ? (atClaim / 1e15) * C_MPS / 2 : null;

  const verifiers = project.participants.filter((p) => p.role === "verifier");
  const outline = hull(verifiers.map((p) => S(positions[p.id]) as unknown as [number, number]));
  const now = sim?.now_fs ?? 0;
  const challenges = (sim?.messages ?? []).filter((m) => m.depart_time_fs !== null && m.depart_time_fs <= now
    && verifiers.some((v) => v.id === m.src)).filter((m, i, a) => a.findIndex((o) => o.src === m.src) === i);
  const stepM = niceStep(span, 6);

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!map) orbit.current = { x: e.clientX, y: e.clientY, cam };
  };
  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
    if (drag) setDrag({ id: drag.id, pos: [...unS(e.clientX - r.left, e.clientY - r.top).slice(0, 2), drag.pos[2]] as V3 });
    else if (orbit.current) {
      const o = orbit.current;
      setCam([o.cam[0] + (e.clientX - o.x) * 0.4, Math.max(-90, Math.min(90, o.cam[1] + (e.clientY - o.y) * 0.4))]);
    }
  };
  const onPointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    orbit.current = null;
    if (drag) {
      const d = drag;
      setDrag(null);
      edit((p) => {
        const q = p.participants.find((x) => x.id === d.id)!;
        q.position = q.position.map((c, i) => (i < 2 ? Math.round(d.pos[i] * 1000) / 1000 : c));
      });
    } else if (map && (e.target as Element).tagName === "rect" && (e.target as Element).classList.contains("hit")) {
      const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
      const p = unS(e.clientX - r.left, e.clientY - r.top);
      const dims = project.claim.position.length;
      api.lightPoint(p.slice(0, Math.max(2, dims)), tauNs).then(setProbe).catch(() => setProbe(null));
    }
  };

  const len = (a: V3, b: V3) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  return (
    <div className="canvas-wrap" ref={ref} data-testid={`space-${mode}`}>
      <div className="canvas-tools">
        {!map && Object.entries(PRESETS).map(([name, c]) => (
          <button key={name} className={`btn ghost${cam[0] === c[0] && cam[1] === c[1] ? " active" : ""}`} onClick={() => setCam(c)}>{name}</button>
        ))}
        <Check checked={cones} onChange={setCones} label="Challenge wavefronts" />
        {map && <Check checked={shading} onChange={setShading} label="Light-cone check" />}
      </div>
      {map && shading && (
        <div className="lc-panel" title={GLOSSARY.light_cone}>
          <div className="lc-legend"><span className="sw red" />a lone adversary here meets every deadline<span className="sw green" />timing catches it</div>
          <label className="lc-tau" title={GLOSSARY.tau}>worst-case processing τ {tauNs.toFixed(2)} ns
            <input type="range" min={0} max={tolerance * 2} step={0.01} value={tauNs} onChange={(e) => setTau(Number(e.target.value))} aria-label="Adversary processing time" />
          </label>
          {project.claim.position.length > 2 && (
            <label className="lc-tau">slice at z = {zNow.toFixed(2)} m
              <input type="range" min={claim[2] - span / 2} max={claim[2] + span / 2} step={span / 100} value={zNow} onChange={(e) => setZ(Number(e.target.value))} aria-label="Slice height" />
            </label>
          )}
          <div className="xs" data-testid="lc-region">{atClaim === null ? "" : regionM === null
            ? "Even at the claim a lone adversary with this processing time misses a deadline."
            : `A lone adversary passes only within about ${regionM < 1 ? `${(regionM * 100).toPrecision(2)} cm` : `${regionM.toPrecision(3)} m`} of the claim.`}</div>
          {probe && !probe.reason && (
            <div className={`lc-probe ${probe.can_answer ? "bad" : "good"}`} data-testid="lc-probe">
              <b>({probe.point.map((c) => c.toFixed(2)).join(", ")}) m: </b>
              {probe.can_answer
                ? `a lone adversary here answers every verifier in time, ${(probe.slack_fs / 1e6).toFixed(3)} ns to spare.`
                : `a lone adversary here misses ${probe.binding}'s deadline by ${(-probe.slack_fs / 1e6).toFixed(3)} ns.`}
              <div className="xs">{probe.per_verifier.map((v) => `${v.id} ${v.slack_fs >= 0 ? "+" : ""}${(v.slack_fs / 1e6).toFixed(3)} ns`).join(" · ")}</div>
            </div>
          )}
          <div className="xs muted">Click the map to test a point. Adversary signals travel at the vacuum speed of light; send times and deadlines are the engine's own (clocks included). Colluding attackers on the verifier-to-claim lines always meet the timing, which is why QPV relies on the qubit.</div>
          {grid?.reason && <div className="xs" style={{ color: "var(--reject)" }}>{grid.reason}</div>}
        </div>
      )}
      <svg width={w} height={h} style={{ position: "absolute", inset: 0, cursor: map ? "crosshair" : "grab" }} role="img"
        aria-label={map ? "Top-down map of the setup" : "Three-dimensional view of the setup"}
        onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerLeave={() => { orbit.current = null; }}>
        <rect className="hit" x={0} y={0} width={w} height={h} fill="transparent" />
        {map && image && grid && (() => {
          const [x0, y0] = S([grid.bounds[0][0], grid.bounds[1][1], zNow]), [x1, y1] = S([grid.bounds[0][1], grid.bounds[1][0], zNow]);
          return <image href={image} x={x0} y={y0} width={x1 - x0} height={y1 - y0} preserveAspectRatio="none" pointerEvents="none" data-testid="lc-shading" />;
        })()}
        {map && Array.from({ length: 13 }, (_, i) => (Math.round(cx / stepM) + i - 6) * stepM).map((g) => (
          <g key={g} pointerEvents="none">
            <line x1={S([g, -1e4, zNow])[0]} x2={S([g, 1e4, zNow])[0]} y1={0} y2={h} stroke="var(--grid)" />
            <line y1={S([0, g, zNow])[1]} y2={S([0, g, zNow])[1]} x1={0} x2={w} stroke="var(--grid)" />
          </g>
        ))}
        {outline.length > 2 && <polygon points={outline.map((q) => q.join(",")).join(" ")} fill="none" stroke="var(--verifier)"
          strokeDasharray="5 4" opacity={0.6} pointerEvents="none"><title>{GLOSSARY.hull}</title></polygon>}
        {project.links.map((l) => {
          const [a, b] = [positions[l.a.node], positions[l.b.node]];
          if (!a || !b) return null;
          const [p, q] = [S(a), S(b)];
          const live = drag && (l.a.node === drag.id || l.b.node === drag.id);
          const q2 = l.kind === "quantum";
          return (
            <g key={l.id} pointerEvents="none">
              <line x1={p[0]} y1={p[1]} x2={q[0]} y2={q[1]} stroke={q2 ? "var(--quantum)" : "var(--classical)"}
                strokeWidth={q2 ? 3 : 1.4} strokeDasharray={q2 ? undefined : "6 4"} opacity={0.55} />
              {live && <text x={(p[0] + q[0]) / 2} y={(p[1] + q[1]) / 2 - 6} textAnchor="middle" fontSize={10} fill="var(--ink)"
                fontFamily="var(--font-code)">{len(a, b).toFixed(3)} m · {nsLabel(Math.ceil((len(a, b) / C_MPS) * 1e15), 3)}</text>}
            </g>
          );
        })}
        {cones && challenges.map((m) => {
          const r = ((now - m.depart_time_fs!) / 1e15) * C_MPS * k;
          const [x, y] = S(positions[m.src]);
          return <circle key={m.id} cx={x} cy={y} r={r} fill="none" stroke={m.kind === "quantum" ? "var(--quantum)" : "var(--classical)"}
            strokeDasharray="2 4" opacity={0.7} pointerEvents="none"><title>{`light cone of ${m.src}'s challenge`}</title></circle>;
        })}
        {(sim?.messages ?? []).filter((m) => m.depart_time_fs !== null && m.depart_time_fs <= now && (m.arrival_time_fs ?? Infinity) > now
          && m.status !== "lost").map((m) => {
          const end = m.arrival_time_fs ?? m.depart_time_fs! + (m.delay_fs ?? 1);
          const f = Math.min(1, (now - m.depart_time_fs!) / Math.max(1, end - m.depart_time_fs!));
          const [a, b] = [S(positions[m.src]), S(positions[m.dst])];
          return <circle key={m.id} cx={a[0] + (b[0] - a[0]) * f} cy={a[1] + (b[1] - a[1]) * f} r={5}
            fill={m.kind === "quantum" ? "var(--quantum)" : "var(--classical)"} stroke="var(--panel)" strokeWidth={1.5}
            style={{ cursor: "pointer" }} onClick={() => select({ kind: "message", id: m.id })} />;
        })}
        {(() => { const [x, y] = S(claim); return (
          <g pointerEvents="none"><path d={`M ${x - 7} ${y} h 14 M ${x} ${y - 7} v 14`} stroke="var(--prover)" strokeWidth={1.5} />
            <text x={x + 9} y={y + 14} fontSize={10} fill="var(--prover)">claimed position</text></g>); })()}
        {map && shading && regionM !== null && (() => { const [x, y] = S(claim); return (
          <circle cx={x} cy={y} r={Math.max(4, regionM * k)} fill="none" stroke="var(--reject)" strokeWidth={1.5} strokeDasharray="3 2"
            pointerEvents="none" data-testid="lc-ring"><title>{GLOSSARY.light_cone}</title></circle>); })()}
        {probe && (() => { const [x, y] = S(v3(probe.point)); return (
          <circle cx={x} cy={y} r={5} fill="none" stroke={probe.can_answer ? "var(--reject)" : "var(--accept)"} strokeWidth={2} pointerEvents="none" />); })()}
        {[...project.participants].sort((a, b) => rot(positions[b.id])[2] - rot(positions[a.id])[2]).map((p) => {
          const [x, y] = S(positions[p.id]);
          const vtype = p.verifier_type ?? vtypes[p.id];
          const live = sim?.nodes[p.id];
          return (
            <g key={p.id} style={{ cursor: map ? "move" : "pointer" }} data-testid={`space-node-${p.id}`}
              onPointerDown={(e) => { e.stopPropagation(); select({ kind: "participant", id: p.id }); if (map) setDrag({ id: p.id, pos: positions[p.id] }); }}>
              <title>{`${p.id}: ${vtype ? GLOSSARY[`${vtype}_verifier`] : GLOSSARY[p.role]}`}</title>
              {p.role === "verifier"
                ? <rect x={x - 7} y={y - 7} width={14} height={14} rx={2} fill="var(--panel)" strokeWidth={2.2}
                    stroke={vtype === "quantum" ? "var(--quantum)" : vtype === "classical" ? "var(--classical)" : "var(--verifier)"} />
                : <circle cx={x} cy={y} r={6.5} fill={`var(--${p.role})`} stroke="var(--panel)" strokeWidth={1.5} />}
              {p.role === "verifier" && <rect x={x - 3} y={y - 3} width={6} height={6} fill="var(--verifier)" />}
              <text x={x} y={y - 12} textAnchor="middle" fontSize={11} fontWeight={700} fill={`var(--${p.role})`}>{p.id}</text>
              {live?.verdict && <circle cx={x + 10} cy={y + 9} r={4} fill={live.verdict.outcome === "accept" ? "var(--accept)" : "var(--reject)"} />}
            </g>
          );
        })}
        <g transform={`translate(16 ${h - 16})`} pointerEvents="none">
          <line x1={0} x2={stepM * k} y1={0} y2={0} stroke="var(--ink-2)" strokeWidth={1.5} />
          <text x={0} y={-5} fontSize={10} fill="var(--ink-3)">{+stepM.toPrecision(3)} m{map ? ` · x → , y ↑${project.claim.position.length > 2 ? ` · slice z = ${zNow.toFixed(2)} m` : ""}` : ` · drag to rotate`}</text>
        </g>
        {!map && <g transform={`translate(${w - 60} ${h - 60})`} pointerEvents="none">
          {([[1, 0, 0], [0, 1, 0], [0, 0, 1]] as V3[]).map((axis, i) => {
            const r = rot(axis);
            return <g key={i}><line x1={0} y1={0} x2={r[0] * 26} y2={-r[1] * 26} stroke="var(--ink-3)" strokeWidth={1.2} />
              <text x={r[0] * 34} y={-r[1] * 34 + 3} textAnchor="middle" fontSize={10} fill="var(--ink-2)">{"xyz"[i]}</text></g>;
          })}
        </g>}
        <text x={w - 12} y={h - 12} textAnchor="end" fontSize={10} fill="var(--now)" pointerEvents="none">engine time {nsLabel(now, 3)}</text>
      </svg>
    </div>
  );
}

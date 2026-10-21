// Formatting helpers. Times arrive from the engine as integer femtoseconds.

export const FS_PER_NS = 1_000_000;
export const C_MPS = 299_792_458;  // vacuum speed of light, exact
export const NS_PER_M = 1e9 / C_MPS;

/** A round axis step (1, 2 or 5 times a power of ten) giving about `target` ticks over `range`. */
export function niceStep(range: number, target: number): number {
  const raw = range / target;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
}

export function ns(fs: number | null | undefined, digits = 6): string {
  if (fs === null || fs === undefined) return "—";
  return (fs / FS_PER_NS).toFixed(digits);
}

export function nsLabel(fs: number | null | undefined, digits = 6): string {
  return fs === null || fs === undefined ? "—" : `${ns(fs, digits)} ns`;
}

export function short(v: unknown, max = 60): string {
  const s = typeof v === "string" ? v : JSON.stringify(v);
  if (s === undefined) return "";
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

export const ROLE_COLOR: Record<string, string> = {
  verifier: "var(--verifier)", prover: "var(--prover)", adversary: "var(--adversary)", other: "var(--other)",
};

export const KIND_COLOR: Record<string, string> = {
  "msg.send": "var(--classical)", "msg.deliver": "var(--classical)", "msg.loss": "var(--reject)",
  "msg.refused": "var(--reject)", "transition.begin": "var(--ink-2)", "transition.complete": "var(--ink)",
  "timer.set": "var(--ink-3)", "timer.fire": "var(--warn)", "timer.cancel": "var(--ink-3)",
  verdict: "var(--verifier)", "node.finish": "var(--ink)", "capability.violation": "var(--reject)",
  "protocol.error": "var(--reject)", "guards.rejected": "var(--warn)", "sim.stop": "var(--ink)",
};

export function uniqueId(base: string, taken: Iterable<string>): string {
  const set = new Set(taken);
  if (!set.has(base)) return base;
  for (let i = 2; ; i++) if (!set.has(`${base}${i}`)) return `${base}${i}`;
}

export function clone<T>(x: T): T {
  return JSON.parse(JSON.stringify(x));
}

// Set a value inside a document addressed by a dotted path where list items may
// be addressed by their `id` (mirrors qpvsim.protocol.project.set_path).
export function setPath(doc: any, path: string, value: any): void {
  const segs = path.split(".");
  let obj = doc;
  for (let i = 0; i < segs.length - 1; i++) obj = step(obj, segs[i], true);
  const last = segs[segs.length - 1];
  if (Array.isArray(obj)) {
    const idx = /^\d+$/.test(last) ? Number(last) : obj.findIndex((x: any) => x?.id === last);
    obj[idx] = value;
  } else obj[last] = value;
}

function step(obj: any, key: string, create: boolean): any {
  if (Array.isArray(obj)) {
    if (/^\d+$/.test(key)) return obj[Number(key)];
    const found = obj.find((x: any) => x?.id === key);
    if (!found) throw new Error(`no item ${key}`);
    return found;
  }
  if (obj[key] === undefined && create) obj[key] = {};
  return obj[key];
}

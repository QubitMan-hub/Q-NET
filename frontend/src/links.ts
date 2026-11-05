import type { Recipe } from "./types";

// Shareable links: #scenario=<gallery id>, #recipe=<any scenario as base64url JSON>, #present=<ids or all>.
function b64url(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  bytes.forEach((b) => { bin += String.fromCharCode(b); });
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function unb64url(s: string): string {
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/"));
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

const here = () => `${window.location.origin}${window.location.pathname}`;

export function recipeLink(r: Recipe): string {
  return `${here()}#recipe=${b64url(JSON.stringify(r))}`;
}
export function scenarioLink(id: string): string {
  return `${here()}#scenario=${id}`;
}
export function presentLink(ids: string[] | "all"): string {
  return `${here()}#present=${ids === "all" ? "all" : ids.join(",")}`;
}
export function recipeFromHash(): Recipe | null {
  const m = window.location.hash.match(/recipe=([\w-]+)/);
  if (!m) return null;
  try {
    const r = JSON.parse(unb64url(m[1]));
    return r && typeof r === "object" && r.base ? r : null;
  } catch { return null; }
}
export function presentFromHash(): string[] | "all" | null {
  const m = window.location.hash.match(/present=([\w,-]+)/);
  if (!m) return null;
  return m[1] === "all" ? "all" : m[1].split(",").filter(Boolean);
}
export async function copyText(text: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}

/** A probability in words, like the engine's: 100%, 37%, about 1 in 830,000. */
export function describeChance(p: number): string {
  if (p >= 0.9995) return p >= 1 - 1e-12 ? "100%" : `${(100 * p).toFixed(3)}%`;
  if (p >= 0.01) return `${Math.round(100 * p)}%`;
  if (p <= 0) return "never";
  if (p < 1e-15) return "practically never";
  return `about 1 in ${Math.round(1 / p).toLocaleString("en-US")}`;
}

export function testRule(t: { rounds: number; min_correct: number; min_answered: number }): string {
  const parts = [`${t.rounds} rounds`];
  if (t.min_answered > 0) parts.push(`at least ${Math.round(100 * t.min_answered)}% answered`);
  parts.push(t.min_correct >= 1 ? "every answer right" : `${(100 * t.min_correct).toFixed(1).replace(/\.0$/, "")}% of answers right`);
  return parts.join(", ");
}

export function download(text: string, filename: string, mime: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: mime }));
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

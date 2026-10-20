// End-to-end UI test: drives the real UI against a running `qpv serve` and
// checks that what the UI displays equals what the engine API reports.
//
//   qpv serve --port 8765 &   then   node e2e/run.mjs [http://127.0.0.1:8765] [screenshot-dir]
//
// Uses the Playwright installation available on the machine (global or local).
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";

const require = createRequire(import.meta.url);
let chromium;
for (const p of ["playwright", "/opt/node22/lib/node_modules/playwright"]) {
  try { ({ chromium } = require(p)); break; } catch { /* try next */ }
}
if (!chromium) { console.error("playwright not found"); process.exit(2); }

const BASE = process.argv[2] ?? "http://127.0.0.1:8765";
const SHOTS = process.argv[3] ?? "e2e/screenshots";
mkdirSync(SHOTS, { recursive: true });

const failures = [];
const check = (cond, msg) => { if (!cond) { failures.push(msg); console.error("FAIL", msg); } else console.log("ok  ", msg); };
const api = async (path, init) => (await fetch(BASE + path, init)).json();
const post = (path, body = {}) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const fmt = (fs) => `${(fs / 1e6).toFixed(6)} ns`;

const launchOpts = { headless: true };
try { require("node:fs").accessSync("/opt/pw-browsers/chromium"); } catch { /* default */ }
const browser = await chromium.launch(launchOpts).catch(() => chromium.launch({ ...launchOpts, executablePath: "/opt/pw-browsers/chromium" }));
const page = await browser.newPage({ viewport: { width: 1600, height: 960 } });
const consoleErrors = [];
page.on("pageerror", (e) => consoleErrors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });

await post("/api/project/example/qpv_bb84_honest");
await page.goto(BASE);
await page.waitForSelector('[data-testid="node-V0"]');
await page.waitForTimeout(400);
check((await page.textContent('[data-testid="clock"]')).trim() === "0.000000 ns", "initial clock shows engine t = 0");
await page.screenshot({ path: `${SHOTS}/01-network.png` });

// Step 5 events via the UI and compare with the engine
for (let i = 0; i < 5; i++) await page.click('[data-testid="btn-step"]');
await page.waitForTimeout(300);
let st = await api("/api/sim/state");
check(st.events_executed === 5, `engine executed exactly 5 events after 5 UI steps (got ${st.events_executed})`);
check((await page.textContent('[data-testid="clock"]')).trim() === fmt(st.now_fs), "UI clock equals engine clock after stepping");

// Run to completion
await page.click('[data-testid="btn-run"]');
await page.waitForTimeout(500);
st = await api("/api/sim/state");
check(st.stopped && st.decision.outcome === "accept", "engine run finished with ACCEPT for the honest prover");
check((await page.textContent('[data-testid="outcome"]')).trim() === "accepted", "UI outcome pill matches engine decision");
check((await page.textContent('[data-testid="clock"]')).trim() === fmt(st.now_fs), "UI clock equals engine clock after run");
const nodeState = (await page.textContent('[data-testid="node-V0"] .state-badge')).trim();
check(nodeState === st.nodes.V0.state, `V0 node badge shows engine state '${st.nodes.V0.state}'`);

// Event log rows equal trace length
await page.click('[data-testid="dock-events"]');
const rows = await page.$$eval("table.grid tbody tr", (trs) => trs.filter((t) => !t.style.opacity).length);
check(rows === st.trace_length, `event log shows all ${st.trace_length} trace records (got ${rows})`);
await page.screenshot({ path: `${SHOTS}/02-network-run.png` });

// Spacetime view: one path per departed message
await page.keyboard.press("3");
await page.waitForTimeout(300);
const stMsgs = await page.$$('[data-testid^="st-msg-"]');
check(stMsgs.length === st.messages.filter((m) => m.depart_time_fs !== null).length, "spacetime diagram draws every departed message");
await page.click('[data-testid="st-msg-3"]');
await page.waitForTimeout(400);
check((await page.textContent('[data-testid="inspector"]')).includes("Causal path"), "clicking a message opens its causal path");
await page.screenshot({ path: `${SHOTS}/03-spacetime.png` });

// Automaton view for V0 shows engine transition counts
await page.keyboard.press("2");
await page.waitForTimeout(400);
const fired = await page.$$eval('[data-testid^="transition-"] .count', (els) => els.length);
check(fired === st.nodes.V0.history.length, `automaton view marks ${st.nodes.V0.history.length} fired transitions (got ${fired})`);
await page.click('[data-testid="transition-accept"]');
await page.waitForTimeout(200);
await page.screenshot({ path: `${SHOTS}/04-automaton.png` });

// Edit through the inspector: raise prover processing above tolerance -> reject
await page.keyboard.press("1");
await page.click('[data-testid="node-P"]');
await page.waitForTimeout(200);
const input = page.locator('.field:has(label:text("Processing (ns)")) input');
await input.fill("0.9");
await input.press("Enter");
await page.waitForTimeout(700);
const proj = await api("/api/project");
check(proj.project.participants.find((p) => p.id === "P").processing_ns === 0.9, "inspector edit reached the engine project");
await page.click('[data-testid="btn-run"]');
await page.waitForTimeout(500);
st = await api("/api/sim/state");
check(st.decision.outcome === "reject", "engine rejects when processing exceeds tolerance");
check((await page.textContent('[data-testid="outcome"]')).trim() === "rejected", "UI shows the rejection");

// Undo restores the accepted configuration
await page.click("body", { position: { x: 5, y: 900 } }).catch(() => {});
await page.keyboard.press("Control+z");
await page.waitForTimeout(700);
await page.click('[data-testid="btn-run"]');
await page.waitForTimeout(500);
st = await api("/api/sim/state");
check(st.decision.outcome === "accept", "undo restores the accepted configuration");

// Console drives the engine
await page.click('[data-testid="dock-console"]');
await page.fill('[data-testid="console-input"]', "load example qpv_bb84_teleportation_attack");
await page.press('[data-testid="console-input"]', "Enter");
await page.waitForTimeout(600);
await page.fill('[data-testid="console-input"]', "run");
await page.press('[data-testid="console-input"]', "Enter");
await page.waitForTimeout(600);
await page.fill('[data-testid="console-input"]', "decision");
await page.press('[data-testid="console-input"]', "Enter");
await page.waitForTimeout(600);
st = await api("/api/sim/state");
const out = await page.textContent('[data-testid="console-out"]');
check(st.decision.outcome === "accept" && out.includes("Position claim ACCEPTED"), "console run + decision reflect the engine (teleportation attack accepted)");
check((await page.textContent('[data-testid="outcome"]')).trim() === "accepted", "toolbar follows console-driven runs");
await page.screenshot({ path: `${SHOTS}/05-console.png` });

// Experiments: run a small sweep and compare against the API job result
await post("/api/project/example/qpv_bb84_collusion_unentangled");
await page.reload();
await page.waitForSelector('[data-testid="node-E0"]');
await page.click('[data-testid="dock-experiments"]');
const runs = page.locator('.field:has(label:text("Runs per point")) input');
await runs.fill("300");
await runs.press("Enter");
await page.click('button:text("Run experiment")');
await page.waitForSelector("text=done in", { timeout: 60000 });
await page.waitForTimeout(300);
const tableText = await page.textContent(".exp-main table.grid");
check(/breidbart/.test(tableText) && /0\.\d{4}/.test(tableText), "experiment results table rendered from the job result");
await page.screenshot({ path: `${SHOTS}/06-experiments.png` });

// Spacetime of the attack, timeline and decision panels
await page.keyboard.press("3");
await page.click('[data-testid="btn-run"]');
await page.waitForTimeout(500);
await page.click('[data-testid="dock-timeline"]');
await page.waitForTimeout(300);
await page.screenshot({ path: `${SHOTS}/07-attack-spacetime-timeline.png` });
await page.click('[data-testid="dock-decision"]');
await page.waitForTimeout(300);
await page.screenshot({ path: `${SHOTS}/08-decision.png` });

check(consoleErrors.length === 0, `no browser errors (${consoleErrors.slice(0, 3).join(" | ")})`);
await browser.close();
if (failures.length) { console.error(`${failures.length} check(s) failed`); process.exit(1); }
console.log("all UI/engine synchronisation checks passed");

// Full-surface audit of a running workbench (live GitHub Pages or local):
// every example x every view/tab, playback, console, editing, themes, viewports.
// Reports browser errors, failed requests and broken UI states.
//   node e2e/audit.mjs https://qubitman-hub.github.io/Q-NET/ [screenshot-dir]
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
let chromium;
for (const p of ["playwright", "/opt/node22/lib/node_modules/playwright"]) {
  try { ({ chromium } = require(p)); break; } catch { /* next */ }
}
const URL_ = process.argv[2] ?? "https://qubitman-hub.github.io/Q-NET/";
const SHOTS = process.argv[3] ?? "e2e/screenshots/audit";
mkdirSync(SHOTS, { recursive: true });
const host = new URL(URL_).hostname;
const proxy = process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY, bypass: `127.0.0.1,localhost${/^\d/.test(host) ? "," + host : ""}` } : undefined;
const findings = [];
const note = (area, msg) => { findings.push(`${area}: ${msg}`); console.log("ISSUE", area, "-", msg); };
const browser = await chromium.launch({ headless: true, proxy });
const ctx = await browser.newContext({ viewport: { width: 1600, height: 940 }, ignoreHTTPSErrors: true, acceptDownloads: true });
const page = await ctx.newPage();
let area = "boot";
page.on("pageerror", (e) => note(area, `pageerror ${String(e).slice(0, 200)}`));
page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") note(area, `console.${m.type()} ${m.text().slice(0, 200)}`); });
page.on("requestfailed", (r) => note(area, `request failed ${r.url().slice(0, 100)} ${r.failure()?.errorText}`));
page.on("response", (r) => { if (r.status() >= 400) note(area, `HTTP ${r.status()} ${r.url().slice(0, 100)}`); });

const t0 = Date.now();
await page.goto(URL_);
await page.waitForSelector('[data-testid="node-V0"]', { timeout: 240000 });
console.log(`booted in ${((Date.now() - t0) / 1000).toFixed(1)} s`);
await page.screenshot({ path: `${SHOTS}/00-boot.png` });

// first-visit start screen: every ready-made scenario runs and opens the right geometry view
area = "start";
// a decision of the current project's run (the pill and the project carry the engine revision they belong to)
const decided = () => page.waitForFunction(() => {
  const pill = document.querySelector('[data-testid="outcome"]');
  return pill?.getAttribute("data-rev") === document.querySelector(".project-name")?.getAttribute("data-rev")
    && ["accepted", "rejected"].includes(pill?.textContent?.trim() ?? "");
}, null, { timeout: 60000 });
if (!(await page.$('[data-testid="start-screen"]'))) note(area, "start screen not shown on first visit");
await page.screenshot({ path: `${SHOTS}/01-start.png` });
for (const d of [1, 2, 3]) for (const who of ["honest", "unentangled", "teleport"]) {
  area = `start ${d}d_${who}`;
  if (!(await page.$('[data-testid="start-screen"]'))) await page.click('button[aria-label="Getting started"]');
  const rev = await page.getAttribute(".project-name", "data-rev");
  await page.click(`[data-testid="start-${d}d_${who}"]`);
  await page.waitForFunction((r) => document.querySelector(".project-name")?.getAttribute("data-rev") !== r, rev, { timeout: 60000 }).catch(() => {});
  await decided().catch(() => note(area, "run did not finish with a decision"));
  const want = d === 1 ? '[data-testid^="st-msg-"]' : d === 2 ? '[data-testid="space-map"]' : '[data-testid="space-3d"]';
  await page.waitForSelector(want, { timeout: 10000 }).catch(() => note(area, `geometry view ${want} not shown`));
  const out = (await page.textContent('[data-testid="outcome"]')).trim();
  if (who !== "unentangled" && out !== "accepted") note(area, `expected accepted, got ${out}`);
  await page.click('[data-testid="dock-timing"]');
  await page.waitForSelector('[data-testid="timing-panel"] tbody tr', { timeout: 10000 }).catch(() => note(area, "timing panel empty"));
}
area = "scenario builder";
await page.click('[data-testid="btn-new"]');
await page.click('[data-testid="scenario-dialog"] button[role="radio"]:text-is("3D")');
await page.click('[data-testid="scenario-run"]');
await decided().catch(() => note(area, "built 3D scenario did not finish"));
await page.waitForSelector('[data-testid="space-3d"]', { timeout: 10000 }).catch(() => {});
if ((await page.locator('[data-testid^="space-node-"]').count()) !== 5) note(area, "3D builder did not create 4 verifiers and a prover");
area = "attack switcher";
for (const who of ["unentangled", "teleport", "guess", "displaced", "honest"]) {
  await page.selectOption('[data-testid="attack-switch"]', who);
  await decided().catch(() => note(area, `${who} did not rerun`));
  await page.waitForTimeout(300);
}
if ((await page.textContent('[data-testid="outcome"]')).trim() !== "accepted") note(area, "switching back to the honest prover did not accept");
area = "compare";
await page.click('[data-testid="dock-compare"]');
await page.click('[data-testid="compare-panel"] button:text("Compare (200 runs each)")');
await page.waitForSelector('[data-testid="compare-panel"] table.grid tbody tr', { timeout: 180000 }).catch(() => note(area, "compare results not shown"));
await page.screenshot({ path: `${SHOTS}/02-compare.png` });

const examples = await page.$$eval('select[aria-label="Open example"] option', (os) => os.map((o) => o.value).filter(Boolean));
const outcome = () => page.textContent('[data-testid="outcome"]').then((t) => t.trim());
for (const ex of examples) {
  area = `example ${ex}`;
  await page.selectOption('select[aria-label="Open example"]', ex);
  await page.waitForFunction((ex) => document.querySelector('[data-testid="clock"]')?.textContent?.startsWith("0.000000"), ex, { timeout: 30000 }).catch(() => note(area, "clock did not reset to 0 after loading"));
  await page.waitForTimeout(300);
  // step a few events, then play briefly, then run to end
  for (let i = 0; i < 3; i++) await page.click('[data-testid="btn-step"]');
  await page.waitForTimeout(300);
  await page.click('[data-testid="btn-play"]');
  await page.waitForTimeout(1200);
  await page.click('[data-testid="btn-play"]').catch(() => {});
  await page.click('[data-testid="btn-run"]').catch(() => {});
  await page.waitForFunction(() => ["accepted", "rejected"].includes(document.querySelector('[data-testid="outcome"]')?.textContent?.trim() ?? ""), null, { timeout: 30000 })
    .catch(() => note(area, "run did not finish with a decision"));
  const out = await outcome();
  for (const [key, view] of [["1", "network"], ["2", "automaton"], ["3", "spacetime"]]) {
    area = `example ${ex} / ${view}`;
    await page.keyboard.press(key);
    await page.waitForTimeout(350);
  }
  for (const tab of ["events", "timeline", "timing", "console", "experiments", "compare", "validation", "decision"]) {
    area = `example ${ex} / tab ${tab}`;
    await page.click(`[data-testid="dock-${tab}"]`);
    await page.waitForTimeout(250);
  }
  await page.screenshot({ path: `${SHOTS}/ex-${ex}.png` });
  console.log(`${ex}: ${out}`);
}

// inspector across selections
area = "inspector";
await page.selectOption('select[aria-label="Open example"]', "qpv_bb84_teleportation_attack");
await page.waitForTimeout(800);
await page.click('[data-testid="btn-run"]');
await page.waitForTimeout(800);
await page.keyboard.press("1");
for (const id of ["V0", "E0", "E1", "V1"]) { await page.click(`[data-testid="node-${id}"] .head`); await page.waitForTimeout(200); }
await page.click('[data-testid="link-q0"]').catch(() => note(area, "could not select link q0"));
await page.waitForTimeout(200);
await page.keyboard.press("2");
await page.waitForTimeout(400);
const tlabel = await page.$('[data-testid^="transition-"]');
if (tlabel) { await tlabel.click(); await page.waitForTimeout(250); } else note(area, "no transition labels in automaton view");
const sn = await page.$('[data-testid^="state-"]');
if (sn) { await sn.click(); await page.waitForTimeout(250); }
await page.keyboard.press("3");
await page.waitForTimeout(300);
const msg = await page.$('[data-testid^="st-msg-"]');
if (msg) { await msg.click(); await page.waitForTimeout(600); } else note(area, "no messages in spacetime");
await page.click('[data-testid="dock-events"]');
const row = await page.$("table.grid tbody tr");
if (row) { await row.click(); await page.waitForTimeout(250); }
await page.screenshot({ path: `${SHOTS}/inspector.png` });

// console
area = "console";
await page.click('[data-testid="dock-console"]');
for (const c of ["help", "participants", "node E0", "fsm E1", "queue", "chain 6", "decision", "invariants", "time", "links", "messages", "events last=5", "timing", "geometry", "strategies", "strategy E0", "profiles", "help set", "timing", "lightcone 0 0", "scenario 2d_unentangled", "attack teleport", "autowire", "compare runs=20",
  "sweep noise 0 0.4 steps=2 runs=20", "load example qpv_bb84_collusion_unentangled", "reset", "run until=15", "step 2", "run", "why", "nonsense", "node", "batch 30 sweep=participants.E0.processing_ns:0,0.6"]) {
  await page.fill('[data-testid="console-input"]', c);
  await page.press('[data-testid="console-input"]', "Enter");
  await page.waitForFunction(() => !document.querySelector(".cx-entry.running"), null, { timeout: 60000 }).catch(() => note(area, `'${c}' did not finish`));
}
const errs = await page.$$eval(".cx-entry.error .cx-cmd", (els) => els.map((e) => e.textContent));
const expectedErr = ["nonsense", "node"];
for (const e of errs) if (!expectedErr.includes(e)) note(area, `command '${e}' failed`);
await page.screenshot({ path: `${SHOTS}/console.png` });

// validation + experiments + downloads
area = "validation";
await page.click('[data-testid="dock-validation"]');
await page.click('button:text("Check current trace")');
await page.waitForTimeout(800);
if (!(await page.textContent(".panel-body, body")).includes("invariants hold")) note(area, "invariant check did not report success");
area = "experiments";
await page.click('[data-testid="dock-experiments"]');
await page.locator('.field:has(label:text("Runs per point")) input').fill("40");
await page.locator('.field:has(label:text("Runs per point")) input').press("Enter");
await page.click('button:text("Run experiment")');
await page.waitForSelector("text=done in", { timeout: 120000 }).catch(() => note(area, "experiment did not finish"));
for (const b of ["Download CSV", "Download raw runs"]) {
  const dl = await Promise.all([page.waitForEvent("download", { timeout: 15000 }), page.click(`button:text("${b}")`)]).catch(() => null);
  if (!dl) note(area, `${b} produced no download`);
}
await page.screenshot({ path: `${SHOTS}/experiments.png` });

// editing: new project, drop participants, undo/redo, save
area = "editing";
await page.click('[data-testid="btn-new"]');
await page.click('[data-testid="btn-blank"]');
await page.waitForTimeout(800);
if (!(await page.$(".canvas-wrap .react-flow"))) note(area, "New did not switch to the network canvas");
const dt = await page.evaluateHandle(() => new DataTransfer());
await page.dispatchEvent('.palette-item:has-text("Verifier")', "dragstart", { dataTransfer: dt });
await page.dispatchEvent(".canvas-wrap", "drop", { dataTransfer: dt, clientX: 600, clientY: 300 });
await page.waitForTimeout(700);
if (!(await page.$('[data-testid="node-V"]'))) note(area, "dropped verifier not shown");
await page.keyboard.press("Escape");
await page.keyboard.press("Control+z");
await page.waitForTimeout(700);
await page.keyboard.press("Control+Shift+z");
await page.waitForTimeout(700);
const save = await Promise.all([page.waitForEvent("download", { timeout: 15000 }), page.click('[data-testid="btn-save"]')]).catch(() => null);
if (!save) note(area, "Save produced no download");

// persistence and shared links
area = "persistence";
const before = await page.inputValue('input[aria-label="Project name"]');
await page.reload();
await page.waitForSelector('[data-testid="btn-run"]', { timeout: 240000 });
await page.waitForTimeout(800);
const after = await page.inputValue('input[aria-label="Project name"]');
if (/github\.io|:8800/.test(URL_) && after !== before) note(area, `project not restored after reload ('${before}' -> '${after}')`);
area = "shared link";
await page.goto(URL_ + "#example=cpv_collusion");
await page.waitForSelector('[data-testid="node-E0"]', { timeout: 240000 }).catch(() => note(area, "#example=cpv_collusion did not load the example"));

// theme + viewports
area = "dark theme";
await page.selectOption('select[aria-label="Open example"]', "qpv_bb84_collusion_unentangled");
await page.waitForTimeout(800);
await page.click('[data-testid="btn-run"]');
await page.click('button[title="Toggle dark theme"]');
await page.keyboard.press("3");
await page.waitForTimeout(500);
await page.screenshot({ path: `${SHOTS}/dark.png` });
for (const [w, h] of [[1366, 768], [1024, 700], [390, 844]]) {
  area = `viewport ${w}x${h}`;
  await page.setViewportSize({ width: w, height: h });
  await page.waitForTimeout(500);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (overflow > 2) note(area, `horizontal overflow ${overflow}px`);
  await page.screenshot({ path: `${SHOTS}/vp-${w}.png` });
}
await browser.close();
console.log(`\n${findings.length} finding(s)`);
for (const f of findings) console.log(" -", f);
process.exit(findings.length ? 1 : 0);

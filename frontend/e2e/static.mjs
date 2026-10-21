// Smoke test of the static (GitHub Pages) build: the engine runs in the browser via Pyodide.
//   node e2e/static.mjs http://127.0.0.1:8800/Q-NET/ [screenshot-dir]
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let chromium;
for (const p of ["playwright", "/opt/node22/lib/node_modules/playwright"]) {
  try { ({ chromium } = require(p)); break; } catch { /* next */ }
}
const URL_ = process.argv[2] ?? "http://127.0.0.1:8800/Q-NET/";
// Behind an HTTP proxy, serve on a non-loopback address: Playwright sends loopback through the proxy.
const SHOTS = process.argv[3] ?? "e2e/screenshots";
const failures = [];
const check = (c, m) => { if (!c) { failures.push(m); console.error("FAIL", m); } else console.log("ok  ", m); };
const proxy = process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY, bypass: "127.0.0.1,localhost" + (/^[\d.]+$/.test(new URL(URL_).hostname) ? "," + new URL(URL_).hostname : "") } : undefined;
const browser = await chromium.launch({ headless: true, proxy });
const page = await browser.newPage({ viewport: { width: 1600, height: 940 }, ignoreHTTPSErrors: true });
await page.addInitScript(() => { try { localStorage.setItem("qpv.welcome.dismissed", "1"); localStorage.setItem("qpv.expert", "1"); } catch {} });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
const t0 = Date.now();
await page.goto(URL_);
await page.waitForSelector('[data-testid="node-V0"]', { timeout: 180000 });
console.log(`engine booted in the browser in ${((Date.now() - t0) / 1000).toFixed(1)} s`);
check((await page.textContent('[data-testid="clock"]')).trim() === "0.000000 ns", "clock starts at 0");
await page.click('[data-testid="btn-run"]');
await page.waitForFunction(() => document.querySelector('[data-testid="outcome"]')?.textContent?.trim() === "accepted", null, { timeout: 30000 });
check((await page.textContent('[data-testid="clock"]')).trim() === "30.206923 ns", "honest round ends at the hand-calculated 30.206923 ns");
await page.click('[data-testid="dock-console"]');
await page.click('.cx-chip:has-text("Why was it accepted")');
await page.waitForSelector(".cx-verdict.accept", { timeout: 30000 });
check(true, "console answers from the in-browser engine");
await page.selectOption('select[aria-label="Open example"]', "qpv_bb84_teleportation_attack");
await page.waitForSelector('[data-testid="node-E0"]', { timeout: 30000 });
await page.click('[data-testid="btn-run"]');
await page.waitForFunction(() => document.querySelector('[data-testid="outcome"]')?.textContent?.trim() === "accepted", null, { timeout: 30000 });
check(true, "teleportation attack accepted in the browser");
await page.click('[data-testid="dock-experiments"]');
const runs = page.locator('.field:has(label:text("Runs per point")) input');
await runs.fill("100");
await runs.press("Enter");
await page.click('button:text("Run experiment")');
await page.waitForSelector("text=done in", { timeout: 120000 });
const table = await page.textContent(".exp-main table.grid");
check(/1\.0000/.test(table) && /0\.0000/.test(table), "timing sweep: attack wins when fast, fails when slow");
await page.keyboard.press("3");
await page.waitForTimeout(500);
await page.screenshot({ path: `${SHOTS}/static-pages.png` });
check(errors.length === 0, `no browser errors (${errors.slice(0, 3).join(" | ")})`);
await browser.close();
if (failures.length) process.exit(1);
console.log("static build works with the in-browser engine");

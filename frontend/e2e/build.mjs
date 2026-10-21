// End-to-end: build QPV_BB84 from an empty project using only the graphical
// editor, run it in the engine, edit an automaton, and save the project file.
//
//   node e2e/build.mjs [http://127.0.0.1:8765] [screenshot-dir]
import { createRequire } from "node:module";
import { mkdirSync, readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
let chromium;
for (const p of ["playwright", "/opt/node22/lib/node_modules/playwright"]) {
  try { ({ chromium } = require(p)); break; } catch { /* next */ }
}
if (!chromium) { console.error("playwright not found"); process.exit(2); }
const BASE = process.argv[2] ?? "http://127.0.0.1:8765";
const SHOTS = process.argv[3] ?? "e2e/screenshots";
mkdirSync(SHOTS, { recursive: true });
const failures = [];
const check = (c, m) => { if (!c) { failures.push(m); console.error("FAIL", m); } else console.log("ok  ", m); };
const api = async (path) => (await fetch(BASE + path)).json();

const browser = await chromium.launch({ headless: true }).catch(() => chromium.launch({ headless: true, executablePath: "/opt/pw-browsers/chromium" }));
const page = await browser.newPage({ viewport: { width: 1600, height: 960 }, acceptDownloads: true });
await page.addInitScript(() => { try { localStorage.setItem("qpv.welcome.dismissed", "1"); } catch {} });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
const settle = () => page.waitForTimeout(450);

await page.goto(BASE);
await page.waitForSelector('[data-testid="btn-new"]');
await page.click('[data-testid="btn-new"]');
await page.click('[data-testid="btn-blank"]');
await settle();
check((await api("/api/project")).project.participants.length === 0, "New creates an empty project in the engine");

// --- drag participants from the palette onto the canvas
async function drop(label, x, y) {
  const dt = await page.evaluateHandle(() => new DataTransfer());
  await page.dispatchEvent(`.palette-item:has-text("${label}")`, "dragstart", { dataTransfer: dt });
  await page.dispatchEvent(".canvas-wrap", "drop", { dataTransfer: dt, clientX: x, clientY: y });
  await settle();
}
await drop("Quantum verifier", 420, 330);
await drop("Classical verifier", 1050, 330);
await drop("Prover", 740, 330);
let proj = (await api("/api/project")).project;
check(proj.participants.map((p) => p.id).join(",") === "V,V2,P", `dropped participants exist in the engine (${proj.participants.map((p) => p.id)})`);
check(proj.participants.map((p) => `${p.verifier_type ?? "-"}:${p.automaton}`).join(",")
  === "quantum:qpv_verifier_quantum,classical:qpv_verifier_classical,-:qpv_prover_2v", "palette adds typed verifiers and a matching prover");
check(await page.locator('[data-testid="node-V"] .vtype').count() === 1 && await page.locator('[data-testid="node-V2"] .vtype').count() === 1,
  "quantum and classical verifiers show their type icon");
check(await page.locator('[data-testid="node-P"] .port-label.missing').count() === 2, "the prover's unconnected ports are flagged");

// --- configure through the inspector
async function selectNode(id) { await page.click(`[data-testid="node-${id}"] .head`); await page.waitForTimeout(150); }
async function setField(label, value, nth = 0) {
  const inp = page.locator(`[data-testid="inspector"] .field:has(> label:text-is("${label}")) input`).nth(nth);
  await inp.fill(String(value));
  await inp.press("Enter");
  await settle();
}
await selectNode("V");
await page.locator('[data-testid="inspector"] input[aria-label="x position"]').fill("-3");
await page.locator('[data-testid="inspector"] input[aria-label="x position"]').press("Enter");
await settle();
await selectNode("V2");
await page.locator('[data-testid="inspector"] input[aria-label="x position"]').fill("3");
await page.locator('[data-testid="inspector"] input[aria-label="x position"]').press("Enter");
await settle();
await selectNode("P");
await setField("Processing (ns)", 0.2);

// --- wire ports: quantum V.prover-P.v0, classical V.prover-P.v0, classical V2.prover-P.v1
async function connect(a, ap, b, bp) {
  const h1 = page.locator(`[data-testid="node-${a}"] .react-flow__handle[data-handleid="${ap}"]`);
  const h2 = page.locator(`[data-testid="node-${b}"] .react-flow__handle[data-handleid="${bp}"]`);
  const b1 = await h1.boundingBox(), b2 = await h2.boundingBox();
  await page.mouse.move(b1.x + b1.width / 2, b1.y + b1.height / 2);
  await page.mouse.down();
  await page.mouse.move((b1.x + b2.x) / 2, (b1.y + b2.y) / 2 + 20, { steps: 8 });
  await page.mouse.move(b2.x + b2.width / 2, b2.y + b2.height / 2, { steps: 8 });
  await page.mouse.up();
  await settle();
}
await connect("V", "prover", "P", "v0");
await connect("V", "prover", "P", "v0");
check((await api("/api/project")).project.links.length === 1 && (await page.textContent(".toast")).includes("already have a quantum link"),
  "a second identical link is refused with an explanation");
await connect("V2", "prover", "P", "v1");  // quantum selected, but V2.prover is classical-only
await page.click('.palette-item:has-text("Classical channel")');
await connect("V", "prover", "P", "v0");
proj = (await api("/api/project")).project;
check(proj.links.map((l) => `${l.id}:${l.kind}`).join(",") === "q:quantum,c:classical,c2:classical",
  `connecting ports picks the kind both ports carry (${proj.links.map((l) => `${l.id}:${l.kind}`)})`);
check(await page.locator('[data-testid="node-P"] .port-label.missing').count() === 0, "flags clear once the ports are wired");

// --- project-level settings: shared randomness and the claim
await page.keyboard.press("Escape");
await page.click('button:text("+ shared random")');
await settle();
await page.click('.section button:has-text("rand0")');
await page.waitForTimeout(150);
const ta = page.locator('[data-testid="inspector"] textarea');
await ta.fill(JSON.stringify({ id: "rand0", type: "shared_random", holders: ["V", "V2"], vars: { x: "rand_bit()", shares: "[rand_bit()]" } }));
await ta.evaluate((el) => el.blur());
await settle();
await page.keyboard.press("Escape");
await page.locator('[data-testid="inspector"] .field:has(> label:text-is("Claimed prover")) select').selectOption("P");
await settle();
const v = (await api("/api/project")).issues.filter((i) => i.level === "error");
check(v.length === 0, `project built in the editor validates (${v.map((i) => i.message).join("; ")})`);
await page.screenshot({ path: `${SHOTS}/10-built-network.png` });

// --- run it
await page.click('[data-testid="btn-run"]');
await settle();
let st = await api("/api/sim/state");
check(st.stopped && st.decision.outcome === "accept", `GUI-built QPV_BB84 runs in the engine and accepts (${st.decision.summary})`);
check(st.messages.length === 4, `engine exchanged 4 messages (qubit, theta, 2 answers) — got ${st.messages.length}`);
await page.hover('[data-testid="link-hit-q"]', { force: true });
const tip = await page.textContent('[data-testid="link-tip"]').catch(() => "");
check(/length 3\.000 m.*propagation 10\.006923 ns/s.test(tip ?? ""), `hovering a link shows its length and engine delay (${tip})`);

// --- edit the prover automaton graphically: add a state and a transition
await page.dblclick('[data-testid="node-P"] .head');
await settle();
await page.click('.canvas-tools button:has-text("State")');
await settle();
proj = (await api("/api/project")).project;
const aut = proj.automata[proj.participants.find((p) => p.id === "P").automaton];
check(aut.states.some((s) => s.id === "state"), "state added in the automaton editor reached the engine project");
const from = page.locator('[data-testid="state-waiting"]');
const fromHandle = from.locator(".react-flow__handle.source");
const to = page.locator('[data-testid="state-state"]');
const b1 = await fromHandle.boundingBox(), b2 = await to.boundingBox();
await page.mouse.move(b1.x + b1.width / 2, b1.y + b1.height / 2);
await page.mouse.down();
await page.mouse.move(b2.x + b2.width / 2, b2.y + b2.height / 2, { steps: 10 });
await page.mouse.up();
await settle();
proj = (await api("/api/project")).project;
const aut2 = proj.automata[proj.participants.find((p) => p.id === "P").automaton];
check(aut2.transitions.some((t) => t.from === "waiting" && t.to === "state"), "transition drawn between states reached the engine project");
// An 'auto' transition with guard true fires as soon as the prover starts (t = 0), before any
// challenge arrives: the prover deadlocks in the new state and both verifiers time out.
await page.click('[data-testid="btn-run"]');
await settle();
st = await api("/api/sim/state");
const pHist = st.nodes.P.history;
check(st.decision.outcome === "reject" && st.nodes.P.state === "state" && pHist[0]?.begin_fs === 0,
  "the drawn auto transition fires at t=0, the prover deadlocks and the claim is rejected");
check(st.decision.verifiers.every((x) => x.category === "timeout"), "both verifiers reject by timeout");
await page.keyboard.press("Control+z");
await settle();
await page.click('[data-testid="btn-run"]');
await settle();
st = await api("/api/sim/state");
check(st.decision.outcome === "accept", "undoing the transition restores acceptance");
await page.screenshot({ path: `${SHOTS}/11-built-automaton.png` });

// --- save the project file and compare with the engine's document
const [download] = await Promise.all([page.waitForEvent("download"), page.click('[data-testid="btn-save"]')]);
const path = await download.path();
const saved = JSON.parse(readFileSync(path, "utf8"));
proj = (await api("/api/project")).project;
const strip = (o) => JSON.parse(JSON.stringify(o, (k, val) => (k === "ui" ? undefined : val)));
check(JSON.stringify(strip(saved)) === JSON.stringify(strip(proj)), "saved file equals the engine's project document");

// --- auto-wiring rebuilds every link from the participants
await fetch(BASE + "/api/project", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...proj, links: [] }) });
await page.reload();
await page.waitForSelector('[data-testid="btn-autowire"]');
await page.click('[data-testid="btn-autowire"]');
await settle();
proj = (await api("/api/project")).project;
check(proj.links.map((l) => `${l.id}:${l.kind}:${l.a.node}.${l.a.port}-${l.b.node}.${l.b.port}`).join(",")
  === "q0:quantum:V.prover-P.v0,c0:classical:V.prover-P.v0,c1:classical:V2.prover-P.v1", `Auto-wire creates the required links (${proj.links.map((l) => l.id)})`);

check(errors.length === 0, `no browser errors (${errors.slice(0, 3).join(" | ")})`);
await browser.close();
if (failures.length) { console.error(`${failures.length} check(s) failed`); process.exit(1); }
console.log("protocol built, run and saved through the graphical editor");

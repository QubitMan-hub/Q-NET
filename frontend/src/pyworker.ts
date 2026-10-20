// Web Worker that runs the Python engine in the browser (Pyodide) for the
// static GitHub Pages build. It loads NumPy and the qpvsim package, then
// answers API calls through qpvsim.webapi.handle_json -- the same dispatcher
// the FastAPI server uses, so results are identical to the server build.

const PYODIDE_VERSION = "0.27.2";
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

type Req = { id: number; method: string; url: string; body?: string };

let ready: Promise<any> | null = null;

async function boot(base: string) {
  post({ type: "status", text: "Downloading the Python runtime…" });
  const mod = await import(/* @vite-ignore */ `${PYODIDE_URL}pyodide.mjs`);
  const py = await mod.loadPyodide({ indexURL: PYODIDE_URL });
  post({ type: "status", text: "Loading NumPy…" });
  await py.loadPackage("numpy");
  post({ type: "status", text: "Loading the simulation engine…" });
  const zip = await fetch(new URL("qpvsim.zip", base)).then((r) => {
    if (!r.ok) throw new Error(`could not download the engine package (HTTP ${r.status})`);
    return r.arrayBuffer();
  });
  py.unpackArchive(zip, "zip", { extractDir: "/home/pyodide/engine" });
  py.runPython("import sys; sys.path.insert(0, '/home/pyodide/engine')\nfrom qpvsim.webapi import handle_json");
  return py.globals.get("handle_json");
}

function post(msg: unknown) {
  (self as unknown as Worker).postMessage(msg);
}

self.onmessage = async (ev: MessageEvent) => {
  const msg = ev.data;
  if (msg.type === "init") {
    ready = boot(msg.base);
    ready.then(() => post({ type: "ready" })).catch((e) => post({ type: "fatal", text: String(e?.message ?? e) }));
    return;
  }
  const req = msg as Req;
  try {
    const handle = await ready!;
    const out = handle(req.method, req.url, req.body ?? "");
    post({ type: "response", id: req.id, payload: out });
  } catch (e: any) {
    post({ type: "response", id: req.id, error: String(e?.message ?? e) });
  }
};
